# converter.py
from __future__ import annotations
import os, re, csv, glob, json, platform, subprocess, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional, Tuple, Set, List

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
        status_cb: Callable[[str], None] | None = None,
        progress_cb: Callable[[int, int], None] | None = None,
        item_cb: Callable[[str, dict], None] | None = None,
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

    @staticmethod
    def _strip_numeric_prefix(name_no_ext: str) -> str:
        return re.sub(r"^\s*\d{3}\s*-\s*", "", name_no_ext).strip()

    # --- keys from CSV row ---
    def _row_keys(self, row: dict) -> List[Tuple]:
        keys: List[Tuple] = []
        uri = row.get("Track URI") or row.get("track uri") or row.get("uri")
        if uri:
            m = re.search(r"(?:spotify:track:|track/)([A-Za-z0-9]+)", uri)
            if m:
                keys.append(("uri", m.group(1)))
            else:
                keys.append(("uri", uri))  # soundcloud: garder l'URL entière

        src = row.get("Source URL") or row.get("source url")
        if src:
            keys.append(("uri", src.strip()))

        title = self._norm_text(row.get("Track Name") or row.get("Track name") or "")
        artist = self._norm_text(row.get("Artist Name(s)") or row.get("Artist name") or "")
        if title or artist:
            keys.append(("meta", title, artist))
        if title:
            keys.append(("title", title))
        return keys

    # --- keys from existing file ---
    def _tag_key_from_file(self, path: str) -> List[Tuple]:
        out: List[Tuple] = []
        title_norm = ""
        artist_norm = ""
        try:
            if path.lower().endswith(".mp3"):
                audio = EasyID3(path)
                title_norm  = self._norm_text("".join(audio.get("title", [])))
                artist_norm = self._norm_text("".join(audio.get("artist", [])))
            else:
                mp4 = MP4(path)
                title_norm  = self._norm_text("".join(mp4.tags.get("\xa9nam", [])) if mp4.tags else "")
                artist_norm = self._norm_text("".join(mp4.tags.get("\xa9ART", [])) if mp4.tags else "")
        except Exception:
            pass

        if title_norm or artist_norm:
            out.append(("meta", title_norm, artist_norm))
        if title_norm:
            out.append(("title", title_norm))
        return out

    def _file_title_key_from_name(self, path: str) -> Optional[Tuple]:
        base = os.path.splitext(os.path.basename(path))[0]
        core = self._strip_numeric_prefix(base)
        title_only_norm = self._norm_text(core)
        if title_only_norm:
            return ("title", title_only_norm)
        return None

    def _scan_existing_keys(self, out_dir: str) -> Set[Tuple]:
        keys: Set[Tuple] = set()
        manifest = os.path.join(out_dir, "manifest.json")
        if os.path.isfile(manifest):
            try:
                data = json.load(open(manifest, "r", encoding="utf-8"))
                for k in data.get("keys", []):
                    keys.add(tuple(k))
            except Exception:
                pass

        for ext in ("*.mp3", "*.m4a", "*.m4b", "*.mka", "*.opus", "*.webm"):
            for p in glob.glob(os.path.join(out_dir, ext)):
                for k in self._tag_key_from_file(p):
                    keys.add(k)
                k2 = self._file_title_key_from_name(p)
                if k2:
                    keys.add(k2)
        return keys

    def _save_manifest(self, out_dir: str, keys: Set[Tuple]):
        try:
            payload = {"keys": [list(k) for k in sorted(keys)]}
            with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _max_existing_index(self, out_dir: str) -> int:
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

    def _make_base_name(self, file_title: str, index: int, prefix_numbers: bool) -> str:
        return f"{index:03d} - {file_title}" if prefix_numbers else file_title

    # ---------- main ----------
    def convert_from_csv(self, csv_path: str, output_folder: str, playlist_name_hint: Optional[str] = None) -> str:
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        total_in_csv = len(rows)
        if total_in_csv == 0:
            self._status("No rows in CSV.")
            return output_folder

        playlist_name = (playlist_name_hint or os.path.splitext(os.path.basename(csv_path))[0]).strip()

        base_out = os.path.normpath(output_folder)
        if os.path.basename(base_out).lower() == playlist_name.lower():
            out_dir = base_out
        else:
            out_dir = os.path.join(base_out, playlist_name)
        os.makedirs(out_dir, exist_ok=True)

        ffmpeg_exe, ytdlp_exe, creationflags = self._bin_paths()
        if not os.path.isfile(ffmpeg_exe) or not os.path.isfile(ytdlp_exe):
            missing = []
            if not os.path.isfile(ffmpeg_exe): missing.append("ffmpeg")
            if not os.path.isfile(ytdlp_exe): missing.append("yt-dlp")
            raise RuntimeError(f"Missing binaries: {', '.join(missing)}")

        transcode_mp3  = bool(self.config.get("transcode_mp3", False))
        m3u_enabled    = bool(self.config.get("generate_m3u", True))
        exclude_instr  = bool(self.config.get("exclude_instrumentals", False))
        cookies_path   = self.config.get("cookies_path") or None
        cookies_browser = (self.config.get("sc_cookies_from_browser") or "").strip() or None
        deep_search    = bool(self.config.get("deep_search", True))
        max_workers    = int(self.config.get("concurrency", 3))
        incremental    = bool(self.config.get("incremental_update", True))
        prefix_numbers = bool(self.config.get("prefix_numbers", False))  # default unchecked

        existing_keys: Set[Tuple] = set()
        to_download: List[Tuple[int, dict, List[Tuple]]] = []
        if incremental and os.path.isdir(out_dir):
            existing_keys = self._scan_existing_keys(out_dir)

        for i, row in enumerate(rows, start=1):
            candidates = self._row_keys(row)
            if not incremental or not any(k in existing_keys for k in candidates):
                to_download.append((i, row, candidates))

        skipped = total_in_csv - len(to_download)
        self._status(f"Playlist “{playlist_name}”: {total_in_csv} total • {skipped} existing • {len(to_download)} new")

        self._item('conv_init', {'total': len(to_download), 'new': len(to_download), 'playlist': playlist_name})
        if len(to_download) == 0:
            if m3u_enabled:
                self._write_m3u(out_dir, playlist_name)
            self._status("✅ Nothing to download")
            return out_dir

        start_index = self._max_existing_index(out_dir) + 1 if prefix_numbers else 1

        lock = threading.Lock()
        new_keys: Set[Tuple] = set()

        def process_one(new_idx: int, original_csv_idx: int, row: dict, cand_keys: List[Tuple]):
            title = row.get('Track Name') or row.get('Track name') or 'Unknown'
            artist_raw = row.get('Artist Name(s)') or row.get('Artist name') or 'Unknown'
            artist_primary = re.split(r'[,/&]| feat\.| ft\.', artist_raw, flags=re.I)[0].strip()
            album = row.get('Album Name') or row.get('Album') or playlist_name

            file_title = self._sanitize(title)
            safe_artist = self._sanitize(artist_primary)
            base = self._make_base_name(file_title=file_title, index=new_idx, prefix_numbers=prefix_numbers)
            out_template = os.path.join(out_dir, base + ".%(ext)s")

            self._item('init', {'idx': new_idx, 'title': f"{title} — {artist_primary}"})

            source_url = (row.get('Source URL') or row.get('source url') or "").strip()

            def yt_cmd(extra_args: list[str], search_spec: str):
                cmd = [ytdlp_exe, f"--ffmpeg-location={os.path.dirname(ffmpeg_exe)}", "--no-config", "--newline"]
                # Auth: privilégie cookies-from-browser, sinon cookies.txt
                if cookies_browser:
                    cmd += ["--cookies-from-browser", cookies_browser]
                elif cookies_path and os.path.isfile(cookies_path):
                    cmd += ["--cookies", cookies_path]
                cmd += extra_args + [search_spec]
                return cmd

            if source_url:
                download_spec = source_url
                fmt_args = ['-f', 'bestaudio']
            else:
                q = ' '.join([file_title, safe_artist]).strip()
                download_spec = f"ytsearch2:{q}" if deep_search else f"ytsearch1:{q}"
                fmt_args = ['-f', 'bestaudio[ext=m4a]/bestaudio']

            args = fmt_args + ['--output', out_template, '--no-playlist']
            if exclude_instr:
                args += ['--reject-title', 'instrumental']

            if transcode_mp3:
                args += ['--extract-audio','--audio-format','mp3','--audio-quality','0']
            else:
                if not source_url:
                    args += ['--remux-video','m4a']

            proc = subprocess.Popen(
                yt_cmd(args, download_spec),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, universal_newlines=True,
                encoding='utf-8', errors='replace',
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
                err = "yt-dlp error"
                try:
                    err = proc.stdout.read() or err
                except Exception:
                    pass
                self._item('error', {'idx': new_idx, 'error': err[:700]})
                return

            outfile = self._find_output_by_base(out_dir, base)
            if not outfile or not os.path.isfile(outfile):
                self._item('error', {'idx': new_idx, 'error': "Output file not found after download."})
                return

            try:
                if outfile.lower().endswith(".mp3"):
                    audio = EasyID3()
                    try: audio.load(outfile)
                    except: pass
                    audio.update({'artist': artist_primary, 'title': title, 'album': album, 'tracknumber': str(new_idx)})
                    audio.save()
                elif outfile.lower().endswith(".m4a"):
                    mp4 = MP4(outfile)
                    tags = mp4.tags or MP4Tags()
                    tags['\xa9nam']=[title]; tags['\xa9ART']=[artist_primary]; tags['\xa9alb']=[album]
                    mp4.save()
            except Exception:
                pass

            self._item('progress', {'idx': new_idx, 'percent': 100.0, 'speed': None, 'eta': None})
            self._item('done', {'idx': new_idx})

            with lock:
                for k in cand_keys:
                    new_keys.add(k)

        self._status(f"Starting: {len(to_download)} new • {max_workers} parallel")
        self._progress(0, len(to_download))

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {}
            for offset, (orig_idx, row, cand_keys) in enumerate(to_download, start=0):
                new_idx = start_index + offset
                fut = ex.submit(process_one, new_idx, orig_idx, row, cand_keys)
                futures[fut] = (new_idx, row, cand_keys)

            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as e:
                    self._item('error', {'idx': futures[fut][0], 'error': str(e)})

        if m3u_enabled:
            self._write_m3u(out_dir, playlist_name)

        try:
            if incremental:
                existing = self._scan_existing_keys(out_dir)
                existing |= new_keys
                self._save_manifest(out_dir, existing)
        except Exception:
            pass

        self._status("✅ Done")
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

    @staticmethod
    def _find_output_by_base(out_dir: str, base: str) -> Optional[str]:
        import glob as _glob
        matches = _glob.glob(os.path.join(out_dir, base + ".*"))
        if not matches:
            return None
        for pref in (".mp3", ".m4a", ".m4b", ".mka", ".opus", ".webm"):
            for m in matches:
                if m.lower().endswith(pref):
                    return m
        return matches[0]
