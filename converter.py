# converter.py
from __future__ import annotations
import csv
import os
import re
import shlex
import sys
import shutil
import threading
import time
import logging
import subprocess
from pathlib import Path
from typing import Callable, Optional, Sequence, List
from concurrent.futures import ThreadPoolExecutor, as_completed, Future

log = logging.getLogger(__name__)

StatusCB = Callable[[str], None]
ProgressCB = Callable[[int, int], None]
ItemCB = Callable[[str, dict], None]


_FORMAT_MAP = {
    "mp3":  {"yt_fmt": "mp3",  "ext": "mp3",  "quality": "0"},
    "m4a":  {"yt_fmt": "m4a",  "ext": "m4a",  "quality": "0"},
    "aac":  {"yt_fmt": "aac",  "ext": "aac",  "quality": "0"},
    "wav":  {"yt_fmt": "wav",  "ext": "wav"},
    "flac": {"yt_fmt": "flac", "ext": "flac"},
    # yt-dlp cannot output AIFF directly; we download WAV then convert to AIFF.
    "aiff": {"yt_fmt": "wav", "ext": "aiff", "needs_aiff": True},
}


# ========================== BINARIES AUTO-DETECT (PyInstaller friendly) ==========================

def _resource_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent

def _which(names: Sequence[str]) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None

def _find_yt_dlp() -> list[str]:
    rd = _resource_dir()
    candidates = [
        rd / "yt-dlp" / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp"),
        rd / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp"),
        Path(__file__).resolve().parent / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp"),
    ]
    for c in candidates:
        if c.exists():
            return [str(c)]

    found = _which(["yt-dlp", "yt-dlp.exe"])
    if found:
        return [found]

    return [sys.executable, "-m", "yt_dlp"]

def _find_ffmpeg_dir() -> str | None:
    rd = _resource_dir()
    dirs = [
        rd / "ffmpeg",
        rd / "ffmpeg" / "bin",
        Path(__file__).resolve().parent / "ffmpeg",
        Path(__file__).resolve().parent / "ffmpeg" / "bin",
    ]
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for d in dirs:
        exe = d / exe_name
        if exe.exists():
            return str(d)

    if shutil.which(exe_name):
        return None
    return None


def _ffmpeg_exe() -> str:
    ffdir = _find_ffmpeg_dir()
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    return str(Path(ffdir) / exe) if ffdir else exe


# ========================================= CONVERTER ============================================

class Converter:
    def __init__(
        self,
        config: dict,
        status_cb: Optional[StatusCB] = None,
        progress_cb: Optional[ProgressCB] = None,
        item_cb: Optional[ItemCB] = None,
        cancel_event: Optional[threading.Event] = None,
    ):
        self.config = config or {}
        self.status_cb = status_cb or (lambda s: None)
        self.progress_cb = progress_cb or (lambda c, m: None)
        self.item_cb = item_cb or (lambda k, d: None)
        self.cancel_event = cancel_event or threading.Event()

        # options
        self.prefix_numbers: bool = bool(self.config.get("prefix_numbers", False))
        self.deep_search: bool = bool(self.config.get("deep_search", True))
        self.transcode_mp3: bool = bool(self.config.get("transcode_mp3", False))  # legacy toggle
        self.output_format: str = self._resolve_output_format(self.config)
        self.generate_m3u: bool = bool(self.config.get("generate_m3u", True))
        self.exclude_instr: bool = bool(self.config.get("exclude_instrumentals", False))
        self.incremental: bool = bool(self.config.get("incremental_update", True))
        self.concurrency: int = max(1, min(8, int(self.config.get("concurrency", 3))))  # pistes en parallèle
        self._segments: int = max(1, min(8, self.concurrency))  # parallélisme segments yt-dlp

        # pour la M3U
        self._made_files_lock = threading.Lock()
        self._made_files: List[str] = []
        self._fmt_entry = _FORMAT_MAP[self.output_format]

    # ------------------------------ public API ------------------------------

    def convert_from_csv(self, csv_path: str, output_folder: str, playlist_hint: Optional[str] = None) -> str:
        """
        Lit un CSV (colonnes: Track Name, Artist Name(s), Album Name, Duration (ms), [Source URL], [Track URI])
        et télécharge les pistes via yt-dlp, en parallèle jusqu’à self.concurrency.
        Retourne le dossier de sortie.
        """
        out_base = Path(output_folder)
        out_dir = out_base
        if playlist_hint:
            safe = _sanitize_filename(playlist_hint, for_dir=True)
            if safe:
                out_dir = out_base / safe
        out_dir.mkdir(parents=True, exist_ok=True)

        rows = _read_csv(csv_path)
        tracks = self._rows_to_jobs(rows)

        if self.exclude_instr:
            tracks = [t for t in tracks if not _looks_instrumental(t["title"])]

        total = len(tracks)
        self.item_cb("conv_init", {"new": total})
        self.status_cb(f"Preparing {total} tracks…")
        log.info("CONV: total tracks to process: %s (out_dir=%s, workers=%s)", total, out_dir, self.concurrency)

        # Lancement parallèle : un worker par piste
        ext_final = self._fmt_entry.get("ext", "mp3")
        futures: list[Future] = []
        with ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="dl") as pool:
            for idx, t in enumerate(tracks, start=1):
                if self.cancel_event.is_set():
                    break
                # calcule le nom final (pour incrémental)
                pretty_title = self._pretty_title(t)
                base_name = _sanitize_filename(pretty_title)
                if self.prefix_numbers:
                    base_name = f"{idx:03d} - {base_name}"
                dest = out_dir / f"{base_name}.{ext_final}"

                futures.append(
                    pool.submit(self._process_one, idx, t, str(dest))
                )

            # on attend la fin (les callbacks UI/progression sont envoyés depuis chaque worker)
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception:
                    # déjà loggé dans le worker → on continue
                    pass

        # M3U
        if self.generate_m3u and self._made_files:
            m3u = out_dir / "playlist.m3u8"
            try:
                # garder l'ordre par index (les noms sont déjà préfixés si demandé)
                with m3u.open("w", encoding="utf-8", newline="\n") as f:
                    for name in self._made_files:
                        f.write(name + "\n")
                log.info("CONV: M3U generated: %s", m3u)
            except Exception:
                log.exception("CONV: failed generating M3U")

        return str(out_dir)

    # ------------------------------ per-track worker ------------------------------

    def _process_one(self, idx: int, t: dict, dest_path: str):
        """Télécharge/convertit une piste (thread worker)."""
        if self.cancel_event.is_set():
            return

        pretty_title = self._pretty_title(t)
        dest_final = Path(dest_path)
        fmt_entry = self._fmt_entry
        needs_aiff = bool(fmt_entry.get("needs_aiff"))
        dl_target = dest_final if not needs_aiff else dest_final.with_suffix(".tmp.wav")

        # UI row init
        self.item_cb("init", {"idx": idx, "title": pretty_title})

        # incrémental
        if self.incremental and dest_final.exists() and dest_final.stat().st_size > 0:
            log.info("CONV: skip existing (%s)", dest_final.name)
            self.item_cb("done", {"idx": idx})
            with self._made_files_lock:
                self._made_files.append(dest_final.name)
            return

        # Construire l’URL et la commande
        url = t.get("source_url") or t.get("track_uri")
        if not url:
            url = self._build_search_query(t)
        cmd = self._build_ytdlp_cmd(url=url, out_path=str(dl_target), fmt_entry=fmt_entry)

        # Statut
        self.status_cb(f"Downloading {pretty_title}… ({self.output_format.upper()}, 44.1 kHz)")

        code = self._run_ytdlp_stream(
            cmd,
            idx=idx,
            on_progress=self._on_progress_line,
            cancel_event=self.cancel_event,
        )

        if self.cancel_event.is_set():
            log.warning("CONV: cancelled during download (idx=%s)", idx)
            self.item_cb("cancel_all", {})
            return

        if code == 127:
            msg = (
                "yt-dlp n'est pas disponible. Installe-le (pip install yt-dlp) "
                "ou place 'yt-dlp(.exe)' et 'ffmpeg' avec l'application."
            )
            log.error("CONV: %s", msg)
            self.item_cb("error", {"idx": idx, "message": msg})
            return

        if code != 0:
            msg = f"yt-dlp failed with code {code} for: {pretty_title}"
            log.error("CONV: %s", msg)
            self.item_cb("error", {"idx": idx, "message": msg})
            return

        if needs_aiff:
            try:
                self._convert_wav_to_aiff(temp_path=str(dl_target), final_path=str(dest_final))
            except Exception as e:
                log.exception("CONV: failed to convert WAV to AIFF")
                self.item_cb("error", {"idx": idx, "message": f"AIFF conversion failed: {e}"})
                return
            try:
                if Path(dl_target).exists():
                    Path(dl_target).unlink()
            except Exception:
                pass

        self.item_cb("done", {"idx": idx})
        with self._made_files_lock:
            self._made_files.append(dest_final.name)

    # ------------------------------ internals ------------------------------

    def _resolve_output_format(self, cfg: dict) -> str:
        fmt = (cfg.get("output_format") or "").strip().lower()
        if fmt == "aif":
            fmt = "aiff"
        if fmt and fmt in _FORMAT_MAP:
            return fmt
        if cfg.get("transcode_mp3"):
            return "mp3"
        return "mp3"

    def _rows_to_jobs(self, rows: list[dict]) -> list[dict]:
        jobs = []
        for r in rows:
            title = (r.get("Track Name") or "").strip()
            artists = (r.get("Artist Name(s)") or "").strip()
            album = (r.get("Album Name") or "").strip()
            url = (r.get("Source URL") or "").strip()
            uri = (r.get("Track URI") or "").strip()
            if not title and not artists and not url and not uri:
                continue
            jobs.append({
                "title": title,
                "artists": artists,
                "album": album,
                "source_url": url if url else None,
                "track_uri": uri if uri else None,
            })
        return jobs

    def _pretty_title(self, t: dict) -> str:
        a = t.get("artists") or ""
        nm = t.get("title") or ""
        if a and nm:
            return f"{a} - {nm}"
        return nm or a or "Unknown"

    def _build_search_query(self, t: dict) -> str:
        artist = (t.get("artists") or "").split(",")[0].strip()
        title = t.get("title") or ""
        query = f"{artist} {title}".strip()
        if self.deep_search:
            query += " audio"
        yts = f"ytsearch1:{query}"
        log.debug("CONV: search query -> %s", yts)
        return yts

    def _build_ytdlp_cmd(self, url: str, out_path: str, fmt_entry: dict) -> list[str]:
        cmd = _find_yt_dlp()
        audio_fmt = fmt_entry.get("yt_fmt", "mp3")
        audio_quality = fmt_entry.get("quality", "0")
        cmd += [
            "--newline",
            "--no-playlist",
            "--ignore-errors",
            "--no-overwrites",
            "-o", out_path,
            "-N", str(self._segments),              # parallélisme segments côté yt-dlp
            "-f", "bestaudio/best",
            "-x",
            "--audio-format", audio_fmt,
            "--audio-quality", audio_quality,
            "--add-metadata",
            "--embed-thumbnail",
            "--postprocessor-args", "FFmpegExtractAudio:-ar 44100",
        ]
        ffdir = _find_ffmpeg_dir()
        if ffdir:
            cmd += ["--ffmpeg-location", ffdir]
        cmd.append(url)
        log.debug("CONV: yt-dlp cmd: %s", " ".join(shlex.quote(c) for c in cmd))
        return cmd

    def _convert_wav_to_aiff(self, temp_path: str, final_path: str):
        exe = _ffmpeg_exe()
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        cmd = [
            exe,
            "-y",
            "-i", temp_path,
            "-ar", "44100",
            "-acodec", "pcm_s16be",
            "-f", "aiff",
            final_path,
        ]
        log.debug("CONV: ffmpeg AIFF cmd: %s", " ".join(shlex.quote(c) for c in cmd))
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              startupinfo=startupinfo, creationflags=creationflags)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or "ffmpeg failed")

    # ---- streaming / parsing de la progression yt-dlp ----

    _RGX_PROGRESS = re.compile(
        r"^\[download\]\s+(?P<pct>\d{1,3}(?:\.\d)?)%\s+of.*?(?:at\s+(?P<speed>[0-9\.]+[KMG]?i?B/s))?(?:\s+ETA\s+(?P<eta>\d{2}:\d{2}))?",
        re.IGNORECASE
    )

    def _on_progress_line(self, idx: int, line: str):
        m = self._RGX_PROGRESS.search(line)
        if m:
            pct = float(m.group("pct"))
            speed = m.group("speed")
            eta = m.group("eta")
            self.item_cb("progress", {"idx": idx, "percent": pct, "speed": speed, "eta": eta})

    def _run_ytdlp_stream(
        self,
        cmd: list[str],
        idx: int,
        on_progress: Callable[[int, str], None],
        cancel_event: threading.Event,
    ) -> int:
        """
        Lance yt-dlp et stream stdout ligne par ligne.
        - Pas de fenêtre console (Windows)
        - Log INFO chaque ligne
        - Parse progression et pousse à l'UI
        - Arrêt propre si cancel_event
        """
        # --- empêcher l'ouverture d'une console sur Windows ---
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                bufsize=1,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
        except FileNotFoundError:
            log.error("yt-dlp introuvable (ni binaire embarqué, ni PATH, ni module).")
            return 127

        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if not line:
                    continue
                log.info("yt-dlp[%03d]: %s", idx, line)
                on_progress(idx, line)
                if cancel_event.is_set():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    break
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass

        try:
            return proc.wait(timeout=20)
        except Exception:
            return 1


# ========================================= HELPERS ==============================================

def _read_csv(path: str) -> list[dict]:
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            rows.append(r)
    log.info("CONV: CSV loaded (%s rows) from %s", len(rows), path)
    return rows


def _sanitize_filename(name: str, for_dir: bool = False) -> str:
    name = name.strip().replace("\n", " ")
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > 150:
        name = name[:150].rstrip()
    if not name:
        name = "untitled"
    if for_dir:
        name = name.rstrip(". ")
    return name


def _looks_instrumental(title: str) -> bool:
    t = (title or "").lower()
    return "instrumental" in t or "karaoke" in t or "8d audio" in t
