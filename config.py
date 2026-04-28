import json
import os
import platform
import sys
from pathlib import Path

from ai_matcher import DEFAULT_AI_MATCH_PROMPT


APP_NAME = "Music2MP3"


def resource_path(relative_path: str) -> str:
    """
    Resolve a bundled resource path.
    - PyInstaller: under _MEIPASS
    - Source run: next to this file
    """
    if hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent
    return str(base / relative_path)


def user_config_file() -> str:
    """
    Return a writable per-user config path.
    """
    system = platform.system()
    home = Path.home()
    if system == "Windows":
        base = Path(os.getenv("APPDATA") or (home / "AppData" / "Roaming"))
        return str(base / APP_NAME / "config.json")
    if system == "Darwin":
        return str(home / "Library" / "Application Support" / APP_NAME / "config.json")
    return str(home / ".music2mp3" / "config.json")


DEFAULT_CONFIG_FILE = resource_path("config.json")
CONFIG_FILE = user_config_file()

_DEFAULT = {
    "variants": [],
    "duration_min": 30,
    "duration_max": 600,
    # Deprecated toggle; kept for backward compat
    "transcode_mp3": False,
    # Output mode: manual fixed format, or auto best available.
    "output_mode": "manual",
    # Try multiple YouTube candidates and only keep confident matches.
    "strict_match": False,
    # Guard against long mixes/sets when searching YouTube.
    "safe_search": True,
    # Optional Google/Vertex-assisted matching for gray-zone YouTube results.
    "ai_match_enabled": False,
    "ai_match_provider": "vertex",
    "ai_match_model": "gemini-2.5-flash",
    "ai_match_gray_min": 0.30,
    "ai_match_prompt": DEFAULT_AI_MATCH_PROMPT,
    # New unified output format (mp3, m4a, aac, wav, flac, aiff)
    "output_format": "mp3",
    # Remember last manual selection even when output_mode is "auto".
    "output_format_manual": "mp3",
    "generate_m3u": True,
    "exclude_instrumentals": False,
    "spotify_client_id": "",
    "spotify_client_secret": ""
}

def load_config() -> dict:
    data = dict(_DEFAULT)

    # Defaults from bundled/repo config.json if available.
    if os.path.isfile(DEFAULT_CONFIG_FILE):
        try:
            with open(DEFAULT_CONFIG_FILE, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except Exception:
            pass

    # User overrides from a stable writable location.
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except Exception:
            pass

    return data
