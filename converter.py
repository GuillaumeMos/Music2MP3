# converter.py
import os
import re
import csv
import sys
import time
import json
import queue
import platform
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils import run_quiet, popen_quiet
from config import resource_path


def _find_binaries():
    _ = getattr(sys, "_MEIPASS", os.path.abspath("."))
    if platform.system() == "Windows":
        ff = os.path.join(resource_path("ffmpeg"), "ffmpeg.exe")
        yd = os.path.join(resource_path("yt-dlp"), "yt-dlp.exe")
        ffmpeg_exe = ff if os.path.isfile(ff) else "ffmpeg.exe"
        ytdlp_exe = yd if os.path.isfile(yd) else "yt-dlp.exe"
    else:
        ff = os.path.join(resource_path("ffmpeg"), "ffmpeg")
        yd = os.path.join(resource_path("yt-dlp"), "yt-dlp")
        ffmpeg_exe = ff if os.path.isfile(ff) else "ffmpeg"
        ytdlp_exe = yd if os.path.isfile(yd) else "yt-dlp"
    return ffmpeg_exe, ytdlp_exe


def _norm(s: str) -> str:
    """
    Robust normalization so keys match filenames even with punctuation/dashes.
    - Lowercase, unify en/em dashes to '-'
    - Remove most punctuation except hyphen (we standardize ' - ' delimiter)
    - Collapse spaces, normalize ' - ' spacing
    """
    s = (s or "").lower()
    s = s.replace("–", "-").replace("—", "-")  # en/em dash -> hyphen
    # keep word chars, spaces, and hyphen
    s = re.sub(r"[^\w\s\-]", "", s, flags=re.U)
    # normalize hyphen spacing
    s = re.sub(r"\s*-\s*", " - ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _strip_leading_index(name: str) -> str:
    base = os.path.splitext(name)[0]
    # strip leading "001 - ", "01.", "12_ ", etc.
    base = re.sub(r"^\s*\d+\s*[-_\.]\s*", "", base)
    return base


def _track_key(title: str, artist: str) -> str:
    a0 = re.split(r'[,/&]| feat\.| ft\.', artist, flags=re.I)[0].strip()
    return _norm(f"{title}::{a0}")


def _existing_keys_in_folder(folder: str) -> set[str]:
    keys = set()
    for fn in os.listdir(folder):
        if not fn.lower().endswith((".mp3", ".m4a")):
            continue
        base = _strip_leading_index(fn)
        # expect "<title> - <artist>"
        if " - " in base:
            t, a = base.rsplit(" - ", 1)
        else:
            t, a = base, ""
        keys.add(_track_key(t, a))
    return keys


def _safe_filename(s: str) -> str:
    s = re.sub(r"[^\w\s\-\.\(\)\[\]&']", "", s, flags=re.U)
    return re.sub(r"\s+", " ", s).strip()


def _choose_best_youtube(ytdlp_exe: str, query: str, duration_ms: int | None, artist_primary: str | None, cookies_path: str | None):
    cmd = [ytdlp_exe, "--flat-playlist", "--dump-single-json", "--no-warnings", "-q", f"ytsearch3:{query}"]
    if cookies_path:
        cmd += ["--cookies", cookies_path]
    proc = run_quiet(cmd, text=True, capture_output=True)
    try:
        data = json.loads(proc.stdout or "{}")
    except Exception:
        data = {}
    entries = data.get("entries") or []
    if not entries:
        return f"ytsearch1:{query}"

    def score(entry: dict) -> float:
        dur = entry.get("duration") or 0
        s = 0.0
        if duration_ms:
            s -= abs(dur - int(duration_ms / 1000))
        title = (entry.get("title") or "").lower()
        if artist_primary and artist_primary.lower() in title:
            s += 10
        return s

    best = max(entries, key=score)
    return best.get("url") or f"ytsearch1:{query}"


class Converter:
    """
    Heavy worker with cooperative cancel support.

    Callbacks:
      - status_cb(str)
      - progress_cb(cur, max)
      - item_cb(event, data)
        * 'conv_init' {'total': N, 'new': M, 'existing': N-M}
        * 'init' {'idx': i, 'title': '…'}
        * 'progress' {'idx': i, 'percent': 0..100, 'speed': '…', 'eta': '…'}
        * 'done' {'idx': i}
        * 'error' {'idx': i, 'message': '…'}
        * 'cancel_all' {}
    """

    def __init__(self, config: dict, status_cb=None, progress_cb=None, item_cb=None, cancel_event: threading.Event | None = None):
        self.cfg = config or {}
        self.status_cb = status_cb or (lambda s: None)
        self.progress_cb = progress_cb or (lambda a, b: None)
        self.item_cb = item_cb or (lambda k, d: None)
        self.cancel = cancel_event or threading.Event()
        self.ffmpeg_exe, self.ytdlp_exe = _find_binaries()

    # --------------------------- Public API ---------------------------

    def convert_from_csv(self, csv_path: str, output_folder: str, playlist_hint: str | None = None) -> str:
        rows = list(self._read_csv(csv_path))
        if not rows:
            raise RuntimeError("CSV is empty or malformed.")

        # Playlist name / output path (avoid double-nesting)
        playlist_name = playlist_hint or os.path.splitext(os.path.basename(csv_path))[0]
        out_dir = output_folder
        if os.path.basename(os.path.normpath(output_folder)).lower() != playlist_name.lower():
            out_dir = os.path.join(output_folder, playlist_name)
        os.makedirs(out_dir, exist_ok=True)

        # incremental snapshot
        existing_keys = _existing_keys_in_folder(out_dir) if self.cfg.get("incremental_update", True) else set()

        todo = []
        for idx, r in enumerate(rows, start=1):
            title = r.get("Track Name") or r.get("Track name") or "Unknown"
            artist = r.get("Artist Name(s)") or r.get("Artist name") or ""
            k = _track_key(title, artist)
            if k in existing_keys:
                continue
            todo.append((idx, r))

        self.item_cb('conv_init', {
            'total': len(rows),
            'new': len(todo),
            'existing': len(rows) - len(todo),
        })

        if self.cancel.is_set():
            self.status_cb("Cancelled.")
            self.item_cb('cancel_all', {})
            return out_dir

        if not todo:
            self.status_cb("Everything already up to date.")
            if self.cfg.get("generate_m3u", True):
                self._write_m3u(out_dir, playlist_name)
            return out_dir

        self.status_cb(f"Starting downloads: {len(todo)} tracks…")

        workers = max(1, min(8, int(self.cfg.get("concurrency", 3))))
        cookies_path = self.cfg.get("cookies_path")

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = []
            for idx, row in todo:
                if self.cancel.is_set():
                    break
                futures.append(ex.submit(self._download_one, idx, row, out_dir, playlist_name, cookies_path, len(rows)))
            for f in as_completed(futures):
                _ = f.exception()
                if self.cancel.is_set():
                    break

        if self.cancel.is_set():
            self.status_cb("Cancelled.")
            self.item_cb('cancel_all', {})
            return out_dir

        if self.cfg.get("generate_m3u", True):
            self._write_m3u(out_dir, playlist_name)

        self.status_cb("All done.")
        return out_dir

    # --------------------------- Internals ---------------------------

    def _read_csv(self, path: str):
        with open(path, newline='', encoding='utf-8') as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                yield row

    def _make_base_name(self, seq_index: int, total_tracks: int, row: dict) -> str:
        title = row.get("Track Name") or row.get("Track name") or "Unknown"
        artist_raw = row.get("Artist Name(s)") or row.get("Artist name") or ""
        artist_primary = re.split(r'[,/&]| feat\.| ft\.', artist_raw, flags=re.I)[0].strip()
        base_title = _safe_filename(title)
        base_artist = _safe_filename(artist_primary)
        name = f"{base_title} - {base_artist}"
        if self.cfg.get("prefix_numbers", False):
            width = len(str(max(1, total_tracks)))
            name = f"{seq_index:0{width}d} - {name}"
        return name

    def _download_one(self, idx: int, row: dict, out_dir: str, playlist_name: str, cookies_path: str | None, total_tracks: int):
        if self.cancel.is_set():
            self.item_cb('error', {'idx': idx, 'message': 'Cancelled'})
            return

        title = row.get("Track Name") or "Track"
        artist = row.get("Artist Name(s)") or ""
        nice_title = f"{title} - {artist}" if artist else title
        self.item_cb('init', {'idx': idx, 'title': nice_title})

        src_url = (row.get("Source URL") or "").strip()
        dur_ms = None
        try:
            d = row.get("Duration (ms)")
            if d:
                dur_ms = int(float(d))
        except Exception:
            dur_ms = None

        base = self._make_base_name(seq_index=idx, total_tracks=total_tracks, row=row)
        out_tmpl = os.path.join(out_dir, base + ".%(ext)s")

        ffmpeg_exe, ytdlp_exe = self.ffmpeg_exe, self.ytdlp_exe
        cmd = [
            ytdlp_exe,
            f"--ffmpeg-location={os.path.dirname(ffmpeg_exe)}",
            "--no-config",
            "--newline",
        ]
        if cookies_path:
            cmd += ["--cookies", cookies_path]

        if self.cfg.get("transcode_mp3", False):
            cmd += ["-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "0"]
        else:
            cmd += ["-f", "bestaudio[ext=m4a]/bestaudio", "--remux-video", "m4a"]

        if self.cfg.get("exclude_instrumentals", False):
            cmd += ["--reject-title", "instrumental"]

        cmd += ["-o", out_tmpl, "--no-playlist"]

        if src_url:
            spec = src_url
        else:
            title = row.get("Track Name") or row.get("Track name") or ""
            artist_raw = row.get("Artist Name(s)") or row.get("Artist name") or ""
            artist_primary = re.split(r'[,/&]| feat\.| ft\.', artist_raw, flags=re.I)[0].strip()
            q = " ".join([title, artist_primary]).strip() or title or artist_primary
            if self.cfg.get("deep_search", True):
                spec = _choose_best_youtube(self.ytdlp_exe, q, dur_ms, artist_primary, cookies_path)
            else:
                spec = f"ytsearch1:{q}"
        cmd += [spec]

        p = popen_quiet(cmd, text=True)

        stderr_q = queue.Queue()
        stdout_q = queue.Queue()

        def _pump(stream, qout):
            for line in iter(stream.readline, ""):
                qout.put(line)
            stream.close()

        t1 = threading.Thread(target=_pump, args=(p.stderr, stderr_q), daemon=True)
        t2 = threading.Thread(target=_pump, args=(p.stdout, stdout_q), daemon=True)
        t1.start(); t2.start()

        prog_re = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%.*?(?:at\s+([^\s]+/s))?.*?(?:ETA\s+([\d:\.]+))?", re.I)

        while True:
            if self.cancel.is_set():
                try: p.terminate()
                except Exception: pass
                try:
                    for _ in range(20):
                        if p.poll() is not None: break
                        time.sleep(0.05)
                    if p.poll() is None:
                        p.kill()
                except Exception:
                    pass
                self.item_cb('error', {'idx': idx, 'message': 'Cancelled'})
                return

            try:
                while True:
                    line = stderr_q.get_nowait()
                    m = prog_re.search(line)
                    if m:
                        pct = float(m.group(1))
                        spd = m.group(2) or None
                        eta = m.group(3) or None
                        self.item_cb('progress', {'idx': idx, 'percent': pct, 'speed': spd, 'eta': eta})
            except queue.Empty:
                pass

            try:
                while True:
                    _ = stdout_q.get_nowait()
            except queue.Empty:
                pass

            if p.poll() is not None:
                break
            time.sleep(0.05)

        rc = p.returncode
        if rc == 0:
            self.item_cb('done', {'idx': idx})
        else:
            # Collect last stderr lines for a meaningful error
            err_lines = []
            try:
                while True:
                    err_lines.append(stderr_q.get_nowait().strip())
            except queue.Empty:
                pass
            tail = [ln for ln in err_lines[-20:] if ln]
            concise = next((ln for ln in reversed(tail)
                            if "ERROR" in ln or "HTTP" in ln or "403" in ln or "404" in ln or "SSL" in ln), None)
            msg = concise or ("\n".join(tail) if tail else "Unknown download error")
            self.item_cb('error', {'idx': idx, 'message': msg})

    def _write_m3u(self, out_dir: str, playlist_name: str):
        files = [f for f in os.listdir(out_dir) if f.lower().endswith((".mp3", ".m4a"))]
        def sort_key(fn):
            m = re.match(r"^\s*(\d+)\s*[-_\.]\s*", fn)
            if m:
                return (0, int(m.group(1)))
            return (1, os.path.getctime(os.path.join(out_dir, fn)))
        files.sort(key=sort_key)

        m3u_path = os.path.join(out_dir, f"{playlist_name}.m3u")
        with open(m3u_path, "w", encoding="utf-8") as m3u:
            m3u.write("#EXTM3U\n")
            for fn in files:
                title = os.path.splitext(fn)[0]
                m3u.write(f"#EXTINF:-1,{title}\n")
                m3u.write(f"{fn}\n")
