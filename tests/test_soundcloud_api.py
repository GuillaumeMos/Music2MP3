import unittest

from soundcloud_api import SoundCloudClient


class SoundCloudApiTests(unittest.TestCase):
    def test_row_from_info_uses_playlist_album_and_source_url(self):
        client = SoundCloudClient()
        row = client._row_from_info(
            {
                "title": "Track",
                "uploader": "Artist",
                "duration": 123.4,
                "webpage_url": "https://soundcloud.com/a/track",
                "id": "abc123",
            },
            playlist_title="Playlist",
        )

        self.assertEqual(row["Track Name"], "Track")
        self.assertEqual(row["Artist Name(s)"], "Artist")
        self.assertEqual(row["Album Name"], "Playlist")
        self.assertEqual(row["Duration (ms)"], 123400)
        self.assertEqual(row["Source URL"], "https://soundcloud.com/a/track")
        self.assertEqual(row["Track URI"], "soundcloud:track:abc123")


if __name__ == "__main__":
    unittest.main()
