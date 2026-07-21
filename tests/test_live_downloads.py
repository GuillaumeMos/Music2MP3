import csv
import json
import os
import tempfile
import unittest
from pathlib import Path

from converter import Converter
from library_manifest import MANIFEST_FILENAME
from soundcloud_api import SoundCloudClient
from spotify_api import SpotifyClient


LIVE_DOWNLOADS = os.environ.get("MUSIC2MP3_LIVE_DOWNLOADS") == "1"
SOUNDCLOUD_EXAMPLE_URL = (
    "https://soundcloud.com/guiggz-1/sets/dl-playlist/s-CgcmK2MGhwO"
    "?si=8a9d42cfc9024436906dfe6ab3d08bb1&utm_source=clipboard&utm_medium=text&utm_campaign=social_sharing"
)
SPOTIFY_EXAMPLE_URL = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
LIVE_AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".aiff", ".aif", ".opus", ".ogg", ".webm", ".mp4"}


def _live_config() -> dict:
    return {
        "output_mode": os.environ.get("MUSIC2MP3_LIVE_OUTPUT_MODE", "auto"),
        "output_format": os.environ.get("MUSIC2MP3_LIVE_OUTPUT_FORMAT", "mp3"),
        "output_format_manual": os.environ.get("MUSIC2MP3_LIVE_OUTPUT_FORMAT", "mp3"),
        "safe_search": True,
        "strict_match": False,
        "deep_search": True,
        "generate_m3u": False,
        "incremental_update": False,
        "concurrency": 1,
        "cookies_path": os.environ.get("MUSIC2MP3_COOKIES_PATH", ""),
        "cookies_from_browser": os.environ.get("MUSIC2MP3_COOKIES_FROM_BROWSER", ""),
        "cookies_browser_profile": os.environ.get("MUSIC2MP3_COOKIES_BROWSER_PROFILE", ""),
    }


def _write_single_track_csv(path: Path, row: dict):
    fieldnames = ["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)", "Source URL", "Track URI"]
    normalized = {key: row.get(key, "") for key in fieldnames}
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(normalized)


def _assert_downloaded_audio(testcase: unittest.TestCase, out_dir: Path):
    audio_files = [
        p for p in out_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in LIVE_AUDIO_EXTS and p.stat().st_size > 0
    ]
    testcase.assertTrue(audio_files, f"No non-empty audio file was produced in {out_dir}")
    manifest_path = out_dir / MANIFEST_FILENAME
    testcase.assertTrue(manifest_path.is_file(), f"Missing manifest at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    statuses = [track.get("status") for track in manifest.get("tracks", [])]
    testcase.assertIn("done", statuses, f"No done track in manifest: {statuses}")


@unittest.skipUnless(LIVE_DOWNLOADS, "set MUSIC2MP3_LIVE_DOWNLOADS=1 to run live network/download tests")
class LiveDownloadTests(unittest.TestCase):
    def test_soundcloud_example_playlist_loads_and_downloads_first_track(self):
        url = os.environ.get("MUSIC2MP3_LIVE_SOUNDCLOUD_URL", SOUNDCLOUD_EXAMPLE_URL)
        config = _live_config()

        rows, name = SoundCloudClient().fetch_playlist(
            url,
            cookies_path=config["cookies_path"],
            cookies_from_browser=config["cookies_from_browser"],
            cookies_browser_profile=config["cookies_browser_profile"],
        )

        self.assertTrue(rows, "SoundCloud playlist returned no rows")
        first = rows[0]
        self.assertTrue(first.get("Source URL"), f"First SoundCloud row has no Source URL: {first}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "soundcloud_single.csv"
            _write_single_track_csv(csv_path, first)

            conv = Converter(config=config)
            result_dir = Path(conv.convert_from_csv(
                str(csv_path),
                str(root / "out"),
                "LiveSoundCloud",
                source_info={"type": "soundcloud", "url": url, "name": name or "SoundCloud"},
            ))

            _assert_downloaded_audio(self, result_dir)

    def test_spotify_example_playlist_loads_and_downloads_first_track(self):
        token = os.environ.get("SPOTIFY_ACCESS_TOKEN", "").strip()
        if not token:
            self.skipTest("set SPOTIFY_ACCESS_TOKEN to run Spotify live download test")

        url = os.environ.get("MUSIC2MP3_LIVE_SPOTIFY_URL", SPOTIFY_EXAMPLE_URL)
        playlist_id = SpotifyClient.extract_playlist_id(url)
        self.assertIsNotNone(playlist_id, f"Invalid Spotify playlist URL: {url}")

        rows, name = SpotifyClient(lambda: token).fetch_playlist(playlist_id)
        self.assertTrue(rows, "Spotify playlist returned no rows")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "spotify_single.csv"
            _write_single_track_csv(csv_path, rows[0])

            conv = Converter(config=_live_config())
            result_dir = Path(conv.convert_from_csv(
                str(csv_path),
                str(root / "out"),
                "LiveSpotify",
                source_info={"type": "spotify", "url": url, "name": name or "Spotify"},
            ))

            _assert_downloaded_audio(self, result_dir)


if __name__ == "__main__":
    unittest.main()
