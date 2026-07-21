from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

try:
    import keyring
except ImportError:  # pragma: no cover - dependency is optional at runtime
    keyring = None

try:
    import slskd_api
except ImportError:  # pragma: no cover - dependency may be absent until installed
    slskd_api = None


log = logging.getLogger(__name__)
SLSKD_KEY_SERVICE = "Music2MP3"
SLSKD_KEY_USER = "slskd_api_key"
AUDIO_EXTENSIONS = {"mp3", "flac", "wav", "aiff", "aif", "m4a", "aac", "ogg", "opus"}


@dataclass
class SlskdSearchResult:
    username: str
    filename: str
    size: int = 0
    extension: str = ""
    bit_rate: int = 0
    bit_depth: int = 0
    sample_rate: int = 0
    length: int = 0
    queue_length: int = 0
    upload_speed: int = 0
    has_free_slot: bool = False
    is_locked: bool = False
    file: dict[str, Any] | None = None

    @property
    def size_mb(self) -> float:
        return self.size / (1024 * 1024) if self.size else 0.0


def get_slskd_api_key() -> str:
    env_key = os.getenv("SLSKD_API_KEY", "").strip()
    if env_key:
        return env_key
    if not keyring:
        return ""
    try:
        return keyring.get_password(SLSKD_KEY_SERVICE, SLSKD_KEY_USER) or ""
    except Exception:
        log.warning("Could not read slskd API key from keyring", exc_info=True)
        return ""


def set_slskd_api_key(api_key: str) -> bool:
    if not keyring:
        return False
    try:
        keyring.set_password(SLSKD_KEY_SERVICE, SLSKD_KEY_USER, api_key)
        return True
    except Exception:
        log.warning("Could not save slskd API key to keyring", exc_info=True)
        return False


def has_saved_slskd_api_key() -> bool:
    return bool(get_slskd_api_key())


def build_slskd_client(config: dict[str, Any]) -> "SlskdClient | None":
    if not bool(config.get("slskd_enabled", False)):
        return None
    host = str(config.get("slskd_host") or "").strip()
    if not host:
        return None
    api_key = get_slskd_api_key()
    if not api_key:
        log.info("slskd enabled but no API key is configured.")
        return None
    timeout_s = _safe_float(config.get("slskd_timeout_s"), 12.0)
    return SlskdClient(host=host, api_key=api_key, timeout_s=timeout_s)


class SlskdClient:
    def __init__(self, host: str, api_key: str, timeout_s: float = 12.0):
        if not slskd_api:
            raise RuntimeError("Missing dependency: install slskd-api to use Soulseek/slskd search.")
        self.host = host.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self._client = slskd_api.SlskdClient(
            self.host,
            api_key=self.api_key,
            timeout=self.timeout_s,
        )

    def search_audio(self, query: str, *, limit: int = 12, timeout_ms: int = 8000) -> list[SlskdSearchResult]:
        query = (query or "").strip()
        if not query:
            return []
        state = self._client.searches.search_text(
            query,
            fileLimit=max(25, limit * 4),
            responseLimit=max(10, limit * 2),
            searchTimeout=max(1000, int(timeout_ms)),
        )
        search_id = str(state.get("id") or "")
        if not search_id:
            return []
        responses = self._client.searches.search_responses(search_id) or []
        results = self._flatten_responses(responses)
        results.sort(key=_result_rank, reverse=True)
        return results[:limit]

    def enqueue(self, result: SlskdSearchResult) -> bool:
        if not result.file:
            raise RuntimeError("No slskd file payload is available for this result.")
        return bool(self._client.searches.enqueue(result.username, [result.file]))

    @staticmethod
    def _flatten_responses(responses: list[dict[str, Any]]) -> list[SlskdSearchResult]:
        results: list[SlskdSearchResult] = []
        for response in responses:
            username = str(response.get("username") or "")
            queue_length = _safe_int(response.get("queueLength"), 0)
            upload_speed = _safe_int(response.get("uploadSpeed"), 0)
            has_free_slot = bool(response.get("hasFreeUploadSlot", False))
            for file_info in response.get("files") or []:
                if not isinstance(file_info, dict):
                    continue
                filename = str(file_info.get("filename") or "")
                extension = str(file_info.get("extension") or "").lower().lstrip(".")
                if not extension:
                    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                if extension not in AUDIO_EXTENSIONS:
                    continue
                results.append(SlskdSearchResult(
                    username=username,
                    filename=filename,
                    size=_safe_int(file_info.get("size"), 0),
                    extension=extension,
                    bit_rate=_safe_int(file_info.get("bitRate"), 0),
                    bit_depth=_safe_int(file_info.get("bitDepth"), 0),
                    sample_rate=_safe_int(file_info.get("sampleRate"), 0),
                    length=_safe_int(file_info.get("length"), 0),
                    queue_length=queue_length,
                    upload_speed=upload_speed,
                    has_free_slot=has_free_slot,
                    is_locked=bool(file_info.get("isLocked", False)),
                    file=file_info,
                ))
        return results


def format_slskd_result(result: SlskdSearchResult) -> str:
    quality = []
    if result.extension:
        quality.append(result.extension.upper())
    if result.bit_rate:
        quality.append(f"{result.bit_rate}kbps")
    if result.bit_depth:
        quality.append(f"{result.bit_depth}bit")
    if result.sample_rate:
        quality.append(f"{result.sample_rate}Hz")
    size = f"{result.size_mb:.1f}MB" if result.size_mb else "?MB"
    slot = "free slot" if result.has_free_slot else f"queue {result.queue_length}"
    locked = " locked" if result.is_locked else ""
    meta = " · ".join([part for part in [", ".join(quality), size, slot] if part])
    return f"{result.filename}\n{result.username}{locked} · {meta}"


def _result_rank(result: SlskdSearchResult) -> tuple[int, int, int, int, int]:
    ext_score = {
        "flac": 6,
        "wav": 5,
        "aiff": 5,
        "aif": 5,
        "m4a": 4,
        "aac": 3,
        "mp3": 3,
        "ogg": 2,
        "opus": 2,
    }.get(result.extension, 0)
    free_slot = 1 if result.has_free_slot else 0
    unlocked = 0 if result.is_locked else 1
    queue_score = max(0, 100000 - result.queue_length)
    speed = result.upload_speed
    return ext_score, unlocked, free_slot, queue_score, speed


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default
