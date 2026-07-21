import tempfile
import unittest
from pathlib import Path

from library_attention import attention_counts, collect_attention_items
from library_manifest import build_manifest, write_manifest


class LibraryAttentionTests(unittest.TestCase):
    def test_collects_failed_review_and_missing_tracks(self):
        with tempfile.TemporaryDirectory() as tmp:
            playlist_dir = Path(tmp).resolve() / "Playlist"
            present_file = playlist_dir / "Present.mp3"
            present_file.parent.mkdir(parents=True)
            present_file.write_bytes(b"audio")
            manifest = build_manifest(
                playlist_name="Playlist",
                playlist_dir=playlist_dir,
                source={"type": "spotify", "url": "https://open.spotify.com/playlist/demo"},
                settings={},
                tracks=[
                    {"idx": 1, "title": "Present", "file": "Present.mp3", "status": "done"},
                    {"idx": 2, "title": "Missing", "file": "Missing.mp3", "status": "done"},
                    {"idx": 3, "title": "Blocked", "file": "", "status": "failed", "error": "HTTP Error 403: Forbidden"},
                    {
                        "idx": 4,
                        "title": "Maybe",
                        "file": "",
                        "status": "failed",
                        "error": "AI suggested candidate. Manual validation required.",
                        "suggested_url": "https://youtu.be/maybe",
                    },
                ],
            )
            manifest_path = write_manifest(playlist_dir, manifest)
            manifest["_manifest_path"] = str(manifest_path)

            items = collect_attention_items([manifest])

            self.assertEqual([item["track_idx"] for item in items], [4, 3, 2])
            self.assertEqual(items[0]["kind"], "review")
            self.assertEqual(items[0]["candidate_url"], "https://youtu.be/maybe")
            self.assertEqual(items[1]["issue"], "Download blocked")
            self.assertEqual(items[2]["kind"], "missing")
            self.assertEqual(
                attention_counts(items),
                {"total": 3, "review": 1, "failed": 1, "missing": 1},
            )

    def test_uses_match_url_for_failed_download_retry(self):
        playlist = {
            "playlist_name": "Demo",
            "playlist_dir": "/tmp/demo",
            "tracks": [{
                "idx": 8,
                "title": "Track",
                "status": "failed",
                "error": "yt-dlp failed",
                "match": {"url": "https://youtu.be/retry", "score": 0.92},
            }],
        }

        items = collect_attention_items([playlist])

        self.assertEqual(items[0]["candidate_url"], "https://youtu.be/retry")


if __name__ == "__main__":
    unittest.main()
