import os
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


if __name__ == "__main__":
    unittest.main()
