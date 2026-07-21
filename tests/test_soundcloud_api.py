import unittest
from unittest.mock import patch

from soundcloud_api import SoundCloudClient, _extract_sc_client_id, _extract_sc_hydration, _find_ytdlp_cmd


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

    def test_row_from_info_strips_playlist_context_from_track_url(self):
        client = SoundCloudClient()
        row = client._row_from_info(
            {
                "title": "Track",
                "uploader": "Artist",
                "duration": 123.4,
                "webpage_url": "https://soundcloud.com/a/track?in=owner/sets/demo",
                "id": "abc123",
            },
            playlist_title="Playlist",
        )

        self.assertEqual(row["Source URL"], "https://soundcloud.com/a/track")

    def test_row_from_info_infers_unknown_title_and_artist_from_url(self):
        client = SoundCloudClient()
        row = client._row_from_info(
            {
                "webpage_url": "https://soundcloud.com/utr2/aprd-crazy-kikker-free-download",
            },
            playlist_title="Playlist",
        )

        self.assertEqual(row["Artist Name(s)"], "utr2")
        self.assertEqual(row["Track Name"], "aprd crazy kikker free download")

    def test_row_from_info_accepts_soundcloud_page_hydration_shape(self):
        client = SoundCloudClient()
        row = client._row_from_info(
            {
                "title": "Track",
                "duration": 123400,
                "permalink_url": "https://soundcloud.com/a/track",
                "id": 123,
                "user": {"username": "Artist"},
            },
            playlist_title="Playlist",
        )

        self.assertEqual(row["Track Name"], "Track")
        self.assertEqual(row["Artist Name(s)"], "Artist")
        self.assertEqual(row["Duration (ms)"], 123400)
        self.assertEqual(row["Track URI"], "soundcloud:track:123")

    def test_dump_json_uses_browser_cookie_auth(self):
        class FakeProc:
            returncode = 0
            stdout = '{"title": "Track"}'
            stderr = ""

        captured = {}

        def fake_run_quiet(cmd, **_kwargs):
            captured["cmd"] = cmd
            return FakeProc()

        client = SoundCloudClient()
        with patch("soundcloud_api.run_quiet", side_effect=fake_run_quiet):
            client._dump_sc_json(
                "https://soundcloud.com/a/track",
                cookie_config={"cookies_from_browser": "safari"},
            )

        self.assertIn("--cookies-from-browser", captured["cmd"])
        self.assertEqual(captured["cmd"][captured["cmd"].index("--cookies-from-browser") + 1], "safari")

    def test_find_ytdlp_falls_back_to_current_python_module(self):
        with patch("utils.os.path.isfile", return_value=False), patch("utils.shutil.which", return_value=None), patch("utils.sys.executable", "/tmp/python"):
            self.assertEqual(_find_ytdlp_cmd(), ["/tmp/python", "-m", "yt_dlp"])

    def test_dump_json_403_error_explains_browser_auth(self):
        class FakeProc:
            returncode = 1
            stdout = ""
            stderr = "ERROR: [soundcloud:set] Unable to download JSON metadata: HTTP Error 403: Forbidden"

        client = SoundCloudClient()
        with patch("soundcloud_api.run_quiet", return_value=FakeProc()):
            with self.assertRaises(RuntimeError) as ctx:
                client._dump_sc_json("https://soundcloud.com/a/sets/private")

        msg = str(ctx.exception)
        self.assertIn("SoundCloud blocked metadata access", msg)
        self.assertIn("Browser auth", msg)
        self.assertIn("HTTP Error 403", msg)

    def test_fetch_playlist_falls_back_to_page_hydration_after_ytdlp_403(self):
        class FakeResponse:
            text = (
                '<script>window.__sc_hydration = [{"hydratable":"playlist","data":'
                '{"title":"Page Playlist","tracks":[{"title":"Track","duration":123400,'
                '"permalink_url":"https://soundcloud.com/a/track","id":123,'
                '"user":{"username":"Artist"}}]}}];</script>'
            )

            def raise_for_status(self):
                return None

        client = SoundCloudClient()
        with patch.object(client, "_dump_sc_json", side_effect=RuntimeError("403")), patch(
            "soundcloud_api.requests.get",
            return_value=FakeResponse(),
        ):
            rows, name = client.fetch_playlist("https://soundcloud.com/a/sets/demo")

        self.assertEqual(name, "Page Playlist")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Track Name"], "Track")
        self.assertEqual(rows[0]["Artist Name(s)"], "Artist")

    def test_page_hydration_enriches_placeholder_tracks_by_id(self):
        html_response = type("FakeResponse", (), {})()
        html_response.text = (
            '<script>window.__sc_hydration = ['
            '{"hydratable":"apiClient","data":{"id":"client-1"}},'
            '{"hydratable":"playlist","data":{"title":"Page Playlist","tracks":['
            '{"id":123,"kind":"track","policy":"ALLOW"}]}}'
            '];</script>'
        )
        html_response.raise_for_status = lambda: None

        api_response = type("FakeResponse", (), {})()
        api_response.raise_for_status = lambda: None
        api_response.json = lambda: [{
            "id": 123,
            "title": "Resolved Track",
            "duration": 123400,
            "permalink_url": "https://soundcloud.com/a/resolved",
            "user": {"username": "Resolved Artist"},
        }]

        with patch("soundcloud_api.requests.get", side_effect=[html_response, api_response]):
            rows, name = SoundCloudClient().fetch_playlist("https://soundcloud.com/a/sets/demo")

        self.assertEqual(name, "Page Playlist")
        self.assertEqual(rows[0]["Track Name"], "Resolved Track")
        self.assertEqual(rows[0]["Artist Name(s)"], "Resolved Artist")
        self.assertEqual(rows[0]["Source URL"], "https://soundcloud.com/a/resolved")

    def test_extract_sc_hydration_returns_empty_on_invalid_html(self):
        self.assertEqual(_extract_sc_hydration("<html></html>"), [])

    def test_extract_sc_client_id_from_hydration(self):
        hydration = [{"hydratable": "apiClient", "data": {"id": "client-1"}}]
        self.assertEqual(_extract_sc_client_id(hydration), "client-1")


if __name__ == "__main__":
    unittest.main()
