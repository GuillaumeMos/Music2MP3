# spotify_api.py
import re
import time
import requests

API = "https://api.spotify.com/v1"

def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

class SpotifyClient:
    """
    Utilisation PKCE (recommandée, pas de secret) :
        auth = PKCEAuth(client_id=..., redirect_uri=..., scopes=[...])
        sp = SpotifyClient(token_supplier=auth.get_token)

    Utilisation Client Credentials (public only) :
        sp = SpotifyClient(token_supplier=lambda: "YOUR_APP_TOKEN")
    """
    def __init__(self, token_supplier):
        self._get_token = token_supplier

    @staticmethod
    def extract_playlist_id(url: str) -> str | None:
        m = re.search(r"(?:playlist/|spotify:playlist:)([A-Za-z0-9]+)", url or "")
        return m.group(1) if m else None

    def _headers(self):
        return {"Authorization": f"Bearer {self._get_token()}"}

    # -------------------- CSV simple (utilisé par ton gui.py) --------------------

    def fetch_playlist(self, playlist_id: str) -> tuple[list[dict], str]:
        """
        Renvoie (rows, playlist_name) avec les colonnes MINIMALES :
        Track Name, Artist Name(s), Album Name, Duration (ms)
        """
        url = f"{API}/playlists/{playlist_id}"
        params = {
            "fields": (
                "name,"
                "tracks.items("
                "track(name,album(name),duration_ms,artists(name),type,is_local)"
                "),"
                "tracks.next"
            )
        }

        r = requests.get(url, headers=self._headers(), params=params, timeout=20)
        r.raise_for_status()
        data = r.json()

        name = data.get("name") or "SpotifyPlaylist"
        items = (data.get("tracks") or {}).get("items") or []

        # pagination
        next_url = (data.get("tracks") or {}).get("next")
        while next_url:
            r = requests.get(next_url, headers=self._headers(), timeout=20)
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", "1")))
                continue
            r.raise_for_status()
            page = r.json()
            items.extend(page.get("items") or [])
            next_url = page.get("next")

        rows = []
        for it in items:
            tr = (it or {}).get("track") or {}
            if not tr or tr.get("type") != "track" or tr.get("is_local"):
                continue
            title = tr.get("name") or ""
            album = (tr.get("album") or {}).get("name") or ""
            artists = ", ".join([a.get("name") for a in (tr.get("artists") or []) if a.get("name")])
            dur = tr.get("duration_ms") or ""
            rows.append({
                "Track Name": title,
                "Artist Name(s)": artists or "Unknown",
                "Album Name": album,
                "Duration (ms)": dur
            })

        return rows, name

