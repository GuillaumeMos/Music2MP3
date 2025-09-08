# converter.py
from __future__ import annotations
import os, re, csv, glob, platform, subprocess, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from mutagen.easyid3 import EasyID3
from mutagen.mp4 import MP4, MP4Tags

try:
    from config import resource_path
except Exception:
    def resource_path(p: str) -> str:
        return os.path.join(os.path.abspath("."), p)


class Converter:
    def __init__(
        self,
        config: dict,
        status_cb: Optional[Callable[[str], None]] = None,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        item_cb: Optional[Callable[[str, dict], None]] = None,  # NEW: per-track events
    ):
        self.config = config or {}
        self.status_cb = status_cb or (lambda s: None)
        self.progress_cb = progress_cb or (lambda c, m: None)
        self.item_cb = item_cb or (lambda _k, _d: None)

    def _status(self, txt: str):
        try: self.status_cb(txt)
        except Exception: pass

    def _progress(self, cur: int, maxi: int):
        try: self.progress_cb(cur, maxi)
        except Exception: pass

    def _item(self, kind: str, data: dict):
        try: self.item_cb(kind, data)
        except Exception: pass

    def _bin_paths(self):
        system = platform.system()
        if system == "Windows":
            ffmpeg_exe = resource_path(os.path.join("ffmpeg", "ffmpeg.exe"))
            ytdlp_exe = resource_path(os.path.join("yt-dlp", "yt-dlp.exe"))
            creationflags = subprocess.CREATE_NO_WINDOW
        else:
            ffmpeg_exe = resource_path(os.path.join("ffmpeg", "ffmpeg"))
            ytdlp_exe = resource_path(os.path.join("yt-dlp", "yt-dlp"))
            creationflags = 0

        if not os.path.isfile(ffmpeg_exe):
            ffmpeg_exe = os.path.join("ffmpeg", os.path.basename(ffmpeg_exe))
        if not os.path.isfile(ytdlp_exe):
            ytdlp_exe = os.path.join("yt-dlp", os.path.basename(ytdlp_exe))
        return ffmpeg_exe, ytdlp_exe, creationflags

    @staticmethod
    def _sanitize(s: str) -> str:
        return re.sub(r"[^\w\s.-]", "", s).strip()

    @staticmethod
    def _find_output_by_base(out_dir: str, base: str) -> Optional[str]:
        matches = glob.glob(os.path.join(out_dir, base + ".*"))
        if not matches:
            return None
        for pref in (".mp3", ".m4a", ".m4b", ".mka", ".opus", ".webm"):
            for m in matches:
                if m.lower().endswith(pref):
                    return m
        return matches[0]

    def convert_from_csv(self, csv_path: str, output_folder: str, playlist_name_hint: Optional[str] = None) -> str:
        with open(csv_path, newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        total = len(rows)
        if total == 0:
            self._status("Aucune ligne dans le CSV.")
            return output_folder

        playlist_name = (playlist_name_hint or os.path.splitext(os.path.basename(csv_path))[0]).strip()
        out_dir = os.path.join(output_folder, playlist_name)
        os.makedirs(out_dir, exist_ok=True)

        ffmpeg_exe, ytdlp_exe, creationflags = self._bin_paths()
        if not os.path.isfile(ffmpeg_exe) or not os.path.isfile(ytdlp_exe):
            missing = []
            if not os.path.isfile(ffmpeg_exe): missing.append("ffmpeg")
            if not os.path.isfile(ytdlp_exe): missing.append("yt-dlp")
            raise RuntimeError(f"Binaires manquants: {', '.join(missing)}")

        transcode_mp3 = bool(self.config.get("transcode_mp3", False))
        m3u_enabled   = bool(self.config.get("generate_m3u", True))
        exclude_instr = bool(self.config.get("exclude_instrumentals", False))
        cookies_path  = self.config.get("cookies_path") or None
        deep_search   = bool(self.config.get("deep_search", True))

        default_workers = 3
        if transcode_mp3:
            default_workers = max(2, min(4, (os.cpu_count() or 4) // 4 or 2))
        max_workers = int(self.config.get("concurrency", default_workers))

        self._status(f"Lancement : {total} titres • {max_workers} téléchargements en parallèle")
        # côté GUI, on utilise une barre globale lissée via les pourcentages → on émet une init
        self._item('conv_init', {'total': total, 'playlist': playlist_name})

        lock = threading.Lock()
        done = 0
        results: list[tuple[int, bool, Optional[str], Optional[str]]] = []

        def process_one(i: int, row: dict) -> tuple[int, bool, Optional[str], Optional[str]]:
            title = row.get('Track Name') or row.get('Track name') or 'Unknown'
            artist_raw = row.get('Artist Name(s)') or row.get('Artist name') or 'Unknown'
            artist_primary = re.split(r'[,/&]| feat\.| ft\.', artist_raw, flags=re.I)[0].strip()
            album = row.get('Album Name') or row.get('Album') or playlist_name

            file_title = self._sanitize(title)
            safe_artist = self._sanitize(artist_primary)
            base = f"{i:03d} - {file_title}"
            out_template = os.path.join(out_dir, base + ".%(ext)s")

            # notify UI : init row
            self._item('init', {'idx': i, 'title': f"{title} — {artist_primary}"})

            # Already downloaded ?
            already = self._find_output_by_base(out_dir, base)
            if already and os.path.isfile(already):
                # push 100% instantly
                self._item('progress', {'idx': i, 'percent': 100.0, 'speed': None, 'eta': None})
                return (i, True, already, None)

            def yt_cmd(extra_args: list[str], search_spec: str):
                cmd = [ytdlp_exe, f"--ffmpeg-location={os.path.dirname(ffmpeg_exe)}", "--no-config", "--newline"]
                if cookies_path and os.path.isfile(cookies_path):
                    cmd += ["--cookies", cookies_path]
                cmd += extra_args + [search_spec]
                return cmd

            q = ' '.join([file_title, safe_artist]).strip()
            download_spec = f"ytsearch2:{q}" if deep_search else f"ytsearch1:{q}"

            args = ['-f', 'bestaudio[ext=m4a]/bestaudio', '--output', out_template, '--no-playlist']
            if exclude_instr:
                args += ['--reject-title', 'instrumental']
            if transcode_mp3:
                args += ['--extract-audio', '--audio-format', 'mp3', '--audio-quality', '0']
            else:
                args += ['--remux-video', 'm4a']

            # stream stdout pour parser le pourcentage
            proc = subprocess.Popen(
                yt_cmd(args, download_spec),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                creationflags=creationflags
            )

            try:
                for line in proc.stdout:
                    # [download]  12.3% of ...
                    m = re.search(r'\[download\]\s+(\d+(?:\.\d+)?)%', line)
                    if m:
                        pct = float(m.group(1))
                        # speed & eta (optionnel)
                        sp = re.search(r'at\s+([\d.]+[A-Za-z]+\/s)', line)
                        eta = re.search(r'ETA\s+(\d{1,2}:\d{2})', line)
                        self._item('progress', {
                            'idx': i,
                            'percent': pct,
                            'speed': sp.group(1) if sp else None,
                            'eta': eta.group(1) if eta else None
                        })
            finally:
                proc.wait()

            if proc.returncode != 0:
                err = proc.stdout.read() if proc.stdout else ''
                return (i, False, None, (err or "yt-dlp error")[:700])

            outfile = self._find_output_by_base(out_dir, base)
            if not outfile or not os.path.isfile(outfile):
                return (i, False, None, "Fichier de sortie introuvable après téléchargement.")

            # tags
            try:
                if outfile.lower().endswith(".mp3"):
                    audio = EasyID3()
                    try: audio.load(outfile)
                    except: pass
                    audio.update({'artist': artist_primary, 'title': title, 'album': album, 'tracknumber': str(i)})
                    audio.save()
                elif outfile.lower().endswith((".m4a", ".m4b")):
                    mp4 = MP4(outfile)
                    tags = mp4.tags or MP4Tags()
                    tags['\xa9nam']=[title]; tags['\xa9ART']=[artist_primary]; tags['\xa9alb']=[album]
                    mp4.save()
            except Exception:
                pass

            self._item('progress', {'idx': i, 'percent': 100.0, 'speed': None, 'eta': None})
            return (i, True, outfile, None)

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(process_one, i, row): (i, row) for i, row in enumerate(rows, start=1)}
            for fut in as_completed(futures):
                i, row = futures[fut]
                ok, path, err = False, None, None
                try:
                    i2, ok, path, err = fut.result()
                except Exception as e:
                    err = str(e)

                with lock:
                    done += 1
                    # on conserve ce progress "par titre terminé" au cas où,
                    # mais l’UI calcule la barre globale via la somme des %
                    self._progress(done, total)

                    if ok:
                        results.append((i, True, path, None))
                        self._item('done', {'idx': i, 'path': path})
                        self._status(f"[{done}/{total}] OK : {row.get('Track Name') or ''}")
                    else:
                        results.append((i, False, None, err))
                        self._item('error', {'idx': i, 'error': err})
                        self._status(f"[{done}/{total}] ÉCHEC : {row.get('Track Name') or ''}")

        if self.config.get("generate_m3u", True):
            m3u_name = playlist_name.replace('_', ' ')
            m3u_path = os.path.join(out_dir, f"{m3u_name}.m3u")
            with open(m3u_path, 'w', encoding='utf-8') as m3u:
                m3u.write('#EXTM3U\n')
                for (idx, ok, path, _) in sorted(results, key=lambda x: x[0]):
                    if ok and path and os.path.isfile(path):
                        fn = os.path.basename(path)
                        m3u.write(f'#EXTINF:-1,{os.path.splitext(fn)[0]}\n')
                        m3u.write(f'{fn}\n')

        # rapport des ratés
        fails = [(idx, err) for (idx, ok, _p, err) in results if not ok]
        if fails:
            nf_path = os.path.join(out_dir, f"{playlist_name}_not_found.csv")
            with open(nf_path, 'w', newline='', encoding='utf-8') as cf:
                w = csv.writer(cf); w.writerow(["#", "Title", "Error"])
                for idx, err in fails:
                    title = rows[idx-1].get('Track Name') or ''
                    w.writerow([idx, title, err or 'unknown'])

        self._status("✅ Terminé")
        return out_dir
