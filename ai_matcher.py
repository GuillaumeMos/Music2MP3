from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

try:
    import keyring
except ImportError:  # pragma: no cover - dependency is optional at runtime
    keyring = None


log = logging.getLogger(__name__)
AI_KEY_SERVICE = "Music2MP3"
AI_KEY_USER = "google_gemini_api_key"
DEFAULT_AI_MATCH_PROMPT = (
    "You are a strict music matching assistant for a DJ downloader.\n"
    "Decide whether one YouTube result is the same music track as the source track.\n"
    "Prefer official audio, topic channels, and matching artist/title/duration.\n"
    "Reject full sets, DJ mixes, live recordings, covers, karaoke, nightcore, sped up/slowed, "
    "lyrics-only, or remixes unless the source title explicitly asks for that variant.\n"
    "If no candidate is acceptable, propose one better YouTube search query."
)


@dataclass
class AIMatchAdvice:
    action: str
    candidate_id: int | None = None
    query: str = ""
    confidence: float = 0.0
    reason: str = ""


class GoogleGeminiMatchAdvisor:
    def __init__(self, api_key: str, model: str, timeout_s: float = 12.0, prompt: str = ""):
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self.prompt = prompt.strip() or DEFAULT_AI_MATCH_PROMPT

    def advise(
        self,
        *,
        track: dict[str, Any],
        candidates: list[dict[str, Any]],
        query: str,
        threshold: float,
        strict: bool,
    ) -> AIMatchAdvice:
        payload = {
            "track": {
                "title": track.get("title") or "",
                "artists": track.get("artists") or "",
                "album": track.get("album") or "",
                "duration_ms": track.get("duration_ms"),
            },
            "youtube_query": query,
            "accept_threshold": threshold,
            "strict_mode": strict,
            "candidates": [
                {
                    "id": int(c.get("ai_id", i)),
                    "title": c.get("title") or "",
                    "channel": c.get("channel") or "",
                    "duration_s": c.get("duration_s"),
                    "heuristic_score": round(float(c.get("score") or 0.0), 3),
                    "url": c.get("url") or "",
                }
                for i, c in enumerate(candidates)
            ],
        }
        prompt = (
            f"{self.prompt}\n"
            "Return only JSON with this shape: "
            '{"action":"accept|reject|retry","candidate_id":0,"query":"","confidence":0.0,"reason":"short"}\n'
            f"Data:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 220,
                "responseMimeType": "application/json",
            },
        }
        raw = self._post_json(body)
        text = self._response_text(raw)
        return parse_ai_match_advice(text)

    def _post_json(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-goog-api-key": self.api_key,
                "user-agent": "Music2MP3/ai-match",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Gemini API error {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Gemini API unavailable: {e.reason}") from e

    @staticmethod
    def _response_text(raw: dict[str, Any]) -> str:
        candidates = raw.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return ""
        content = candidates[0].get("content") if isinstance(candidates[0], dict) else {}
        parts = content.get("parts") if isinstance(content, dict) else []
        if not isinstance(parts, list):
            return ""
        return "\n".join(
            str(part.get("text") or "")
            for part in parts
            if isinstance(part, dict) and part.get("text")
        ).strip()


def get_ai_api_key() -> str:
    env_key = (
        os.getenv("GOOGLE_API_KEY", "").strip()
        or os.getenv("GEMINI_API_KEY", "").strip()
    )
    if env_key:
        return env_key
    if not keyring:
        return ""
    try:
        return keyring.get_password(AI_KEY_SERVICE, AI_KEY_USER) or ""
    except Exception:
        log.warning("Could not read AI API key from keyring", exc_info=True)
        return ""


def set_ai_api_key(api_key: str) -> bool:
    if not keyring:
        return False
    try:
        keyring.set_password(AI_KEY_SERVICE, AI_KEY_USER, api_key)
        return True
    except Exception:
        log.warning("Could not save AI API key to keyring", exc_info=True)
        return False


def has_saved_ai_api_key() -> bool:
    return bool(get_ai_api_key())


def build_ai_match_advisor(config: dict[str, Any]) -> GoogleGeminiMatchAdvisor | None:
    if not bool(config.get("ai_match_enabled", False)):
        return None
    provider = str(config.get("ai_match_provider") or "vertex").strip().lower()
    timeout_s = _float_config(config, "ai_match_timeout_s", 12.0)
    if provider not in {"google", "gemini", "vertex", "vertex_gemini", "vertex-gemini"}:
        log.warning("AI match disabled: unsupported provider %r", provider)
        return None

    api_key = get_ai_api_key()
    if not api_key:
        log.info("AI match enabled but no Google/Gemini API key is configured.")
        return None
    model = (
        os.getenv("GEMINI_MODEL", "").strip()
        or os.getenv("GOOGLE_AI_MODEL", "").strip()
        or str(config.get("ai_match_model") or "gemini-2.5-flash").strip()
    )
    prompt = str(config.get("ai_match_prompt") or DEFAULT_AI_MATCH_PROMPT)
    return GoogleGeminiMatchAdvisor(api_key=api_key, model=model, timeout_s=timeout_s, prompt=prompt)


def parse_ai_match_advice(text: str) -> AIMatchAdvice:
    data = _extract_json_object(text)
    action = str(data.get("action") or "reject").strip().lower()
    if action not in {"accept", "reject", "retry"}:
        action = "reject"
    candidate_id = data.get("candidate_id")
    try:
        candidate_id = int(candidate_id) if candidate_id is not None else None
    except Exception:
        candidate_id = None
    confidence = _safe_float(data.get("confidence"), 0.0)
    return AIMatchAdvice(
        action=action,
        candidate_id=candidate_id,
        query=str(data.get("query") or "").strip(),
        confidence=max(0.0, min(1.0, confidence)),
        reason=str(data.get("reason") or "").strip(),
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _float_config(config: dict[str, Any], key: str, default: float) -> float:
    return _safe_float(config.get(key), default)


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default
