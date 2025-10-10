# spotify_api.py
import re
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API = "https://api.spotify.com/v1"
log = logging.getLogger(__name__)

def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def _retrying_session(
    total=5,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    methods=frozenset(["HEAD", "GET", "OPTIONS", "POST"])
):
    s = requests.Session()
    r = Retry(
        total=total,
        read=total,
        connect=total,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=methods,
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=r))
    s.mount("http://", HTTPAdapter(max_retries=r))

    # inject default timeout for all requests
    orig_request = s.request
    def _with_timeout(method, url, **kw):
        kw.setdefault("timeout", 20)
        return orig_request(method, url, **kw)
    s.request = _with_timeout
    return s

_SESSION = _retrying_session()

class SpotifyClient:
    """
    token_supplier: callable -> str (access_token)
    """
    # --------- helpers de parsing (compat avec gui.py) ---------
    _RGX = re.compile(
        r"spotify:(?P<kind>track|album|artist|playlist):(?P<id>[A-Za-z0-9]+)|"
        r"open\.spotify\.com/(?P<kind2>track|album|artist|playlist)/(?P<id2>[A-Za-z0-9]+)"
    )

    @staticmethod
    def extract_playlist_id(s: str | None) -> str | None:
        """Retourne l'ID playlist depuis une URL/URI Spotify, sinon None."""
        if not s:
            return None
        m = re.search(r"(?:spotify:playlist:|open\.spotify\.com/playlist/)([A-Za-z0-9]+)", s)
        return m.group(1) if m else None

    def _parse_spotify_id(self, s):
        """Retourne (kind, id) ou (None, None)"""
        m = self._RGX.search(s or "")
        if not m:
            return (None, None)
        kind = m.group("kind") or m.group("kind2")
        ident = m.group("id") or m.group("id2")
        return (kind, ident)

    def __init__(self, token_supplier):
        if not callable(token_supplier):
            raise ValueError("token_supplier must be callable")
        self._token_supplier = token_supplier

    # -----------------------
    # HTTP helpers
    # -----------------------
    def _headers(self):
        return {"Authorization": f"Bearer {self._token_supplier()}"}

    def _get(self, url, params=None, _retry401=True):
        r = _SESSION.get(url, headers=self._headers(), params=params)
        if r.status_code == 401 and _retry401:
            log.info("401 from Spotify API — attempting token refresh and retry.")
            try:
                _ = self._token_supplier()
            except Exception as e:
                log.warning("Token supplier refresh raised: %s", e)
            r = _SESSION.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, url, json_body=None, _retry401=True):
        r = _SESSION.post(url, headers=self._headers(), json=json_body)
        if r.status_code == 401 and _retry401:
            log.info("401 on POST — attempting token refresh and retry.")
            try:
                _ = self._token_supplier()
            except Exception as e:
                log.warning("Token supplier refresh raised: %s", e)
            r = _SESSION.post(url, headers=self._headers(), json=json_body)
        r.raise_for_status()
        return r.json()

    # -----------------------
    # Resolvers
    # -----------------------
    def resolve(self, url_or_uri):
        kind, ident = self._parse_spotify_id(url_or_uri)
        if kind == "track":
            tr = self.track(ident)
            return [tr] if tr else []
        elif kind == "album":
            return self.album_tracks(ident)
        elif kind == "playlist":
            return self.playlist_tracks(ident)
        elif kind == "artist":
            return self.artist_top_tracks(ident)
        else:
            return []

    # -----------------------
    # Entities
    # -----------------------
    def track(self, track_id):
        return self._get(f"{API}/tracks/{track_id}")

    def album_tracks(self, album_id):
        items = []
        url = f"{API}/albums/{album_id}/tracks"
        params = {"limit": 50, "offset": 0}
        while True:
            page = self._get(url, params=params)
            items.extend(page.get("items", []))
            if page.get("next"):
                params["offset"] += params["limit"]
            else:
                break

        album = self._get(f"{API}/albums/{album_id}")
        album_name = album.get("name")
        arts = album.get("artists") or []
        album_artists = [a.get("name") for a in arts if a.get("name")]

        out = []
        for tr in items:
            out.append({
                "id": tr.get("id"),
                "name": tr.get("name"),
                "duration_ms": tr.get("duration_ms"),
                "album": {"name": album_name},
                "artists": [{"name": n} for n in album_artists] if album_artists else (tr.get("artists") or []),
            })
        return out

    def playlist_tracks(self, playlist_id):
        fields = "items(track(id,name,artists(name),album(name),duration_ms,is_local)),next"
        url = f"{API}/playlists/{playlist_id}/tracks"
        params = {"limit": 100, "fields": fields}
        items = []
        while True:
            page = self._get(url, params=params)
            items.extend(page.get("items", []))
            next_url = page.get("next")
            if next_url:
                url = next_url
                params = None
            else:
                break

        out = []
        for it in items:
            tr = it.get("track") or {}
            if not tr or tr.get("is_local"):
                continue
            out.append({
                "id": tr.get("id"),
                "name": tr.get("name"),
                "duration_ms": tr.get("duration_ms"),
                "album": {"name": (tr.get("album") or {}).get("name")},
                "artists": (tr.get("artists") or []),
            })
        return out

    def artist_top_tracks(self, artist_id, market="US"):
        data = self._get(f"{API}/artists/{artist_id}/top-tracks", params={"market": market})
        tracks = data.get("tracks") or []
        out = []
        for tr in tracks:
            out.append({
                "id": tr.get("id"),
                "name": tr.get("name"),
                "duration_ms": tr.get("duration_ms"),
                "album": {"name": (tr.get("album") or {}).get("name")},
                "artists": (tr.get("artists") or []),
            })
        return out

    # -----------------------
    # Batch lookups
    # -----------------------
    def tracks(self, track_ids):
        out = []
        ids = list(track_ids or [])
        for chunk in _chunks(ids, 50):
            data = self._get(f"{API}/tracks", params={"ids": ",".join(chunk)})
            out.extend(data.get("tracks") or [])
        return out

    # -----------------------
    # Playlists utilitaires (compat gui.py)
    # -----------------------
    def current_user_id(self):
        me = self._get(f"{API}/me")
        return me.get("id")

    def create_playlist(self, user_id, name, public=False, description=None):
        body = {"name": name, "public": public}
        if description:
            body["description"] = description
        return self._post(f"{API}/users/{user_id}/playlists", json_body=body)

    def add_tracks_to_playlist(self, playlist_id, track_ids_or_uris):
        uris = []
        for t in track_ids_or_uris:
            if isinstance(t, str) and t.startswith("spotify:track:"):
                uris.append(t)
            else:
                uris.append(f"spotify:track:{t}")
        body = {"uris": uris}
        return self._post(f"{API}/playlists/{playlist_id}/tracks", json_body=body)

    def fetch_playlist(self, playlist_id: str):
        """
        Utilisé par gui.py :
          rows, name = fetch_playlist(playlist_id)
        rows -> liste de dicts CSV ("Track Name", "Artist Name(s)", "Album Name", "Duration (ms)")
        name -> nom de la playlist
        """
        # nom de la playlist
        meta = self._get(f"{API}/playlists/{playlist_id}", params={"fields": "name"})
        name = meta.get("name")
        # tracks
        tracks = self.playlist_tracks(playlist_id)
        rows, _ = self.to_csv_rows(tracks, playlist_name=name)
        return rows, name

    # -----------------------
    # Helpers CSV
    # -----------------------
    def to_csv_rows(self, track_dicts, playlist_name=None):
        rows = []
        for tr in track_dicts or []:
            if not tr:
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
        return rows, (playlist_name or "")
