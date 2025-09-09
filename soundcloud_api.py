# soundcloud_api.py
import json, subprocess, os, re, platform

def _bin_ytdlp():
    if platform.system() == "Windows":
        return os.path.join("yt-dlp", "yt-dlp.exe")
    return os.path.join("yt-dlp", "yt-dlp")

class SoundCloudClient:
    @staticmethod
    def is_playlist_url(url: str) -> bool:
        # https://soundcloud.com/<user>/sets/<playlist>
        return bool(re.search(r"soundcloud\.com/.+?/sets/.+", url or "", re.I))

    def fetch_playlist(self, playlist_url: str):
        """
        Retourne (rows, playlist_name)
        rows: dicts avec "Track Name", "Artist Name(s)", "Album Name", "Duration (ms)", "Source URL", "Track URI"
        """
        ytdlp = _bin_ytdlp()
        # --dump-single-json -> renvoie un JSON unique de la playlist (entries = tracks)
        cmd = [ytdlp, "--dump-single-json", "--no-warnings", "--no-playlist", playlist_url]
        # Ici on veut bien la playlist → donc on va enlever --no-playlist si c’est un set:
        if self.is_playlist_url(playlist_url):
            cmd = [ytdlp, "--dump-single-json", "--no-warnings", playlist_url]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or "yt-dlp failed")

        data = json.loads(proc.stdout or "{}")
        # Cas 1: data = playlist (avec entries)
        # Cas 2: si l’URL n’est pas un set, data peut être une seule track
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

            # Track URI générique (utilisé pour la dédup). On peut utiliser l’URL comme clé stable.
            track_uri = webpage or (e.get("id") and f"soundcloud:track:{e['id']}") or ""

            rows.append({
                "Track Name": title,
                "Artist Name(s)": artist,
                "Album Name": playlist_title,      # on met le nom du set comme "album"
                "Duration (ms)": str(dur_ms),
                "Source URL": webpage,            # ← important: on téléchargera DIRECTEMENT cette URL
                "Track URI": track_uri,           # ← aide à la déduplication
            })

        return rows, playlist_title
