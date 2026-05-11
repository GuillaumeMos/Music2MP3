import unittest
import importlib.util
from unittest.mock import patch

REQUESTS_AVAILABLE = importlib.util.find_spec("requests") is not None

class _Store:
    def __init__(self, token=None):
        self.token = token

    def get(self):
        return self.token

    def set(self, token):
        self.token = token


class SpotifyAuthTests(unittest.TestCase):
    @unittest.skipUnless(REQUESTS_AVAILABLE, "requests is not installed in this environment")
    def test_fallback_to_authorize_when_refresh_fails(self):
        from spotify_auth import PKCEAuth
        store = _Store(token="stale-refresh-token")
        auth = PKCEAuth(client_id="dummy", refresh_token_store=store)

        with patch.object(auth, "_refresh", side_effect=RuntimeError("refresh failed")):
            def _authorize_side_effect():
                auth._access_token = "fresh-access-token"

            with patch.object(auth, "_authorize", side_effect=_authorize_side_effect) as auth_mock:
                tok = auth.get_token()

        self.assertEqual(tok, "fresh-access-token")
        self.assertIsNone(auth._refresh_token)
        auth_mock.assert_called_once()

    def test_authorize_reports_callback_port_start_failure(self):
        from spotify_auth import PKCEAuth
        auth = PKCEAuth(client_id="dummy", redirect_uri="http://127.0.0.1:9999/callback")

        with patch("spotify_auth.HTTPServer", side_effect=OSError("address in use")):
            with self.assertRaisesRegex(RuntimeError, "callback server could not start"):
                auth._authorize()


if __name__ == "__main__":
    unittest.main()
