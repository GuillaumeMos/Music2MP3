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
from ai_matcher import AIMatchAdvice, build_ai_match_advisor
from library_manifest import build_manifest, read_manifest, write_manifest

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

_BAD_CONTEXTS = {
    "1 hour",
    "2 hour",
    "album complet",
    "boiler room",
    "compilation",
    "continuous mix",
    "dj set",
    "full album",
    "full concert",
    "full mix",
    "full set",
    "hour mix",
    "live set",
    "playlist",
    "reaction",
    "set complet",
    "tutorial",
    "how to play",
    "lyrics",
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
        self.safe_search: bool = bool(self.config.get("safe_search", True))
        self.ai_match_enabled: bool = bool(self.config.get("ai_match_enabled", False))
        self.ai_match_gray_min: float = max(0.0, min(1.0, float(self.config.get("ai_match_gray_min", 0.30))))
        self.ai_match_min_confidence: float = max(0.0, min(1.0, float(self.config.get("ai_match_min_confidence", 0.72))))
        self.ai_match_accept_margin: float = max(0.0, min(0.4, float(self.config.get("ai_match_accept_margin", 0.12))))
        self.duration_min: int = max(0, int(self.config.get("duration_min", 30)))
        self.duration_max: int = max(self.duration_min or 1, int(self.config.get("duration_max", 600)))
        self.generate_m3u: bool = bool(self.config.get("generate_m3u", True))
        self.exclude_instr: bool = bool(self.config.get("exclude_instrumentals", False))
        self.incremental: bool = bool(self.config.get("incremental_update", True))
        self.concurrency: int = max(1, min(8, int(self.config.get("concurrency", 3))))  # pistes en parallèle
        self._segments: int = max(1, min(8, self.concurrency))  # parallélisme segments yt-dlp
        self.auto_best: bool = self.output_mode == "auto"
        self.append_to_existing_playlist: bool = bool(self.config.get("append_to_existing_playlist", False))

        # pour la M3U
        self._made_files_lock = threading.Lock()
        self._made_files: List[tuple[int, str]] = []
        self._manifest_lock = threading.Lock()
        self._manifest_entries: list[dict] = []
        self._match_details_lock = threading.Lock()
        self._match_details: dict[int, dict] = {}
        self._fmt_entry = _FORMAT_MAP[self.output_format] if not self.auto_best else None
        self._ai_match_advisor = build_ai_match_advisor(self.config)

    # ------------------------------ public API ------------------------------

    def convert_from_csv(
        self,
        csv_path: str,
        output_folder: str,
        playlist_hint: Optional[str] = None,
        source_info: Optional[dict] = None,
    ) -> str:
        """
        Lit un CSV (colonnes: Track Name, Artist Name(s), Album Name, Duration (ms), [Source URL], [Track URI])
        et télécharge les pistes via yt-dlp, en parallèle jusqu’à self.concurrency.
        Retourne le dossier de sortie.
        """
        out_base = Path(output_folder)
        out_dir = out_base
        if playlist_hint and not bool(self.config.get("sync_existing_playlist", False)):
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
                if self.append_to_existing_playlist and m3u.is_file():
                    previous_lines = [
                        line.strip()
                        for line in m3u.read_text(encoding="utf-8").splitlines()
                        if line.strip() and not line.lstrip().startswith("#")
                    ]
                    seen = set(previous_lines)
                    ordered = previous_lines + [name for name in ordered if name not in seen]
                with m3u.open("w", encoding="utf-8", newline="\n") as f:
                    for name in ordered:
                        f.write(name + "\n")
                log.info("CONV: M3U generated: %s", m3u)
            except Exception:
                log.exception("CONV: failed generating M3U")

        self._write_playlist_manifest(out_dir, playlist_hint, source_info)

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
                self.item_cb("done", {"idx": idx, "format": fmt_existing, "file": existing.name, "path": str(existing)})
                self._record_manifest_entry(idx, t, "skipped", existing.name, fmt_existing)
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
            self.item_cb("done", {"idx": idx, "format": self.output_format.upper(), "file": dest_final.name, "path": str(dest_final)})
            self._record_manifest_entry(idx, t, "skipped", dest_final.name, self.output_format.upper())
            with self._made_files_lock:
                self._made_files.append((idx, dest_final.name))
            return

        # Construire l’URL et la commande
        url = t.get("source_url") or t.get("track_uri")
        if not url:
            if self.safe_search or self.strict_match:
                self.status_cb(f"Matching best source for {pretty_title}…")
                best, reject_reason, best_url = self._pick_best_youtube_match(t)
                if not best:
                    if self.strict_match or self.safe_search:
                        self.item_cb(
                            "error",
                            {
                                "idx": idx,
                                "message": reject_reason or f"No safe YouTube match found for: {pretty_title}.",
                                "best_url": best_url,
                                "track": t,
                                "out_dir": str(out_dir),
                            },
                        )
                        self._record_manifest_entry(idx, t, "failed", None, self._selected_format_label(), reject_reason or "No safe YouTube match found")
                        return
                    url = self._build_search_query(t)
                else:
                    url = best["url"]
                    self._record_match_detail(idx, best)
                    self.item_cb(
                        "match",
                        {
                            "idx": idx,
                            "title": best.get("title", ""),
                            "channel": best.get("channel", ""),
                            "score": round(float(best.get("score", 0.0)), 2),
                            "score_details": best.get("score_details") or {},
                            "ai_confidence": best.get("ai_confidence"),
                            "ai_reason": best.get("ai_reason", ""),
                            "url": best.get("url", ""),
                        },
                    )
                    log.info(
                        "MATCH: %03d %s -> %s | score %.2f%s",
                        idx,
                        pretty_title,
                        best.get("title", ""),
                        float(best.get("score", 0.0)),
                        f" | AI {float(best.get('ai_confidence')):.2f}: {best.get('ai_reason')}"
                        if isinstance(best.get("ai_confidence"), (int, float)) else "",
                    )
            else:
                url = self._build_search_query(t)
        elif self._is_probable_soundcloud_set_url(url):
            self.item_cb(
                "error",
                {
                    "idx": idx,
                    "message": (
                        "Refusing to download a SoundCloud set/playlist URL as a single track. "
                        "Load the SoundCloud playlist first so each track gets its own Source URL."
                    ),
                },
            )
            self._record_manifest_entry(idx, t, "failed", None, self._selected_format_label(), "SoundCloud set URL used as a single track")
            return
        elif self._is_probable_bandcamp_album_url(url):
            self.item_cb(
                "error",
                {
                    "idx": idx,
                    "message": (
                        "Refusing to download a Bandcamp album URL as a single track. "
                        "Load the Bandcamp release first so each track gets its own Source URL."
                    ),
                },
            )
            self._record_manifest_entry(idx, t, "failed", None, self._selected_format_label(), "Bandcamp album URL used as a single track")
            return
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
            self._record_manifest_entry(idx, t, "failed", None, self._selected_format_label(), msg)
            return

        if code != 0:
            msg = f"yt-dlp failed with code {code} for: {pretty_title}"
            log.error("CONV: %s", msg)
            self.item_cb("error", {"idx": idx, "message": msg})
            self._record_manifest_entry(idx, t, "failed", None, self._selected_format_label(), msg)
            return

        if needs_aiff:
            try:
                self._convert_wav_to_aiff(temp_path=str(dl_target), final_path=str(dest_final))
            except Exception as e:
                log.exception("CONV: failed to convert WAV to AIFF")
                self.item_cb("error", {"idx": idx, "message": f"AIFF conversion failed: {e}"})
                self._record_manifest_entry(idx, t, "failed", None, self.output_format.upper(), f"AIFF conversion failed: {e}")
                return
            try:
                if Path(dl_target).exists():
                    Path(dl_target).unlink()
            except Exception:
                pass

        if self.auto_best:
            produced = self._find_new_auto_file(out_dir_p, base_name, before_files)
            fmt_final = self._format_label_from_path(produced) if produced is not None else "AUTO"
            self.item_cb(
                "done",
                {
                    "idx": idx,
                    "format": fmt_final,
                    "file": produced.name if produced is not None else "",
                    "path": str(produced) if produced is not None else "",
                },
            )
            if produced is not None:
                self._record_manifest_entry(idx, t, "done", produced.name, fmt_final)
                with self._made_files_lock:
                    self._made_files.append((idx, produced.name))
            else:
                self._record_manifest_entry(idx, t, "done", None, fmt_final)
            return

        self.item_cb("done", {"idx": idx, "format": self.output_format.upper(), "file": dest_final.name, "path": str(dest_final)})
        self._record_manifest_entry(idx, t, "done", dest_final.name, self.output_format.upper())
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

    def _manifest_settings(self) -> dict:
        keys = [
            "prefix_numbers",
            "deep_search",
            "safe_search",
            "strict_match",
            "match_candidates",
            "ai_match_enabled",
            "ai_match_provider",
            "ai_match_model",
            "ai_match_gray_min",
            "ai_match_min_confidence",
            "ai_match_accept_margin",
            "output_mode",
            "output_format",
            "output_format_manual",
            "generate_m3u",
            "exclude_instrumentals",
            "incremental_update",
            "concurrency",
            "duration_min",
            "duration_max",
        ]
        return {key: self.config.get(key) for key in keys if key in self.config}

    def _record_manifest_entry(
        self,
        idx: int,
        t: dict,
        status: str,
        file_name: str | None,
        fmt: str | None,
        error: str | None = None,
    ) -> None:
        entry = {
            "idx": idx,
            "title": t.get("title") or "",
            "artists": t.get("artists") or "",
            "album": t.get("album") or "",
            "duration_ms": t.get("duration_ms"),
            "source_url": t.get("source_url") or "",
            "track_uri": t.get("track_uri") or "",
            "file": file_name or "",
            "status": status,
            "format": fmt or "",
        }
        if error:
            entry["error"] = error
        with self._match_details_lock:
            match_detail = dict(self._match_details.get(idx) or {})
        if match_detail:
            entry["match"] = match_detail
        with self._manifest_lock:
            self._manifest_entries = [e for e in self._manifest_entries if e.get("idx") != idx]
            self._manifest_entries.append(entry)

    def _record_match_detail(self, idx: int, best: dict) -> None:
        detail = {
            "url": best.get("url") or "",
            "title": best.get("title") or "",
            "channel": best.get("channel") or "",
            "score": round(float(best.get("score") or 0.0), 4),
            "score_details": best.get("score_details") or {},
        }
        if isinstance(best.get("ai_confidence"), (int, float)):
            detail["ai_confidence"] = round(float(best["ai_confidence"]), 4)
        if best.get("ai_reason"):
            detail["ai_reason"] = str(best.get("ai_reason"))
        with self._match_details_lock:
            self._match_details[idx] = detail

    def _write_playlist_manifest(
        self,
        out_dir: Path,
        playlist_hint: Optional[str],
        source_info: Optional[dict],
    ) -> None:
        try:
            previous = read_manifest(out_dir)
            previous = previous if isinstance(previous, dict) else None
            source = source_info if isinstance(source_info, dict) else {}
            if self.append_to_existing_playlist and previous and not source:
                prev_source = previous.get("source")
                source = prev_source if isinstance(prev_source, dict) else {}
            playlist_name = (
                (previous.get("playlist_name") if self.append_to_existing_playlist and previous else "")
                or source.get("name")
                or playlist_hint
                or out_dir.name
                or "Music2MP3"
            )
            with self._manifest_lock:
                tracks = sorted((dict(e) for e in self._manifest_entries), key=lambda e: int(e.get("idx") or 0))
            if self.append_to_existing_playlist and previous:
                previous_tracks = previous.get("tracks")
                if isinstance(previous_tracks, list):
                    tracks = self._merge_manifest_tracks(previous_tracks, tracks)
            manifest = build_manifest(
                playlist_name=str(playlist_name),
                playlist_dir=out_dir,
                source=source,
                settings=self._manifest_settings(),
                tracks=tracks,
                previous_manifest=previous,
            )
            path = write_manifest(out_dir, manifest)
            log.info("CONV: manifest generated: %s", path)
        except Exception:
            log.exception("CONV: failed generating playlist manifest")

    @staticmethod
    def _manifest_track_key(track: dict) -> str:
        for field in ("track_uri", "source_url", "file"):
            value = str(track.get(field) or "").strip().lower()
            if value:
                return f"{field}:{value}"
        title = _norm_text(str(track.get("title") or ""))
        artists = _norm_text(str(track.get("artists") or ""))
        if title or artists:
            return f"title:{artists}|{title}"
        return ""

    @classmethod
    def _merge_manifest_tracks(cls, previous_tracks: list, new_tracks: list[dict]) -> list[dict]:
        incoming_by_key: dict[str, dict] = {}
        incoming_without_key: list[dict] = []
        for track in new_tracks:
            item = dict(track)
            key = cls._manifest_track_key(item)
            if key:
                incoming_by_key[key] = item
            else:
                incoming_without_key.append(item)

        merged: list[dict] = []
        consumed: set[str] = set()
        for track in previous_tracks:
            if not isinstance(track, dict):
                continue
            key = cls._manifest_track_key(track)
            if key and key in incoming_by_key:
                merged.append(dict(incoming_by_key[key]))
                consumed.add(key)
            else:
                merged.append(dict(track))

        for key, track in incoming_by_key.items():
            if key not in consumed:
                merged.append(dict(track))
        merged.extend(dict(track) for track in incoming_without_key)

        for idx, track in enumerate(merged, start=1):
            track["idx"] = idx
        return merged

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

    def _pick_best_youtube_match(self, t: dict) -> tuple[dict | None, str, str | None]:
        """Returns (best_match, reject_reason, best_url_even_if_rejected)."""
        query = self._build_search_terms(t)
        min_score = 0.58 if self.strict_match else 0.42
        candidates = self._search_youtube_candidates(query, self.match_candidates)
        if not candidates:
            ai_best, ai_reason = self._try_ai_youtube_match(
                t=t,
                original_query=query,
                ranked_candidates=[],
                min_score=min_score,
                best_score=0.0,
            )
            if ai_best:
                return self._ai_manual_validation_result(ai_best, ai_reason, min_score)
            reason_lines = [
                f"No YouTube results for query: {query!r}",
                "The track title/artist may be too obscure or misspelled.",
            ]
            if ai_reason:
                reason_lines.append(f"AI assist: {ai_reason}")
            return None, "\n".join(reason_lines), None

        n_total = len(candidates)
        ranked, n_rejected_duration = self._rank_youtube_candidates(t, candidates)
        best = ranked[0] if ranked else None
        best_score = float(best.get("score") or -1.0) if best else -1.0

        if not best:
            # All candidates were rejected by duration filter
            src_ms = t.get("duration_ms")
            if isinstance(src_ms, int) and src_ms > 0:
                src_s = src_ms / 1000.0
                lo = max(10, src_s * 0.45)
                hi = max(src_s + 75, src_s * 1.45)
                reason = (
                    f"All {n_total} YouTube candidates rejected — duration too far from expected.\n"
                    f"Expected: ~{src_s:.0f}s  |  Acceptable range: {lo:.0f}s – {hi:.0f}s\n"
                    "Tip: check that the source track has a correct duration."
                )
            else:
                lo = self.duration_min or 0
                hi = self.duration_max or 0
                reason = (
                    f"All {n_total} YouTube candidates rejected by duration filter.\n"
                    f"Configured range: {lo}s – {hi}s\n"
                    "Tip: widen duration_min / duration_max in settings."
                )
            return None, reason, None

        if best_score < min_score:
            ai_best, ai_reason = self._try_ai_youtube_match(
                t=t,
                original_query=query,
                ranked_candidates=ranked,
                min_score=min_score,
                best_score=best_score,
            )
            if ai_best:
                return self._ai_manual_validation_result(ai_best, ai_reason, min_score)

            best_title = str(best.get("title") or "?")
            best_channel = str(best.get("channel") or "")
            best_url = str(best.get("url") or "")
            cand_low = best_title.lower()
            active_variants = [v for v in _BAD_VARIANTS if v in cand_low]
            active_contexts = [v for v in _BAD_CONTEXTS if v in cand_low]
            penalty_parts = active_variants + active_contexts
            threshold_label = "strict (0.58)" if self.strict_match else "normal (0.42)"
            reason_lines = [
                f"Best YouTube candidate: \"{best_title}\"" + (f" — {best_channel}" if best_channel else ""),
                f"Match score: {best_score:.2f}  |  Threshold: {threshold_label}",
            ]
            if penalty_parts:
                reason_lines.append(f"Active penalties: {', '.join(penalty_parts)}")
            if n_rejected_duration:
                reason_lines.append(f"({n_rejected_duration}/{n_total} candidate(s) also rejected by duration)")
            reason_lines.append("")
            if self.strict_match:
                reason_lines.append("Tip: disable 'strict' flag to lower the threshold to 0.42.")
            elif self.safe_search:
                reason_lines.append("Tip: disable 'safe' flag to allow variants like live/remix, or add artist details.")
            if ai_reason:
                reason_lines.append(f"AI assist: {ai_reason}")
            return None, "\n".join(reason_lines), best_url or None

        return best, "", None

    def _ai_manual_validation_result(
        self,
        ai_best: dict,
        ai_reason: str,
        min_score: float,
    ) -> tuple[None, str, str | None]:
        ai_title = str(ai_best.get("title") or "?")
        ai_channel = str(ai_best.get("channel") or "")
        ai_url = str(ai_best.get("url") or "")
        ai_score = float(ai_best.get("score") or 0.0)
        ai_conf = ai_best.get("ai_confidence")
        ai_reason_detail = str(ai_best.get("ai_reason") or ai_reason or "")
        threshold_label = "strict (0.58)" if min_score >= 0.58 else "normal (0.42)"
        reason_lines = [
            f"AI suggested candidate: \"{ai_title}\"" + (f" — {ai_channel}" if ai_channel else ""),
            f"Local match score: {ai_score:.2f}  |  Threshold: {threshold_label}",
        ]
        if isinstance(ai_conf, (int, float)):
            reason_lines.append(f"AI confidence: {float(ai_conf):.2f}")
        if ai_reason_detail:
            reason_lines.append(f"AI reason: {ai_reason_detail}")
        reason_lines.extend([
            "",
            "Manual validation required: open the failed track details and click Download only if this candidate is correct.",
        ])
        return None, "\n".join(reason_lines), ai_url or None

    def _rank_youtube_candidates(self, t: dict, candidates: list[dict]) -> tuple[list[dict], int]:
        ranked: list[dict] = []
        n_rejected_duration = 0
        for cand in candidates:
            if not self._is_acceptable_candidate_duration(t, cand):
                log.info(
                    "CONV: reject candidate by duration: title=%r duration=%r track=%r",
                    cand.get("title"),
                    cand.get("duration_s"),
                    t.get("title"),
                )
                n_rejected_duration += 1
                continue
            score = self._score_match_candidate(t, cand)
            item = dict(cand)
            item["score"] = score
            item["score_details"] = self._score_match_candidate_details(t, cand)
            ranked.append(item)
        ranked.sort(key=lambda c: float(c.get("score") or 0.0), reverse=True)
        return ranked, n_rejected_duration

    def _try_ai_youtube_match(
        self,
        *,
        t: dict,
        original_query: str,
        ranked_candidates: list[dict],
        min_score: float,
        best_score: float,
    ) -> tuple[dict | None, str]:
        if not self.ai_match_enabled or not self._ai_match_advisor:
            return None, ""
        if ranked_candidates and best_score < self.ai_match_gray_min:
            return None, "skipped; heuristic score below AI gray zone"

        first = self._ask_ai_match_advisor(
            t=t,
            candidates=ranked_candidates[:6],
            query=original_query,
            threshold=min_score,
        )
        best = self._apply_ai_match_advice(first, ranked_candidates, min_score=min_score)
        if best:
            return best, f"AI suggested candidate ({first.confidence:.2f})"

        if first.action == "retry" and first.query:
            retry_query = first.query[:160]
            log.info("CONV: AI match retry query for %r -> %r", t.get("title"), retry_query)
            retry_candidates = self._search_youtube_candidates(retry_query, self.match_candidates)
            retry_ranked, _ = self._rank_youtube_candidates(t, retry_candidates)
            if retry_ranked:
                retry_best = retry_ranked[0]
                if float(retry_best.get("score") or 0.0) >= min_score:
                    retry_best["ai_confidence"] = first.confidence
                    retry_best["ai_reason"] = first.reason
                    return retry_best, "AI retry query found a candidate"
                second = self._ask_ai_match_advisor(
                    t=t,
                    candidates=retry_ranked[:6],
                    query=retry_query,
                    threshold=min_score,
                )
                best = self._apply_ai_match_advice(second, retry_ranked, min_score=min_score)
                if best:
                    return best, f"AI suggested retry candidate ({second.confidence:.2f})"
                return None, second.reason or "AI rejected retry candidates"
            return None, "AI retry query returned no acceptable candidates"

        return None, first.reason or "AI rejected candidates"

    def _ask_ai_match_advisor(
        self,
        *,
        t: dict,
        candidates: list[dict],
        query: str,
        threshold: float,
    ) -> AIMatchAdvice:
        for i, cand in enumerate(candidates):
            cand["ai_id"] = i
        try:
            advice = self._ai_match_advisor.advise(
                track=t,
                candidates=candidates,
                query=query,
                threshold=threshold,
                strict=self.strict_match,
            )
            log.info(
                "CONV: AI match advice action=%s candidate=%s confidence=%.2f reason=%s",
                advice.action,
                advice.candidate_id,
                advice.confidence,
                advice.reason,
            )
            return advice
        except Exception as e:
            log.warning("CONV: AI match advisor failed: %s", e)
            return AIMatchAdvice(action="reject", reason=f"AI unavailable: {e}")

    def _apply_ai_match_advice(self, advice: AIMatchAdvice, candidates: list[dict], *, min_score: float) -> dict | None:
        if advice.action != "accept" or advice.candidate_id is None:
            return None
        if advice.confidence < self.ai_match_min_confidence:
            log.info(
                "CONV: AI suggestion ignored; confidence %.2f below %.2f",
                advice.confidence,
                self.ai_match_min_confidence,
            )
            return None
        accept_floor = max(self.ai_match_gray_min, min_score - self.ai_match_accept_margin)
        for cand in candidates:
            if int(cand.get("ai_id", -1)) == advice.candidate_id:
                score = float(cand.get("score") or 0.0)
                if score < accept_floor:
                    log.info(
                        "CONV: AI suggestion ignored; heuristic score %.2f below AI floor %.2f",
                        score,
                        accept_floor,
                    )
                    return None
                item = dict(cand)
                item["ai_confidence"] = advice.confidence
                item["ai_reason"] = advice.reason
                return item
        return None

    def _is_acceptable_candidate_duration(self, t: dict, cand: dict) -> bool:
        cand_s = cand.get("duration_s")
        if not isinstance(cand_s, int) or cand_s <= 0:
            return True

        src_ms = t.get("duration_ms")
        if isinstance(src_ms, int) and src_ms > 0:
            src_s = src_ms / 1000.0
            if cand_s > max(src_s + 75, src_s * 1.45):
                return False
            if cand_s < max(10, src_s * 0.45):
                return False
            return True

        if self.duration_min and cand_s < self.duration_min:
            return False
        if self.duration_max and cand_s > self.duration_max:
            return False
        return True

    @staticmethod
    def _is_probable_soundcloud_set_url(url: str) -> bool:
        low = (url or "").lower()
        return "soundcloud.com" in low and ("/sets/" in low or "/playlists/" in low)

    @staticmethod
    def _is_probable_bandcamp_album_url(url: str) -> bool:
        low = (url or "").lower()
        return ".bandcamp.com" in low and "/album/" in low

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
        return float(self._score_match_candidate_details(t, cand)["score"])

    def _score_match_candidate_details(self, t: dict, cand: dict) -> dict:
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
        title_tokens = [tk for tk in src_title.split() if len(tk) > 1]
        title_coverage = 0.0
        if title_tokens and cand_title:
            title_coverage = sum(1 for tk in title_tokens if tk in cand_title) / len(title_tokens)

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
                penalties += 0.11
        for bad in _BAD_CONTEXTS:
            if bad in cand_low:
                penalties += 0.07

        bonus = 0.0
        if title_coverage >= 0.95 and artist_score >= 0.8:
            bonus += 0.08
        if "topic" in cand_channel.lower() and artist_score >= 0.8:
            bonus += 0.03

        score = (
            (0.43 * title_ratio)
            + (0.20 * title_coverage)
            + (0.25 * artist_score)
            + (0.18 * duration_score)
            + bonus
            - penalties
        )
        return {
            "score": max(0.0, min(1.0, score)),
            "title_ratio": round(title_ratio, 4),
            "title_coverage": round(title_coverage, 4),
            "artist_score": round(artist_score, 4),
            "duration_score": round(duration_score, 4),
            "bonus": round(bonus, 4),
            "penalties": round(penalties, 4),
        }

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
