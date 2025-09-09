# soundcloud_api.py
import json
import os
import platform
import re
import subprocess

try:
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

    def fetch_playlist(self, playlist_url: str, cookies_path: str | None = None):
        """
        Retourne (rows, playlist_name)
        rows: dicts compatibles avec le converter + 'Source URL' (pour download direct)
        Colonnes:
          - Track Name
          - Artist Name(s)
          - Album Name  (nom du set/playlist SoundCloud)
          - Duration (ms)
          - Source URL  (URL directe SoundCloud de la piste)
          - Track URI   (clé stable pour dédup : URL ou soundcloud:track:<id>)
        """
        ytdlp = _bin_ytdlp()

        # Playlist SoundCloud → JSON complet avec entries
        if self.is_playlist_url(playlist_url):
            cmd = [ytdlp, "--dump-single-json", "--no-warnings", playlist_url]
        else:
            # URL piste unique → un seul objet
            cmd = [ytdlp, "--dump-single-json", "--no-warnings", "--no-playlist", playlist_url]

        if cookies_path and os.path.isfile(cookies_path):
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
            title = e.get("title") or "Unknown"
            artist = e.get("uploader") or e.get("artist") or e.get("uploader_id") or "Unknown"
            dur_ms = int(float(e.get("duration") or 0) * 1000)
            webpage = e.get("webpage_url") or e.get("url") or ""
            track_id = e.get("id")

            # clé de dédup
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
