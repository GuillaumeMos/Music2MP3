import unittest

from converter import Converter, _looks_instrumental, _sanitize_filename


class ConverterHelpersTests(unittest.TestCase):
    def test_sanitize_filename_removes_illegal_chars(self):
        out = _sanitize_filename('  A/B:C*D?"E<F>G|  ')
        self.assertEqual(out, "A_B_C_D__E_F_G_")

    def test_looks_instrumental_variants(self):
        self.assertTrue(_looks_instrumental("My Song (Instrumental)"))
        self.assertTrue(_looks_instrumental("Artist - Title Karaoke Version"))
        self.assertFalse(_looks_instrumental("Artist - Title"))

    def test_rows_to_jobs_filters_empty_rows(self):
        conv = Converter(config={})
        rows = [
            {"Track Name": "", "Artist Name(s)": "", "Album Name": "", "Source URL": "", "Track URI": ""},
            {
                "Track Name": "Song",
                "Artist Name(s)": "Artist",
                "Album Name": "Album",
                "Duration (ms)": "123000",
                "Source URL": "",
                "Track URI": "",
            },
        ]
        jobs = conv._rows_to_jobs(rows)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Song")
        self.assertEqual(jobs[0]["artists"], "Artist")
        self.assertEqual(jobs[0]["duration_ms"], 123000)

    def test_build_search_query_honors_deep_search(self):
        conv_fast = Converter(config={"deep_search": False})
        q_fast = conv_fast._build_search_query({"artists": "Daft Punk", "title": "One More Time"})
        self.assertEqual(q_fast, "ytsearch1:Daft Punk One More Time")

        conv_deep = Converter(config={"deep_search": True})
        q_deep = conv_deep._build_search_query({"artists": "Daft Punk", "title": "One More Time"})
        self.assertEqual(q_deep, "ytsearch1:Daft Punk One More Time audio")

    def test_progress_parser_emits_item_event(self):
        events = []
        conv = Converter(config={}, item_cb=lambda k, d: events.append((k, d)))

        line = "[download]  47.3% of 3.45MiB at 1.23MiB/s ETA 00:10"
        conv._on_progress_line(5, line)

        self.assertEqual(len(events), 1)
        kind, payload = events[0]
        self.assertEqual(kind, "progress")
        self.assertEqual(payload["idx"], 5)
        self.assertAlmostEqual(payload["percent"], 47.3)
        self.assertIn("speed", payload)
        self.assertIn("eta", payload)

    def test_output_mode_auto_from_output_mode_key(self):
        conv = Converter(config={"output_mode": "auto", "output_format": "mp3"})
        self.assertTrue(conv.auto_best)
        self.assertEqual(conv.output_mode, "auto")

    def test_output_mode_auto_from_legacy_output_format(self):
        conv = Converter(config={"output_format": "auto"})
        self.assertTrue(conv.auto_best)
        self.assertEqual(conv.output_mode, "auto")

    def test_build_cmd_auto_does_not_force_44100_postprocess(self):
        conv = Converter(config={"output_mode": "auto"})
        cmd = conv._build_ytdlp_cmd("ytsearch1:test", "/tmp/out.%(ext)s", None)
        cmd_text = " ".join(cmd)
        self.assertIn("--audio-format best", cmd_text)
        self.assertNotIn("FFmpegExtractAudio:-ar 44100", cmd_text)

    def test_progress_parser_emits_converting_event(self):
        events = []
        conv = Converter(config={}, item_cb=lambda k, d: events.append((k, d)))

        conv._on_progress_line(3, "[ExtractAudio] Destination: /tmp/file.mp3")

        self.assertEqual(len(events), 1)
        kind, payload = events[0]
        self.assertEqual(kind, "converting")
        self.assertEqual(payload["idx"], 3)

    def test_match_scoring_prefers_correct_artist_and_duration(self):
        conv = Converter(config={"strict_match": True})
        track = {"title": "Strobe", "artists": "Deadmau5", "duration_ms": 630000}
        good = {
            "title": "deadmau5 - Strobe (Original Mix)",
            "channel": "deadmau5",
            "duration_s": 631,
            "url": "https://youtu.be/good",
        }
        bad = {
            "title": "Strobe (Nightcore Remix)",
            "channel": "random edits",
            "duration_s": 220,
            "url": "https://youtu.be/bad",
        }
        self.assertGreater(conv._score_match_candidate(track, good), conv._score_match_candidate(track, bad))


if __name__ == "__main__":
    unittest.main()
