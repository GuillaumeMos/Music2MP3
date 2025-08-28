# spotify_api.py
import re, requests

class SpotifyClient:
    def __init__(self, token_supplier):
        self._get_token = token_supplier

    @staticmethod
    def extract_playlist_id(url: str) -> str | None:
        m = re.search(r"(?:playlist/|spotify:playlist:)([A-Za-z0-9]+)", url or "")
        return m.group(1) if m else None

    def _headers(self):
        return {"Authorization": f"Bearer {self._get_token()}"}

    def fetch_playlist(self, playlist_id: str) -> tuple[list[dict], str]:
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}"
        params = {"fields": "name,tracks.items(track(name,album(name),duration_ms,artists(name),type,is_local)),tracks.next"}
        rows, name = [], "SpotifyPlaylist"

        def items_to_rows(items):
            for it in items or []:
                t = it.get("track") or {}
                if not t or t.get("type") != "track" or t.get("is_local"):
                    continue
                title = t.get("name") or "Unknown"
                album = (t.get("album") or {}).get("name") or ""
                artists = ", ".join([a.get("name") for a in (t.get("artists") or []) if a.get("name")])
                rows.append({
                    "Track Name": title,
                    "Artist Name(s)": artists or "Unknown",
                    "Album Name": album or "",
                    "Duration (ms)": t.get("duration_ms") or ""
                })

        r = requests.get(url, headers=self._headers(), params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        name = data.get("name") or name
        items_to_rows((data.get("tracks") or {}).get("items"))
        next_url = (data.get("tracks") or {}).get("next")
        while next_url:
            r = requests.get(next_url, headers=self._headers(), timeout=20)
            r.raise_for_status()
            page = r.json()
            items_to_rows(page.get("items"))
            next_url = page.get("next")
        return rows, name
