import csv
import json
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

    def test_manifest_skipped_tracks_show_skipped_not_cancelled(self):
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
                self.assertIn("skipped", state_item.text())
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
                self.assertIn("Sync selected playlist", window.sync_btn.toolTip())
                self.assertEqual(window.sync_all_btn.toolTip(), "Sync all playlists: no playlists with a saved URL")
                self.assertLessEqual(window.sync_btn.height(), 24)
                self.assertLessEqual(window.sync_all_btn.height(), 24)
                self.assertEqual(window.library_scan_btn.toolTip(), "Scan library root")
            finally:
                window.close()
                window.deleteLater()

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

    def test_bandcamp_manifest_is_syncable(self):
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
                self.assertTrue(window._manifest_is_syncable(window.library_items[0]))
                window._on_playlist_item_clicked(0)
                self.assertTrue(window.sync_btn.isEnabled())
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
