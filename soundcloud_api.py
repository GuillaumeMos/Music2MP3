# soundcloud_api.py
import json
import os
import sys
import platform
from typing import Tuple, List, Dict

from utils import run_quiet
from config import resource_path


def _find_ytdlp() -> str:
    """
    Try to use the bundled yt-dlp first, then fallback to PATH.
    """
    _ = getattr(sys, "_MEIPASS", os.path.abspath("."))
    if platform.system() == "Windows":
        cand = os.path.join(resource_path("yt-dlp"), "yt-dlp.exe")
        return cand if os.path.isfile(cand) else "yt-dlp.exe"
    else:
        cand = os.path.join(resource_path("yt-dlp"), "yt-dlp")
        return cand if os.path.isfile(cand) else "yt-dlp"


class SoundCloudClient:
    """
    Build a CSV-ready list of rows from a SoundCloud playlist (or single track) URL,
    without any authentication. Private links with secret token also work.
    """

    def fetch_playlist(self, url: str, cookies_path: str | None = None) -> Tuple[List[Dict], str]:
        """
        Returns (rows, name)

        Each row:
          Track Name, Artist Name(s), Album Name, Duration (ms), Source URL, Track URI
        """
        # Use NON-FLAT JSON to get full metadata (flat often misses uploader/duration).
        data = self._dump_sc_json(url, cookies_path=cookies_path, flat=False)

        rows: List[Dict] = []
        playlist_title = data.get("title") or data.get("playlist_title") or "SoundCloud"

        entries = data.get("entries")
        if isinstance(entries, list) and entries:
            # Playlist case
            for e in entries:
                # Some extractors still return semi-flat entries: enrich if needed.
                if not self._looks_full(e):
                    track_url = e.get("webpage_url") or e.get("url")
                    if track_url:
                        e = self._dump_sc_json(track_url, cookies_path=cookies_path, flat=False)
                rows.append(self._row_from_info(e, playlist_title))
            return rows, playlist_title

        # Single track
        rows.append(self._row_from_info(data, playlist_title))
        return rows, playlist_title

    # ------------------ helpers ------------------

    def _looks_full(self, info: Dict) -> bool:
        """Heuristic to see if we have rich fields already."""
        return bool(info.get("title")) and bool(info.get("uploader") or info.get("uploader_id") or info.get("artist") or info.get("creator"))

    def _row_from_info(self, info: Dict, playlist_title: str = "") -> Dict:
        title = (info.get("title")
                 or info.get("track")
                 or "Unknown")
        artist = (info.get("artist")
                  or info.get("uploader")
                  or info.get("creator")
                  or info.get("channel")
                  or info.get("uploader_id")
                  or "Unknown")
        duration_sec = info.get("duration") or 0
        try:
            dur_ms = int(float(duration_sec) * 1000) if duration_sec else ""
        except Exception:
            dur_ms = ""
        url = info.get("webpage_url") or info.get("url") or ""
        tid = info.get("id") or ""
        album = info.get("album") or (playlist_title if playlist_title else "")

        return {
            "Track Name": title,
            "Artist Name(s)": artist,
            "Album Name": album,
            "Duration (ms)": dur_ms,
            "Source URL": url,
            "Track URI": f"soundcloud:track:{tid}" if tid else "",
        }

    def _dump_sc_json(self, url: str, cookies_path: str | None = None, flat: bool = False) -> Dict:
        """
        Dump JSON from yt-dlp.
        flat=False  -> full metadata (preferred)
        """
        ytdlp = _find_ytdlp()
        cmd = [
            ytdlp,
            "--dump-single-json",
            "--no-warnings",
            "-q",
            url,
        ]
        if flat:
            cmd.insert(1, "--flat-playlist")
        if cookies_path:
            cmd += ["--cookies", cookies_path]

        proc = run_quiet(cmd, text=True, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or "yt-dlp failed on SoundCloud URL")
        try:
            return json.loads(proc.stdout or "{}")
        except Exception as e:
            raise RuntimeError(f"Invalid JSON from yt-dlp: {e}")
