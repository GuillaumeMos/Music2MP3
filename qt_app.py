"""
Experimental Qt frontend (PySide6) for Music2MP3.

This is a progressive migration path from Tkinter:
- keeps existing converter/business logic unchanged
- offers a responsive split layout with a persistent downloads panel
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import csv
import tempfile
import platform
import subprocess
from pathlib import Path

from config import CONFIG_FILE, load_config
from converter import Converter
from soundcloud_api import SoundCloudClient
from spotify_api import SpotifyClient
from spotify_auth import PKCEAuth
from token_store import RefreshTokenStore

try:
    from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
    from PySide6.QtGui import QAction, QColor, QPainter, QPen
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHeaderView,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QProgressBar,
        QProxyStyle,
        QSpinBox,
        QSplitter,
        QStyle,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as e:
    print("PySide6 is required for qt_app.py. Install with: pip install PySide6")
    raise


APP_QSS = """
QWidget {
  font-family: "SF Pro Text", "Segoe UI", "Inter";
  font-size: 14px;
  color: #111827;
}
QMainWindow {
  background: #f3f5f9;
}
QGroupBox {
  border: 1px solid #d7deeb;
  border-radius: 12px;
  margin-top: 14px;
  padding-top: 8px;
  background: #ffffff;
}
QGroupBox::title {
  subcontrol-origin: padding;
  subcontrol-position: top left;
  left: 12px;
  top: -8px;
  background: #f3f5f9;
  border-radius: 6px;
  padding: 1px 7px;
  font-weight: 600;
  color: #4b5563;
}
QLineEdit, QComboBox, QSpinBox, QTableWidget {
  border: 1px solid #cfd6e2;
  border-radius: 8px;
  background: #ffffff;
  padding: 6px 8px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
  border: 1px solid #2563eb;
}
QComboBox {
  padding-right: 22px;
}
QComboBox::drop-down {
  subcontrol-origin: padding;
  subcontrol-position: top right;
  width: 22px;
  border-left: 1px solid #d7deeb;
}
QComboBox QAbstractItemView {
  background: #ffffff;
  color: #111827;
  border: 1px solid #cfd6e2;
  selection-background-color: #2563eb;
  selection-color: #ffffff;
  outline: 0;
}
QComboBox QAbstractItemView::item {
  min-height: 24px;
  padding: 4px 8px;
}
QComboBox QAbstractItemView::item:hover {
  background: #dbeafe;
  color: #111827;
}
QComboBox QAbstractItemView::item:selected {
  background: #2563eb;
  color: #ffffff;
}
QPushButton {
  border: 1px solid #cfd6e2;
  border-radius: 8px;
  background: #f8fafc;
  padding: 7px 12px;
}
QPushButton:hover {
  background: #eef3ff;
}
QPushButton#accent {
  background: #2563eb;
  color: white;
  border: 1px solid #1e40af;
}
QPushButton#accent:hover {
  background: #1d4ed8;
}
QPushButton#danger {
  background: #ef4444;
  color: white;
  border: 1px solid #be123c;
}
QPushButton#danger:hover {
  background: #dc2626;
}
QLabel#muted {
  color: #6b7280;
}
QLabel#chip {
  color: #1e3a8a;
  background: #e5edff;
  border-radius: 999px;
  padding: 3px 10px;
}
QTableWidget {
  background: #f8fafc;
  gridline-color: #e5e7eb;
}
QHeaderView::section {
  background: #edf2fb;
  color: #334155;
  border: none;
  padding: 6px;
}
QCheckBox {
  spacing: 8px;
}
QCheckBox::indicator {
  width: 18px;
  height: 18px;
}
QProgressBar {
  border: 1px solid #d1d9e7;
  border-radius: 7px;
  background: #eef2f8;
  text-align: center;
  min-height: 14px;
}
QProgressBar::chunk {
  border-radius: 6px;
  background: #2563eb;
}
QSplitter::handle:vertical {
  background: #dbe3f0;
  height: 8px;
  margin: 0;
}
QSplitter::handle:vertical:hover {
  background: #bfceed;
}
"""


class VisibleCheckStyle(QProxyStyle):
    """
    Cross-platform checkbox indicator with a clear white checkmark on checked state.
    """

    def drawPrimitive(self, element, option, painter, widget=None):
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            return super().drawPrimitive(element, option, painter, widget)

        rect = option.rect.adjusted(0, 0, -1, -1)
        checked = bool(option.state & QStyle.StateFlag.State_On)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)

        border = QColor("#94a3b8")
        fill = QColor("#ffffff")
        if checked:
            border = QColor("#1e40af")
            fill = QColor("#2563eb")
        elif hovered:
            border = QColor("#64748b")
        if not enabled:
            if checked:
                border = QColor("#64748b")
                fill = QColor("#94a3b8")
            else:
                border = QColor("#cbd5e1")
                fill = QColor("#f8fafc")

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 4, 4)

        if checked:
            pen = QPen(QColor("#ffffff"), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            x = rect.x()
            y = rect.y()
            w = rect.width()
            h = rect.height()
            p1x, p1y = x + int(0.22 * w), y + int(0.55 * h)
            p2x, p2y = x + int(0.42 * w), y + int(0.74 * h)
            p3x, p3y = x + int(0.78 * w), y + int(0.30 * h)
            painter.drawLine(p1x, p1y, p2x, p2y)
            painter.drawLine(p2x, p2y, p3x, p3y)

        painter.restore()


def _open_folder(path: str | None) -> bool:
    if not path or not os.path.isdir(path):
        return False
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(path)  # noqa: P204
        elif system == "Darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
        return True
    except Exception:
        return False


def _open_path(path: str | None) -> bool:
    if not path or not os.path.exists(path):
        return False
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(path)  # noqa: P204
        elif system == "Darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
        return True
    except Exception:
        return False


class ConverterWorker(QObject):
    status = Signal(str)
    progress = Signal(int, int)
    item = Signal(str, object)
    done = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, config: dict, csv_path: str, output_folder: str, playlist_hint: str | None):
        super().__init__()
        self._config = config
        self._csv_path = csv_path
        self._output_folder = output_folder
        self._playlist_hint = playlist_hint
        self._cancel_event = threading.Event()

    def stop(self):
        self._cancel_event.set()

    @Slot()
    def run(self):
        try:
            conv = Converter(
                config=self._config,
                status_cb=lambda s: self.status.emit(s),
                progress_cb=lambda c, m: self.progress.emit(c, m),
                item_cb=lambda k, d: self.item.emit(k, d),
                cancel_event=self._cancel_event,
            )
            out_dir = conv.convert_from_csv(self._csv_path, self._output_folder, self._playlist_hint)
            self.done.emit(out_dir)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self.finished.emit()


class PlaylistLoadWorker(QObject):
    status = Signal(str)
    done = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, mode: str, url: str, config: dict):
        super().__init__()
        self.mode = mode
        self.url = url
        self.config = config or {}

    @Slot()
    def run(self):
        try:
            if self.mode == "spotify":
                payload = self._load_spotify()
            elif self.mode == "soundcloud":
                payload = self._load_soundcloud()
            else:
                raise RuntimeError(f"Unsupported load mode: {self.mode}")
            self.done.emit(payload)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self.finished.emit()

    def _load_spotify(self) -> dict:
        pid = SpotifyClient.extract_playlist_id(self.url)
        if not pid:
            raise RuntimeError("Invalid Spotify playlist URL.")
        client_id = self.config.get("spotify_client_id")
        if not client_id:
            raise RuntimeError('Missing "spotify_client_id" in config.')

        self.status.emit("Opening browser for Spotify authorization...")
        token_store = RefreshTokenStore(service="Music2MP3", user="spotify_pkce")
        auth = PKCEAuth(
            client_id=client_id,
            redirect_uri="http://127.0.0.1:8765/callback",
            scopes=["playlist-read-private", "playlist-read-collaborative"],
            refresh_token_store=token_store,
        )
        sp = SpotifyClient(token_supplier=auth.get_token)
        self.status.emit("Fetching playlist from Spotify...")
        rows, name = sp.fetch_playlist(pid)
        tmp = self._write_temp_csv(
            rows,
            ["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)"],
            "spotify_playlist_",
        )
        return {"csv_path": tmp, "playlist_name": name or "SpotifyPlaylist", "count": len(rows), "source": "Spotify"}

    def _load_soundcloud(self) -> dict:
        self.status.emit("Fetching playlist from SoundCloud...")
        cookies_path = self.config.get("cookies_path")
        sc = SoundCloudClient()
        rows, name = sc.fetch_playlist(self.url, cookies_path=cookies_path)
        tmp = self._write_temp_csv(
            rows,
            ["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)", "Source URL", "Track URI"],
            "soundcloud_playlist_",
        )
        return {"csv_path": tmp, "playlist_name": name or "SoundCloud", "count": len(rows), "source": "SoundCloud"}

    @staticmethod
    def _write_temp_csv(rows: list[dict], fieldnames: list[str], prefix: str) -> str:
        fd, tmp = tempfile.mkstemp(prefix=prefix, suffix=".csv")
        os.close(fd)
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return tmp


class QtMusic2MP3Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Music2MP3 (Qt)")
        self.resize(1140, 760)
        self.setMinimumSize(920, 580)

        self.config = load_config()
        self.csv_path: str | None = None
        self.output_folder: str | None = self.config.get("default_output_dir")
        self.last_output_dir: str | None = None
        self.loaded_playlist_name: str | None = None
        self._rows: dict[int, dict] = {}
        self._perc: dict[int, float] = {}
        self._errors: dict[int, tuple[str, str]] = {}
        self._total_tracks = 0
        self._started_at: float | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_timer)
        self._was_cancelled = False

        self._thread: QThread | None = None
        self._worker: ConverterWorker | None = None
        self._load_thread: QThread | None = None
        self._load_worker: PlaylistLoadWorker | None = None

        self._build_ui()
        self._load_from_config()
        self._update_convert_state()

    def _build_ui(self):
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Music2MP3")
        title.setStyleSheet("font-size: 26px; font-weight: 700;")
        subtitle = QLabel("Responsive Qt frontend (experimental)")
        subtitle.setObjectName("muted")
        subtitle.setStyleSheet("font-size: 13px;")
        hl = QVBoxLayout()
        hl.addWidget(title)
        hl.addWidget(subtitle)
        header.addLayout(hl)
        header.addStretch()
        self.logs_btn = QPushButton("Logs")
        self.logs_btn.setEnabled(False)
        self.logs_btn.setToolTip("Use Tk app for live log window for now.")
        header.addWidget(self.logs_btn)
        outer.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(8)
        outer.addWidget(splitter, 1)

        top_panel = QWidget()
        top_layout = QVBoxLayout(top_panel)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        src_group = QGroupBox("Source")
        src_layout = QGridLayout(src_group)
        src_layout.setColumnStretch(1, 1)

        src_layout.addWidget(QLabel("Spotify URL:"), 0, 0)
        self.spotify_edit = QLineEdit()
        self.spotify_edit.setPlaceholderText("https://open.spotify.com/playlist/...")
        src_layout.addWidget(self.spotify_edit, 0, 1)
        self.spotify_load_btn = QPushButton("Load from Spotify")
        self.spotify_load_btn.clicked.connect(self._load_spotify)
        src_layout.addWidget(self.spotify_load_btn, 0, 2)

        src_layout.addWidget(QLabel("SoundCloud URL:"), 1, 0)
        self.soundcloud_edit = QLineEdit()
        self.soundcloud_edit.setPlaceholderText("https://soundcloud.com/.../sets/...")
        src_layout.addWidget(self.soundcloud_edit, 1, 1)
        self.soundcloud_load_btn = QPushButton("Load from SoundCloud")
        self.soundcloud_load_btn.clicked.connect(self._load_soundcloud)
        src_layout.addWidget(self.soundcloud_load_btn, 1, 2)

        src_layout.addWidget(QLabel("CSV:"), 2, 0)
        self.csv_edit = QLineEdit()
        self.csv_edit.setReadOnly(True)
        src_layout.addWidget(self.csv_edit, 2, 1)
        self.csv_browse_btn = QPushButton("Browse…")
        self.csv_browse_btn.clicked.connect(self._browse_csv)
        src_layout.addWidget(self.csv_browse_btn, 2, 2)
        self.csv_open_btn = QPushButton("Open")
        self.csv_open_btn.clicked.connect(self._open_csv)
        src_layout.addWidget(self.csv_open_btn, 2, 3)
        self.csv_clear_btn = QPushButton("Clear")
        self.csv_clear_btn.clicked.connect(self._clear_csv)
        src_layout.addWidget(self.csv_clear_btn, 2, 4)

        info = QLabel("Load from Spotify/SoundCloud or browse a CSV file.")
        info.setObjectName("muted")
        src_layout.addWidget(info, 3, 0, 1, 4)
        self.csv_status_chip = QLabel("CSV not ready")
        self.csv_status_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.csv_status_chip.setFixedHeight(24)
        src_layout.addWidget(self.csv_status_chip, 3, 4)
        top_layout.addWidget(src_group)

        out_group = QGroupBox("Output & Options")
        out_layout = QVBoxLayout(out_group)
        out_layout.setSpacing(8)
        out_form = QGridLayout()
        out_form.setColumnStretch(1, 1)
        out_form.addWidget(QLabel("Folder:"), 0, 0)
        self.out_edit = QLineEdit()
        self.out_edit.setReadOnly(True)
        out_form.addWidget(self.out_edit, 0, 1)
        self.out_choose_btn = QPushButton("Choose…")
        self.out_choose_btn.clicked.connect(self._choose_output_folder)
        out_form.addWidget(self.out_choose_btn, 0, 2)
        self.out_open_btn = QPushButton("Open")
        self.out_open_btn.clicked.connect(self._open_output_folder)
        out_form.addWidget(self.out_open_btn, 0, 3)
        out_layout.addLayout(out_form)

        opt_grid = QGridLayout()
        opt_grid.setHorizontalSpacing(16)
        opt_grid.setVerticalSpacing(6)
        self.opt_prefix = QCheckBox("Number files (001, 002...)")
        self.opt_deep = QCheckBox("Deep search")
        self.opt_strict = QCheckBox("Strict matching (safer, slower)")
        self.opt_m3u = QCheckBox("Generate M3U")
        self.opt_excl = QCheckBox('Exclude "instrumental"')
        self.opt_incremental = QCheckBox("Incremental update")
        opt_grid.addWidget(self.opt_prefix, 0, 0)
        opt_grid.addWidget(self.opt_deep, 0, 1)
        opt_grid.addWidget(self.opt_strict, 0, 2)
        opt_grid.addWidget(self.opt_m3u, 0, 3)
        opt_grid.addWidget(self.opt_excl, 1, 0)
        opt_grid.addWidget(self.opt_incremental, 1, 1)

        self.mode_label = QLabel("Format mode")
        opt_grid.addWidget(self.mode_label, 1, 2)
        self.opt_mode = QComboBox()
        self.opt_mode.addItem("Auto (Best available)", "auto")
        self.opt_mode.addItem("Manual", "manual")
        self.opt_mode.currentIndexChanged.connect(self._on_output_mode_changed)
        opt_grid.addWidget(self.opt_mode, 1, 3)

        self.format_label = QLabel("Output format")
        opt_grid.addWidget(self.format_label, 1, 4)
        self.opt_format = QComboBox()
        self.opt_format.addItems(["mp3", "m4a", "aac", "wav", "flac", "aiff"])
        opt_grid.addWidget(self.opt_format, 1, 5)
        opt_grid.addWidget(QLabel("Threads"), 1, 6)
        self.opt_threads = QSpinBox()
        self.opt_threads.setRange(1, 8)
        self.opt_threads.setFixedWidth(84)
        opt_grid.addWidget(self.opt_threads, 1, 7)
        opt_grid.setColumnStretch(8, 1)
        out_layout.addLayout(opt_grid)

        actions = QHBoxLayout()
        actions.addStretch()
        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setObjectName("accent")
        self.convert_btn.clicked.connect(self._start_conversion)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.clicked.connect(self._stop_conversion)
        self.stop_btn.setEnabled(False)
        actions.addWidget(self.convert_btn)
        actions.addWidget(self.stop_btn)
        out_layout.addLayout(actions)
        top_layout.addWidget(out_group)

        splitter.addWidget(top_panel)

        # Downloads panel
        dl_panel = QWidget()
        dl_layout = QVBoxLayout(dl_panel)
        dl_layout.setContentsMargins(0, 0, 0, 0)
        dl_layout.setSpacing(8)
        dl_group = QGroupBox("Downloads")
        dl_group_layout = QVBoxLayout(dl_group)

        top_status = QHBoxLayout()
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(14, 14)
        top_status.addWidget(self.status_dot)
        self.status_label = QLabel("Status: Waiting…")
        self.info_label = QLabel("")
        self.info_label.setObjectName("chip")
        self.info_label.hide()
        top_status.addWidget(self.status_label)
        top_status.addStretch()
        top_status.addWidget(self.info_label)
        dl_group_layout.addLayout(top_status)

        self.global_progress = QProgressBar()
        self.global_progress.setRange(0, 100)
        self.global_progress.setValue(0)
        dl_group_layout.addWidget(self.global_progress)

        self.time_label = QLabel("")
        self.time_label.setObjectName("muted")
        dl_group_layout.addWidget(self.time_label)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["#", "Track", "State", "Format", "Match", "Progress", "Details", "Error"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        dl_group_layout.addWidget(self.table, 1)

        dl_layout.addWidget(dl_group, 1)
        splitter.addWidget(dl_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([320, 460])

        # Menu helpers
        open_out_action = QAction("Open Output Folder", self)
        open_out_action.triggered.connect(self._open_output_folder)
        self.menuBar().addAction(open_out_action)

        self.setCentralWidget(root)
        self._set_status_dot_state("idle")
        self._set_csv_state("idle")

    def _load_from_config(self):
        if self.output_folder and os.path.isdir(self.output_folder):
            self.out_edit.setText(self.output_folder)

        self.opt_prefix.setChecked(bool(self.config.get("prefix_numbers", False)))
        self.opt_deep.setChecked(bool(self.config.get("deep_search", True)))
        self.opt_strict.setChecked(bool(self.config.get("strict_match", False)))
        self.opt_m3u.setChecked(bool(self.config.get("generate_m3u", True)))
        self.opt_excl.setChecked(bool(self.config.get("exclude_instrumentals", False)))
        self.opt_incremental.setChecked(bool(self.config.get("incremental_update", True)))
        self.opt_threads.setValue(int(self.config.get("concurrency", 3)))
        mode = str(self.config.get("output_mode", "")).strip().lower()
        fmt_raw = str(self.config.get("output_format", "mp3")).lower()
        if mode not in {"auto", "manual"}:
            mode = "auto" if fmt_raw == "auto" else "manual"
        for i in range(self.opt_mode.count()):
            if self.opt_mode.itemData(i) == mode:
                self.opt_mode.setCurrentIndex(i)
                break

        fmt = str(self.config.get("output_format_manual", fmt_raw)).lower()
        if fmt == "auto":
            fmt = "mp3"
        idx = self.opt_format.findText(fmt)
        if idx >= 0:
            self.opt_format.setCurrentIndex(idx)
        self._sync_output_mode_ui()

    def _save_config(self):
        try:
            cfg_dir = os.path.dirname(CONFIG_FILE)
            if cfg_dir:
                os.makedirs(cfg_dir, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _current_output_mode(self) -> str:
        data = self.opt_mode.currentData()
        if isinstance(data, str) and data in {"auto", "manual"}:
            return data
        text = self.opt_mode.currentText().strip().lower()
        return "auto" if text.startswith("auto") else "manual"

    def _sync_output_mode_ui(self):
        manual = self._current_output_mode() == "manual"
        self.format_label.setVisible(manual)
        self.opt_format.setVisible(manual)
        if self._worker is None and self._load_worker is None:
            self.opt_format.setEnabled(manual)

    def _on_output_mode_changed(self, _index: int):
        self._sync_output_mode_ui()

    def _set_status_dot_color(self, color: str):
        fill = QColor(color)
        border = fill.darker(135).name()
        self.status_dot.setStyleSheet(
            f"border-radius:7px; background:{fill.name()}; border:1px solid {border};"
        )

    def _set_status_dot_state(self, state: str):
        palette = {
            "idle": "#9ca3af",
            "loading": "#3b82f6",
            "running": "#f59e0b",
            "success": "#16a34a",
            "warning": "#f59e0b",
            "cancelled": "#64748b",
            "error": "#ef4444",
        }
        self._set_status_dot_color(palette.get(state, palette["idle"]))

    def _set_status_dot_progress(self):
        max_value = self.global_progress.maximum()
        if max_value <= 0:
            self._set_status_dot_state("running")
            return
        ratio = max(0.0, min(1.0, self.global_progress.value() / float(max_value)))
        start = QColor("#f59e0b")
        end = QColor("#16a34a")
        r = int(start.red() + (end.red() - start.red()) * ratio)
        g = int(start.green() + (end.green() - start.green()) * ratio)
        b = int(start.blue() + (end.blue() - start.blue()) * ratio)
        self._set_status_dot_color(QColor(r, g, b).name())

    def _set_csv_state(self, state: str, detail: str | None = None):
        if state == "pending":
            bg, fg = "#fef3c7", "#92400e"
            text = detail or "Generating CSV..."
        elif state == "ready":
            bg, fg = "#dcfce7", "#166534"
            text = detail or "CSV ready"
        elif state == "error":
            bg, fg = "#fee2e2", "#991b1b"
            text = detail or "CSV failed"
        else:
            bg, fg = "#e5e7eb", "#4b5563"
            text = detail or "CSV not ready"

        self.csv_status_chip.setText(text)
        self.csv_status_chip.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:7px; padding:3px 10px; font-weight:600;"
        )

    def _browse_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select CSV", str(Path.home() / "Downloads"), "CSV files (*.csv)")
        if not path:
            return
        self.csv_path = path
        self.loaded_playlist_name = None
        self.csv_edit.setText(path)
        self._update_convert_state()
        self.status_label.setText("Status: CSV loaded")
        self._set_csv_state("ready", "CSV ready (local file)")

    def _load_spotify(self):
        url = self.spotify_edit.text().strip()
        if not SpotifyClient.extract_playlist_id(url):
            QMessageBox.warning(self, "Spotify", "Invalid Spotify playlist URL.")
            return
        if not self.config.get("spotify_client_id"):
            QMessageBox.warning(self, "Spotify", 'Missing "spotify_client_id" in config.')
            return
        self._start_source_loader("spotify", url)

    def _load_soundcloud(self):
        url = self.soundcloud_edit.text().strip()
        if not url or "soundcloud.com" not in url:
            QMessageBox.warning(self, "SoundCloud", "Please paste a valid SoundCloud URL.")
            return
        self._start_source_loader("soundcloud", url)

    def _start_source_loader(self, mode: str, url: str):
        if self._worker is not None:
            QMessageBox.warning(self, "Busy", "A conversion is running. Stop it first.")
            return
        if self._load_worker is not None:
            QMessageBox.warning(self, "Busy", "A source loading task is already running.")
            return

        self.status_label.setText(f"Status: Loading from {mode.title()}...")
        self._set_status_dot_state("loading")
        self._set_csv_state("pending", f"Generating CSV from {mode.title()}...")
        self._set_ui_enabled(False)
        self.convert_btn.setEnabled(False)

        self._load_thread = QThread(self)
        self._load_worker = PlaylistLoadWorker(mode, url, self.config.copy())
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.status.connect(self._on_source_status)
        self._load_worker.done.connect(self._on_source_loaded)
        self._load_worker.failed.connect(self._on_source_failed)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._on_source_loader_finished)
        self._load_thread.start()

    def _open_csv(self):
        if not _open_path(self.csv_path):
            QMessageBox.warning(self, "Open CSV", "No CSV selected.")

    def _clear_csv(self):
        self.csv_path = None
        self.loaded_playlist_name = None
        self.csv_edit.clear()
        self._clear_download_rows()
        self._errors.clear()
        self._total_tracks = 0
        self.global_progress.setRange(0, 100)
        self.global_progress.setValue(0)
        self.info_label.hide()
        self._timer.stop()
        self._started_at = None
        self.time_label.clear()
        self._update_convert_state()
        self.status_label.setText("Status: Waiting…")
        self._set_csv_state("idle")
        self._set_status_dot_state("idle")

    def _choose_output_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder", str(Path.home() / "Downloads"))
        if not path:
            return
        self.output_folder = path
        self.out_edit.setText(path)
        self.config["default_output_dir"] = path
        self._save_config()
        self._update_convert_state()

    def _open_output_folder(self):
        target = self.last_output_dir or self.output_folder
        if not _open_folder(target):
            QMessageBox.warning(self, "Open Folder", "No valid folder to open.")

    def _update_convert_state(self):
        ok = bool(self.csv_path and os.path.isfile(self.csv_path) and self.output_folder)
        self.convert_btn.setEnabled(ok and self._worker is None and self._load_worker is None)
        self.csv_clear_btn.setEnabled(bool(self.csv_path))
        self.csv_open_btn.setEnabled(bool(self.csv_path))

    def _apply_ui_to_config(self):
        self.config["prefix_numbers"] = self.opt_prefix.isChecked()
        self.config["deep_search"] = self.opt_deep.isChecked()
        self.config["strict_match"] = self.opt_strict.isChecked()
        self.config["generate_m3u"] = self.opt_m3u.isChecked()
        self.config["exclude_instrumentals"] = self.opt_excl.isChecked()
        self.config["incremental_update"] = self.opt_incremental.isChecked()
        mode = self._current_output_mode()
        chosen_fmt = self.opt_format.currentText()
        self.config["output_mode"] = mode
        self.config["output_format_manual"] = chosen_fmt
        self.config["output_format"] = chosen_fmt if mode == "manual" else "auto"
        self.config["concurrency"] = int(self.opt_threads.value())
        if self.output_folder:
            self.config["default_output_dir"] = self.output_folder
        self._save_config()

    def _set_ui_enabled(self, enabled: bool):
        self.spotify_edit.setEnabled(enabled)
        self.spotify_load_btn.setEnabled(enabled)
        self.soundcloud_edit.setEnabled(enabled)
        self.soundcloud_load_btn.setEnabled(enabled)
        self.csv_browse_btn.setEnabled(enabled)
        self.csv_open_btn.setEnabled(enabled and bool(self.csv_path))
        self.csv_clear_btn.setEnabled(enabled and bool(self.csv_path))
        self.out_choose_btn.setEnabled(enabled)
        self.out_open_btn.setEnabled(enabled)
        self.opt_prefix.setEnabled(enabled)
        self.opt_deep.setEnabled(enabled)
        self.opt_strict.setEnabled(enabled)
        self.opt_m3u.setEnabled(enabled)
        self.opt_excl.setEnabled(enabled)
        self.opt_incremental.setEnabled(enabled)
        self.opt_mode.setEnabled(enabled)
        self.opt_format.setEnabled(enabled and self._current_output_mode() == "manual")
        self.opt_threads.setEnabled(enabled)

    def _start_conversion(self):
        if self._load_worker is not None:
            QMessageBox.warning(self, "Busy", "Wait for source loading to finish.")
            return
        if not (self.csv_path and self.output_folder):
            QMessageBox.warning(self, "Conversion", "Select CSV and output folder first.")
            return
        self._apply_ui_to_config()

        self._clear_download_rows()
        self._errors.clear()
        self._total_tracks = 0
        self._was_cancelled = False
        self.global_progress.setRange(0, 100)
        self.global_progress.setValue(0)
        self.status_label.setText("Status: Starting conversion…")
        self._set_status_dot_state("running")
        self.info_label.hide()
        self._started_at = time.time()
        self.time_label.setText("")
        self._timer.start(1000)
        self._set_ui_enabled(False)
        self.convert_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self._thread = QThread(self)
        self._worker = ConverterWorker(self.config.copy(), self.csv_path, self.output_folder, self.loaded_playlist_name)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.status.connect(self._on_status)
        self._worker.item.connect(self._on_item)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_worker_finished)
        self._thread.start()

    @Slot(str)
    def _on_source_status(self, text: str):
        self.status_label.setText(f"Status: {text}")
        self._set_status_dot_state("loading")

    @Slot(object)
    def _on_source_loaded(self, payload_obj: object):
        payload = payload_obj if isinstance(payload_obj, dict) else {}
        csv_path = str(payload.get("csv_path", "")).strip()
        if not csv_path or not os.path.isfile(csv_path):
            QMessageBox.warning(self, "Source", "Source loaded but no CSV was produced.")
            return

        self.csv_path = csv_path
        self.loaded_playlist_name = str(payload.get("playlist_name") or "").strip() or None
        self.csv_edit.setText(csv_path)
        source = str(payload.get("source", "Source"))
        count = int(payload.get("count", 0))
        self.status_label.setText(f"Status: Loaded from {source}: {self.loaded_playlist_name or 'Playlist'} ({count} tracks)")
        self._set_status_dot_state("idle")
        self._set_csv_state("ready", f"CSV ready ({source}, {count} tracks)")
        self._update_convert_state()

    @Slot(str)
    def _on_source_failed(self, error_text: str):
        QMessageBox.critical(self, "Source loading error", error_text)
        self.status_label.setText("Status: Source loading failed")
        self._set_status_dot_state("error")
        self._set_csv_state("error", "CSV generation failed")

    def _on_source_loader_finished(self):
        if self._load_thread:
            self._load_thread.deleteLater()
            self._load_thread = None
        self._load_worker = None
        self._set_ui_enabled(True)
        self._update_convert_state()

    def _stop_conversion(self):
        if self._worker:
            self._worker.stop()
            self.status_label.setText("Status: Cancelling…")
            self._set_status_dot_state("cancelled")
            self.stop_btn.setEnabled(False)

    def _on_worker_finished(self):
        if self._thread:
            self._thread.deleteLater()
            self._thread = None
        self._worker = None
        self._set_ui_enabled(True)
        self.stop_btn.setEnabled(False)
        self._update_convert_state()

    @Slot(str)
    def _on_status(self, text: str):
        self.status_label.setText(f"Status: {text}")
        if self._worker is not None:
            self._set_status_dot_state("running")

    @Slot(str, object)
    def _on_item(self, ev: str, data_obj: object):
        data = data_obj if isinstance(data_obj, dict) else {}

        if ev == "conv_init":
            total = int(data.get("new", data.get("total", 0)))
            self._total_tracks = total
            self._perc.clear()
            self.global_progress.setRange(0, max(1, total * 100))
            self.global_progress.setValue(0)
            self._set_status_dot_state("running")
            if total == 0:
                self.info_label.setText("0 new track")
            elif total == 1:
                self.info_label.setText("1 new track")
            else:
                self.info_label.setText(f"{total} new tracks")
            self.info_label.show()
            return

        if ev == "cancel_all":
            self._was_cancelled = True
            self.status_label.setText("Status: Cancelled")
            self._set_status_dot_state("cancelled")
            self._mark_inflight_rows_cancelled()
            return

        if ev == "init":
            idx = int(data.get("idx", 0))
            title = str(data.get("title", f"Track {idx}"))
            fmt = str(data.get("format", "")).strip()
            self._ensure_row(idx, title)
            self._set_row_state(idx, "queued")
            self._set_row_match_score(idx, None)
            if fmt:
                self._set_row_format(idx, fmt)
            self._set_row_progress(idx, 0)
            return

        if ev == "progress":
            idx = int(data.get("idx", 0))
            pct = float(data.get("percent", 0.0))
            self._set_row_state(idx, "downloading")
            self._set_row_progress(idx, pct)
            detail = []
            sp = data.get("speed")
            eta = data.get("eta")
            if sp:
                detail.append(str(sp))
            if eta:
                detail.append(f"ETA {eta}")
            self._set_row_detail(idx, ", ".join(detail))
            return

        if ev == "match":
            idx = int(data.get("idx", 0))
            cand_title = str(data.get("title", "")).strip()
            score = data.get("score")
            score_txt = ""
            if isinstance(score, (int, float)):
                score_txt = f" (score {float(score):.2f})"
                self._set_row_match_score(idx, float(score))
            if cand_title:
                self._set_row_detail(idx, f"Matched: {cand_title[:90]}{score_txt}")
            return

        if ev == "converting":
            idx = int(data.get("idx", 0))
            self._set_row_state(idx, "converting")
            detail_raw = str(data.get("detail", "")).strip()
            if detail_raw.lower().startswith("[extractaudio]"):
                detail = "Extracting audio (ffmpeg)..."
            elif detail_raw.lower().startswith("[ffmpeg]"):
                detail = "Post-processing with ffmpeg..."
            else:
                detail = "Converting..."
            self._set_row_detail(idx, detail)
            return

        if ev == "done":
            idx = int(data.get("idx", 0))
            fmt = str(data.get("format", "")).strip()
            self._set_row_state(idx, "done")
            if fmt:
                self._set_row_format(idx, fmt)
            self._set_row_progress(idx, 100.0)
            self._set_row_detail(idx, "Done")
            return

        if ev == "error":
            idx = int(data.get("idx", 0))
            msg = str(data.get("message", "Unknown error"))
            self._set_row_state(idx, "failed")
            self._set_row_progress(idx, 100.0)
            self._set_row_detail(idx, "Error")
            self._set_row_error(idx, msg)
            return

    @Slot(str)
    def _on_done(self, out_dir: str):
        self.last_output_dir = out_dir
        elapsed = int(time.time() - self._started_at) if self._started_at else 0
        self._timer.stop()
        self.time_label.setText(f"Total: {self._format_duration(elapsed)}")
        if self._total_tracks > 0:
            self.global_progress.setValue(self._total_tracks * 100)
        if self._was_cancelled:
            self.status_label.setText("Status: Cancelled")
            self._set_status_dot_state("cancelled")
            return
        if self._errors:
            self.status_label.setText(f"Status: Completed with {len(self._errors)} error(s)")
            self._set_status_dot_state("warning")
        else:
            self.status_label.setText("Status: Conversion complete")
            self._set_status_dot_state("success")
        self._clear_source_forms_after_done()

    @Slot(str)
    def _on_failed(self, error_text: str):
        self._timer.stop()
        self.status_label.setText("Status: Failed")
        self._set_status_dot_state("error")
        QMessageBox.critical(self, "Conversion error", error_text)

    def _ensure_row(self, idx: int, title: str):
        if idx in self._rows:
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        n_item = QTableWidgetItem(f"{idx:03d}")
        t_item = QTableWidgetItem(title)
        s_item = QTableWidgetItem("")
        f_item = QTableWidgetItem("")
        m_item = QTableWidgetItem("")
        d_item = QTableWidgetItem("")
        e_item = QTableWidgetItem("")
        pb = QProgressBar()
        pb.setRange(0, 100)
        pb.setValue(0)
        pb.setTextVisible(True)

        self.table.setItem(row, 0, n_item)
        self.table.setItem(row, 1, t_item)
        self.table.setItem(row, 2, s_item)
        self.table.setItem(row, 3, f_item)
        self.table.setItem(row, 4, m_item)
        self.table.setCellWidget(row, 5, pb)
        self.table.setItem(row, 6, d_item)
        self.table.setItem(row, 7, e_item)
        self._rows[idx] = {"row": row, "pb": pb, "state": "queued"}

    def _set_row_state(self, idx: int, state: str):
        row = self._rows.get(idx)
        if not row:
            return
        item = self.table.item(row["row"], 2)
        if not item:
            return

        states = {
            "queued": ("○", "Queued", "#6b7280"),
            "downloading": ("↓", "Downloading", "#2563eb"),
            "converting": ("↺", "Converting", "#d97706"),
            "done": ("✓", "Done", "#16a34a"),
            "failed": ("✕", "Failed", "#dc2626"),
            "cancelled": ("■", "Cancelled", "#475569"),
        }
        icon, label, color = states.get(state, states["queued"])
        item.setText(f"{icon} {label}")
        item.setForeground(QColor(color))
        row["state"] = state

    def _set_row_format(self, idx: int, fmt: str):
        row = self._rows.get(idx)
        if not row:
            return
        item = self.table.item(row["row"], 3)
        if not item:
            return
        value = fmt.strip().upper() or "-"
        item.setText(value)
        if value == "AUTO":
            item.setForeground(QColor("#6b7280"))
        else:
            item.setForeground(QColor("#0f172a"))

    def _set_row_progress(self, idx: int, pct: float):
        row = self._rows.get(idx)
        if not row:
            return
        p = max(0.0, min(100.0, pct))
        row["pb"].setValue(int(round(p)))
        self._perc[idx] = p
        if self._total_tracks:
            total = int(sum(self._perc.values()))
            self.global_progress.setValue(total)
            self._set_status_dot_progress()

    def _set_row_detail(self, idx: int, txt: str):
        row = self._rows.get(idx)
        if not row:
            return
        item = self.table.item(row["row"], 6)
        if item:
            item.setText(txt)

    def _set_row_match_score(self, idx: int, score: float | None):
        row = self._rows.get(idx)
        if not row:
            return
        item = self.table.item(row["row"], 4)
        if not item:
            return
        if not isinstance(score, (int, float)):
            item.setText("-")
            item.setForeground(QColor("#6b7280"))
            return

        value = max(0.0, min(1.0, float(score)))
        item.setText(f"{value * 100:.0f}%")
        if value >= 0.85:
            item.setForeground(QColor("#15803d"))  # excellent
        elif value >= 0.70:
            item.setForeground(QColor("#1d4ed8"))  # good
        elif value >= 0.58:
            item.setForeground(QColor("#b45309"))  # acceptable
        else:
            item.setForeground(QColor("#b91c1c"))  # low confidence

    def _set_row_error(self, idx: int, msg: str):
        row = self._rows.get(idx)
        if not row:
            return
        item = self.table.item(row["row"], 7)
        if item:
            item.setText("View")
            item.setToolTip(msg[:3000])
            item.setForeground(Qt.GlobalColor.red)
        t_item = self.table.item(row["row"], 1)
        title = t_item.text() if t_item else f"Track {idx}"
        self._errors[idx] = (title, msg)

    def _mark_inflight_rows_cancelled(self):
        for idx, row in self._rows.items():
            state = str(row.get("state", ""))
            if state in {"done", "failed", "cancelled"}:
                continue
            self._set_row_state(idx, "cancelled")
            self._set_row_detail(idx, "Cancelled")

    def _clear_download_rows(self):
        self.table.setRowCount(0)
        self._rows.clear()
        self._perc.clear()

    def _clear_source_forms_after_done(self):
        self.csv_path = None
        self.loaded_playlist_name = None
        self.csv_edit.clear()
        self.spotify_edit.clear()
        self.soundcloud_edit.clear()
        self._set_csv_state("idle")
        self._update_convert_state()

    def _tick_timer(self):
        if not self._started_at:
            return
        elapsed = int(time.time() - self._started_at)
        self.time_label.setText(f"Elapsed: {self._format_duration(elapsed)}")

    @staticmethod
    def _format_duration(sec: int) -> str:
        h, rem = divmod(int(sec), 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def main():
    app = QApplication(sys.argv)
    # Force a predictable cross-platform base style before QSS.
    app.setStyle("Fusion")
    app.setStyle(VisibleCheckStyle(app.style()))
    app.setStyleSheet(APP_QSS)
    w = QtMusic2MP3Window()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
