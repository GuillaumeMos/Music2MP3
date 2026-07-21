from __future__ import annotations

import csv
import os
import tempfile
import threading

from PySide6.QtCore import QObject, Signal, Slot

from bandcamp_api import BandcampClient
from converter import Converter
from library_cleanup import analyze_library_cleanup
from soundcloud_api import SoundCloudClient
from spotify_api import SpotifyClient
from spotify_auth import PKCEAuth
from token_store import RefreshTokenStore


class ConverterWorker(QObject):
    status = Signal(str)
    progress = Signal(int, int)
    item = Signal(str, object)
    done = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, config, csv_path, output_folder, playlist_hint, source_info=None):
        super().__init__()
        self._config = config
        self._csv_path = csv_path
        self._output_folder = output_folder
        self._playlist_hint = playlist_hint
        self._source_info = source_info
        self._cancel_event = threading.Event()

    def stop(self):
        self._cancel_event.set()

    @Slot()
    def run(self):
        try:
            conv = Converter(
                config=self._config,
                status_cb=lambda s: self.status.emit(s),
                progress_cb=lambda c, m: self.progress.emit(c, m),
                item_cb=lambda k, d: self.item.emit(k, d),
                cancel_event=self._cancel_event,
            )
            out_dir = conv.convert_from_csv(
                self._csv_path, self._output_folder,
                self._playlist_hint, source_info=self._source_info,
            )
            self.done.emit(out_dir)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self.finished.emit()


class PlaylistLoadWorker(QObject):
    status = Signal(str)
    done = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, mode: str, url: str, config: dict):
        super().__init__()
        self.mode = mode
        self.url = url
        self.config = config or {}

    @Slot()
    def run(self):
        try:
            if self.mode == "spotify":
                payload = self._load_spotify()
            elif self.mode == "soundcloud":
                payload = self._load_soundcloud()
            elif self.mode == "bandcamp":
                payload = self._load_bandcamp()
            else:
                raise RuntimeError(f"Unsupported mode: {self.mode}")
            self.done.emit(payload)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self.finished.emit()

    def _load_spotify(self) -> dict:
        pid = SpotifyClient.extract_playlist_id(self.url)
        if not pid:
            raise RuntimeError("Invalid Spotify playlist URL.")
        client_id = self.config.get("spotify_client_id")
        if not client_id:
            raise RuntimeError('Missing "spotify_client_id" in config.')
        self.status.emit("Opening browser for Spotify authorization...")
        token_store = RefreshTokenStore(service="Music2MP3", user="spotify_pkce")
        auth = PKCEAuth(
            client_id=client_id,
            redirect_uri="http://127.0.0.1:8765/callback",
            scopes=["playlist-read-private", "playlist-read-collaborative"],
            refresh_token_store=token_store,
        )
        sp = SpotifyClient(token_supplier=auth.get_token)
        self.status.emit("Fetching playlist from Spotify...")
        rows, name = sp.fetch_playlist(pid)
        tmp = self._write_temp_csv(rows, ["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)"], "spotify_playlist_")
        return {"csv_path": tmp, "playlist_name": name or "SpotifyPlaylist", "count": len(rows),
                "source": "Spotify", "source_type": "spotify", "source_url": self.url}

    def _load_soundcloud(self) -> dict:
        self.status.emit("Fetching playlist from SoundCloud...")
        sc = SoundCloudClient()
        rows, name = sc.fetch_playlist(
            self.url,
            cookies_path=self.config.get("cookies_path"),
            cookies_from_browser=self.config.get("cookies_from_browser"),
            cookies_browser_profile=self.config.get("cookies_browser_profile"),
        )
        tmp = self._write_temp_csv(
            rows,
            ["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)", "Source URL", "Track URI"],
            "soundcloud_playlist_",
        )
        return {"csv_path": tmp, "playlist_name": name or "SoundCloud", "count": len(rows),
                "source": "SoundCloud", "source_type": "soundcloud", "source_url": self.url}

    def _load_bandcamp(self) -> dict:
        self.status.emit("Fetching release from Bandcamp...")
        bc = BandcampClient()
        cookies_path = self.config.get("cookies_path")
        rows, name = bc.fetch_playlist(self.url, cookies_path=cookies_path)
        tmp = self._write_temp_csv(
            rows,
            ["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)", "Source URL", "Track URI"],
            "bandcamp_release_",
        )
        return {"csv_path": tmp, "playlist_name": name or "Bandcamp", "count": len(rows),
                "source": "Bandcamp", "source_type": "bandcamp", "source_url": self.url}

    @staticmethod
    def _write_temp_csv(rows, fieldnames, prefix) -> str:
        fd, tmp = tempfile.mkstemp(prefix=prefix, suffix=".csv")
        os.close(fd)
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return tmp


class LibraryCleanupWorker(QObject):
    done = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, root_dir: str):
        super().__init__()
        self.root_dir = root_dir

    @Slot()
    def run(self):
        try:
            self.done.emit(analyze_library_cleanup(self.root_dir))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
