import csv
import os
import tempfile
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


class QtAppSmokeTests(unittest.TestCase):
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

    def test_sync_buttons_are_in_library_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = self._make_window(root)
            try:
                self.assertIn(window.sync_btn.toolTip(), {"", "Sync selected playlist"})
                self.assertEqual(window.sync_all_btn.toolTip(), "No playlists with a saved URL")
                self.assertLessEqual(window.sync_btn.height(), 24)
                self.assertLessEqual(window.sync_all_btn.height(), 24)
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
                window._on_playlist_item_clicked(-1)

                self.assertEqual(window.csv_path, str(csv_path))
                self.assertEqual(window.loaded_source_info["type"], "csv")
                self.assertEqual(window.table.rowCount(), 1)
                self.assertTrue(window.convert_btn.isEnabled())
                self.assertEqual(window.hero_title_label.text(), "session")
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
            })
        try:
            self.assertIn("keychain", dlg.ai_key_edit.placeholderText().lower())
            dlg.ai_enabled_cb.setChecked(True)
            dlg.ai_key_edit.setText("test-google-key")

            values = dlg.get_values()

            self.assertTrue(values["ai_match_enabled"])
            self.assertEqual(values["ai_match_provider"], "vertex")
            self.assertEqual(values["ai_match_model"], "gemini-2.5-flash")
            self.assertEqual(values["ai_match_prompt"], "Custom prompt")
            self.assertEqual(values["_ai_api_key"], "test-google-key")
        finally:
            dlg.close()
            dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()
