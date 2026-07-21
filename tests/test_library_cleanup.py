import json
import tempfile
import unittest
from pathlib import Path

from library_cleanup import analyze_library_cleanup, apply_library_cleanup, cleanup_action_count
from library_manifest import build_manifest, scan_library, write_manifest


class LibraryCleanupTests(unittest.TestCase):
    def test_analyze_and_apply_safe_library_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            parent = root / "Parent"
            nested = parent / "Nested"
            kept = nested / "Track.mp3"
            orphan = nested / "Old match.mp3"
            kept.parent.mkdir(parents=True)
            kept.write_bytes(b"kept")
            orphan.write_bytes(b"orphan")
            loose = root / "Loose.mp3"
            loose.write_bytes(b"loose")
            shared = root / "Other" / "Track.mp3"
            shared.parent.mkdir()
            shared.write_bytes(b"kept")

            manifest = build_manifest(
                playlist_name="Nested",
                playlist_dir=nested,
                source={"type": "spotify", "url": "https://open.spotify.com/playlist/nested?si=one"},
                settings={},
                tracks=[
                    {"idx": 1, "title": "Track", "file": "Track.mp3", "status": "done"},
                    {"idx": 2, "title": "Track", "file": "Track.mp3", "status": "done"},
                ],
            )
            write_manifest(nested, manifest)
            other_manifest = build_manifest(
                playlist_name="Other",
                playlist_dir=shared.parent,
                source={"type": "spotify", "url": "https://open.spotify.com/playlist/other"},
                settings={},
                tracks=[{"idx": 1, "title": "Track", "file": "Track.mp3", "status": "done"}],
            )
            write_manifest(shared.parent, other_manifest)

            report = analyze_library_cleanup(root)
            self.assertEqual(report["orphan_files"], [str(orphan)])
            self.assertEqual(report["loose_root_files"], [str(loose)])
            self.assertEqual(report["exact_duplicate_copies"], 1)
            self.assertEqual(len(report["nested_playlists"]), 1)
            self.assertEqual(cleanup_action_count(report), 4)

            result = apply_library_cleanup(report)
            self.assertEqual(result["moved_files"], 2)
            self.assertEqual(result["removed_track_entries"], 1)
            self.assertEqual(result["flattened_playlists"], 1)
            self.assertEqual(result["errors"], [])
            self.assertFalse(orphan.exists())
            self.assertFalse(loose.exists())
            self.assertTrue((root / "Nested" / "Track.mp3").is_file())
            self.assertTrue(shared.is_file())

            cleaned = json.loads((root / "Nested" / "music2mp3.manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(cleaned["playlist_dir"], str(root / "Nested"))
            self.assertEqual(len(cleaned["tracks"]), 1)
            self.assertEqual(len(scan_library(root)), 2)
            self.assertTrue(Path(result["backup_dir"], "cleanup.json").is_file())

    def test_duplicate_source_query_parameters_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for name, query in (("One", "first"), ("Two", "second")):
                folder = root / name
                manifest = build_manifest(
                    playlist_name=name,
                    playlist_dir=folder,
                    source={
                        "type": "spotify",
                        "url": f"https://open.spotify.com/playlist/same?si={query}",
                    },
                    settings={},
                    tracks=[],
                )
                write_manifest(folder, manifest)

            report = analyze_library_cleanup(root)
            self.assertEqual(len(report["duplicate_sources"]), 1)
            self.assertEqual(cleanup_action_count(report), 0)


if __name__ == "__main__":
    unittest.main()
