import tempfile
import unittest
from pathlib import Path

from library_manifest import (
    MANIFEST_FILENAME,
    build_manifest,
    manifest_source,
    playlist_output_parent,
    read_manifest,
    scan_library,
    write_manifest,
)


class LibraryManifestTests(unittest.TestCase):
    def test_write_read_and_scan_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Playlist"
            manifest = build_manifest(
                playlist_name="Playlist",
                playlist_dir=playlist_dir,
                source={"type": "spotify", "url": "https://open.spotify.com/playlist/abc", "name": "Playlist"},
                settings={"safe_search": True},
                tracks=[{"idx": 1, "title": "Track", "status": "done", "file": "Track.mp3"}],
            )

            path = write_manifest(playlist_dir, manifest)
            self.assertEqual(path.name, MANIFEST_FILENAME)

            loaded = read_manifest(playlist_dir)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["playlist_name"], "Playlist")
            self.assertEqual(loaded["source"]["type"], "spotify")

            found = scan_library(root)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["playlist_name"], "Playlist")
            self.assertEqual(found[0]["track_count"], 1)
            self.assertEqual(manifest_source(found[0])["type"], "spotify")
            self.assertEqual(playlist_output_parent(found[0]), str(root.resolve()))

    def test_build_manifest_preserves_created_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = build_manifest(
                playlist_name="Updated",
                playlist_dir=tmp,
                source=None,
                settings={},
                tracks=[],
                previous_manifest={"created_at": "2026-01-01T00:00:00+00:00"},
            )

            self.assertEqual(manifest["created_at"], "2026-01-01T00:00:00+00:00")

    def test_scan_library_includes_legacy_audio_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "Old Playlist"
            legacy.mkdir()
            (legacy / "Track.mp3").write_bytes(b"audio")

            found = scan_library(root)

            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["playlist_name"], "Old Playlist")
            self.assertEqual(found[0]["source"]["type"], "legacy")
            self.assertTrue(found[0]["_legacy"])


if __name__ == "__main__":
    unittest.main()
