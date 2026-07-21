import tempfile
import unittest
from pathlib import Path

from library_manifest import (
    IGNORE_FILENAME,
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

    def test_scan_library_finds_nested_legacy_audio_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "crate" / "Nested Playlist"
            nested.mkdir(parents=True)
            (nested / "Track.flac").write_bytes(b"audio")

            found = scan_library(root)

            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["playlist_name"], "Nested Playlist")
            self.assertEqual(found[0]["track_count"], 1)

    def test_ignore_marker_hides_legacy_audio_folder_until_manifest_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "Removed"
            legacy.mkdir()
            (legacy / "Track.mp3").write_bytes(b"audio")
            ignore_path = legacy / IGNORE_FILENAME
            ignore_path.write_text("hide", encoding="utf-8")

            self.assertEqual(scan_library(root), [])

            write_manifest(legacy, build_manifest(
                playlist_name="Removed",
                playlist_dir=legacy,
                source={"type": "spotify", "url": "https://open.spotify.com/playlist/removed", "name": "Removed"},
                settings={},
                tracks=[],
            ))

            self.assertFalse(ignore_path.exists())
            found = scan_library(root)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["playlist_name"], "Removed")

    def test_scan_library_dedupes_same_source_url_and_keeps_largest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            small_dir = root / "tech pepite"
            large_dir = root / "tech pépite"
            source = {"type": "spotify", "url": "https://open.spotify.com/playlist/same", "name": "tech pépite"}
            write_manifest(small_dir, build_manifest(
                playlist_name="tech pepite",
                playlist_dir=small_dir,
                source=source,
                settings={},
                tracks=[{"idx": 1, "title": "One"}],
            ))
            write_manifest(large_dir, build_manifest(
                playlist_name="tech pépite",
                playlist_dir=large_dir,
                source=source,
                settings={},
                tracks=[{"idx": i, "title": f"Track {i}"} for i in range(1, 50)],
            ))

            found = scan_library(root)

            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["playlist_name"], "tech pépite")
            self.assertEqual(found[0]["track_count"], 49)


if __name__ == "__main__":
    unittest.main()
