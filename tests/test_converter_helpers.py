import unittest
import csv
import json
import tempfile
import time
from pathlib import Path

from converter import Converter, _looks_instrumental, _sanitize_filename
from ai_matcher import AIMatchAdvice
from library_manifest import MANIFEST_FILENAME, build_manifest, write_manifest


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
        best, reject_reason, best_url = conv._pick_best_youtube_match(
            {"title": "Track", "artists": "Artist", "duration_ms": 180000}
        )

        self.assertIsNotNone(best)
        self.assertEqual(reject_reason, "")
        self.assertIsNone(best_url)
        self.assertEqual(best["url"], "https://youtu.be/short")

    def test_ai_match_suggests_gray_zone_candidate_for_manual_validation(self):
        class FakeAdvisor:
            def advise(self, **_kwargs):
                return AIMatchAdvice(
                    action="accept",
                    candidate_id=0,
                    confidence=0.88,
                    reason="same artist and title",
                )

        class FakeAIConverter(Converter):
            def _search_youtube_candidates(self, _query, _limit):
                return [{
                    "title": "Artist - Track official audio",
                    "channel": "Artist",
                    "duration_s": 181,
                    "url": "https://youtu.be/ai",
                    "fake_score": 0.35,
                }]

            def _score_match_candidate(self, _track, cand):
                return float(cand["fake_score"])

        conv = FakeAIConverter(config={"safe_search": True, "ai_match_enabled": True})
        conv._ai_match_advisor = FakeAdvisor()

        best, reject_reason, best_url = conv._pick_best_youtube_match(
            {"title": "Track", "artists": "Artist", "duration_ms": 180000}
        )

        self.assertIsNone(best)
        self.assertIn("AI suggested candidate", reject_reason)
        self.assertIn("Manual validation required", reject_reason)
        self.assertEqual(best_url, "https://youtu.be/ai")

    def test_ai_match_rejects_low_confidence_accept(self):
        class FakeAdvisor:
            def advise(self, **_kwargs):
                return AIMatchAdvice(
                    action="accept",
                    candidate_id=0,
                    confidence=0.61,
                    reason="probably same",
                )

        class FakeAIConverter(Converter):
            def _search_youtube_candidates(self, _query, _limit):
                return [{
                    "title": "Artist - Track official audio",
                    "channel": "Artist",
                    "duration_s": 181,
                    "url": "https://youtu.be/ai",
                    "fake_score": 0.35,
                }]

            def _score_match_candidate(self, _track, cand):
                return float(cand["fake_score"])

        conv = FakeAIConverter(config={"safe_search": True, "ai_match_enabled": True})
        conv._ai_match_advisor = FakeAdvisor()

        best, reject_reason, best_url = conv._pick_best_youtube_match(
            {"title": "Track", "artists": "Artist", "duration_ms": 180000}
        )

        self.assertIsNone(best)
        self.assertIn("AI assist", reject_reason)
        self.assertEqual(best_url, "https://youtu.be/ai")

    def test_ai_match_rejects_accept_below_heuristic_floor(self):
        conv = Converter(config={"ai_match_enabled": True})
        accepted = conv._apply_ai_match_advice(
            AIMatchAdvice(action="accept", candidate_id=0, confidence=0.95, reason="same words"),
            [{"ai_id": 0, "score": 0.25, "url": "https://youtu.be/weak"}],
            min_score=0.42,
        )

        self.assertIsNone(accepted)

    def test_ai_match_retry_query_suggests_heuristic_winner_for_manual_validation(self):
        class FakeAdvisor:
            def advise(self, **_kwargs):
                return AIMatchAdvice(
                    action="retry",
                    query="Artist Track official audio",
                    confidence=0.75,
                    reason="try official audio query",
                )

        class FakeAIConverter(Converter):
            def _search_youtube_candidates(self, query, _limit):
                if query == "Artist Track official audio":
                    return [{
                        "title": "Artist - Track",
                        "channel": "Artist - Topic",
                        "duration_s": 180,
                        "url": "https://youtu.be/retry",
                        "fake_score": 0.85,
                    }]
                return [{
                    "title": "Track lyrics",
                    "channel": "random",
                    "duration_s": 180,
                    "url": "https://youtu.be/weak",
                    "fake_score": 0.31,
                }]

            def _score_match_candidate(self, _track, cand):
                return float(cand["fake_score"])

        conv = FakeAIConverter(config={"safe_search": True, "ai_match_enabled": True})
        conv._ai_match_advisor = FakeAdvisor()

        best, reject_reason, best_url = conv._pick_best_youtube_match(
            {"title": "Track", "artists": "Artist", "duration_ms": 180000}
        )

        self.assertIsNone(best)
        self.assertIn("AI suggested candidate", reject_reason)
        self.assertIn("Manual validation required", reject_reason)
        self.assertEqual(best_url, "https://youtu.be/retry")

    def test_ai_match_retry_query_can_help_when_initial_search_has_no_results(self):
        class FakeAdvisor:
            def advise(self, **kwargs):
                if not kwargs["candidates"]:
                    return AIMatchAdvice(
                        action="retry",
                        query="Artist Track official audio",
                        confidence=0.80,
                        reason="try a cleaner artist title query",
                    )
                return AIMatchAdvice(action="reject", reason="not enough confidence")

        class FakeAIConverter(Converter):
            def _search_youtube_candidates(self, query, _limit):
                if query == "Artist Track official audio":
                    return [{
                        "title": "Artist - Track",
                        "channel": "Artist - Topic",
                        "duration_s": 180,
                        "url": "https://youtu.be/retry",
                        "fake_score": 0.85,
                    }]
                return []

            def _score_match_candidate(self, _track, cand):
                return float(cand["fake_score"])

        conv = FakeAIConverter(config={"safe_search": True, "ai_match_enabled": True})
        conv._ai_match_advisor = FakeAdvisor()

        best, reject_reason, best_url = conv._pick_best_youtube_match(
            {"title": "Track", "artists": "Artist", "duration_ms": 180000}
        )

        self.assertIsNone(best)
        self.assertIn("AI suggested candidate", reject_reason)
        self.assertIn("Manual validation required", reject_reason)
        self.assertEqual(best_url, "https://youtu.be/retry")

    def test_soundcloud_set_url_is_not_treated_as_single_track(self):
        self.assertTrue(Converter._is_probable_soundcloud_set_url("https://soundcloud.com/user/sets/demo"))
        self.assertFalse(Converter._is_probable_soundcloud_set_url("https://soundcloud.com/user/track"))

    def test_bandcamp_album_url_is_not_treated_as_single_track(self):
        self.assertTrue(Converter._is_probable_bandcamp_album_url("https://artist.bandcamp.com/album/demo"))
        self.assertFalse(Converter._is_probable_bandcamp_album_url("https://artist.bandcamp.com/track/demo"))

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

    def test_sync_existing_playlist_does_not_create_playlist_subfolder(self):
        class NoDownloadConverter(Converter):
            def _run_ytdlp_stream(self, *args, **kwargs):
                return 0

        with tempfile.TemporaryDirectory() as tmp:
            playlist_dir = Path(tmp) / "Existing"
            csv_path = Path(tmp) / "playlist.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)", "Source URL"],
                )
                writer.writeheader()
                writer.writerow({
                    "Track Name": "Track",
                    "Artist Name(s)": "Artist",
                    "Album Name": "",
                    "Duration (ms)": "180000",
                    "Source URL": "https://www.youtube.com/watch?v=test",
                })

            conv = NoDownloadConverter(config={
                "safe_search": True,
                "generate_m3u": False,
                "sync_existing_playlist": True,
            })
            result_dir = Path(conv.convert_from_csv(str(csv_path), str(playlist_dir), "Renamed From Source"))

            self.assertEqual(result_dir, playlist_dir)
            self.assertFalse((playlist_dir / "Renamed From Source").exists())

    def test_convert_writes_match_details_to_manifest(self):
        class MatchedConverter(Converter):
            def _search_youtube_candidates(self, _query, _limit):
                return [{
                    "title": "Artist - Track",
                    "channel": "Artist - Topic",
                    "duration_s": 180,
                    "url": "https://youtu.be/match",
                }]

            def _run_ytdlp_stream(self, *args, **kwargs):
                return 0

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "playlist.csv"
            out_dir = Path(tmp) / "out"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)"],
                )
                writer.writeheader()
                writer.writerow({
                    "Track Name": "Track",
                    "Artist Name(s)": "Artist",
                    "Album Name": "Album",
                    "Duration (ms)": "180000",
                })

            conv = MatchedConverter(config={"safe_search": True, "generate_m3u": False})
            result_dir = Path(conv.convert_from_csv(str(csv_path), str(out_dir), "Demo"))
            manifest = json.loads((result_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
            match = manifest["tracks"][0]["match"]

            self.assertEqual(match["url"], "https://youtu.be/match")
            self.assertGreater(match["score"], 0.42)
            self.assertIn("title_ratio", match["score_details"])

    def test_append_to_existing_playlist_merges_manifest_and_m3u(self):
        class NoDownloadConverter(Converter):
            def _run_ytdlp_stream(self, *args, **kwargs):
                return 0

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Existing"
            existing_manifest = build_manifest(
                playlist_name="Existing",
                playlist_dir=playlist_dir,
                source={"type": "spotify", "url": "https://open.spotify.com/playlist/existing", "name": "Existing"},
                settings={"safe_search": True},
                tracks=[{
                    "idx": 1,
                    "title": "Old",
                    "artists": "Artist",
                    "source_url": "https://soundcloud.com/user/old",
                    "file": "Artist - Old.mp3",
                    "status": "done",
                    "format": "MP3",
                }],
            )
            write_manifest(playlist_dir, existing_manifest)
            (playlist_dir / "playlist.m3u8").write_text("Artist - Old.mp3\n", encoding="utf-8")

            csv_path = root / "single.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)", "Source URL"],
                )
                writer.writeheader()
                writer.writerow({
                    "Track Name": "New",
                    "Artist Name(s)": "Artist",
                    "Album Name": "",
                    "Duration (ms)": "180000",
                    "Source URL": "https://soundcloud.com/user/new",
                })

            conv = NoDownloadConverter(config={
                "safe_search": True,
                "generate_m3u": True,
                "append_to_existing_playlist": True,
            })
            result_dir = Path(conv.convert_from_csv(
                str(csv_path),
                str(playlist_dir),
                None,
                source_info={"type": "spotify", "url": "https://open.spotify.com/playlist/existing", "name": "Existing"},
            ))
            manifest = json.loads((result_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))

            self.assertEqual(result_dir, playlist_dir)
            self.assertEqual(manifest["playlist_name"], "Existing")
            self.assertEqual(manifest["track_count"], 2)
            self.assertEqual([t["title"] for t in manifest["tracks"]], ["Old", "New"])
            self.assertEqual(
                (playlist_dir / "playlist.m3u8").read_text(encoding="utf-8").splitlines(),
                ["Artist - Old.mp3", "Artist - New.mp3"],
            )


if __name__ == "__main__":
    unittest.main()
