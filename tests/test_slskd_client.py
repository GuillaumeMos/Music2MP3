import unittest
from types import SimpleNamespace
from unittest.mock import patch

import slskd_client
from slskd_client import SlskdClient, build_slskd_client, format_slskd_result


class _FakeSearches:
    def __init__(self):
        self.enqueued = []

    def search_text(self, *_args, **_kwargs):
        return {"id": "search-1"}

    def search_responses(self, _search_id):
        return [
            {
                "username": "fast-user",
                "queueLength": 0,
                "uploadSpeed": 1000,
                "hasFreeUploadSlot": True,
                "files": [
                    {
                        "filename": "Artist - Track.flac",
                        "extension": "flac",
                        "size": 42 * 1024 * 1024,
                        "bitDepth": 16,
                        "sampleRate": 44100,
                        "length": 180,
                    },
                    {
                        "filename": "cover.jpg",
                        "extension": "jpg",
                        "size": 1000,
                    },
                ],
            },
            {
                "username": "slow-user",
                "queueLength": 10,
                "uploadSpeed": 10,
                "hasFreeUploadSlot": False,
                "files": [{
                    "filename": "Artist - Track.mp3",
                    "extension": "mp3",
                    "size": 9 * 1024 * 1024,
                    "bitRate": 320,
                }],
            },
        ]

    def enqueue(self, username, files):
        self.enqueued.append((username, files))
        return True


class _FakeSlskdApiClient:
    last_instance = None

    def __init__(self, *_args, **_kwargs):
        self.searches = _FakeSearches()
        _FakeSlskdApiClient.last_instance = self


class SlskdClientTests(unittest.TestCase):
    def test_search_audio_filters_audio_and_ranks_lossless_first(self):
        fake_module = SimpleNamespace(SlskdClient=_FakeSlskdApiClient)
        with patch.object(slskd_client, "slskd_api", fake_module):
            client = SlskdClient("http://127.0.0.1:5030", "api-key")
            results = client.search_audio("Artist Track", limit=5, timeout_ms=1000)

        self.assertEqual([r.extension for r in results], ["flac", "mp3"])
        self.assertEqual(results[0].username, "fast-user")
        self.assertIn("FLAC", format_slskd_result(results[0]))

    def test_enqueue_uses_original_file_payload(self):
        fake_module = SimpleNamespace(SlskdClient=_FakeSlskdApiClient)
        with patch.object(slskd_client, "slskd_api", fake_module):
            client = SlskdClient("http://127.0.0.1:5030", "api-key")
            result = client.search_audio("Artist Track", limit=1)[0]
            self.assertTrue(client.enqueue(result))

        fake = _FakeSlskdApiClient.last_instance
        self.assertEqual(fake.searches.enqueued[0][0], "fast-user")
        self.assertEqual(fake.searches.enqueued[0][1][0]["filename"], "Artist - Track.flac")

    def test_build_slskd_client_requires_enabled_host_and_key(self):
        with patch("slskd_client.get_slskd_api_key", return_value=""):
            self.assertIsNone(build_slskd_client({"slskd_enabled": True, "slskd_host": "http://localhost:5030"}))
        with patch("slskd_client.get_slskd_api_key", return_value="key"), patch.object(
            slskd_client,
            "slskd_api",
            SimpleNamespace(SlskdClient=_FakeSlskdApiClient),
        ):
            self.assertIsNotNone(build_slskd_client({"slskd_enabled": True, "slskd_host": "http://localhost:5030"}))


if __name__ == "__main__":
    unittest.main()
