# spotify_auth.py
import base64, hashlib, os, time, threading, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse as urlparse
import requests

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

class PKCEAuth:
    def __init__(self, client_id: str, redirect_uri="http://127.0.0.1:8765/callback",
                 scopes=None, refresh_token_store=None):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.scopes = scopes or ["playlist-read-private","playlist-read-collaborative"]
        self._access_token = None
        self._refresh_token = refresh_token_store.get() if refresh_token_store else None
        self._expires_at = 0
        self._store = refresh_token_store

    def get_token(self) -> str:
        now = time.time()
        if self._access_token and now < self._expires_at - 30:
            return self._access_token
        if self._refresh_token:
            self._refresh()
            return self._access_token
        self._authorize()
        return self._access_token

    # ---- internals ----
    def _make_verifier_challenge(self):
        verifier = base64.urlsafe_b64encode(os.urandom(64)).rstrip(b"=").decode()
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return verifier, challenge

    def _authorize(self):
        verifier, challenge = self._make_verifier_challenge()
        code_holder = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self_inner):
                parsed = urlparse.urlparse(self_inner.path)
                if parsed.path != urlparse.urlparse(self.redirect_uri).path:
                    self_inner.send_response(404); self_inner.end_headers(); return
                qs = urlparse.parse_qs(parsed.query)
                if "code" in qs:
                    code_holder["code"] = qs["code"][0]
                    self_inner.send_response(200)
                    self_inner.send_header("Content-Type","text/html")
                    self_inner.end_headers()
                    self_inner.wfile.write(b"<html><body><h3>Logged in. You can close this window.</h3></body></html>")
                else:
                    self_inner.send_response(400); self_inner.end_headers()

        host = urlparse.urlparse(self.redirect_uri).hostname
        port = urlparse.urlparse(self.redirect_uri).port or 8765
        httpd = HTTPServer((host, port), Handler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
            "code_challenge_method": "S256",
            "code_challenge": challenge
        }
        webbrowser.open(f"{SPOTIFY_AUTH_URL}?{urlparse.urlencode(params)}")

        while "code" not in code_holder:
            time.sleep(0.1)
        httpd.shutdown()

        data = {
            "client_id": self.client_id,
            "grant_type": "authorization_code",
            "code": code_holder["code"],
            "redirect_uri": self.redirect_uri,
            "code_verifier": verifier
        }
        r = requests.post(SPOTIFY_TOKEN_URL, data=data, timeout=20)
        r.raise_for_status()
        tok = r.json()
        self._set_tokens(tok)

    def _refresh(self):
        data = {
            "client_id": self.client_id,
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token
        }
        r = requests.post(SPOTIFY_TOKEN_URL, data=data, timeout=20)
        r.raise_for_status()
        tok = r.json()
        if "refresh_token" not in tok:
            tok["refresh_token"] = self._refresh_token
        self._set_tokens(tok)

    def _set_tokens(self, tok: dict):
        self._access_token = tok["access_token"]
        self._refresh_token = tok.get("refresh_token", self._refresh_token)
        self._expires_at = time.time() + int(tok.get("expires_in", 3600))
        if self._store and self._refresh_token:
            self._store.set(self._refresh_token)
