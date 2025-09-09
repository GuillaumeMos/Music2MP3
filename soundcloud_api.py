# soundcloud_api.py
import json
import os
import platform
import re
import subprocess

try:
    # PyInstaller-friendly path resolver
    from config import resource_path
except Exception:
    def resource_path(p: str) -> str:
        return os.path.join(os.path.abspath("."), p)


def _bin_ytdlp() -> str:
    if platform.system() == "Windows":
        cand = resource_path(os.path.join("yt-dlp", "yt-dlp.exe"))
        return cand if os.path.isfile(cand) else os.path.join("yt-dlp", "yt-dlp.exe")
    else:
        cand = resource_path(os.path.join("yt-dlp", "yt-dlp"))
        return cand if os.path.isfile(cand) else os.path.join("yt-dlp", "yt-dlp")


class SoundCloudClient:
    @staticmethod
    def is_playlist_url(url: str) -> bool:
        # ex: https://soundcloud.com/<user>/sets/<playlist-slug>
        return bool(re.search(r"soundcloud\.com/.+?/sets/.+", url or "", re.I))

    def fetch_playlist(
        self,
        playlist_url: str,
        cookies_path: str | None = None,
        cookies_from_browser: str | None = None
    ):
        """
        Retourne (rows, playlist_name). Supporte playlists privées:
          - via lien secret (URL avec token) -> aucun cookie requis
          - via cookies du navigateur (--cookies-from-browser <browser>)
          - via cookies.txt si fourni (fallback)
        """
        ytdlp = _bin_ytdlp()

        # On demande à yt-dlp de nous donner le JSON de la playlist/piste
        if self.is_playlist_url(playlist_url):
            cmd = [ytdlp, "--dump-single-json", "--no-warnings", playlist_url]
        else:
            cmd = [ytdlp, "--dump-single-json", "--no-warnings", "--no-playlist", playlist_url]

        # Auth sans fichier: utilise la session du navigateur
        if cookies_from_browser:
            cmd += ["--cookies-from-browser", cookies_from_browser]
        elif cookies_path and os.path.isfile(cookies_path):
            cmd += ["--cookies", cookies_path]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or "yt-dlp failed on SoundCloud URL")

        data = json.loads(proc.stdout or "{}")
        playlist_title = data.get("title") or "SoundCloud"
        entries = data.get("entries") or [data]

        rows = []
        for e in entries:
            if not e:
                continue
            title  = e.get("title") or "Unknown"
            artist = e.get("uploader") or e.get("artist") or e.get("uploader_id") or "Unknown"
            dur_ms = int(float(e.get("duration") or 0) * 1000)
            webpage = e.get("webpage_url") or e.get("url") or ""
            track_id = e.get("id")
            track_uri = webpage or (track_id and f"soundcloud:track:{track_id}") or ""

            rows.append({
                "Track Name": title,
                "Artist Name(s)": artist,
                "Album Name": playlist_title,
                "Duration (ms)": str(dur_ms),
                "Source URL": webpage,
                "Track URI": track_uri,
            })

        return rows, playlist_title
