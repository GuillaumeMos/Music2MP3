import unittest
import importlib.util


REQUESTS_AVAILABLE = importlib.util.find_spec("requests") is not None

class SpotifyApiTests(unittest.TestCase):
    @unittest.skipUnless(REQUESTS_AVAILABLE, "requests is not installed in this environment")
    def test_extract_playlist_id_from_url(self):
        from spotify_api import SpotifyClient
        pid = SpotifyClient.extract_playlist_id("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
        self.assertEqual(pid, "37i9dQZF1DXcBWIGoYBM5M")

    @unittest.skipUnless(REQUESTS_AVAILABLE, "requests is not installed in this environment")
    def test_extract_playlist_id_from_uri(self):
        from spotify_api import SpotifyClient
        pid = SpotifyClient.extract_playlist_id("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M")
        self.assertEqual(pid, "37i9dQZF1DXcBWIGoYBM5M")

    @unittest.skipUnless(REQUESTS_AVAILABLE, "requests is not installed in this environment")
    def test_extract_playlist_id_invalid(self):
        from spotify_api import SpotifyClient
        self.assertIsNone(SpotifyClient.extract_playlist_id("https://example.com/not-spotify"))


if __name__ == "__main__":
    unittest.main()
