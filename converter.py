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
from typing import Callable, Optional, Sequence

log = logging.getLogger(__name__)

StatusCB = Callable[[str], None]
ProgressCB = Callable[[int, int], None]
ItemCB = Callable[[str, dict], None]


# ========================== BINARIES AUTO-DETECT (PyInstaller friendly) ==========================

def _resource_dir() -> Path:
    """
    Retourne le répertoire ressources du bundle (PyInstaller) ou le dossier du script.
    - Quand packagé : sys._MEIPASS pointe sur un dossier temporaire qui contient les datas (ffmpeg/yt-dlp).
    - En dev : on retombe sur le dossier du fichier courant.
    """
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
    """
    Cherche yt-dlp dans l'ordre :
      1) _MEIPASS/yt-dlp/yt-dlp(.exe) (comme dans ton .spec)
      2) _MEIPASS/yt-dlp(.exe)
      3) dossier source (développement) : ./yt-dlp(.exe)
      4) PATH
      5) fallback module: python -m yt_dlp
    Retourne argv (liste) à exécuter.
    """
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

    # Dernier recours : module Python
    return [sys.executable, "-m", "yt_dlp"]

def _find_ffmpeg_dir() -> str | None:
    """
    Dossier à fournir à --ffmpeg-location si utile.
      - _MEIPASS/ffmpeg  (Windows: ffmpeg.exe ici)
      - _MEIPASS/ffmpeg/bin (macOS/Linux)
      - côté source (dev)
      - sinon None si ffmpeg dispo via PATH
    """
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
        self.transcode_mp3: bool = bool(self.config.get("transcode_mp3", False))
        self.generate_m3u: bool = bool(self.config.get("generate_m3u", True))
        self.exclude_instr: bool = bool(self.config.get("exclude_instrumentals", False))
        self.incremental: bool = bool(self.config.get("incremental_update", True))
        self.concurrency: int = int(self.config.get("concurrency", 3))

    # ------------------------------ public API ------------------------------

    def convert_from_csv(self, csv_path: str, output_folder: str, playlist_hint: Optional[str] = None) -> str:
        """
        Lit un CSV (colonnes: Track Name, Artist Name(s), Album Name, Duration (ms), [Source URL], [Track URI])
        et télécharge les pistes via yt-dlp, avec transcodage optionnel en MP3 VBR0.
        Retourne le dossier de sortie (souvent output_folder / playlist_hint s'il est fourni).
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

        # Option d'exclusion "instrumental"
        if self.exclude_instr:
            tracks = [t for t in tracks if not _looks_instrumental(t["title"])]

        total = len(tracks)
        self.item_cb("conv_init", {"new": total})
        self.status_cb(f"Preparing {total} tracks…")
        log.info("CONV: total tracks to process: %s (out_dir=%s)", total, out_dir)

        made_files: list[str] = []
        for idx, t in enumerate(tracks, start=1):
            if self.cancel_event.is_set():
                log.warning("CONV: cancel requested, stopping")
                self.item_cb("cancel_all", {})
                break

            # UI row init
            pretty_title = self._pretty_title(t)
            self.item_cb("init", {"idx": idx, "title": pretty_title})

            # Destination filename
            ext = "mp3" if self.transcode_mp3 else "m4a"
            base_name = _sanitize_filename(pretty_title)
            if self.prefix_numbers:
                base_name = f"{idx:03d} - {base_name}"
            dest = out_dir / f"{base_name}.{ext}"

            if self.incremental and dest.exists() and dest.stat().st_size > 0:
                log.info("CONV: skip existing (%s)", dest.name)
                self.item_cb("done", {"idx": idx})
                made_files.append(dest.name)
                continue

            # Construire la commande yt-dlp
            url = t.get("source_url") or t.get("track_uri")
            if not url:
                url = self._build_search_query(t)

            cmd = self._build_ytdlp_cmd(url=url, out_path=str(dest), want_mp3=self.transcode_mp3)

            # Lancer yt-dlp et streamer la progression
            self.status_cb(f"Downloading {pretty_title}…")
            code = self._run_ytdlp_stream(
                cmd,
                idx=idx,
                on_progress=self._on_progress_line,
                cancel_event=self.cancel_event,
            )

            if self.cancel_event.is_set():
                log.warning("CONV: cancelled during download (idx=%s)", idx)
                self.item_cb("cancel_all", {})
                break

            if code == 127:
                msg = (
                    "yt-dlp n'est pas disponible. Installe-le (pip install yt-dlp) "
                    "ou place 'yt-dlp(.exe)' et 'ffmpeg' avec l'application."
                )
                log.error("CONV: %s", msg)
                self.item_cb("error", {"idx": idx, "message": msg})
                continue

            if code != 0:
                msg = f"yt-dlp failed with code {code} for: {pretty_title}"
                log.error("CONV: %s", msg)
                self.item_cb("error", {"idx": idx, "message": msg})
                continue

            # Done
            self.item_cb("done", {"idx": idx})
            made_files.append(dest.name)

        # M3U
        if self.generate_m3u and made_files:
            m3u = out_dir / "playlist.m3u8"
            try:
                with m3u.open("w", encoding="utf-8", newline="\n") as f:
                    for name in made_files:
                        f.write(name + "\n")
                log.info("CONV: M3U generated: %s", m3u)
            except Exception:
                log.exception("CONV: failed generating M3U")

        return str(out_dir)

    # ------------------------------ internals ------------------------------

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
        # Favorise audio officiel : ajoute "audio" et enlève des termes bruyants
        artist = (t.get("artists") or "").split(",")[0].strip()
        title = t.get("title") or ""
        query = f"{artist} {title}".strip()
        if self.deep_search:
            query += " audio"
        yts = f"ytsearch1:{query}"
        log.debug("CONV: search query -> %s", yts)
        return yts

    def _build_ytdlp_cmd(self, url: str, out_path: str, want_mp3: bool) -> list[str]:
        # argv pointant vers le bon binaire/module yt-dlp
        cmd = _find_yt_dlp()
        # options yt-dlp
        cmd += [
            "--newline",
            "--no-playlist",
            "--ignore-errors",
            "--no-overwrites",
            "-o", out_path,
            "-N", str(max(1, min(8, self.concurrency))),  # parallélisme de téléchargement
            "-f", "bestaudio/best",
            "-x",  # extract audio
            "--audio-format", "mp3" if want_mp3 else "m4a",
            "--audio-quality", "0" if want_mp3 else "0",
            "--add-metadata",
            "--embed-thumbnail",
        ]
        ffdir = _find_ffmpeg_dir()
        if ffdir:
            cmd += ["--ffmpeg-location", ffdir]

        cmd.append(url)
        log.debug("CONV: yt-dlp cmd: %s", " ".join(shlex.quote(c) for c in cmd))
        return cmd

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
        - Loggue chaque ligne (INFO)
        - Parse les lignes de progression pour mettre à jour l'UI
        - Gère l'annulation via cancel_event
        """
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                bufsize=1,
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
    # enlever caractères interdits
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    # tronquer raisonnablement
    if len(name) > 150:
        name = name[:150].rstrip()
    # éviter noms vides
    if not name:
        name = "untitled"
    # si c'est un nom de dossier, éviter le point final Windows
    if for_dir:
        name = name.rstrip(". ")
    return name


def _looks_instrumental(title: str) -> bool:
    t = (title or "").lower()
    return "instrumental" in t or "karaoke" in t or "8d audio" in t
