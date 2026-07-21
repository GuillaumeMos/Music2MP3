import csv
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover - depends on local dev env
    raise unittest.SkipTest("PySide6 is not installed") from exc

import qt_app
from library_manifest import build_manifest, write_manifest


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _FakeButton:
    def __init__(self, text: str):
        self._text = text

    def text(self):
        return self._text


class _FakeDeleteMessageBox:
    question_calls = 0
    _click_text = ""

    class ButtonRole:
        AcceptRole = object()
        DestructiveRole = object()
        RejectRole = object()

    class StandardButton:
        Yes = 1
        No = 2

    @classmethod
    def for_click(cls, click_text: str):
        class _ConfiguredFakeDeleteMessageBox(cls):
            pass

        _ConfiguredFakeDeleteMessageBox._click_text = click_text
        _ConfiguredFakeDeleteMessageBox.question_calls = 0
        return _ConfiguredFakeDeleteMessageBox

    def __init__(self, *_args, **_kwargs):
        self._buttons: dict[str, _FakeButton] = {}

    def setWindowTitle(self, _title):
        pass

    def setText(self, _text):
        pass

    def setInformativeText(self, _text):
        pass

    def addButton(self, text, _role):
        btn = _FakeButton(text)
        self._buttons[text] = btn
        return btn

    def exec(self):
        return None

    def clickedButton(self):
        return self._buttons.get(self._click_text)

    @classmethod
    def question(cls, *_args, **_kwargs):
        cls.question_calls += 1
        return cls.StandardButton.Yes

    @staticmethod
    def warning(*_args, **_kwargs):
        pass

    @staticmethod
    def critical(*_args, **_kwargs):
        pass


class QtAppSmokeTests(unittest.TestCase):
    def setUp(self):
        self._config_dir = tempfile.TemporaryDirectory()
        test_config = Path(self._config_dir.name) / "config.json"
        self._config_patch = patch.object(qt_app, "CONFIG_FILE", str(test_config))
        self._config_patch.start()

    def _make_window(self, root: Path):
        app = _app()
        original_load_config = qt_app.load_config
        qt_app.load_config = lambda: {
            "default_output_dir": str(root),
            "library_root": str(root),
            "deep_search": True,
            "incremental_update": True,
            "safe_search": True,
            "generate_m3u": True,
            "prefix_numbers": False,
            "strict_match": False,
            "exclude_instrumentals": False,
            "output_mode": "manual",
            "output_format": "mp3",
            "concurrency": 3,
        }
        try:
            with patch("qt_app.QTimer.singleShot"):
                window = qt_app.QtMusic2MP3Window()
        finally:
            qt_app.load_config = original_load_config
        app.processEvents()
        return window

    def tearDown(self):
        _app().processEvents()
        self._config_patch.stop()
        self._config_dir.cleanup()

    def test_main_window_scans_manifest_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Warehouse"
            audio_file = playlist_dir / "Midnight Signal.mp3"
            audio_file.parent.mkdir(parents=True, exist_ok=True)
            audio_file.write_bytes(b"audio")
            manifest = build_manifest(
                playlist_name="Warehouse",
                playlist_dir=playlist_dir,
                source={
                    "type": "spotify",
                    "url": "https://open.spotify.com/playlist/demo",
                    "name": "Warehouse",
                },
                settings={"safe_search": True},
                tracks=[
                    {
                        "idx": 1,
                        "title": "Midnight Signal",
                        "artists": "Local Artist",
                        "status": "done",
                        "format": "MP3",
                        "file": "Midnight Signal.mp3",
                    }
                ],
            )
            write_manifest(playlist_dir, manifest)

            window = self._make_window(root)
            try:
                self.assertEqual(len(window.library_items), 1)
                self.assertEqual(len(window._playlist_item_widgets), 1)
                self.assertTrue(window.sync_all_btn.isEnabled())
                self.assertFalse(window.convert_btn.isEnabled())

                window._on_playlist_item_clicked(0)
                self.assertEqual(window.table.rowCount(), 1)
                self.assertTrue(window.sync_btn.isEnabled())
                self.assertEqual(window.hero_title_label.text(), "Warehouse")
                self.assertIn("mp3", window.format_pill.text().lower())
            finally:
                window.close()
                window.deleteLater()

    def test_manifest_skipped_tracks_with_files_show_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Warehouse"
            audio_file = playlist_dir / "Midnight Signal.mp3"
            audio_file.parent.mkdir(parents=True, exist_ok=True)
            audio_file.write_bytes(b"audio")
            manifest = build_manifest(
                playlist_name="Warehouse",
                playlist_dir=playlist_dir,
                source={
                    "type": "spotify",
                    "url": "https://open.spotify.com/playlist/demo",
                    "name": "Warehouse",
                },
                settings={"incremental_update": True},
                tracks=[{
                    "idx": 1,
                    "title": "Midnight Signal",
                    "artists": "Local Artist",
                    "status": "skipped",
                    "format": "MP3",
                    "file": audio_file.name,
                }],
            )
            write_manifest(playlist_dir, manifest)

            window = self._make_window(root)
            try:
                window._on_playlist_item_clicked(0)
                state_item = window.table.item(0, 4)
                self.assertIsNotNone(state_item)
                self.assertIn("done", state_item.text())
                self.assertNotIn("cancelled", state_item.text())
            finally:
                window.close()
                window.deleteLater()

    def test_double_click_done_track_opens_audio_in_music(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Warehouse"
            audio_file = playlist_dir / "Midnight Signal.mp3"
            audio_file.parent.mkdir(parents=True, exist_ok=True)
            audio_file.write_bytes(b"audio")
            manifest = build_manifest(
                playlist_name="Warehouse",
                playlist_dir=playlist_dir,
                source={"type": "spotify", "url": "https://open.spotify.com/playlist/demo", "name": "Warehouse"},
                settings={"safe_search": True},
                tracks=[{
                    "idx": 1,
                    "title": "Midnight Signal",
                    "artists": "Local Artist",
                    "status": "done",
                    "format": "MP3",
                    "file": audio_file.name,
                }],
            )
            write_manifest(playlist_dir, manifest)

            window = self._make_window(root)
            try:
                window._on_playlist_item_clicked(0)
                with (
                    patch("qt_app.platform.system", return_value="Darwin"),
                    patch("qt_app.subprocess.run") as run,
                    patch("qt_app.subprocess.Popen") as popen,
                ):
                    window._on_table_double_click(0, 1)

                run.assert_called_once_with(["open", "-a", "Music", str(audio_file.resolve())], check=True, timeout=5)
                popen.assert_called_once()
            finally:
                window.close()
                window.deleteLater()

    def test_done_event_sets_audio_path_for_fresh_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio_file = root / "Artist - Track.mp3"
            audio_file.write_bytes(b"audio")
            window = self._make_window(root)
            try:
                window._ensure_row(1, "Track", "Artist")
                window._on_item("done", {
                    "idx": 1,
                    "format": "MP3",
                    "file": audio_file.name,
                    "path": str(audio_file),
                })

                self.assertEqual(window._rows[1]["audio_path"], str(audio_file))
                self.assertEqual(window.table.item(0, 4).text(), "● done")
            finally:
                window.close()
                window.deleteLater()

    def test_retry_item_events_are_remapped_to_original_failed_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = self._make_window(root)
            try:
                window._ensure_row(25, "Missing Track", "Artist")
                window._set_row_state(25, "queued")

                window._on_retry_item(25, "init", {"idx": 1, "title": "Artist - Missing Track", "format": "MP3"})
                window._on_retry_item(25, "done", {"idx": 1, "format": "MP3", "file": "Artist - Missing Track.mp3"})

                self.assertIn(25, window._rows)
                self.assertNotIn(1, window._rows)
                self.assertEqual(window._rows[25]["state"], "done")
                self.assertEqual(window.table.rowCount(), 1)
                self.assertEqual(window.table.item(0, 4).text(), "● done")
            finally:
                window.close()
                window.deleteLater()

    def test_retry_success_refreshes_manifest_attention_and_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Retry playlist"
            failed_manifest = build_manifest(
                playlist_name="Retry playlist",
                playlist_dir=playlist_dir,
                source={
                    "type": "spotify",
                    "url": "https://open.spotify.com/playlist/retry",
                    "name": "Retry playlist",
                },
                settings={},
                tracks=[{
                    "idx": 7,
                    "title": "Blocked track",
                    "artists": "Artist",
                    "status": "failed",
                    "file": "",
                    "error": "Download blocked",
                }],
            )
            write_manifest(playlist_dir, failed_manifest)
            window = self._make_window(root)
            try:
                self.assertEqual(len(window._attention_items), 1)
                audio_path = playlist_dir / "Artist - Blocked track.mp3"
                audio_path.write_bytes(b"audio")
                done_manifest = build_manifest(
                    playlist_name="Retry playlist",
                    playlist_dir=playlist_dir,
                    source=failed_manifest["source"],
                    settings={},
                    tracks=[{
                        "idx": 7,
                        "title": "Blocked track",
                        "artists": "Artist",
                        "status": "done",
                        "file": audio_path.name,
                        "format": "MP3",
                    }],
                    previous_manifest=failed_manifest,
                )
                write_manifest(playlist_dir, done_manifest)
                window._retry_context = {
                    "idx": 7,
                    "title": "Blocked track",
                    "out_dir": str(playlist_dir),
                    "succeeded": True,
                    "failed": False,
                }
                window._total_tracks = 1
                window._started_at = time.time()

                window._on_done(str(playlist_dir))

                self.assertEqual(len(window._attention_items), 0)
                self.assertEqual(window.needs_attention_btn.text(), "Needs attention · 0")
                self.assertEqual(
                    window.footer_status_lbl.text(),
                    "Retry successful · Blocked track",
                )
                self.assertEqual(window.table.item(0, 4).text(), "● done")
            finally:
                window.close()
                window.deleteLater()

    def test_retry_failure_stays_in_attention_with_clear_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Retry playlist"
            failed_manifest = build_manifest(
                playlist_name="Retry playlist",
                playlist_dir=playlist_dir,
                source={
                    "type": "spotify",
                    "url": "https://open.spotify.com/playlist/retry",
                    "name": "Retry playlist",
                },
                settings={},
                tracks=[{
                    "idx": 7,
                    "title": "Blocked track",
                    "artists": "Artist",
                    "status": "failed",
                    "file": "",
                    "error": "The manual URL is unavailable",
                }],
            )
            write_manifest(playlist_dir, failed_manifest)
            window = self._make_window(root)
            try:
                window._retry_context = {
                    "idx": 7,
                    "title": "Blocked track",
                    "out_dir": str(playlist_dir),
                    "succeeded": False,
                    "failed": True,
                }
                window._total_tracks = 1
                window._started_at = time.time()

                window._on_done(str(playlist_dir))

                self.assertEqual(len(window._attention_items), 1)
                self.assertEqual(window.needs_attention_btn.text(), "Needs attention · 1")
                self.assertEqual(
                    window.footer_status_lbl.text(),
                    "Retry failed · Blocked track",
                )
                self.assertIn(7, window._errors)
            finally:
                window.close()
                window.deleteLater()

    def test_retry_worker_cleanup_removes_temporary_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            retry_csv = root / "retry.csv"
            retry_csv.write_text("Track Name\nTrack\n", encoding="utf-8")
            window = self._make_window(root)
            try:
                window._retry_tmp_csv = str(retry_csv)
                window._retry_context = {"title": "Track"}

                window._on_worker_finished()

                self.assertFalse(retry_csv.exists())
                self.assertIsNone(window._retry_tmp_csv)
                self.assertIsNone(window._retry_context)
            finally:
                window.close()
                window.deleteLater()

    def test_local_scan_button_chooses_root_and_selects_playlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Legacy"
            playlist_dir.mkdir()
            (playlist_dir / "Track.mp3").write_bytes(b"audio")

            window = self._make_window(root / "empty")
            try:
                with patch("qt_app.QFileDialog.getExistingDirectory", return_value=str(root)):
                    window.add_scan_btn.click()
                    _app().processEvents()

                self.assertEqual(Path(window.library_root).resolve(), root.resolve())
                self.assertEqual(len(window.library_items), 1)
                self.assertEqual(window._selected_playlist_idx, 0)
                self.assertEqual(window.table.rowCount(), 1)
                self.assertEqual(window.hero_title_label.text(), "Legacy")
            finally:
                window.close()
                window.deleteLater()

    def test_startup_prompts_for_library_root_when_missing(self):
        app = _app()
        original_load_config = qt_app.load_config
        qt_app.load_config = lambda: {
            "default_output_dir": "",
            "library_root": "",
            "output_format": "mp3",
            "concurrency": 3,
        }
        try:
            with patch("qt_app.QTimer.singleShot") as single_shot:
                window = qt_app.QtMusic2MP3Window()
        finally:
            qt_app.load_config = original_load_config
        try:
            app.processEvents()
            self.assertTrue(single_shot.called)
            self.assertEqual(single_shot.call_args.args[1].__name__, "_choose_library_root")
        finally:
            window.close()
            window.deleteLater()

    def test_startup_prefers_library_root_over_stale_output_dir(self):
        app = _app()
        original_load_config = qt_app.load_config
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "library"
            stale = Path(tmp) / "stale"
            root.mkdir()
            stale.mkdir()
            qt_app.load_config = lambda: {
                "default_output_dir": str(stale),
                "library_root": str(root),
                "output_format": "mp3",
                "concurrency": 3,
            }
            try:
                with patch("qt_app.QTimer.singleShot"):
                    window = qt_app.QtMusic2MP3Window()
            finally:
                qt_app.load_config = original_load_config
            try:
                app.processEvents()
                self.assertEqual(Path(window.output_folder).resolve(), root.resolve())
                self.assertEqual(Path(window.config["default_output_dir"]).resolve(), root.resolve())
            finally:
                window.close()
                window.deleteLater()

    def test_choose_library_root_updates_output_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chosen = root / "Library"
            chosen.mkdir()
            window = self._make_window(root / "old")
            try:
                with patch("qt_app.QFileDialog.getExistingDirectory", return_value=str(chosen)):
                    window._choose_library_root()
                    _app().processEvents()

                self.assertEqual(Path(window.library_root).resolve(), chosen.resolve())
                self.assertEqual(Path(window.output_folder).resolve(), chosen.resolve())
                self.assertEqual(Path(window.config["default_output_dir"]).resolve(), chosen.resolve())
            finally:
                window.close()
                window.deleteLater()

    def test_choose_library_root_ignores_stale_temporary_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = root / "deleted" / "library"
            window = self._make_window(root)
            window.library_root = str(stale)
            window.output_folder = str(stale)
            expected = Path.home() / "Music"
            if not expected.is_dir():
                expected = Path.home()
            try:
                with patch(
                    "qt_app.QFileDialog.getExistingDirectory",
                    return_value="",
                ) as choose:
                    window._choose_library_root()

                self.assertEqual(Path(choose.call_args.args[2]), expected)
            finally:
                window.close()
                window.deleteLater()

    def test_library_actions_use_explicit_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = self._make_window(root)
            try:
                self.assertEqual(window.sync_btn.text(), "Sync selected")
                self.assertIn("selected playlist", window.sync_btn.toolTip())
                self.assertEqual(window.sync_all_btn.text(), "Sync all")
                self.assertEqual(window.sync_all_btn.toolTip(), "Sync all playlists: no playlists with a saved URL")
                self.assertGreaterEqual(window.sync_btn.minimumHeight(), 28)
                self.assertGreaterEqual(window.sync_all_btn.minimumHeight(), 28)
                self.assertEqual(window.library_scan_btn.text(), "Refresh library")
                self.assertIn("no download", window.library_scan_btn.toolTip())
                self.assertEqual(window.library_cleanup_btn.text(), "Clean library")
                self.assertIn("orphan files", window.library_cleanup_btn.toolTip())
            finally:
                window.close()
                window.deleteLater()

    def test_refresh_library_reports_result_and_keeps_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "First"
            second = root / "Second"
            first.mkdir()
            second.mkdir()
            (first / "One.mp3").write_bytes(b"audio")
            (second / "Two.mp3").write_bytes(b"audio")

            window = self._make_window(root)
            try:
                second_idx = next(
                    i
                    for i, item in enumerate(window.library_items)
                    if Path(item["playlist_dir"]).name == "Second"
                )
                window._on_playlist_item_clicked(second_idx)

                (root / "Third").mkdir()
                (root / "Third" / "Three.mp3").write_bytes(b"audio")
                window.library_scan_btn.click()
                _app().processEvents()

                selected = window._selected_library_manifest()
                self.assertIsNotNone(selected)
                self.assertEqual(Path(selected["playlist_dir"]).name, "Second")
                self.assertEqual(len(window.library_items), 3)
                self.assertEqual(
                    window.footer_status_lbl.text(),
                    "Library refreshed · 3 playlists",
                )
                self.assertFalse(window.footer_bar.isHidden())
            finally:
                window.close()
                window.deleteLater()

    def test_library_cleanup_summary_explains_safe_and_shared_items(self):
        report = {
            "orphan_files": ["/library/Playlist/old.mp3"],
            "loose_root_files": ["/library/loose.mp3"],
            "duplicate_track_entries": [{"playlist_name": "Playlist", "indexes": [2]}],
            "nested_playlists": [
                {"playlist_dir": "/library/Parent/Child", "target_dir": "/library/Child", "can_flatten": True},
                {"playlist_dir": "/library/Parent/Other", "target_dir": "/library/Other", "can_flatten": False},
            ],
            "exact_duplicate_copies": 4,
            "exact_duplicate_bytes": 12 * 1024 * 1024,
            "duplicate_sources": [["/library/One", "/library/Two"]],
            "errors": [],
        }
        headline, details = qt_app.QtMusic2MP3Window._library_cleanup_summary(report)

        self.assertIn("4 safe cleanup action(s)", headline)
        self.assertIn("Shared copies kept: 4 (12.0 MiB)", headline)
        self.assertIn("Nested playlist conflicts: 1", headline)
        self.assertIn("old.mp3", details)

    def test_library_cleanup_analysis_runs_in_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = self._make_window(Path(tmp))
            try:
                with patch.object(window, "_present_library_cleanup_report") as present:
                    window._start_library_cleanup()
                    cleanup_thread = window._cleanup_thread
                    self.assertIsNotNone(cleanup_thread)
                    deadline = time.monotonic() + 3
                    while cleanup_thread.isRunning() and time.monotonic() < deadline:
                        _app().processEvents()
                        time.sleep(0.01)
                    _app().processEvents()

                self.assertFalse(cleanup_thread.isRunning())
                present.assert_called_once()
                self.assertIsNone(window._cleanup_worker)
                self.assertIsNone(window._cleanup_thread)
            finally:
                window.close()
                window.deleteLater()

    def test_needs_attention_counts_and_opens_failed_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Problem Playlist"
            manifest = build_manifest(
                playlist_name="Problem Playlist",
                playlist_dir=playlist_dir,
                source={"type": "spotify", "url": "https://open.spotify.com/playlist/problems"},
                settings={},
                tracks=[
                    {
                        "idx": 7,
                        "title": "Needs Review",
                        "artists": "Artist",
                        "status": "failed",
                        "file": "",
                        "error": "AI suggested candidate. Manual validation required.",
                        "suggested_url": "https://youtu.be/review",
                    },
                    {
                        "idx": 8,
                        "title": "Missing File",
                        "artists": "Artist",
                        "status": "done",
                        "file": "Missing File.mp3",
                    },
                ],
            )
            write_manifest(playlist_dir, manifest)
            window = self._make_window(root)
            try:
                self.assertEqual(window.needs_attention_btn.text(), "Needs attention · 2")
                self.assertEqual(window.needs_attention_btn.objectName(), "attentionButtonActive")
                self.assertEqual(window._attention_items[0]["kind"], "review")

                with (
                    patch("qt_app.NeedsAttentionDialog") as dialog_cls,
                    patch.object(window, "_show_error_dialog") as show_error,
                ):
                    dialog = dialog_cls.return_value
                    dialog.exec.return_value = qt_app.QDialog.DialogCode.Accepted
                    dialog.selected_item.return_value = dict(window._attention_items[0])
                    window._show_needs_attention()

                show_error.assert_called_once_with(7)
                self.assertEqual(window._selected_playlist_idx, 0)
                self.assertEqual(window._errors[7][2], "https://youtu.be/review")
            finally:
                window.close()
                window.deleteLater()

    def test_error_dialog_focuses_manual_url_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = self._make_window(Path(tmp))
            observed = {}

            def fake_exec(dialog):
                dialog.show()
                _app().processEvents()
                url_input = next(
                    edit
                    for edit in dialog.findChildren(qt_app.QLineEdit)
                    if "YouTube URL" in edit.placeholderText()
                )
                observed["focused"] = url_input.hasFocus()
                observed["cursor_position"] = url_input.cursorPosition()
                observed["text_length"] = len(url_input.text())
                dialog.close()
                return qt_app.QDialog.DialogCode.Rejected

            try:
                window._errors[1] = (
                    "Track",
                    "No reliable match was found.",
                    "https://youtu.be/candidate",
                    {},
                    str(Path(tmp)),
                )
                with patch.object(qt_app.QDialog, "exec", new=fake_exec):
                    window._show_error_dialog(1)

                self.assertTrue(observed["focused"])
                self.assertEqual(observed["cursor_position"], observed["text_length"])
            finally:
                window.close()
                window.deleteLater()

    def test_needs_attention_dialog_exposes_selected_item(self):
        _app()
        dialog = qt_app.NeedsAttentionDialog([
            {
                "playlist_name": "First playlist",
                "track_idx": 4,
                "title": "First track",
                "artists": "Artist",
                "kind": "failed",
                "issue": "Download failed",
                "error": "yt-dlp failed",
                "candidate_url": "",
            },
            {
                "playlist_name": "Retry playlist",
                "track_idx": 7,
                "title": "Retry track",
                "artists": "Artist",
                "kind": "failed",
                "issue": "Download blocked",
                "error": "yt-dlp failed",
                "candidate_url": "https://youtu.be/retry",
            },
        ])
        try:
            retry_btn = dialog.table.cellWidget(1, 3)
            self.assertIsInstance(retry_btn, qt_app.QPushButton)
            self.assertEqual(retry_btn.text(), "Retry")

            retry_btn.click()

            self.assertEqual(dialog.result(), qt_app.QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.selected_item()["track_idx"], 7)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_hover_tooltips_describe_icon_and_flag_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = self._make_window(root)
            try:
                self.assertEqual(window.logs_btn.toolTip(), "Open logs")
                self.assertEqual(window.library_choose_btn.toolTip(), "Choose library root folder")
                self.assertIn("Convert", window.convert_btn.toolTip())
                self.assertIn("Stop", window.stop_btn.toolTip())
                self.assertIn("Safe search", window.flag_btns["safe_search"].toolTip())
                self.assertIn("Open settings", window.format_pill.toolTip())
            finally:
                window.close()
                window.deleteLater()

    def test_quick_options_show_their_state_in_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = self._make_window(Path(tmp))
            try:
                self.assertEqual(window.flag_btns["incremental_update"].text(), "Incremental  ON")
                self.assertEqual(window.flag_btns["safe_search"].text(), "Safe search  ON")
                self.assertEqual(window.flag_btns["ai_match_enabled"].text(), "AI assist  OFF")
                self.assertEqual(window.flag_btns["generate_m3u"].text(), "M3U  ON")
                self.assertEqual(window.flag_btns["prefix_numbers"].text(), "Number files  OFF")

                with patch.object(window, "_save_config"):
                    window._toggle_flag("safe_search")
                self.assertEqual(window.flag_btns["safe_search"].text(), "Safe search  OFF")
            finally:
                window.close()
                window.deleteLater()

    def test_bandcamp_manifest_is_not_syncable_while_source_is_backlogged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Bandcamp Release"
            manifest = build_manifest(
                playlist_name="Bandcamp Release",
                playlist_dir=playlist_dir,
                source={
                    "type": "bandcamp",
                    "url": "https://artist.bandcamp.com/album/release",
                    "name": "Bandcamp Release",
                },
                settings={},
                tracks=[],
            )
            write_manifest(playlist_dir, manifest)

            window = self._make_window(root)
            try:
                self.assertEqual(len(window.library_items), 1)
                self.assertFalse(window._manifest_is_syncable(window.library_items[0]))
                window._on_playlist_item_clicked(0)
                self.assertFalse(window.sync_btn.isEnabled())
            finally:
                window.close()
                window.deleteLater()

    def test_sync_all_continues_after_source_load_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("One", "Two"):
                playlist_dir = root / name
                manifest = build_manifest(
                    playlist_name=name,
                    playlist_dir=playlist_dir,
                    source={
                        "type": "spotify",
                        "url": f"https://open.spotify.com/playlist/{name.lower()}",
                        "name": name,
                    },
                    settings={},
                    tracks=[],
                )
                write_manifest(playlist_dir, manifest)

            window = self._make_window(root)
            try:
                started: list[str] = []

                def fail_loader(_mode, url):
                    started.append(url)
                    window._on_source_failed(f"boom {len(started)}")
                    window._on_source_loader_finished()

                window._start_source_loader = fail_loader
                with patch("qt_app.QMessageBox.critical") as critical:
                    window._sync_all_library_playlists()

                self.assertEqual(len(started), 2)
                self.assertFalse(window._sync_queue_active)
                self.assertEqual(
                    [r["status"] for r in window._sync_queue_results],
                    ["load_failed", "load_failed"],
                )
                critical.assert_not_called()
                self.assertIn("failed/skipped", window.footer_status_lbl.text().lower())
            finally:
                window.close()
                window.deleteLater()

    def test_sync_source_load_does_not_create_duplicate_session_playlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Test"
            manifest = build_manifest(
                playlist_name="Test",
                playlist_dir=playlist_dir,
                source={
                    "type": "spotify",
                    "url": "https://open.spotify.com/playlist/test",
                    "name": "Test",
                },
                settings={},
                tracks=[],
            )
            write_manifest(playlist_dir, manifest)

            csv_path = root / "loaded.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)"],
                )
                writer.writeheader()
                writer.writerow({
                    "Track Name": "Track",
                    "Artist Name(s)": "Artist",
                    "Album Name": "",
                    "Duration (ms)": "180000",
                })

            window = self._make_window(root)
            try:
                window._on_playlist_item_clicked(0)
                target = window._selected_library_manifest()
                window._pending_sync_manifest = target
                window._sync_target_manifest = target

                window._on_source_loaded({
                    "csv_path": str(csv_path),
                    "playlist_name": "Test",
                    "count": 1,
                    "source": "Spotify",
                    "source_type": "spotify",
                    "source_url": "https://open.spotify.com/playlist/test",
                })

                self.assertIsNone(window._session_playlist)
                self.assertEqual(window._selected_playlist_idx, 0)
                self.assertEqual(len(window._playlist_item_widgets), len(window.library_items))
                self.assertEqual([w._name_lbl.text() for w in window._playlist_item_widgets], ["Test"])
            finally:
                window.close()
                window.deleteLater()

    def test_done_after_sync_clears_temporary_session_playlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Test"
            manifest = build_manifest(
                playlist_name="Test",
                playlist_dir=playlist_dir,
                source={
                    "type": "spotify",
                    "url": "https://open.spotify.com/playlist/test",
                    "name": "Test",
                },
                settings={},
                tracks=[],
            )
            write_manifest(playlist_dir, manifest)

            window = self._make_window(root)
            try:
                target = window.library_items[0]
                window._selected_playlist_idx = 0
                window._sync_target_manifest = target
                window._session_playlist = {"name": "Test", "source_type": "spotify", "count": 1}

                window._on_done(str(playlist_dir))

                self.assertIsNone(window._session_playlist)
                self.assertEqual(len(window._playlist_item_widgets), len(window.library_items))
                self.assertEqual([w._name_lbl.text() for w in window._playlist_item_widgets], ["Test"])
            finally:
                window.close()
                window.deleteLater()

    def test_done_after_fresh_conversion_selects_downloaded_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Fresh Playlist"
            manifest = build_manifest(
                playlist_name="Fresh Playlist",
                playlist_dir=playlist_dir,
                source={
                    "type": "spotify",
                    "url": "https://open.spotify.com/playlist/fresh",
                    "name": "Fresh Playlist",
                },
                settings={},
                tracks=[
                    {
                        "idx": 1,
                        "title": "Downloaded Track",
                        "artists": "Artist",
                        "status": "done",
                        "format": "MP3",
                        "file": "Artist - Downloaded Track.mp3",
                    }
                ],
            )
            write_manifest(playlist_dir, manifest)
            (playlist_dir / "Artist - Downloaded Track.mp3").write_bytes(b"audio")

            window = self._make_window(root)
            try:
                window._session_playlist = {"name": "Fresh Playlist", "source_type": "spotify", "count": 1}
                window._selected_playlist_idx = -1
                window._ensure_row(1, "Downloaded Track", "Artist")
                window._total_tracks = 1

                window._on_done(str(playlist_dir))

                self.assertIsNone(window._session_playlist)
                self.assertEqual(Path(window._selected_library_manifest()["playlist_dir"]).resolve(), playlist_dir.resolve())
                self.assertEqual(window.table.rowCount(), 1)
                self.assertEqual(window.table.item(0, 4).text(), "● done")
            finally:
                window.close()
                window.deleteLater()

    def test_bandcamp_loader_writes_csv_payload(self):
        rows = [{
            "Track Name": "Track",
            "Artist Name(s)": "Artist",
            "Album Name": "Release",
            "Duration (ms)": 180000,
            "Source URL": "https://artist.bandcamp.com/track/track",
            "Track URI": "bandcamp:track:1",
        }]
        worker = qt_app.PlaylistLoadWorker(
            "bandcamp",
            "https://artist.bandcamp.com/album/release",
            {},
        )
        with patch("qt_workers.BandcampClient.fetch_playlist", return_value=(rows, "Release")):
            payload = worker._load_bandcamp()

        try:
            self.assertEqual(payload["source_type"], "bandcamp")
            self.assertEqual(payload["playlist_name"], "Release")
            with open(payload["csv_path"], newline="", encoding="utf-8") as f:
                loaded = list(csv.DictReader(f))
            self.assertEqual(loaded[0]["Track Name"], "Track")
            self.assertEqual(loaded[0]["Track URI"], "bandcamp:track:1")
        finally:
            Path(payload["csv_path"]).unlink(missing_ok=True)

    def test_library_file_helpers_move_skip_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            dst = root / "dst"
            src.mkdir()
            dst.mkdir()
            (src / "move.mp3").write_bytes(b"audio")
            (src / "skip.mp3").write_bytes(b"src")
            (src / "notes.txt").write_text("ignore", encoding="utf-8")
            (dst / "skip.mp3").write_bytes(b"dst")

            moved, skipped, errors = qt_app.QtMusic2MP3Window._merge_playlist_audio_files(str(src), str(dst))

            self.assertEqual((moved, skipped, errors), (1, 1, []))
            self.assertFalse((src / "move.mp3").exists())
            self.assertTrue((dst / "move.mp3").is_file())
            self.assertTrue((src / "notes.txt").is_file())

            manifest_file = src / "music2mp3.manifest.json"
            manifest_file.write_text("{}", encoding="utf-8")
            qt_app.QtMusic2MP3Window._remove_manifest_file(str(manifest_file))
            self.assertFalse(manifest_file.exists())

            qt_app.QtMusic2MP3Window._delete_playlist_folder(str(src))
            self.assertFalse(src.exists())

    def test_context_rename_updates_manifest_and_sidebar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Old"
            manifest = build_manifest(
                playlist_name="Old",
                playlist_dir=playlist_dir,
                source={"type": "spotify", "url": "https://open.spotify.com/playlist/old", "name": "Old"},
                settings={},
                tracks=[],
            )
            manifest_path = write_manifest(playlist_dir, manifest)

            window = self._make_window(root)
            try:
                self.assertEqual(window.library_items[0]["playlist_name"], "Old")
                with patch("qt_app.QInputDialog.getText", return_value=("New Name", True)):
                    window._ctx_rename(0, window.library_items[0])

                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(data["playlist_name"], "New Name")
                self.assertEqual(window.library_items[0]["playlist_name"], "New Name")
                self.assertEqual(window._playlist_item_widgets[0]._name_lbl.text(), "New Name")
                self.assertEqual(window.hero_title_label.text(), "New Name")
            finally:
                window.close()
                window.deleteLater()

    def test_context_delete_remove_from_library_keeps_audio_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Keep Audio"
            audio_file = playlist_dir / "Track.mp3"
            audio_file.parent.mkdir(parents=True, exist_ok=True)
            audio_file.write_bytes(b"audio")
            manifest = build_manifest(
                playlist_name="Keep Audio",
                playlist_dir=playlist_dir,
                source={"type": "spotify", "url": "https://open.spotify.com/playlist/keep", "name": "Keep Audio"},
                settings={},
                tracks=[],
            )
            manifest_path = write_manifest(playlist_dir, manifest)

            window = self._make_window(root)
            try:
                with patch("qt_app.QMessageBox", _FakeDeleteMessageBox.for_click("Remove from library")):
                    window._ctx_delete(0, window.library_items[0])

                self.assertFalse(manifest_path.exists())
                self.assertTrue(audio_file.exists())
                self.assertEqual(window.library_items, [])
            finally:
                window.close()
                window.deleteLater()

    def test_context_delete_everything_removes_playlist_folder_after_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Delete All"
            audio_file = playlist_dir / "Track.mp3"
            audio_file.parent.mkdir(parents=True, exist_ok=True)
            audio_file.write_bytes(b"audio")
            manifest = build_manifest(
                playlist_name="Delete All",
                playlist_dir=playlist_dir,
                source={"type": "spotify", "url": "https://open.spotify.com/playlist/delete", "name": "Delete All"},
                settings={},
                tracks=[],
            )
            write_manifest(playlist_dir, manifest)

            window = self._make_window(root)
            try:
                fake_box = _FakeDeleteMessageBox.for_click("Delete everything")
                with patch("qt_app.QMessageBox", fake_box):
                    window._ctx_delete(0, window.library_items[0])

                self.assertFalse(playlist_dir.exists())
                self.assertEqual(window.library_items, [])
                self.assertEqual(fake_box.question_calls, 1)
            finally:
                window.close()
                window.deleteLater()

    def test_match_tooltip_shows_score_details_and_ai_impact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = self._make_window(root)
            try:
                window._ensure_row(1, "Track", "Artist")
                window._set_row_match_score(
                    1,
                    0.51,
                    title="Artist - Track",
                    channel="Artist - Topic",
                    url="https://youtu.be/demo",
                    score_details={
                        "title_ratio": 0.8,
                        "title_coverage": 1.0,
                        "artist_score": 1.0,
                        "duration_score": 0.55,
                        "bonus": 0.08,
                        "penalties": 0.0,
                    },
                    ai_confidence=0.87,
                    ai_reason="same recording",
                )

                item = window.table.item(0, 3)
                self.assertEqual(item.text(), "51 AI")
                self.assertIn("Score details", item.toolTip())
                self.assertIn("AI impact", item.toolTip())
            finally:
                window.close()
                window.deleteLater()

    def test_click_match_score_opens_detail_dialog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = self._make_window(root)
            try:
                window._ensure_row(1, "Track", "Artist")
                window._set_row_match_score(1, 0.77, title="Artist - Track")
                with patch("qt_app.QMessageBox.information") as info:
                    window._on_table_cell_clicked(0, 3)

                info.assert_called_once()
                self.assertIn("77%", info.call_args.args[2])
            finally:
                window.close()
                window.deleteLater()

    def test_logs_dialog_formats_and_refreshes_live(self):
        _app()
        handler = qt_app._QtLogHandler()
        handler.emit(qt_app.logging.LogRecord(
            name="converter",
            level=qt_app.logging.INFO,
            pathname="",
            lineno=1,
            msg="MATCH: 001 Artist - Track -> Artist - Track | score 0.88 | AI 0.91: same recording",
            args=(),
            exc_info=None,
        ))
        dlg = qt_app.LogsDialog(handler)
        try:
            self.assertIn("MATCH", dlg._text.toHtml())
            handler.emit(qt_app.logging.LogRecord(
                name="converter",
                level=qt_app.logging.INFO,
                pathname="",
                lineno=1,
                msg="CONV: M3U generated: playlist.m3u8",
                args=(),
                exc_info=None,
            ))
            dlg._refresh_live()
            self.assertIn("M3U", dlg._text.toHtml())
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_csv_session_preview_populates_table_and_convert_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "session.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)"],
                )
                writer.writeheader()
                writer.writerow({
                    "Track Name": "Glue",
                    "Artist Name(s)": "Bicep",
                    "Album Name": "",
                    "Duration (ms)": "269000",
                })

            window = self._make_window(root)
            try:
                window._load_csv_file(str(csv_path))

                self.assertEqual(window.csv_path, str(csv_path))
                self.assertEqual(window.loaded_source_info["type"], "csv")
                self.assertEqual(window._session_playlist["count"], 1)
                self.assertEqual(window.table.rowCount(), 1)
                self.assertEqual(window.table.item(0, 0).text(), "01")
                self.assertTrue(window.convert_btn.isEnabled())
                self.assertEqual(window.hero_title_label.text(), "session")
            finally:
                window.close()
                window.deleteLater()

    def test_remote_source_load_previews_tracks_without_extra_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "spotify.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)"],
                )
                writer.writeheader()
                writer.writerow({
                    "Track Name": "DIS_GUSTING [EXPROZ_RMX]",
                    "Artist Name(s)": "KRUELTY, DEATH CODE",
                    "Album Name": "",
                    "Duration (ms)": "206000",
                })

            window = self._make_window(root)
            try:
                window._on_source_loaded({
                    "csv_path": str(csv_path),
                    "playlist_name": "Hard Techno",
                    "count": 1,
                    "source": "Spotify",
                    "source_type": "spotify",
                    "source_url": "https://open.spotify.com/playlist/demo",
                })

                self.assertEqual(window._selected_playlist_idx, -1)
                self.assertEqual(window.table.rowCount(), 1)
                self.assertEqual(window.table.item(0, 0).text(), "01")
                self.assertEqual(window.hero_title_label.text(), "Hard Techno")
                self.assertTrue(window.convert_btn.isEnabled())
            finally:
                window.close()
                window.deleteLater()

    def test_soundcloud_single_track_targets_selected_playlist_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Warehouse"
            manifest = build_manifest(
                playlist_name="Warehouse",
                playlist_dir=playlist_dir,
                source={
                    "type": "spotify",
                    "url": "https://open.spotify.com/playlist/demo",
                    "name": "Warehouse",
                },
                settings={"safe_search": True},
                tracks=[],
            )
            write_manifest(playlist_dir, manifest)

            csv_path = root / "single.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)", "Source URL"],
                )
                writer.writeheader()
                writer.writerow({
                    "Track Name": "Single",
                    "Artist Name(s)": "Artist",
                    "Album Name": "",
                    "Duration (ms)": "180000",
                    "Source URL": "https://soundcloud.com/user/single",
                })

            window = self._make_window(root)
            try:
                window._on_playlist_item_clicked(0)
                window._on_source_loaded({
                    "csv_path": str(csv_path),
                    "playlist_name": "Single",
                    "count": 1,
                    "source": "SoundCloud",
                    "source_type": "soundcloud",
                    "source_url": "https://soundcloud.com/user/single",
                })

                self.assertEqual(Path(window.output_folder).resolve(), playlist_dir.resolve())
                self.assertIsNone(window.loaded_playlist_name)
                self.assertIsNotNone(window._append_to_library_manifest)
                self.assertEqual(window.loaded_source_info["name"], "Warehouse")
                self.assertTrue(window.convert_btn.isEnabled())
            finally:
                window.close()
                window.deleteLater()

    def test_sync_uses_existing_playlist_folder_even_if_source_name_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist_dir = root / "Old Name"
            manifest = build_manifest(
                playlist_name="Old Name",
                playlist_dir=playlist_dir,
                source={
                    "type": "csv",
                    "url": str(root / "source.csv"),
                    "name": "Old Name",
                },
                settings={"safe_search": True},
                tracks=[],
            )
            write_manifest(playlist_dir, manifest)

            csv_path = root / "source.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)"],
                )
                writer.writeheader()
                writer.writerow({
                    "Track Name": "Track",
                    "Artist Name(s)": "Artist",
                    "Album Name": "",
                    "Duration (ms)": "180000",
                })

            window = self._make_window(root)
            try:
                window._on_playlist_item_clicked(0)
                manifest = window._selected_library_manifest()
                window.output_folder = str(root)
                window.loaded_playlist_name = "New Name From Source"
                window._sync_target_manifest = manifest

                worker_config = window.config.copy()
                sync_manifest = window._sync_target_manifest
                playlist_hint = window.loaded_playlist_name
                if sync_manifest:
                    playlist_dir_value = str(sync_manifest.get("playlist_dir") or "").strip()
                    if playlist_dir_value:
                        window.output_folder = playlist_dir_value
                        playlist_hint = None
                        window.loaded_playlist_name = str(sync_manifest.get("playlist_name") or window.loaded_playlist_name or "")
                        worker_config["sync_existing_playlist"] = True

                self.assertIsNone(playlist_hint)
                self.assertTrue(worker_config["sync_existing_playlist"])
                self.assertEqual(window.loaded_playlist_name, "Old Name")
                self.assertEqual(Path(window.output_folder).resolve(), playlist_dir.resolve())
            finally:
                window.close()
                window.deleteLater()

    def test_settings_dialog_exposes_ai_key_and_toggle(self):
        _app()
        with patch("qt_app.has_saved_ai_api_key", return_value=True):
            dlg = qt_app.SettingsDialog({
                "output_format": "mp3",
                "concurrency": 3,
                "ai_match_enabled": False,
                "ai_match_model": "gemini-2.5-flash",
                "ai_match_prompt": "Custom prompt",
                "cookies_path": "/tmp/cookies.txt",
                "cookies_from_browser": "safari",
                "cookies_browser_profile": "",
            })
        try:
            self.assertIn("keychain", dlg.ai_key_edit.placeholderText().lower())
            self.assertFalse(hasattr(dlg, "slskd_key_edit"))
            dlg.ai_enabled_cb.setChecked(True)
            dlg.ai_key_edit.setText("test-google-key")

            values = dlg.get_values()

            self.assertTrue(values["ai_match_enabled"])
            self.assertEqual(values["ai_match_provider"], "vertex")
            self.assertEqual(values["ai_match_model"], "gemini-2.5-flash")
            self.assertEqual(values["ai_match_prompt"], "Custom prompt")
            self.assertEqual(values["cookies_path"], "/tmp/cookies.txt")
            self.assertEqual(values["cookies_from_browser"], "safari")
            self.assertEqual(values["cookies_browser_profile"], "")
            self.assertEqual(values["_ai_api_key"], "test-google-key")
            self.assertNotIn("slskd_enabled", values)
            self.assertNotIn("_slskd_api_key", values)
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_soulseek_query_from_track_uses_artist_and_title(self):
        query = qt_app.QtMusic2MP3Window._soulseek_query_from_track({
            "title": "Track",
            "artists": ["Artist", "Guest"],
        })
        self.assertEqual(query, "Artist Guest Track")


if __name__ == "__main__":
    unittest.main()
