import unittest
import csv
import json
import tempfile
import time
from pathlib import Path

from converter import Converter, _looks_instrumental, _sanitize_filename
from library_manifest import MANIFEST_FILENAME


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

    def test_match_scoring_rewards_title_coverage_and_topic_channel(self):
        conv = Converter(config={"strict_match": True})
        track = {"title": "One More Time", "artists": "Daft Punk", "duration_ms": 320000}
        official = {
            "title": "Daft Punk - One More Time",
            "channel": "Daft Punk - Topic",
            "duration_s": 321,
        }
        weak = {
            "title": "One More Time lyrics playlist",
            "channel": "random uploader",
            "duration_s": 321,
        }

        self.assertGreater(conv._score_match_candidate(track, official), conv._score_match_candidate(track, weak))

    def test_duration_guard_rejects_hour_long_candidate_without_source_duration(self):
        conv = Converter(config={"safe_search": True, "duration_min": 30, "duration_max": 600})

        self.assertFalse(conv._is_acceptable_candidate_duration(
            {"title": "Track", "artists": "Artist"},
            {"title": "Artist - Track full set", "duration_s": 3600},
        ))
        self.assertTrue(conv._is_acceptable_candidate_duration(
            {"title": "Track", "artists": "Artist"},
            {"title": "Artist - Track", "duration_s": 240},
        ))

    def test_duration_guard_rejects_candidate_far_longer_than_spotify_duration(self):
        conv = Converter(config={"safe_search": True})

        self.assertFalse(conv._is_acceptable_candidate_duration(
            {"title": "Track", "artists": "Artist", "duration_ms": 180000},
            {"title": "Artist - Track full set", "duration_s": 3600},
        ))
        self.assertTrue(conv._is_acceptable_candidate_duration(
            {"title": "Track", "artists": "Artist", "duration_ms": 180000},
            {"title": "Artist - Track", "duration_s": 185},
        ))

    def test_pick_best_youtube_match_skips_long_set_candidate(self):
        class FakeSearchConverter(Converter):
            def _search_youtube_candidates(self, _query, _limit):
                return [
                    {
                        "title": "Artist - Track full set",
                        "channel": "Artist",
                        "duration_s": 3600,
                        "url": "https://youtu.be/long",
                    },
                    {
                        "title": "Artist - Track",
                        "channel": "Artist - Topic",
                        "duration_s": 181,
                        "url": "https://youtu.be/short",
                    },
                ]

        conv = FakeSearchConverter(config={"safe_search": True, "duration_max": 600})
        best = conv._pick_best_youtube_match({"title": "Track", "artists": "Artist", "duration_ms": 180000})

        self.assertIsNotNone(best)
        self.assertEqual(best["url"], "https://youtu.be/short")

    def test_soundcloud_set_url_is_not_treated_as_single_track(self):
        self.assertTrue(Converter._is_probable_soundcloud_set_url("https://soundcloud.com/user/sets/demo"))
        self.assertFalse(Converter._is_probable_soundcloud_set_url("https://soundcloud.com/user/track"))

    def test_m3u_is_written_in_playlist_order_even_when_workers_finish_out_of_order(self):
        class OutOfOrderConverter(Converter):
            def _process_one(self, idx, _track, _dest_path, _out_dir, base_name):
                if idx == 1:
                    time.sleep(0.03)
                with self._made_files_lock:
                    self._made_files.append((idx, f"{base_name}.mp3"))

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "playlist.csv"
            out_dir = Path(tmp) / "out"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)"])
                writer.writeheader()
                writer.writerow({"Track Name": "One", "Artist Name(s)": "", "Album Name": "", "Duration (ms)": ""})
                writer.writerow({"Track Name": "Two", "Artist Name(s)": "", "Album Name": "", "Duration (ms)": ""})

            conv = OutOfOrderConverter(config={"generate_m3u": True, "concurrency": 2})
            result_dir = Path(conv.convert_from_csv(str(csv_path), str(out_dir), "Demo"))

            self.assertEqual((result_dir / "playlist.m3u8").read_text(encoding="utf-8").splitlines(), [
                "One.mp3",
                "Two.mp3",
            ])

    def test_convert_writes_playlist_manifest_with_source_info(self):
        class NoDownloadConverter(Converter):
            def _run_ytdlp_stream(self, *args, **kwargs):
                return 0

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "playlist.csv"
            out_dir = Path(tmp) / "out"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)", "Source URL", "Track URI"],
                )
                writer.writeheader()
                writer.writerow({
                    "Track Name": "Track",
                    "Artist Name(s)": "Artist",
                    "Album Name": "Album",
                    "Duration (ms)": "180000",
                    "Source URL": "https://www.youtube.com/watch?v=test",
                    "Track URI": "",
                })

            conv = NoDownloadConverter(config={"safe_search": True, "generate_m3u": False})
            result_dir = Path(conv.convert_from_csv(
                str(csv_path),
                str(out_dir),
                "Demo",
                source_info={"type": "spotify", "url": "https://open.spotify.com/playlist/demo", "name": "Demo"},
            ))
            manifest = json.loads((result_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))

            self.assertEqual(manifest["playlist_name"], "Demo")
            self.assertEqual(manifest["source"]["type"], "spotify")
            self.assertEqual(manifest["track_count"], 1)
            self.assertEqual(manifest["tracks"][0]["status"], "done")
            self.assertEqual(manifest["tracks"][0]["file"], "Artist - Track.mp3")


if __name__ == "__main__":
    unittest.main()
