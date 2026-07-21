from __future__ import annotations

import json
from typing import Dict, List, Tuple

from config import resource_path
from utils import find_ytdlp_cmd, run_quiet


def _find_ytdlp_cmd() -> list[str]:
    return find_ytdlp_cmd(resource_path)


class BandcampClient:
    """Build CSV-ready rows from a Bandcamp album or track URL via yt-dlp."""

    def fetch_playlist(self, url: str, cookies_path: str | None = None) -> Tuple[List[Dict], str]:
        data = self._dump_bandcamp_json(url, cookies_path=cookies_path, flat=False)

        rows: List[Dict] = []
        playlist_title = data.get("title") or data.get("playlist_title") or data.get("album") or "Bandcamp"
        entries = data.get("entries")
        if isinstance(entries, list) and entries:
            for entry in entries:
                if not self._looks_full(entry):
                    track_url = entry.get("webpage_url") or entry.get("url")
                    if track_url:
                        entry = self._dump_bandcamp_json(track_url, cookies_path=cookies_path, flat=False)
                rows.append(self._row_from_info(entry, playlist_title))
            return rows, playlist_title

        rows.append(self._row_from_info(data, playlist_title))
        return rows, playlist_title

    def _looks_full(self, info: Dict) -> bool:
        return bool(info.get("title")) and bool(
            info.get("artist") or info.get("uploader") or info.get("creator") or info.get("channel")
        )

    def _row_from_info(self, info: Dict, playlist_title: str = "") -> Dict:
        title = info.get("title") or info.get("track") or "Unknown"
        artist = (
            info.get("artist")
            or info.get("uploader")
            or info.get("creator")
            or info.get("channel")
            or "Unknown"
        )
        duration_sec = info.get("duration") or 0
        try:
            dur_ms = int(float(duration_sec) * 1000) if duration_sec else ""
        except Exception:
            dur_ms = ""
        url = info.get("webpage_url") or info.get("url") or ""
        track_id = info.get("id") or ""
        album = info.get("album") or playlist_title or ""
        return {
            "Track Name": title,
            "Artist Name(s)": artist,
            "Album Name": album,
            "Duration (ms)": dur_ms,
            "Source URL": url,
            "Track URI": f"bandcamp:track:{track_id}" if track_id else "",
        }

    def _dump_bandcamp_json(self, url: str, cookies_path: str | None = None, flat: bool = False) -> Dict:
        cmd = _find_ytdlp_cmd()
        if flat:
            cmd += ["--flat-playlist"]
        cmd += [
            "--dump-single-json",
            "--no-warnings",
            "-q",
            url,
        ]
        if cookies_path:
            cmd += ["--cookies", cookies_path]

        try:
            proc = run_quiet(cmd, text=True, capture_output=True)
        except FileNotFoundError as e:
            raise RuntimeError(
                "yt-dlp is not available. Install it with `pip install yt-dlp` "
                "or bundle the yt-dlp binary with the app."
            ) from e
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or "yt-dlp failed on Bandcamp URL")
        try:
            return json.loads(proc.stdout or "{}")
        except Exception as e:
            raise RuntimeError(f"Invalid JSON from yt-dlp: {e}")
