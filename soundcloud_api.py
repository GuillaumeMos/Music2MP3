# soundcloud_api.py
import json
import re
from typing import Tuple, List, Dict
from urllib.parse import parse_qs, urlsplit, urlunsplit

import requests

from utils import build_ytdlp_cookie_args, find_ytdlp_cmd, run_quiet
from config import resource_path


def _find_ytdlp_cmd() -> list[str]:
    return find_ytdlp_cmd(resource_path)


class SoundCloudClient:
    """
    Build a CSV-ready list of rows from a SoundCloud playlist (or single track) URL,
    without any authentication. Private links with secret token also work.
    """

    def fetch_playlist(
        self,
        url: str,
        cookies_path: str | None = None,
        cookies_from_browser: str | None = None,
        cookies_browser_profile: str | None = None,
    ) -> Tuple[List[Dict], str]:
        """
        Returns (rows, name)

        Each row:
          Track Name, Artist Name(s), Album Name, Duration (ms), Source URL, Track URI
        """
        # Use NON-FLAT JSON to get full metadata (flat often misses uploader/duration).
        # If SoundCloud blocks rich set metadata, try flat once so public entries may
        # still be listed and enriched individually.
        cookie_config = {
            "cookies_path": cookies_path or "",
            "cookies_from_browser": cookies_from_browser or "",
            "cookies_browser_profile": cookies_browser_profile or "",
        }
        data = self._fetch_page_hydration(url) if _is_soundcloud_set_url(url) else {}
        if not data:
            data = self._fetch_with_ytdlp(url, cookie_config)

        rows: List[Dict] = []
        playlist_title = data.get("title") or data.get("playlist_title") or "SoundCloud"

        entries = data.get("entries")
        if isinstance(entries, list) and entries:
            # Playlist case
            for e in entries:
                # Some extractors still return semi-flat entries: enrich if needed.
                # Page hydration already has title, duration, URL and nested user.
                if not self._looks_full(e):
                    track_url = e.get("webpage_url") or e.get("permalink_url") or e.get("url")
                    if track_url:
                        try:
                            e = self._dump_sc_json(track_url, cookie_config=cookie_config, flat=False)
                        except RuntimeError:
                            pass
                rows.append(self._row_from_info(e, playlist_title))
            return rows, playlist_title

        # Single track
        rows.append(self._row_from_info(data, playlist_title))
        return rows, playlist_title

    def _fetch_with_ytdlp(self, url: str, cookie_config: dict) -> Dict:
        try:
            return self._dump_sc_json(url, cookie_config=cookie_config, flat=False)
        except RuntimeError as first_error:
            try:
                return self._dump_sc_json(url, cookie_config=cookie_config, flat=True)
            except RuntimeError as second_error:
                data = self._fetch_page_hydration(url)
                if not data:
                    raise second_error from first_error
                return data

    # ------------------ helpers ------------------

    def _looks_full(self, info: Dict) -> bool:
        """Heuristic to see if we have rich fields already."""
        user = info.get("user") if isinstance(info.get("user"), dict) else {}
        return bool(info.get("title")) and bool(
            info.get("uploader")
            or info.get("uploader_id")
            or info.get("artist")
            or info.get("creator")
            or user.get("username")
            or user.get("permalink")
        )

    def _row_from_info(self, info: Dict, playlist_title: str = "") -> Dict:
        url = self._best_track_url(info)
        inferred_artist, inferred_title = _title_artist_from_soundcloud_url(url)
        user = info.get("user") if isinstance(info.get("user"), dict) else {}
        title = (info.get("title")
                 or info.get("track")
                 or inferred_title
                 or "Unknown")
        artist = (info.get("artist")
                  or info.get("uploader")
                  or info.get("creator")
                  or info.get("channel")
                  or info.get("uploader_id")
                  or user.get("username")
                  or user.get("permalink")
                  or inferred_artist
                  or "Unknown")
        dur_ms = _duration_ms(info.get("duration"))
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

    def _best_track_url(self, info: Dict) -> str:
        for key in ("permalink_url", "webpage_url", "original_url", "url"):
            raw = str(info.get(key) or "").strip()
            if not raw:
                continue
            cleaned = _clean_soundcloud_track_url(raw)
            if cleaned and not _is_soundcloud_set_url(cleaned):
                return cleaned
        return ""

    def _dump_sc_json(self, url: str, cookie_config: dict | None = None, flat: bool = False) -> Dict:
        """
        Dump JSON from yt-dlp.
        flat=False  -> full metadata (preferred)
        """
        cmd = _find_ytdlp_cmd()
        if flat:
            cmd += ["--flat-playlist"]
        cmd += [
            "--dump-single-json",
            "--no-warnings",
            "-q",
            url,
        ]
        cmd += build_ytdlp_cookie_args(cookie_config)

        try:
            proc = run_quiet(cmd, text=True, capture_output=True)
        except FileNotFoundError as e:
            raise RuntimeError(
                "yt-dlp is not available. Install it with `pip install yt-dlp` "
                "or bundle the yt-dlp binary with the app."
            ) from e
        if proc.returncode != 0:
            raise RuntimeError(_format_soundcloud_ytdlp_error(proc.stderr or "", cookie_config))
        try:
            return json.loads(proc.stdout or "{}")
        except Exception as e:
            raise RuntimeError(f"Invalid JSON from yt-dlp: {e}")

    def _fetch_page_hydration(self, url: str) -> Dict:
        if not _is_soundcloud_set_url(url):
            return {}
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            response.raise_for_status()
        except Exception:
            return {}
        hydration = _extract_sc_hydration(response.text)
        client_id = _extract_sc_client_id(hydration)
        for item in hydration:
            if not isinstance(item, dict) or item.get("hydratable") != "playlist":
                continue
            data = item.get("data")
            if isinstance(data, dict) and isinstance(data.get("tracks"), list):
                tracks = self._enrich_hydration_tracks(data.get("tracks") or [], client_id)
                return {
                    "title": data.get("title") or "SoundCloud",
                    "entries": tracks,
                }
        return {}

    def _enrich_hydration_tracks(self, tracks: list, client_id: str) -> list:
        if not client_id:
            return tracks
        missing_ids = [
            str(t.get("id"))
            for t in tracks
            if isinstance(t, dict) and t.get("id") and not t.get("permalink_url")
        ]
        if not missing_ids:
            return tracks
        enriched: dict[str, dict] = {}
        for start in range(0, len(missing_ids), 50):
            chunk = missing_ids[start:start + 50]
            try:
                response = requests.get(
                    "https://api-v2.soundcloud.com/tracks",
                    params={"ids": ",".join(chunk), "client_id": client_id},
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=15,
                )
                response.raise_for_status()
                payload = response.json()
            except Exception:
                continue
            if not isinstance(payload, list):
                continue
            for item in payload:
                if isinstance(item, dict) and item.get("id"):
                    enriched[str(item.get("id"))] = item
        if not enriched:
            return tracks
        merged = []
        for track in tracks:
            if isinstance(track, dict) and track.get("id"):
                merged.append(enriched.get(str(track.get("id")), track))
            else:
                merged.append(track)
        return merged


def _format_soundcloud_ytdlp_error(stderr: str, cookie_config: dict | None = None) -> str:
    detail = (stderr or "yt-dlp failed on SoundCloud URL").strip()
    low = detail.lower()
    cfg = cookie_config or {}
    has_auth = bool(str(cfg.get("cookies_from_browser") or "").strip() or str(cfg.get("cookies_path") or "").strip())
    if "403" in low or "forbidden" in low or "unable to download json metadata" in low:
        msg = (
            "SoundCloud blocked metadata access (HTTP 403). "
            "Open Settings and set Browser auth to your logged-in browser, "
            "or provide a Netscape cookies.txt file."
        )
        if has_auth:
            msg += " If auth is already configured, refresh your browser session or try a cookies.txt export."
        return f"{msg}\n\nSoundCloud yt-dlp output:\n{detail}"
    return detail


def _extract_sc_hydration(html_text: str) -> list:
    if not html_text:
        return []
    match = re.search(r"<script>window\.__sc_hydration\s*=\s*(.*?);</script>", html_text, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _extract_sc_client_id(hydration: list) -> str:
    for item in hydration:
        if not isinstance(item, dict) or item.get("hydratable") != "apiClient":
            continue
        data = item.get("data")
        if isinstance(data, dict):
            return str(data.get("id") or "").strip()
    return ""


def _duration_ms(value) -> int | str:
    if value in ("", None):
        return ""
    try:
        duration = float(value)
    except Exception:
        return ""
    if duration <= 0:
        return ""
    # yt-dlp returns seconds; SoundCloud page hydration returns milliseconds.
    if duration > 36000:
        return int(duration)
    return int(duration * 1000)


def _clean_soundcloud_track_url(url: str) -> str:
    if "soundcloud.com" not in (url or "").lower():
        return url
    try:
        parts = urlsplit(url)
    except Exception:
        return url
    # Track URLs inside playlists often look like:
    # https://soundcloud.com/user/track?in=owner/sets/playlist
    # Keeping the in= query can make yt-dlp pick the soundcloud:set extractor.
    query = parse_qs(parts.query)
    if "in" in query:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def _is_soundcloud_set_url(url: str) -> bool:
    low = (url or "").lower()
    if low.startswith("soundcloud:set:"):
        return True
    if "soundcloud.com" not in low:
        return False
    try:
        path = urlsplit(low).path.rstrip("/")
    except Exception:
        path = low
    return "/sets/" in f"{path}/" or path.endswith("/sets") or "/playlists/" in f"{path}/" or path.endswith("/playlists")


def _title_artist_from_soundcloud_url(url: str) -> tuple[str, str]:
    if "soundcloud.com" not in (url or "").lower():
        return "", ""
    try:
        path_parts = [p for p in urlsplit(url).path.split("/") if p]
    except Exception:
        return "", ""
    if len(path_parts) < 2:
        return "", ""
    artist = path_parts[0].replace("-", " ").strip()
    title = path_parts[-1].replace("-", " ").strip()
    return artist, title
