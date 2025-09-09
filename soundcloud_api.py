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
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
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
        data = self._dump_sc_json(url, cookies_path=cookies_path)
        rows: List[Dict] = []
        title = data.get("title") or data.get("playlist_title") or "SoundCloud"

        # Playlist with entries
        entries = data.get("entries")
        if isinstance(entries, list) and entries:
            for e in entries:
                if not isinstance(e, dict):
                    continue
                rows.append(self._row_from_info(e))
            return rows, title

        # Single track
        rows.append(self._row_from_info(data))
        return rows, title

    def _row_from_info(self, info: Dict) -> Dict:
        name = info.get("title") or "Unknown"
        artist = info.get("uploader") or info.get("uploader_id") or "Unknown"
        duration_sec = info.get("duration") or 0
        dur_ms = int(float(duration_sec) * 1000) if duration_sec else ""
        url = info.get("webpage_url") or ""
        tid = info.get("id") or ""
        album = info.get("album") or ""  # SoundCloud rarely set

        return {
            "Track Name": name,
            "Artist Name(s)": artist,
            "Album Name": album,
            "Duration (ms)": dur_ms,
            "Source URL": url,
            "Track URI": f"soundcloud:track:{tid}" if tid else "",
        }

    def _dump_sc_json(self, url: str, cookies_path: str | None = None) -> Dict:
        ytdlp = _find_ytdlp()
        cmd = [
            ytdlp,
            "--flat-playlist",
            "--dump-single-json",
            "--no-warnings",
            "-q",
            url,
        ]
        if cookies_path:
            cmd += ["--cookies", cookies_path]

        proc = run_quiet(cmd, text=True, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or "yt-dlp failed on SoundCloud URL")
        try:
            return json.loads(proc.stdout or "{}")
        except Exception as e:
            raise RuntimeError(f"Invalid JSON from yt-dlp: {e}")
