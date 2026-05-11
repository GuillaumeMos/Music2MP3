import unittest
from unittest.mock import patch

from bandcamp_api import BandcampClient


class BandcampApiTests(unittest.TestCase):
    def test_row_from_info_uses_album_and_source_url(self):
        client = BandcampClient()
        row = client._row_from_info(
            {
                "title": "Track",
                "artist": "Artist",
                "album": "Album",
                "duration": 123.4,
                "webpage_url": "https://artist.bandcamp.com/track/track",
                "id": "abc123",
            },
            playlist_title="Release",
        )

        self.assertEqual(row["Track Name"], "Track")
        self.assertEqual(row["Artist Name(s)"], "Artist")
        self.assertEqual(row["Album Name"], "Album")
        self.assertEqual(row["Duration (ms)"], 123400)
        self.assertEqual(row["Source URL"], "https://artist.bandcamp.com/track/track")
        self.assertEqual(row["Track URI"], "bandcamp:track:abc123")

    def test_fetch_playlist_enriches_flat_album_entries(self):
        client = BandcampClient()
        with patch.object(client, "_dump_bandcamp_json") as dump:
            dump.side_effect = [
                {
                    "title": "Album",
                    "entries": [
                        {"title": "Flat", "webpage_url": "https://artist.bandcamp.com/track/flat"}
                    ],
                },
                {
                    "title": "Flat",
                    "artist": "Artist",
                    "duration": 180,
                    "webpage_url": "https://artist.bandcamp.com/track/flat",
                    "id": "1",
                },
            ]

            rows, name = client.fetch_playlist("https://artist.bandcamp.com/album/album")

        self.assertEqual(name, "Album")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Artist Name(s)"], "Artist")
        self.assertEqual(dump.call_count, 2)


if __name__ == "__main__":
    unittest.main()
