# converter.py
from __future__ import annotations
import os, re, csv, glob, json, platform, subprocess, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional, Tuple, Set, List

from mutagen.easyid3 import EasyID3
from mutagen.mp4 import MP4, MP4Tags

# resource_path compatible PyInstaller
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
        item_cb: Optional[Callable[[str, dict], None]] = None,  # per-track events
    ):
        self.config = config or {}
        self.status_cb = status_cb or (lambda s: None)
        self.progress_cb = progress_cb or (lambda c, m: None)
        self.item_cb = item_cb or (lambda _k, _d: None)

    # ---------- reporting ----------
    def _status(self, txt: str): 
        try: self.status_cb(txt)
        except Exception: pass

    def _progress(self, cur: int, maxi: int):
        try: self.progress_cb(cur, maxi)
        except Exception: pass

    def _item(self, kind: str, data: dict):
        try: self.item_cb(kind, data)
        except Exception: pass

    # ---------- binaries ----------
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

    # ---------- utils ----------
    @staticmethod
    def _sanitize(s: str) -> str:
        return re.sub(r"[^\w\s.-]", "", (s or "")).strip()

    @staticmethod
    def _norm_text(s: str) -> str:
        s = (s or "").lower()
        s = re.sub(r"\s+", " ", s)
        s = re.sub(r"[^\w\s]", "", s)
        return s.strip()

    def _row_key(self, row: dict) -> Tuple:
        """
        Clé stable pour comparer les morceaux du CSV.
        Priorité: Track URI -> sinon (title+artist) normalisés.
        """
        uri = row.get("Track URI") or row.get("track uri") or row.get("uri")
        if uri:
            m = re.search(r"(?:spotify:track:|track/)([A-Za-z0-9]+)", uri)
            if m:
                return ("uri", m.group(1))
            return ("uri", uri)
        title = self._norm_text(row.get("Track Name") or row.get("Track name") or "")
        artist = self._norm_text(row.get("Artist Name(s)") or row.get("Artist name") or "")
        return ("meta", title, artist)

    def _tag_key_from_file(self, path: str) -> Optional[Tuple]:
        """Reconstitue une clé à partir des tags du fichier (title+artist)."""
        try:
            if path.lower().endswith(".mp3"):
                audio = EasyID3(path)
                title = self._norm_text("".join(audio.get("title", [])))
                artist = self._norm_text("".join(audio.get("artist", [])))
            else:
                mp4 = MP4(path)
                title = self._norm_text("".join(mp4.tags.get("\xa9nam", [])) if mp4.tags else "")
                artist = self._norm_text("".join(mp4.tags.get("\xa9ART", [])) if mp4.tags else "")
            if title or artist:
                return ("meta", title, artist)
        except Exception:
            pass
        return None

    def _scan_existing_keys(self, out_dir: str) -> Set[Tuple]:
        """Charge manifest.json si présent, sinon reconstruit via tags."""
        keys: Set[Tuple] = set()
        manifest = os.path.join(out_dir, "manifest.json")
        if os.path.isfile(manifest):
            try:
                data = json.load(open(manifest, "r", encoding="utf-8"))
                for k in data.get("keys", []):
                    keys.add(tuple(k))
            except Exception:
                pass
        if not keys:
            for ext in ("*.mp3", "*.m4a", "*.m4b", "*.mka", "*.opus", "*.webm"):
                for p in glob.glob(os.path.join(out_dir, ext)):
                    k = self._tag_key_from_file(p)
                    if k:
                        keys.add(k)
        return keys

    def _save_manifest(self, out_dir: str, keys: Set[Tuple]):
        try:
            payload = {"keys": [list(k) for k in sorted(keys)]}
            with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _max_existing_index(self, out_dir: str) -> int:
        """Renvoie le plus grand index 'NNN - ' déjà présent, sinon 0."""
        mx = 0
        for p in glob.glob(os.path.join(out_dir, "*.*")):
            base = os.path.basename(p)
            m = re.match(r"^(\d{3})\s*-\s*", base)
            if m:
                try:
                    mx = max(mx, int(m.group(1)))
                except Exception:
                    pass
        return mx

    # ---------- main ----------
    def convert_from_csv(self, csv_path: str, output_folder: str, playlist_name_hint: Optional[str] = None) -> str:
        # Lecture CSV
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        total_in_csv = len(rows)
        if total_in_csv == 0:
            self._status("Aucune ligne dans le CSV.")
            return output_folder

        # Dossier playlist
        playlist_name = (playlist_name_hint or os.path.splitext(os.path.basename(csv_path))[0]).strip()
        out_dir = os.path.join(output_folder, playlist_name)
        os.makedirs(out_dir, exist_ok=True)

        # Binaries
        ffmpeg_exe, ytdlp_exe, creationflags = self._bin_paths()
        if not os.path.isfile(ffmpeg_exe) or not os.path.isfile(ytdlp_exe):
            missing = []
            if not os.path.isfile(ffmpeg_exe): missing.append("ffmpeg")
            if not os.path.isfile(ytdlp_exe): missing.append("yt-dlp")
            raise RuntimeError(f"Binaires manquants: {', '.join(missing)}")

        # Options
        transcode_mp3 = bool(self.config.get("transcode_mp3", False))
        m3u_enabled   = bool(self.config.get("generate_m3u", True))
        exclude_instr = bool(self.config.get("exclude_instrumentals", False))
        cookies_path  = self.config.get("cookies_path") or None
        deep_search   = bool(self.config.get("deep_search", True))
        max_workers   = int(self.config.get(
            "concurrency",
            3 if not transcode_mp3 else max(2, min(4, (os.cpu_count() or 4)//4 or 2))
        ))
        incremental   = bool(self.config.get("incremental_update", True))

        # Filtrage incrémental (nouveaux uniquement si dossier existe)
        existing_keys: Set[Tuple] = set()
        to_download: List[Tuple[int, dict, Tuple]] = []
        if incremental and os.path.isdir(out_dir):
            existing_keys = self._scan_existing_keys(out_dir)

        for i, row in enumerate(rows, start=1):
            key = self._row_key(row)
            if not incremental or key not in existing_keys:
                to_download.append((i, row, key))

        skipped = total_in_csv - len(to_download)
        self._status(f"Playlist « {playlist_name} » : {total_in_csv} dans le CSV • {skipped} déjà présents • {len(to_download)} nouveaux")

        # Annonce au GUI : nouveaux uniquement
        self._item('conv_init', {
            'total': len(to_download),
            'new':   len(to_download),
            'playlist': playlist_name
        })
        if len(to_download) == 0:
            if m3u_enabled:
                self._write_m3u(out_dir, playlist_name)
            self._status("✅ Rien à télécharger")
            return out_dir

        # Numérotation → reprend à la suite
        start_index = self._max_existing_index(out_dir) + 1

        # Locks / shared
        lock = threading.Lock()
        done_count = 0
        new_keys: Set[Tuple] = set()
        results: List[Tuple[int, bool, Optional[str], Optional[str]]] = []

        # ---------- worker ----------
        def process_one(new_idx: int, original_csv_idx: int, row: dict, key: Tuple) -> Tuple[int, bool, Optional[str], Optional[str], Tuple]:
            title = row.get('Track Name') or row.get('Track name') or 'Unknown'
            artist_raw = row.get('Artist Name(s)') or row.get('Artist name') or 'Unknown'
            artist_primary = re.split(r'[,/&]| feat\.| ft\.', artist_raw, flags=re.I)[0].strip()
            album = row.get('Album Name') or row.get('Album') or playlist_name

            file_title = self._sanitize(title)
            safe_artist = self._sanitize(artist_primary)
            base = f"{new_idx:03d} - {file_title}"
            out_template = os.path.join(out_dir, base + ".%(ext)s")

            # UI init de la piste
            self._item('init', {'idx': new_idx, 'title': f"{title} — {artist_primary}"})

            # déjà présent ?
            already = self._find_output_by_base(out_dir, base)
            if already and os.path.isfile(already):
                self._item('progress', {'idx': new_idx, 'percent': 100.0, 'speed': None, 'eta': None})
                return (new_idx, True, already, None, key)

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

            proc = subprocess.Popen(
                yt_cmd(args, download_spec),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, universal_newlines=True,
                encoding='utf-8', errors='replace',
                creationflags=creationflags
            )
            try:
                for line in proc.stdout:
                    m = re.search(r'\[download\]\s+(\d+(?:\.\d+)?)%', line)
                    if m:
                        pct = float(m.group(1))
                        sp = re.search(r'at\s+([\d.]+[A-Za-z]+\/s)', line)
                        eta = re.search(r'ETA\s+(\d{1,2}:\d{2})', line)
                        self._item('progress', {
                            'idx': new_idx,
                            'percent': pct,
                            'speed': sp.group(1) if sp else None,
                            'eta': eta.group(1) if eta else None
                        })
            finally:
                proc.wait()

            if proc.returncode != 0:
                err_all = ""
                try:
                    if proc.stdout:
                        err_all = proc.stdout.read() or ""
                except Exception:
                    pass
                return (new_idx, False, None, (err_all or "yt-dlp error")[:700], key)

            outfile = self._find_output_by_base(out_dir, base)
            if not outfile or not os.path.isfile(outfile):
                return (new_idx, False, None, "Fichier de sortie introuvable après téléchargement.", key)

            # tags (best-effort)
            try:
                if outfile.lower().endswith(".mp3"):
                    audio = EasyID3()
                    try: audio.load(outfile)
                    except: pass
                    audio.update({'artist': artist_primary, 'title': title, 'album': album, 'tracknumber': str(new_idx)})
                    audio.save()
                else:
                    mp4 = MP4(outfile)
                    tags = mp4.tags or MP4Tags()
                    tags['\xa9nam']=[title]; tags['\xa9ART']=[artist_primary]; tags['\xa9alb']=[album]
                    mp4.save()
            except Exception:
                pass

            self._item('progress', {'idx': new_idx, 'percent': 100.0, 'speed': None, 'eta': None})
            return (new_idx, True, outfile, None, key)

        # ---------- exécution parallèle ----------
        self._status(f"Lancement : {len(to_download)} nouveaux • {max_workers} téléchargements en parallèle")
        self._progress(0, len(to_download))

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {}
            for offset, (orig_idx, row, key) in enumerate(to_download, start=0):
                new_idx = start_index + offset
                fut = ex.submit(process_one, new_idx, orig_idx, row, key)
                futures[fut] = (new_idx, row)

            for fut in as_completed(futures):
                new_idx, row = futures[fut]
                ok, path, err, key = False, None, None, None
                try:
                    new_idx2, ok, path, err, key = fut.result()
                except Exception as e:
                    err = str(e)

                with lock:
                    done_count += 1
                    self._progress(done_count, len(to_download))
                    if ok:
                        self._item('done', {'idx': new_idx})
                        self._status(f"[{done_count}/{len(to_download)}] OK : {row.get('Track Name') or ''}")
                        if key: new_keys.add(key)
                    else:
                        self._item('error', {'idx': new_idx, 'error': err})
                        self._status(f"[{done_count}/{len(to_download)}] ÉCHEC : {row.get('Track Name') or ''}")

        # ---------- M3U ----------
        if m3u_enabled:
            self._write_m3u(out_dir, playlist_name)

        # ---------- manifest ----------
        try:
            if incremental:
                if not existing_keys:
                    existing_keys = set()
                existing_keys |= new_keys
                self._save_manifest(out_dir, existing_keys)
        except Exception:
            pass

        self._status("✅ Terminé")
        return out_dir

    # ---------- write M3U ----------
    def _write_m3u(self, out_dir: str, playlist_name: str):
        m3u_name = playlist_name.replace('_', ' ')
        m3u_path = os.path.join(out_dir, f"{m3u_name}.m3u")
        with open(m3u_path, 'w', encoding='utf-8') as m3u:
            m3u.write('#EXTM3U\n')
            files = []
            for p in glob.glob(os.path.join(out_dir, "*.*")):
                if os.path.splitext(p)[1].lower() in (".mp3", ".m4a", ".m4b", ".mka", ".opus", ".webm"):
                    base = os.path.basename(p)
                    m = re.match(r"^(\d{3})\s*-\s*", base)
                    idx = int(m.group(1)) if m else 999999
                    files.append((idx, os.path.getmtime(p), base))
            files.sort(key=lambda x: (x[0], x[1]))
            for _, __, fn in files:
                m3u.write(f'#EXTINF:-1,{os.path.splitext(fn)[0]}\n')
                m3u.write(f'{fn}\n')

    # ---------- helpers for output detection ----------
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
