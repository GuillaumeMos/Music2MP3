import os
import json
import unittest
from unittest.mock import patch

from ai_matcher import GoogleGeminiMatchAdvisor, build_ai_match_advisor, parse_ai_match_advice


class AIMatcherTests(unittest.TestCase):
    def test_parse_json_advice_from_fenced_response(self):
        advice = parse_ai_match_advice(
            '```json\n{"action":"accept","candidate_id":2,"confidence":0.91,"reason":"same recording"}\n```'
        )

        self.assertEqual(advice.action, "accept")
        self.assertEqual(advice.candidate_id, 2)
        self.assertEqual(advice.confidence, 0.91)
        self.assertEqual(advice.reason, "same recording")

    def test_parse_invalid_action_falls_back_to_reject(self):
        advice = parse_ai_match_advice('{"action":"maybe","confidence":2}')

        self.assertEqual(advice.action, "reject")
        self.assertEqual(advice.confidence, 1.0)

    def test_build_google_advisor_requires_enabled_flag_and_key(self):
        self.assertIsNone(build_ai_match_advisor({"ai_match_enabled": False}))

        with patch.dict(os.environ, {}, clear=True), patch("ai_matcher.keyring", None):
            self.assertIsNone(build_ai_match_advisor({"ai_match_enabled": True}))

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=True):
            advisor = build_ai_match_advisor({
                "ai_match_enabled": True,
                "ai_match_provider": "vertex",
                "ai_match_model": "gemini-2.5-flash",
            })

        self.assertIsNotNone(advisor)
        self.assertEqual(advisor.model, "gemini-2.5-flash")

    def test_google_response_text_extracts_first_candidate(self):
        text = GoogleGeminiMatchAdvisor._response_text({
            "candidates": [{
                "content": {
                    "parts": [{"text": '{"action":"reject","reason":"bad duration"}'}],
                }
            }]
        })

        self.assertIn("bad duration", text)

    def test_google_advisor_uses_custom_prompt(self):
        advisor = GoogleGeminiMatchAdvisor("key", "gemini-2.5-flash", prompt="Custom DJ prompt")
        self.assertEqual(advisor.prompt, "Custom DJ prompt")

    def test_google_advisor_sends_score_details(self):
        class CapturingAdvisor(GoogleGeminiMatchAdvisor):
            def _post_json(self, body):
                self.body = body
                return {
                    "candidates": [{
                        "content": {
                            "parts": [{"text": '{"action":"reject","reason":"bad"}'}],
                        }
                    }]
                }

        advisor = CapturingAdvisor("key", "gemini-2.5-flash")
        advisor.advise(
            track={"title": "Track", "artists": "Artist", "duration_ms": 180000},
            candidates=[{
                "ai_id": 0,
                "title": "Track lyrics",
                "channel": "random",
                "duration_s": 180,
                "score": 0.31,
                "score_details": {"artist_score": 0.0, "penalties": 0.07},
                "url": "https://youtu.be/weak",
            }],
            query="Artist Track",
            threshold=0.42,
            strict=False,
        )

        prompt = advisor.body["contents"][0]["parts"][0]["text"]
        payload = json.loads(prompt.split("Data:\n", 1)[1])
        self.assertEqual(payload["candidates"][0]["score_details"]["artist_score"], 0.0)
        self.assertEqual(payload["candidates"][0]["score_details"]["penalties"], 0.07)


if __name__ == "__main__":
    unittest.main()
