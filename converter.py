# converter.py
from __future__ import annotations
import csv
import json
import os
import re
import shlex
import sys
import shutil
import threading
import time
import logging
import subprocess
import unicodedata
from pathlib import Path
from typing import Callable, Optional, Sequence, List
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from difflib import SequenceMatcher

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

_AUDIO_EXTS = {
    "mp3", "m4a", "aac", "wav", "flac", "aiff", "aif",
    "opus", "ogg", "oga", "vorbis", "webm", "mp4", "mka",
}

_BAD_VARIANTS = {
    "live",
    "remix",
    "karaoke",
    "nightcore",
    "sped up",
    "slowed",
    "reverb",
    "instrumental",
    "cover",
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
        self.output_mode: str = self._resolve_output_mode(self.config)
        self.output_format: str = self._resolve_output_format(self.config)
        self.strict_match: bool = bool(self.config.get("strict_match", False))
        self.match_candidates: int = max(3, min(15, int(self.config.get("match_candidates", 8))))
        self.generate_m3u: bool = bool(self.config.get("generate_m3u", True))
        self.exclude_instr: bool = bool(self.config.get("exclude_instrumentals", False))
        self.incremental: bool = bool(self.config.get("incremental_update", True))
        self.concurrency: int = max(1, min(8, int(self.config.get("concurrency", 3))))  # pistes en parallèle
        self._segments: int = max(1, min(8, self.concurrency))  # parallélisme segments yt-dlp
        self.auto_best: bool = self.output_mode == "auto"

        # pour la M3U
        self._made_files_lock = threading.Lock()
        self._made_files: List[tuple[int, str]] = []
        self._fmt_entry = _FORMAT_MAP[self.output_format] if not self.auto_best else None

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
        ext_final = self._fmt_entry.get("ext", "mp3") if self._fmt_entry else None
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
                if self.auto_best:
                    dest = out_dir / f"{base_name}.%(ext)s"
                else:
                    dest = out_dir / f"{base_name}.{ext_final}"

                futures.append(
                    pool.submit(self._process_one, idx, t, str(dest), str(out_dir), base_name)
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
                ordered = [name for _, name in sorted(self._made_files, key=lambda x: x[0])]
                with m3u.open("w", encoding="utf-8", newline="\n") as f:
                    for name in ordered:
                        f.write(name + "\n")
                log.info("CONV: M3U generated: %s", m3u)
            except Exception:
                log.exception("CONV: failed generating M3U")

        return str(out_dir)

    # ------------------------------ per-track worker ------------------------------

    def _process_one(self, idx: int, t: dict, dest_path: str, out_dir: str, base_name: str):
        """Télécharge/convertit une piste (thread worker)."""
        if self.cancel_event.is_set():
            return

        pretty_title = self._pretty_title(t)
        out_dir_p = Path(out_dir)
        fmt_entry = self._fmt_entry
        dest_final = Path(dest_path)

        # In auto mode we keep best available audio format and extension.
        if self.auto_best:
            existing = self._find_existing_auto_file(out_dir_p, base_name)
            if self.incremental and existing is not None:
                log.info("CONV: skip existing auto (%s)", existing.name)
                fmt_existing = self._format_label_from_path(existing)
                self.item_cb("init", {"idx": idx, "title": pretty_title, "format": fmt_existing})
                self.item_cb("done", {"idx": idx, "format": fmt_existing})
                with self._made_files_lock:
                    self._made_files.append((idx, existing.name))
                return
            needs_aiff = False
            dl_target = dest_final
            before_files = set(str(p) for p in self._list_matching_audio_files(out_dir_p, base_name))
        else:
            assert fmt_entry is not None
            needs_aiff = bool(fmt_entry.get("needs_aiff"))
            dl_target = dest_final if not needs_aiff else dest_final.with_suffix(".tmp.wav")
            before_files = set()

        # UI row init
        self.item_cb("init", {"idx": idx, "title": pretty_title, "format": self._selected_format_label()})

        # incrémental
        if (not self.auto_best) and self.incremental and dest_final.exists() and dest_final.stat().st_size > 0:
            log.info("CONV: skip existing (%s)", dest_final.name)
            self.item_cb("done", {"idx": idx, "format": self.output_format.upper()})
            with self._made_files_lock:
                self._made_files.append((idx, dest_final.name))
            return

        # Construire l’URL et la commande
        url = t.get("source_url") or t.get("track_uri")
        if not url:
            if self.strict_match:
                self.status_cb(f"Matching best source for {pretty_title}…")
                best = self._pick_best_youtube_match(t)
                if not best:
                    self.item_cb(
                        "error",
                        {"idx": idx, "message": f"No confident YouTube match found for: {pretty_title}"},
                    )
                    return
                url = best["url"]
                self.item_cb(
                    "match",
                    {
                        "idx": idx,
                        "title": best.get("title", ""),
                        "channel": best.get("channel", ""),
                        "score": round(float(best.get("score", 0.0)), 2),
                    },
                )
            else:
                url = self._build_search_query(t)
        cmd = self._build_ytdlp_cmd(url=url, out_path=str(dl_target), fmt_entry=fmt_entry)

        # Statut
        if self.auto_best:
            self.status_cb(f"Downloading {pretty_title}… (AUTO, best available)")
        else:
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

        if self.auto_best:
            produced = self._find_new_auto_file(out_dir_p, base_name, before_files)
            fmt_final = self._format_label_from_path(produced) if produced is not None else "AUTO"
            self.item_cb("done", {"idx": idx, "format": fmt_final})
            if produced is not None:
                with self._made_files_lock:
                    self._made_files.append((idx, produced.name))
            return

        self.item_cb("done", {"idx": idx, "format": self.output_format.upper()})
        with self._made_files_lock:
            self._made_files.append((idx, dest_final.name))

    # ------------------------------ internals ------------------------------

    def _resolve_output_format(self, cfg: dict) -> str:
        fmt = (cfg.get("output_format") or "").strip().lower()
        if fmt == "auto":
            return "mp3"
        if fmt == "aif":
            fmt = "aiff"
        if fmt and fmt in _FORMAT_MAP:
            return fmt
        if cfg.get("transcode_mp3"):
            return "mp3"
        return "mp3"

    def _resolve_output_mode(self, cfg: dict) -> str:
        mode = (cfg.get("output_mode") or "").strip().lower()
        if mode in {"auto", "manual"}:
            return mode
        # Backward-compatible fallback: output_format=auto implies auto mode.
        if (cfg.get("output_format") or "").strip().lower() == "auto":
            return "auto"
        return "manual"

    def _list_matching_audio_files(self, out_dir: Path, base_name: str) -> list[Path]:
        files = [p for p in out_dir.glob(f"{base_name}.*") if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files

    def _find_existing_auto_file(self, out_dir: Path, base_name: str) -> Path | None:
        for p in self._list_matching_audio_files(out_dir, base_name):
            ext = p.suffix.lower().lstrip(".")
            if ext in _AUDIO_EXTS and p.stat().st_size > 0:
                return p
        return None

    def _find_new_auto_file(self, out_dir: Path, base_name: str, before_files: set[str]) -> Path | None:
        candidates = self._list_matching_audio_files(out_dir, base_name)
        for p in candidates:
            if str(p) not in before_files and p.stat().st_size > 0:
                return p
        return self._find_existing_auto_file(out_dir, base_name)

    def _selected_format_label(self) -> str:
        return "AUTO" if self.auto_best else self.output_format.upper()

    @staticmethod
    def _format_label_from_path(path: Path | None) -> str:
        if path is None:
            return "AUTO"
        ext = path.suffix.lower().lstrip(".")
        if not ext:
            return "AUTO"
        if ext == "aif":
            return "AIFF"
        return ext.upper()

    def _pick_best_youtube_match(self, t: dict) -> dict | None:
        query = self._build_search_terms(t)
        candidates = self._search_youtube_candidates(query, self.match_candidates)
        if not candidates:
            return None

        best: dict | None = None
        best_score = -1.0
        for cand in candidates:
            score = self._score_match_candidate(t, cand)
            if score > best_score:
                best_score = score
                best = dict(cand)
                best["score"] = score

        if not best:
            return None
        if best_score < 0.58:
            return None
        return best

    def _search_youtube_candidates(self, query: str, limit: int) -> list[dict]:
        if self.cancel_event.is_set():
            return []
        cmd = _find_yt_dlp() + [
            "--no-warnings",
            "--ignore-errors",
            "--skip-download",
            "--print-json",
            f"ytsearch{limit}:{query}",
        ]

        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                startupinfo=startupinfo,
                creationflags=creationflags,
                timeout=50,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

        out: list[dict] = []
        for raw in (proc.stdout or "").splitlines():
            line = raw.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue

            url = str(item.get("webpage_url") or item.get("url") or "").strip()
            if not url:
                vid = str(item.get("id") or "").strip()
                if vid:
                    url = f"https://www.youtube.com/watch?v={vid}"
            if not url:
                continue

            duration = item.get("duration")
            try:
                duration_s = int(duration) if duration is not None else None
            except Exception:
                duration_s = None

            out.append(
                {
                    "url": url,
                    "title": str(item.get("title") or ""),
                    "channel": str(item.get("channel") or item.get("uploader") or ""),
                    "duration_s": duration_s,
                }
            )
        return out

    def _score_match_candidate(self, t: dict, cand: dict) -> float:
        src_title = _norm_text(str(t.get("title") or ""))
        src_artists = _norm_text(str(t.get("artists") or ""))
        src_primary_artist = _norm_text(str((str(t.get("artists") or "").split(",")[0]).strip()))
        src_raw_title = str(t.get("title") or "").lower()

        cand_title_raw = str(cand.get("title") or "")
        cand_channel_raw = str(cand.get("channel") or "")
        cand_title = _norm_text(cand_title_raw)
        cand_channel = _norm_text(cand_channel_raw)
        cand_hay = f"{cand_title} {cand_channel}".strip()

        title_ratio = SequenceMatcher(None, src_title, cand_title).ratio() if src_title and cand_title else 0.0

        artist_score = 0.0
        if src_primary_artist:
            if src_primary_artist in cand_hay:
                artist_score = 1.0
            else:
                tokens = [tk for tk in src_primary_artist.split() if len(tk) > 1]
                if tokens:
                    found = sum(1 for tk in tokens if tk in cand_hay)
                    artist_score = found / len(tokens)
        elif src_artists:
            artist_score = 0.4

        duration_score = 0.2
        src_ms = t.get("duration_ms")
        cand_s = cand.get("duration_s")
        if isinstance(src_ms, int) and src_ms > 0 and isinstance(cand_s, int) and cand_s > 0:
            diff = abs((src_ms / 1000.0) - float(cand_s))
            if diff <= 3:
                duration_score = 1.0
            elif diff <= 8:
                duration_score = 0.8
            elif diff <= 15:
                duration_score = 0.55
            elif diff <= 30:
                duration_score = 0.3
            elif diff <= 45:
                duration_score = 0.1
            else:
                duration_score = -0.25

        penalties = 0.0
        cand_low = cand_title_raw.lower()
        for bad in _BAD_VARIANTS:
            if bad in cand_low and bad not in src_raw_title:
                penalties += 0.08

        score = (0.58 * title_ratio) + (0.27 * artist_score) + (0.20 * duration_score) - penalties
        return max(0.0, min(1.0, score))

    def _rows_to_jobs(self, rows: list[dict]) -> list[dict]:
        jobs = []
        for r in rows:
            title = (r.get("Track Name") or "").strip()
            artists = (r.get("Artist Name(s)") or "").strip()
            album = (r.get("Album Name") or "").strip()
            duration_raw = (r.get("Duration (ms)") or "").strip()
            url = (r.get("Source URL") or "").strip()
            uri = (r.get("Track URI") or "").strip()
            if not title and not artists and not url and not uri:
                continue
            duration_ms = None
            if duration_raw:
                try:
                    duration_ms = int(float(duration_raw))
                except Exception:
                    duration_ms = None
            jobs.append({
                "title": title,
                "artists": artists,
                "album": album,
                "duration_ms": duration_ms,
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

    def _build_search_terms(self, t: dict) -> str:
        artist = (t.get("artists") or "").split(",")[0].strip()
        title = t.get("title") or ""
        query = f"{artist} {title}".strip()
        if self.deep_search:
            query += " audio"
        return query

    def _build_search_query(self, t: dict) -> str:
        query = self._build_search_terms(t)
        yts = f"ytsearch1:{query}"
        log.debug("CONV: search query -> %s", yts)
        return yts

    def _build_ytdlp_cmd(self, url: str, out_path: str, fmt_entry: dict | None) -> list[str]:
        cmd = _find_yt_dlp()
        cmd += [
            "--newline",
            "--no-playlist",
            "--ignore-errors",
            "--no-overwrites",
            "-o", out_path,
            "-N", str(self._segments),              # parallélisme segments côté yt-dlp
            "-f", "bestaudio/best",
            "-x",
            "--add-metadata",
            "--embed-thumbnail",
        ]
        if self.auto_best:
            cmd += ["--audio-format", "best"]
        else:
            assert fmt_entry is not None
            audio_fmt = fmt_entry.get("yt_fmt", "mp3")
            audio_quality = fmt_entry.get("quality", "0")
            cmd += [
                "--audio-format", audio_fmt,
                "--audio-quality", audio_quality,
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
        low = line.lower()
        if (
            low.startswith("[extractaudio]")
            or low.startswith("[ffmpeg]")
            or "post-process" in low
            or "postprocess" in low
        ):
            self.item_cb("converting", {"idx": idx, "detail": line})
            return

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


def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[\(\)\[\]\{\}\|_/\\\-]+", " ", s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _looks_instrumental(title: str) -> bool:
    t = (title or "").lower()
    return "instrumental" in t or "karaoke" in t or "8d audio" in t
