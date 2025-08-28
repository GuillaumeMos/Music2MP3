import re, base64, requests

class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None

    def _get_token(self) -> str:
        if self._token:
            return self._token
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {auth}"},
            data={"grant_type": "client_credentials"},
            timeout=15,
        )
        r.raise_for_status()
        self._token = r.json()["access_token"]
        return self._token

    @staticmethod
    def extract_playlist_id(url: str) -> str | None:
        m = re.search(r"(?:playlist/|spotify:playlist:)([A-Za-z0-9]+)", url or "")
        return m.group(1) if m else None

    def fetch_playlist(self, playlist_id: str) -> tuple[list[dict], str]:
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}"
        params = {
            "fields": "name,tracks.items(track(name,album(name),duration_ms,artists(name),type,is_local)),tracks.next"
        }
        rows: list[dict] = []
        name = "SpotifyPlaylist"

        def items_to_rows(items):
            for it in items or []:
                t = it.get("track") or {}
                if not t or t.get("type") != "track" or t.get("is_local"):
                    continue
                title = t.get("name") or "Unknown"
                album = (t.get("album") or {}).get("name") or ""
                artists = ", ".join([a.get("name") for a in (t.get("artists") or []) if a.get("name")])
                dur = t.get("duration_ms") or ""
                rows.append({
                    "Track Name": title,
                    "Artist Name(s)": artists or "Unknown",
                    "Album Name": album or "",
                    "Duration (ms)": dur,
                })

        r = requests.get(url, headers=headers, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        name = data.get("name") or name
        items_to_rows((data.get("tracks") or {}).get("items"))

        next_url = (data.get("tracks") or {}).get("next")
        while next_url:
            r = requests.get(next_url, headers=headers, timeout=20)
            r.raise_for_status()
            page = r.json()
            items_to_rows(page.get("items"))
            next_url = page.get("next")

        return rows, name