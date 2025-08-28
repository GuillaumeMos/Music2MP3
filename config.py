import os, sys, json

def resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

CONFIG_FILE = resource_path("config.json")

_DEFAULT = {
    "variants": [],
    "duration_min": 30,
    "duration_max": 600,
    "transcode_mp3": False,
    "generate_m3u": True,
    "exclude_instrumentals": False,
    "spotify_client_id": "",
    "spotify_client_secret": ""
}

def load_config() -> dict:
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**_DEFAULT, **data}
        except Exception:
            return dict(_DEFAULT)
    return dict(_DEFAULT)