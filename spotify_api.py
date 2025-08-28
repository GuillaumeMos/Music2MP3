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
    Si tu es en PKCE:
        sp = SpotifyClient(token_supplier=auth.get_token)
    Si tu es en Client Credentials:
        sp = SpotifyClient(token_supplier=lambda: your_app_token_string)
    """
    def __init__(self, token_supplier):
        self._get_token = token_supplier

    @staticmethod
    def extract_playlist_id(url: str) -> str | None:
        m = re.search(r"(?:playlist/|spotify:playlist:)([A-Za-z0-9]+)", url or "")
        return m.group(1) if m else None

    def _headers(self):
        return {"Authorization": f"Bearer {self._get_token()}"}

    def fetch_playlist_detailed(self, playlist_id: str) -> tuple[list[dict], str]:
        """
        Renvoie (rows, playlist_name) avec les colonnes:
        Track URI,Track Name,Album Name,Artist Name(s),Release Date,Duration (ms),Popularity,Explicit,
        Added By,Added At,Genres,Record Label,Danceability,Energy,Key,Loudness,Mode,Speechiness,
        Acousticness,Instrumentalness,Liveness,Valence,Tempo,Time Signature
        """
        # 1) Lire la playlist paginée
        url = f"{API}/playlists/{playlist_id}"
        params = {
            "fields": "name,tracks.items(added_at,added_by(id),track(uri,name,explicit,popularity,duration_ms,album(name,release_date,label),artists(id,name),type,is_local)),tracks.next"
        }
        r = requests.get(url, headers=self._headers(), params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        name = data.get("name") or "SpotifyPlaylist"

        items = (data.get("tracks") or {}).get("items") or []
        next_url = (data.get("tracks") or {}).get("next")
        while next_url:
            # paginate
            r = requests.get(next_url, headers=self._headers(), timeout=20)
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", "1")))
                continue
            r.raise_for_status()
            page = r.json()
            items.extend(page.get("items") or [])
            next_url = page.get("next")

        # 2) Collecter IDs pour batchs (audio-features & artists)
        track_ids, artist_ids = [], []
        flat_items = []  # conserve les champs déjà parsés (pour réassemblage)

        for it in items:
            tr = (it or {}).get("track") or {}
            if not tr or tr.get("type") != "track" or tr.get("is_local"):
                continue

            t_uri = tr.get("uri") or ""
            # on peut extraire l’ID à partir de l’URI spotify:track:<id>
            t_id = t_uri.split(":")[-1] if ":" in t_uri else tr.get("id")
            if t_id: track_ids.append(t_id)

            artists = tr.get("artists") or []
            artist_ids.extend([a.get("id") for a in artists if a.get("id")])

            flat_items.append({
                "uri": t_uri,
                "name": tr.get("name") or "",
                "explicit": bool(tr.get("explicit")),
                "popularity": tr.get("popularity") if tr.get("popularity") is not None else "",
                "duration_ms": tr.get("duration_ms") or "",
                "album_name": (tr.get("album") or {}).get("name") or "",
                "release_date": (tr.get("album") or {}).get("release_date") or "",
                "label": (tr.get("album") or {}).get("label") or "",
                "artist_names": ", ".join([a.get("name") for a in artists if a.get("name")]),
                "artist_ids": [a.get("id") for a in artists if a.get("id")],
                "added_by": (it.get("added_by") or {}).get("id") or "",
                "added_at": it.get("added_at") or "",
                "track_id": t_id,
            })

        # 3) Audio features par batch de 100
        features_by_id = {}
        for chunk in _chunks([tid for tid in track_ids if tid], 100):
            q = ",".join(chunk)
            rr = requests.get(f"{API}/audio-features", headers=self._headers(), params={"ids": q}, timeout=20)
            if rr.status_code == 429:
                time.sleep(int(rr.headers.get("Retry-After", "1")))
                rr = requests.get(f"{API}/audio-features", headers=self._headers(), params={"ids": q}, timeout=20)
            rr.raise_for_status()
            for af in (rr.json().get("audio_features") or []):
                if af and af.get("id"):
                    features_by_id[af["id"]] = af

        # 4) Genres via artists par batch de 50 (on fusionne les genres de tous les artistes du titre)
        genres_by_artist = {}
        uniq_artist_ids = list({aid for aid in artist_ids if aid})
        for chunk in _chunks(uniq_artist_ids, 50):
            q = ",".join(chunk)
            rr = requests.get(f"{API}/artists", headers=self._headers(), params={"ids": q}, timeout=20)
            if rr.status_code == 429:
                time.sleep(int(rr.headers.get("Retry-After", "1")))
                rr = requests.get(f"{API}/artists", headers=self._headers(), params={"ids": q}, timeout=20)
            rr.raise_for_status()
            for ar in (rr.json().get("artists") or []):
                if ar and ar.get("id"):
                    genres_by_artist[ar["id"]] = ar.get("genres") or []

        # 5) Assemblage final des lignes CSV
        rows = []
        for it in flat_items:
            tfeat = features_by_id.get(it["track_id"], {}) if it["track_id"] else {}
            # fusion des genres de tous les artistes du titre
            gset = set()
            for aid in (it.get("artist_ids") or []):
                for g in genres_by_artist.get(aid, []):
                    gset.add(g)
            genres = ", ".join(sorted(gset)) if gset else ""

            rows.append({
                "Track URI": it["uri"],
                "Track Name": it["name"],
                "Album Name": it["album_name"],
                "Artist Name(s)": it["artist_names"],
                "Release Date": it["release_date"],
                "Duration (ms)": it["duration_ms"],
                "Popularity": it["popularity"],
                "Explicit": str(it["explicit"]).lower(),  # to match your sample (true/false)
                "Added By": it["added_by"],
                "Added At": it["added_at"],
                "Genres": genres,
                "Record Label": it["label"],
                "Danceability": tfeat.get("danceability", ""),
                "Energy": tfeat.get("energy", ""),
                "Key": tfeat.get("key", ""),
                "Loudness": tfeat.get("loudness", ""),
                "Mode": tfeat.get("mode", ""),
                "Speechiness": tfeat.get("speechiness", ""),
                "Acousticness": tfeat.get("acousticness", ""),
                "Instrumentalness": tfeat.get("instrumentalness", ""),
                "Liveness": tfeat.get("liveness", ""),
                "Valence": tfeat.get("valence", ""),
                "Tempo": tfeat.get("tempo", ""),
                "Time Signature": tfeat.get("time_signature", ""),
            })

        return rows, name
