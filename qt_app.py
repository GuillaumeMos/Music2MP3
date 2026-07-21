"""PySide6 frontend for Music2MP3."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import time
import csv
import html
import tempfile
import platform
import subprocess
import shutil
from pathlib import Path

log = logging.getLogger(__name__)


class _QtLogHandler(logging.Handler):
    """In-memory ring-buffer handler so the Logs dialog can replay recent entries."""

    def __init__(self, capacity: int = 800):
        super().__init__()
        self._records: list[str] = []
        self._capacity = capacity
        self._lock = threading.Lock()
        self.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = str(record.getMessage())
        with self._lock:
            self._records.append(msg)
            if len(self._records) > self._capacity:
                self._records.pop(0)

    def get_lines(self) -> list[str]:
        with self._lock:
            return list(self._records)


_LOG_HANDLER = _QtLogHandler()
_root_logger = logging.getLogger()
_root_logger.addHandler(_LOG_HANDLER)
# Default to INFO so converter/API logs appear; override with APP_LOG_LEVEL=DEBUG
_root_logger.setLevel(getattr(logging, os.environ.get("APP_LOG_LEVEL", "INFO").upper(), logging.INFO))

from config import CONFIG_FILE, load_config
from ai_matcher import has_saved_ai_api_key, set_ai_api_key
from library_attention import attention_counts, collect_attention_items
from library_cleanup import apply_library_cleanup, cleanup_action_count
from library_manifest import IGNORE_FILENAME, manifest_source, playlist_output_parent, scan_library
from spotify_api import SpotifyClient
from qt_workers import ConverterWorker, LibraryCleanupWorker, PlaylistLoadWorker
from slskd_client import (
    build_slskd_client,
    format_slskd_result,
    has_saved_slskd_api_key,
    set_slskd_api_key,
)
from utils import YTDLP_COOKIE_BROWSERS

FEATURE_BANDCAMP_SOURCE = False
FEATURE_SOULSEEK_ASSIST = False
SYNCABLE_REMOTE_SOURCE_TYPES = {"spotify", "soundcloud"}

try:
    from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal, Slot
    from PySide6.QtGui import (
        QColor, QDesktopServices, QPainter, QPen, QBrush,
        QLinearGradient, QFont,
    )
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QDialog,
        QFileDialog, QFrame, QGridLayout, QHBoxLayout,
        QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
        QListWidgetItem, QMainWindow,
        QMenu, QMessageBox, QPushButton, QProgressBar, QProxyStyle,
        QScrollArea, QSizePolicy, QSpinBox, QStyle,
        QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    )
except ImportError as e:
    print("PySide6 is required. Install with: pip install PySide6")
    raise


APP_QSS = """
QWidget {
  font-family: "Helvetica Neue", "Segoe UI", "Inter", "Arial";
  font-size: 13px;
  color: #f5f5f5;
  outline: none;
}
QMainWindow, QDialog { background: #121212; }

QFrame#topBar {
  background: #090909;
  border-bottom: 1px solid #242424;
}
QFrame#brandMark {
  background: #1ed760;
  border: none;
  border-radius: 14px;
}
QLabel#brandTitle {
  color: #f5f5f5; font-size: 15px; font-weight: 700;
}
QLabel#brandSub {
  color: #8b8b8b; font-size: 10px;
}
QLabel#chip {
  color: #b3b3b3;
  background: #181818;
  border: none;
  border-radius: 10px;
  padding: 4px 9px;
  font-size: 11px;
}

QFrame#sidebar {
  background: #090909;
  border-right: 1px solid #242424;
}
QFrame#rootDirBox {
  background: #181818;
  border: none;
  border-radius: 8px;
}

QPushButton#sourceTile {
  background: #181818;
  border: none;
  border-radius: 8px;
  color: #d8d8d8;
  padding: 9px 4px;
  font-size: 11px;
  font-weight: 600;
}
QPushButton#sourceTile:hover {
  background: #242424;
  color: #f5f5f5;
}
QPushButton#sourceTile:disabled {
  background: #121212;
  color: #555555;
}

QFrame#hero {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #242424, stop:1 #181818);
  border: none;
}
QFrame#heroCover {
  background: #282828;
  border-radius: 8px;
  border: none;
}
QLabel#heroSource {
  color: #b3b3b3; font-size: 11px; font-weight: 600;
}
QLabel#heroTitle {
  color: #f5f5f5; font-size: 32px; font-weight: 700; letter-spacing: -0.4px;
}
QLabel#heroMeta {
  color: #b3b3b3; font-size: 11px;
}

QFrame#actionBar {
  background: #121212;
  border-bottom: 1px solid #242424;
}
QFrame#flagsBar {
  background: #121212;
  border-bottom: 1px solid #242424;
}
QFrame#footerBar {
  background: #181818;
  border-top: 1px solid #2a2a2a;
}

QPushButton {
  border: none;
  border-radius: 7px;
  background: #242424;
  color: #f0f0f0;
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 600;
}
QPushButton:hover {
  background: #303030;
  color: #f5f5f5;
}
QPushButton:disabled {
  background: #181818;
  color: #747474;
}
QPushButton#accent {
  background: #1ed760;
  color: #090909;
  border: none;
  border-radius: 18px;
  font-weight: 700;
}
QPushButton#accent:hover { background: #3be477; }
QPushButton#accent:disabled {
  background: #1b1b1b;
  color: #7f7f7f;
}
QPushButton#danger {
  background: transparent;
  color: #b3b3b3;
  border: 1px solid #333333;
  border-radius: 18px;
}
QPushButton#danger:hover { background: #242424; color: #f5f5f5; }
QPushButton#danger:disabled {
  background: #181818;
  color: #7a7a7a;
  border-color: #333333;
}
QPushButton#accentReady {
  background: #242424;
  border: none;
  border-radius: 18px;
  color: #7d7d7d;
}
QPushButton#accentReady:disabled {
  background: #1b1b1b;
  color: #7f7f7f;
}
QPushButton#dangerActive {
  background: #e85d75;
  color: #f5f5f5;
  border: none;
  border-radius: 18px;
}
QPushButton#dangerActive:hover { background: #ef7489; }
QPushButton#ghost {
  background: transparent;
  border: none;
  color: #b3b3b3;
}
QPushButton#ghost:hover {
  background: #242424;
  color: #f5f5f5;
}
QPushButton#libraryAction {
  background: #181818;
  border: none;
  border-radius: 6px;
  color: #b3b3b3;
  padding: 6px 8px;
  font-size: 10px;
  font-weight: 600;
}
QPushButton#libraryAction:hover {
  background: #242424;
  color: #f5f5f5;
}
QPushButton#libraryAction:disabled {
  background: #121212;
  color: #707070;
}
QPushButton#attentionButton, QPushButton#attentionButtonActive {
  background: #181818;
  border: none;
  border-left: 3px solid #383838;
  border-radius: 6px;
  color: #b3b3b3;
  padding: 7px 9px;
  text-align: left;
  font-size: 10px;
  font-weight: 700;
}
QPushButton#attentionButton:hover, QPushButton#attentionButtonActive:hover {
  background: #242424;
  color: #f5f5f5;
}
QPushButton#attentionButtonActive {
  border-left-color: #f5b942;
  color: #f5f5f5;
}
QPushButton#attentionButton:disabled, QPushButton#attentionButtonActive:disabled {
  background: #121212;
  border-left-color: #2d2d2d;
  color: #707070;
}
QPushButton#flagOff {
  background: #181818;
  border: 1px solid #383838;
  border-radius: 12px;
  color: #b3b3b3;
  padding: 4px 10px;
  font-size: 10px;
  font-weight: 600;
}
QPushButton#flagOn {
  background: #173522;
  border: 1px solid #1ed760;
  border-radius: 12px;
  color: #5ee889;
  padding: 4px 10px;
  font-size: 10px;
  font-weight: 700;
}
QPushButton#flagOff:hover {
  background: #333333;
  color: #f5f5f5;
}
QPushButton#flagOn:hover {
  background: #1d472b;
  color: #7df0a0;
}
QPushButton#flagOff:disabled, QPushButton#flagOn:disabled {
  background: #161616;
  border-color: #2d2d2d;
  color: #747474;
}
QPushButton#formatPill {
  background: #242424;
  border: none;
  border-radius: 12px;
  color: #f5f5f5;
  padding: 4px 10px;
  font-size: 10px;
  font-weight: 600;
}
QPushButton#formatPill:hover {
  background: #333333;
}

QLabel#kicker {
  color: #b3b3b3;
  font-size: 11px;
  font-weight: 700;
}
QLabel#muted { color: #9b9b9b; font-size: 11px; }
QLabel#outputPath { color: #9b9b9b; font-size: 11px; }
QLabel#footerStatus {
  color: #f5f5f5; font-size: 11px; font-weight: 600;
}
QLabel#footerEta {
  color: #b3b3b3; font-size: 11px;
  font-family: "SF Mono", "Menlo", "Courier New", monospace;
}

QTableWidget {
  background: #121212;
  color: #f5f5f5;
  border: none;
  gridline-color: #242424;
  selection-background-color: #242424;
  selection-color: #f5f5f5;
  outline: none;
}
QHeaderView::section {
  background: #121212;
  color: #8b8b8b;
  border: none;
  border-bottom: 1px solid #242424;
  padding: 8px 16px;
  font-size: 10px;
  font-weight: 700;
}
QTableWidget::item {
  border-bottom: 1px solid #1f1f1f;
}
QTableWidget::item:selected { background: #242424; }

QScrollBar:vertical {
  background: transparent; width: 6px; margin: 0;
}
QScrollBar::handle:vertical {
  background: #3a3a3a; border-radius: 3px; min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #555555; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
  background: transparent; height: 6px;
}
QScrollBar::handle:horizontal {
  background: #3a3a3a; border-radius: 3px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QProgressBar {
  border: none; border-radius: 3px;
  background: #2a2a2a;
  min-height: 4px; max-height: 4px;
}
QProgressBar::chunk {
  border-radius: 3px;
  background: #1ed760;
}

QLineEdit, QComboBox, QSpinBox {
  border: 1px solid #3a3a3a;
  border-radius: 7px;
  background: #181818;
  color: #f5f5f5;
  padding: 7px 10px;
  selection-background-color: #1ed760;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
  border-color: #1ed760;
  background: #181818;
}
QComboBox::drop-down { border-left: 1px solid #3a3a3a; width: 22px; }
QComboBox QAbstractItemView {
  background: #181818; color: #f5f5f5;
  border: 1px solid #3a3a3a;
  selection-background-color: #303030;
  outline: 0;
}
QCheckBox { spacing: 8px; color: #d8d8d8; }
QCheckBox::indicator { width: 16px; height: 16px; }
QMenu {
  background: #181818;
  border: 1px solid #2a2a2a;
  border-radius: 7px;
  padding: 4px 0;
  color: #f5f5f5;
}
QMenu::item { padding: 7px 20px 7px 12px; font-size: 12px; }
QMenu::item:selected { background: #2a2a2a; color: #f5f5f5; }
QMenu::item:disabled { color: #555555; }
QMenu::separator { height: 1px; background: #2a2a2a; margin: 3px 8px; }
"""


class VisibleCheckStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            return super().drawPrimitive(element, option, painter, widget)
        rect = option.rect.adjusted(0, 0, -1, -1)
        checked = bool(option.state & QStyle.StateFlag.State_On)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        border = QColor("#5a5a5a")
        fill = QColor("#181818")
        if checked:
            border = QColor("#1ed760"); fill = QColor("#1ed760")
        elif hovered:
            border = QColor("#1ed760")
        if not enabled:
            border = QColor("#2a3441"); fill = QColor("#121212")
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 4, 4)
        if checked:
            pen = QPen(QColor("#090909"), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
            painter.drawLine(x + int(0.22*w), y + int(0.55*h), x + int(0.42*w), y + int(0.74*h))
            painter.drawLine(x + int(0.42*w), y + int(0.74*h), x + int(0.78*w), y + int(0.30*h))
        painter.restore()


def _open_folder(path: str | None) -> bool:
    if not path or not os.path.isdir(path):
        return False
    try:
        sys = platform.system()
        if sys == "Windows":
            os.startfile(path)  # noqa: P204
        elif sys == "Darwin":
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
        sys = platform.system()
        if sys == "Windows":
            os.startfile(path)  # noqa: P204
        elif sys == "Darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
        return True
    except Exception:
        return False


# ── UI Components ──────────────────────────────────────────────────────────────

class LogsDialog(QDialog):
    """Scrollable log viewer with live refresh."""

    def __init__(self, handler: _QtLogHandler, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Music2MP3 — Logs")
        self.resize(980, 620)
        self._handler = handler
        self._seen_count = 0
        self._auto_scroll = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        intro = QLabel("Readable activity log: loading, matching decisions, AI impact, downloads.")
        intro.setObjectName("muted")
        layout.addWidget(intro)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setObjectName("logsText")
        self._text.setStyleSheet(
            "QTextEdit#logsText {"
            "  background:#090909; color:#f5f5f5;"
            "  font-family:'SF Mono','Menlo','Courier New',monospace; font-size:12px;"
            "  border:1px solid #2a2a2a; border-radius:7px;"
            "}"
        )
        layout.addWidget(self._text)

        btn_row = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._refresh)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._refresh_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_live)
        self._timer.start(700)
        self._refresh()

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)

    def _refresh_live(self):
        lines = self._handler.get_lines()
        if len(lines) != self._seen_count:
            self._refresh()

    def _refresh(self):
        lines = self._handler.get_lines()
        sb = self._text.verticalScrollBar()
        self._auto_scroll = sb.value() >= sb.maximum() - 8
        self._seen_count = len(lines)
        self._text.setHtml(self._render_html(lines))
        if self._auto_scroll:
            sb = self._text.verticalScrollBar()
            sb.setValue(sb.maximum())

    @classmethod
    def _render_html(cls, lines: list[str]) -> str:
        rows = [cls._format_line(line) for line in lines]
        body = "\n".join(rows) or cls._empty_html()
        return (
            "<html><body style='background:#090909;color:#f5f5f5;"
            "font-family:SF Mono,Menlo,Courier New,monospace;font-size:12px;'>"
            f"{body}</body></html>"
        )

    @staticmethod
    def _empty_html() -> str:
        return "<div style='color:#64748b;padding:18px;'>No log entries yet.</div>"

    @staticmethod
    def _badge(label: str, color: str) -> str:
        return (
            f"<span style='display:inline-block;color:{color};"
            f"font-weight:800;letter-spacing:1px;width:52px;'>{label}</span>"
        )

    @classmethod
    def _format_line(cls, line: str) -> str:
        safe = html.escape(line)
        color = "#9aa8ba"
        badge = cls._badge("LOG", "#64748b")
        if " MATCH: " in line:
            badge = cls._badge("MATCH", "#1ed760")
            color = "#f5f5f5"
        elif " CONV: AI match advice" in line:
            badge = cls._badge("AI", "#1ed760")
            color = "#d8d8d8"
        elif " CONV: reject candidate by duration:" in line:
            badge = cls._badge("SKIP", "#f5b942")
            color = "#ffe7a3"
        elif " CONV: total tracks to process:" in line:
            badge = cls._badge("START", "#1ed760")
            color = "#d8d8d8"
        elif " CONV: M3U generated:" in line:
            badge = cls._badge("M3U", "#b3b3b3")
            color = "#d8d8d8"
        elif " CONV: manifest generated:" in line or "Library scan:" in line:
            badge = cls._badge("LIB", "#b3b3b3")
            color = "#d8d8d8"
        elif "yt-dlp[" in line:
            badge = cls._badge("DL", "#b3b3b3")
            color = "#d8d8d8"
        elif " ERROR " in line or " failed" in line.lower():
            badge = cls._badge("ERR", "#e85d75")
            color = "#f0c2ca"
        elif " WARNING " in line:
            badge = cls._badge("WARN", "#f5b942")
            color = "#ffe7a3"
        return (
            "<div style='border-left:2px solid #333333;"
            "padding:5px 8px;margin:2px 0;background:rgba(255,255,255,0.025);'>"
            f"{badge}<span style='color:{color};'>{safe}</span></div>"
        )


class NeedsAttentionDialog(QDialog):
    def __init__(self, items: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Needs attention")
        self.resize(860, 500)
        self._items = list(items)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("Needs attention")
        title.setStyleSheet("font-size:22px; font-weight:700; color:#f5f5f5;")
        layout.addWidget(title)

        counts = attention_counts(self._items)
        summary_parts = [f"{counts['total']} track(s)"]
        if counts["review"]:
            summary_parts.append(f"{counts['review']} to review")
        if counts["failed"]:
            summary_parts.append(f"{counts['failed']} failed")
        if counts["missing"]:
            summary_parts.append(f"{counts['missing']} missing")
        summary = QLabel(" · ".join(summary_parts))
        summary.setObjectName("muted")
        layout.addWidget(summary)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Playlist", "Track", "Issue", "Next action"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(2, 170)
        self.table.setColumnWidth(3, 110)
        self.table.doubleClicked.connect(lambda _index: self.accept())
        layout.addWidget(self.table, 1)

        issue_colors = {"review": "#f5b942", "failed": "#e85d75", "missing": "#b3b3b3"}
        for row, item in enumerate(self._items):
            self.table.insertRow(row)
            self.table.setRowHeight(row, 42)
            playlist_item = QTableWidgetItem(str(item.get("playlist_name") or "Playlist"))
            playlist_item.setData(Qt.ItemDataRole.UserRole, row)
            self.table.setItem(row, 0, playlist_item)
            title_text = str(item.get("title") or "Track")
            artists = str(item.get("artists") or "")
            track_item = QTableWidgetItem(f"{title_text}\n{artists}" if artists else title_text)
            track_item.setToolTip(str(item.get("error") or item.get("issue") or ""))
            self.table.setItem(row, 1, track_item)
            issue_item = QTableWidgetItem(str(item.get("issue") or "Needs attention"))
            issue_item.setForeground(QColor(issue_colors.get(str(item.get("kind")), "#b3b3b3")))
            self.table.setItem(row, 2, issue_item)
            if item.get("kind") == "review":
                next_action = "Review"
            elif item.get("candidate_url"):
                next_action = "Retry"
            else:
                next_action = "Open"
            action_item = QTableWidgetItem(next_action)
            action_item.setForeground(QColor("#1ed760" if item.get("candidate_url") else "#b3b3b3"))
            action_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, action_item)

        if self._items:
            self.table.selectRow(0)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        self.open_btn = QPushButton("Show in playlist")
        self.open_btn.setObjectName("accent")
        self.open_btn.setEnabled(bool(self._items))
        self.open_btn.clicked.connect(self.accept)
        buttons.addWidget(self.open_btn)
        layout.addLayout(buttons)

    def selected_item(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return dict(self._items[row]) if 0 <= row < len(self._items) else None


class ArtworkWidget(QWidget):
    """Muted fallback artwork derived deterministically from a playlist name."""

    def __init__(self, name: str, size: int = 32, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        h = hashlib.md5(name.encode("utf-8", errors="replace")).hexdigest()
        tone = int(h[:4], 16) % 28
        self._c1 = QColor(32 + tone // 2, 48 + tone, 38 + tone // 2)
        self._c2 = QColor(20 + tone // 3, 28 + tone // 2, 23 + tone // 3)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0.0, 0.0, float(self.width()), float(self.height()))
        grad.setColorAt(0.0, self._c1)
        grad.setColorAt(1.0, self._c2)
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 5.0, 5.0)
        painter.end()


class TrackCellWidget(QWidget):
    """Two-line cell widget: title bold + artist dimmer."""

    def __init__(self, title: str, artist: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(1)
        self._title_lbl = QLabel(title or "Unknown")
        self._title_lbl.setStyleSheet(
            "font-size:13px; font-weight:500; color:#f5f5f5; background:transparent;"
        )
        self._artist_lbl = QLabel(artist or "")
        self._artist_lbl.setStyleSheet(
            "font-size:11px; color:#8b8b8b; background:transparent;"
        )
        layout.addWidget(self._title_lbl)
        if artist:
            layout.addWidget(self._artist_lbl)
        self.setStyleSheet("background:transparent;")


class PlaylistItemWidget(QFrame):
    """One playlist entry in the sidebar."""

    item_clicked = Signal(int)
    context_menu_requested = Signal(int)  # emits index on right-click

    def __init__(self, index: int, name: str, source_type: str, count: int, parent=None):
        super().__init__(parent)
        self._index = index
        self.setMinimumHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 4, 8, 4)
        outer.setSpacing(0)

        self._indicator = QFrame()
        self._indicator.setFixedSize(2, 24)
        self._indicator.setStyleSheet("background:transparent; border-radius:1px;")
        outer.addWidget(self._indicator)
        outer.addSpacing(8)

        self._artwork = ArtworkWidget(name, 32)
        outer.addWidget(self._artwork)
        outer.addSpacing(10)

        text = QVBoxLayout()
        text.setSpacing(1)
        text.setContentsMargins(0, 0, 0, 0)
        self._name_lbl = QLabel(name)
        self._name_lbl.setStyleSheet(
            "font-size:13px; font-weight:500; color:#f5f5f5; background:transparent;"
        )
        self._name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        source_text = f"{count} tracks · {source_type}" if count else source_type
        self._meta_lbl = QLabel(source_text)
        self._meta_lbl.setStyleSheet(
            "font-size:10px; color:#8b8b8b; background:transparent;"
        )
        text.addWidget(self._name_lbl)
        text.addWidget(self._meta_lbl)
        outer.addLayout(text, 1)

        self.setSelected(False)

    def setSelected(self, selected: bool):
        if selected:
            self.setStyleSheet(
                "QFrame { background:#242424; border:none; border-radius:7px; }"
            )
            self._indicator.setStyleSheet("background:#1ed760; border-radius:1px;")
            self._name_lbl.setStyleSheet(
                "font-size:13px; font-weight:600; color:#f5f5f5; background:transparent;"
            )
            self._meta_lbl.setStyleSheet(
                "font-size:10px; color:#b3b3b3; background:transparent;"
            )
        else:
            self.setStyleSheet(
                "QFrame { background:transparent; border:none; border-radius:7px; }"
                "QFrame:hover { background:#181818; }"
            )
            self._indicator.setStyleSheet("background:transparent; border-radius:1px;")
            self._name_lbl.setStyleSheet(
                "font-size:13px; font-weight:500; color:#f5f5f5; background:transparent;"
            )
            self._meta_lbl.setStyleSheet(
                "font-size:10px; color:#8b8b8b; background:transparent;"
            )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.context_menu_requested.emit(self._index)
        else:
            self.item_clicked.emit(self._index)
        super().mousePressEvent(event)


class HeroWidget(QFrame):
    """Quiet playlist header surface."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hero")
        self.setFixedHeight(152)


class AddSourceDialog(QDialog):
    """Minimal modal for entering a playlist URL."""

    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        titles = {
            "spotify": "Add Spotify Playlist",
            "soundcloud": "Add SoundCloud Playlist",
            "bandcamp": "Add Bandcamp Release",
        }
        self.setWindowTitle(titles.get(mode, "Add Source"))
        self.setMinimumWidth(460)
        self.setStyleSheet("background:#121212;")
        self._url = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        kicker = QLabel(f"Add from {mode.title()}")
        kicker.setObjectName("kicker")
        layout.addWidget(kicker)

        placeholders = {
            "spotify": "https://open.spotify.com/playlist/...",
            "soundcloud": "https://soundcloud.com/.../sets/...",
            "bandcamp": "https://artist.bandcamp.com/album/...",
        }
        lbl_texts = {
            "spotify": "Spotify playlist URL",
            "soundcloud": "SoundCloud playlist URL",
            "bandcamp": "Bandcamp album or track URL",
        }
        lbl = QLabel(lbl_texts.get(mode, "URL"))
        lbl.setObjectName("muted")
        layout.addWidget(lbl)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholders.get(mode, ""))
        self._edit.setMinimumHeight(36)
        layout.addWidget(self._edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("ghost")
        cancel_btn.clicked.connect(self.reject)
        load_btn = QPushButton("Load")
        load_btn.setObjectName("accent")
        load_btn.setMinimumWidth(100)
        load_btn.clicked.connect(self._on_accept)
        self._edit.returnPressed.connect(self._on_accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(load_btn)
        layout.addLayout(btn_row)

    def _on_accept(self):
        self._url = self._edit.text().strip()
        if self._url:
            self.accept()

    def url(self) -> str:
        return self._url


class SettingsDialog(QDialog):
    """Settings / options dialog."""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)
        self.setStyleSheet("background:#121212;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        kicker = QLabel("Settings")
        kicker.setObjectName("kicker")
        layout.addWidget(kicker)
        layout.addSpacing(4)

        # Format row
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Output format"))
        fmt_row.addStretch()
        self.format_combo = QComboBox()
        self.format_combo.addItems(["mp3", "m4a", "aac", "wav", "flac", "aiff"])
        current_fmt = str(config.get("output_format_manual", config.get("output_format", "mp3"))).lower()
        idx = self.format_combo.findText(current_fmt)
        if idx >= 0:
            self.format_combo.setCurrentIndex(idx)
        fmt_row.addWidget(self.format_combo)
        layout.addLayout(fmt_row)

        # Threads row
        thr_row = QHBoxLayout()
        thr_row.addWidget(QLabel("Threads"))
        thr_row.addStretch()
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 8)
        self.threads_spin.setValue(int(config.get("concurrency", 3)))
        thr_row.addWidget(self.threads_spin)
        layout.addLayout(thr_row)

        # AI match row
        ai_row = QHBoxLayout()
        self.ai_enabled_cb = QCheckBox("AI match assist")
        self.ai_enabled_cb.setChecked(bool(config.get("ai_match_enabled", False)))
        ai_row.addWidget(self.ai_enabled_cb)
        ai_row.addStretch()
        self.ai_model_combo = QComboBox()
        self.ai_model_combo.addItems(["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"])
        current_model = str(config.get("ai_match_model") or "gemini-2.5-flash")
        model_idx = self.ai_model_combo.findText(current_model)
        if model_idx >= 0:
            self.ai_model_combo.setCurrentIndex(model_idx)
        ai_row.addWidget(self.ai_model_combo)
        layout.addLayout(ai_row)

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("Google API key"))
        self.ai_key_edit = QLineEdit()
        self.ai_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_key_edit.setPlaceholderText("Saved in keychain" if has_saved_ai_api_key() else "Paste Gemini API key")
        key_row.addWidget(self.ai_key_edit, 1)
        layout.addLayout(key_row)

        prompt_lbl = QLabel("AI matching prompt")
        prompt_lbl.setObjectName("muted")
        layout.addWidget(prompt_lbl)
        self.ai_prompt_edit = QTextEdit()
        self.ai_prompt_edit.setFixedHeight(92)
        self.ai_prompt_edit.setPlainText(str(config.get("ai_match_prompt") or ""))
        self.ai_prompt_edit.setPlaceholderText("Instructions used by Gemini to accept/reject/retry gray-zone matches")
        layout.addWidget(self.ai_prompt_edit)

        source_sep = QFrame()
        source_sep.setFixedHeight(1)
        source_sep.setStyleSheet("background:#2a2a2a;")
        layout.addWidget(source_sep)
        source_lbl = QLabel("Sources")
        source_lbl.setObjectName("muted")
        layout.addWidget(source_lbl)

        cookies_row = QHBoxLayout()
        cookies_row.addWidget(QLabel("cookies.txt"))
        self.cookies_edit = QLineEdit()
        self.cookies_edit.setPlaceholderText("Optional yt-dlp cookies file for SoundCloud/YouTube")
        self.cookies_edit.setText(str(config.get("cookies_path") or ""))
        self.cookies_edit.setToolTip("Netscape cookies.txt passed to yt-dlp for blocked SoundCloud/YouTube links")
        cookies_row.addWidget(self.cookies_edit, 1)
        cookies_browse_btn = QPushButton("Browse")
        cookies_browse_btn.setObjectName("ghost")
        cookies_browse_btn.setToolTip("Select cookies.txt")
        cookies_browse_btn.clicked.connect(self._browse_cookies_file)
        cookies_row.addWidget(cookies_browse_btn)
        layout.addLayout(cookies_row)

        browser_cookie_row = QHBoxLayout()
        browser_cookie_row.addWidget(QLabel("Browser auth"))
        self.cookies_browser_combo = QComboBox()
        for browser in YTDLP_COOKIE_BROWSERS:
            self.cookies_browser_combo.addItem(browser or "none", browser)
        current_browser = str(config.get("cookies_from_browser") or "").strip().lower()
        browser_idx = self.cookies_browser_combo.findData(current_browser)
        if browser_idx >= 0:
            self.cookies_browser_combo.setCurrentIndex(browser_idx)
        self.cookies_browser_combo.setToolTip("Let yt-dlp read SoundCloud/YouTube cookies from a browser profile")
        browser_cookie_row.addWidget(self.cookies_browser_combo)
        self.cookies_profile_edit = QLineEdit()
        self.cookies_profile_edit.setPlaceholderText("Profile name/path optional")
        self.cookies_profile_edit.setText(str(config.get("cookies_browser_profile") or ""))
        self.cookies_profile_edit.setToolTip("Optional browser profile for yt-dlp cookies-from-browser")
        browser_cookie_row.addWidget(self.cookies_profile_edit, 1)
        layout.addLayout(browser_cookie_row)

        if FEATURE_SOULSEEK_ASSIST:
            soul_sep = QFrame()
            soul_sep.setFixedHeight(1)
            soul_sep.setStyleSheet("background:#2a2a2a;")
            layout.addWidget(soul_sep)
            soul_lbl = QLabel("Soulseek / slskd")
            soul_lbl.setObjectName("muted")
            layout.addWidget(soul_lbl)

            self.slskd_enabled_cb = QCheckBox("Enable slskd search assist")
            self.slskd_enabled_cb.setChecked(bool(config.get("slskd_enabled", False)))
            layout.addWidget(self.slskd_enabled_cb)

            slskd_host_row = QHBoxLayout()
            slskd_host_row.addWidget(QLabel("slskd host"))
            self.slskd_host_edit = QLineEdit()
            self.slskd_host_edit.setPlaceholderText("http://127.0.0.1:5030")
            self.slskd_host_edit.setText(str(config.get("slskd_host") or "http://127.0.0.1:5030"))
            slskd_host_row.addWidget(self.slskd_host_edit, 1)
            layout.addLayout(slskd_host_row)

            slskd_key_row = QHBoxLayout()
            slskd_key_row.addWidget(QLabel("slskd API key"))
            self.slskd_key_edit = QLineEdit()
            self.slskd_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.slskd_key_edit.setPlaceholderText("Saved in keychain" if has_saved_slskd_api_key() else "Paste slskd API key")
            slskd_key_row.addWidget(self.slskd_key_edit, 1)
            layout.addLayout(slskd_key_row)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#2a2a2a;")
        layout.addWidget(sep)
        layout.addSpacing(2)

        self.checks: dict[str, QCheckBox] = {}
        for key, label in [
            ("deep_search", "Deep search (slower, more accurate)"),
            ("incremental_update", "Incremental update (skip existing)"),
            ("safe_search", "Safe search (avoid long sets)"),
            ("generate_m3u", "Generate M3U"),
            ("exclude_instrumentals", 'Exclude "instrumental" matches'),
            ("prefix_numbers", "Number files (001, 002…)"),
            ("strict_match", "Strict matching"),
        ]:
            cb = QCheckBox(label)
            cb.setChecked(bool(config.get(key, False)))
            self.checks[key] = cb
            layout.addWidget(cb)

        layout.addSpacing(6)
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background:#2a2a2a;")
        layout.addWidget(sep2)
        layout.addSpacing(4)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("ghost")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("accent")
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def get_values(self) -> dict:
        fmt = self.format_combo.currentText().lower()
        values: dict = {
            "output_format_manual": fmt,
            "output_format": fmt,
            "concurrency": int(self.threads_spin.value()),
            "ai_match_enabled": self.ai_enabled_cb.isChecked(),
            "ai_match_provider": "vertex",
            "ai_match_model": self.ai_model_combo.currentText().strip() or "gemini-2.5-flash",
            "ai_match_prompt": self.ai_prompt_edit.toPlainText().strip(),
            "cookies_path": self.cookies_edit.text().strip(),
            "cookies_from_browser": str(self.cookies_browser_combo.currentData() or ""),
            "cookies_browser_profile": self.cookies_profile_edit.text().strip(),
        }
        if FEATURE_SOULSEEK_ASSIST:
            values.update({
                "slskd_enabled": self.slskd_enabled_cb.isChecked(),
                "slskd_host": self.slskd_host_edit.text().strip() or "http://127.0.0.1:5030",
            })
        for key, cb in self.checks.items():
            values[key] = cb.isChecked()
        api_key = self.ai_key_edit.text().strip()
        if api_key:
            values["_ai_api_key"] = api_key
        if FEATURE_SOULSEEK_ASSIST:
            slskd_key = self.slskd_key_edit.text().strip()
            if slskd_key:
                values["_slskd_api_key"] = slskd_key
        return values

    def _browse_cookies_file(self):
        initial = self.cookies_edit.text().strip() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select cookies.txt",
            initial,
            "Cookies (*.txt);;All files (*)",
        )
        if path:
            self.cookies_edit.setText(path)


# ── Main window ────────────────────────────────────────────────────────────────

class QtMusic2MP3Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Music2MP3")
        self.resize(1160, 800)
        self.setMinimumSize(900, 600)

        self.config = load_config()
        self.csv_path: str | None = None
        configured_output = self.config.get("default_output_dir")
        configured_root = self.config.get("library_root") or configured_output
        self.output_folder: str | None = configured_output
        self.last_output_dir: str | None = None
        self.loaded_playlist_name: str | None = None
        self.loaded_source_info: dict | None = None
        self.library_root: str | None = configured_root
        if self.library_root and os.path.isdir(self.library_root):
            # The visible library root is the expected parent for new imports.
            # Keep the older output setting in sync to avoid downloads landing in
            # a stale hidden folder from a previous session.
            self.output_folder = self.library_root
            self.config["default_output_dir"] = self.library_root
        self.library_items: list[dict] = []
        self._pending_sync_manifest: dict | None = None
        self._append_to_library_manifest: dict | None = None
        self._sync_target_manifest: dict | None = None
        self._sync_queue: list[dict] = []  # manifests waiting for sync-all
        self._sync_queue_total: int = 0
        self._sync_queue_active: bool = False
        self._sync_queue_cancel_requested: bool = False
        self._sync_queue_results: list[dict] = []
        self._source_load_failed: bool = False
        self._rows: dict[int, dict] = {}
        self._perc: dict[int, float] = {}
        # (title, msg, best_url, track_t, out_dir)
        self._errors: dict[int, tuple[str, str, str, dict, str]] = {}
        self._total_tracks = 0
        self._started_at: float | None = None
        self._load_started_at: float | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_timer)
        self._was_cancelled = False

        self._thread: QThread | None = None
        self._worker: ConverterWorker | None = None
        self._load_thread: QThread | None = None
        self._load_worker: PlaylistLoadWorker | None = None
        self._cleanup_thread: QThread | None = None
        self._cleanup_worker: LibraryCleanupWorker | None = None
        self._cleanup_report: dict | None = None
        self._cleanup_error: str = ""
        self._attention_items: list[dict] = []

        # Sidebar playlist items
        self._playlist_item_widgets: list[PlaylistItemWidget] = []
        self._selected_playlist_idx: int = -1  # -1 = session, 0+ = library_items

        # Session playlist entry (freshly loaded from Spotify/SC/CSV)
        self._session_playlist: dict | None = None

        self._build_ui()
        self.setAcceptDrops(True)
        self._load_from_config()
        self._update_convert_state()
        if not (self.library_root and os.path.isdir(self.library_root)):
            QTimer.singleShot(0, self._choose_library_root)

    # ── Build UI ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── TopBar ──────────────────────────────────────────────────────────
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_bar.setFixedHeight(56)
        header = QHBoxLayout(top_bar)
        header.setContentsMargins(18, 0, 18, 0)
        header.setSpacing(10)

        mark = QFrame()
        mark.setObjectName("brandMark")
        mark.setFixedSize(28, 28)
        mark_inner = QVBoxLayout(mark)
        mark_inner.setContentsMargins(0, 0, 0, 0)
        mark_lbl = QLabel("M2")
        mark_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark_lbl.setStyleSheet("color:#090909; font-weight:800; font-size:11px;")
        mark_inner.addWidget(mark_lbl)
        header.addWidget(mark)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(0)
        brand_title = QLabel("Music2MP3")
        brand_title.setObjectName("brandTitle")
        brand_title.setTextFormat(Qt.TextFormat.RichText)
        brand_sub = QLabel("DJ-ready library")
        brand_sub.setObjectName("brandSub")
        brand_col.addWidget(brand_title)
        brand_col.addWidget(brand_sub)
        header.addLayout(brand_col)
        header.addStretch()

        self.online_chip = QLabel("Ready")
        self.online_chip.setObjectName("chip")
        header.addWidget(self.online_chip)

        self.logs_btn = QPushButton("Logs")
        self.logs_btn.setObjectName("ghost")
        self.logs_btn.setToolTip("Open logs")
        self.logs_btn.clicked.connect(self._open_logs)
        header.addWidget(self.logs_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.setObjectName("ghost")
        settings_btn.setFixedHeight(34)
        settings_btn.setToolTip("Settings")
        settings_btn.clicked.connect(self._open_settings)
        header.addWidget(settings_btn)

        outer.addWidget(top_bar)

        # ── Body ────────────────────────────────────────────────────────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # ── Sidebar ─────────────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(12, 14, 12, 12)
        sb.setSpacing(0)

        add_kicker = QLabel("Add music")
        add_kicker.setObjectName("kicker")
        sb.addWidget(add_kicker)
        sb.addSpacing(8)

        add_grid = QGridLayout()
        add_grid.setHorizontalSpacing(6)
        add_grid.setVerticalSpacing(6)
        self.add_spotify_btn = QPushButton("Spotify")
        self.add_soundcloud_btn = QPushButton("SoundCloud")
        self.add_bandcamp_btn = QPushButton("Bandcamp")
        self.add_soulseek_btn = QPushButton("Soulseek")
        self.add_csv_btn = QPushButton("CSV file")
        self.add_scan_btn = QPushButton("Local scan")
        self.add_spotify_btn.setToolTip("Load a Spotify playlist URL")
        self.add_soundcloud_btn.setToolTip("Load a SoundCloud playlist or track URL")
        self.add_bandcamp_btn.setToolTip("Bandcamp source is parked in backlog")
        self.add_soulseek_btn.setToolTip("Soulseek assist is parked in backlog")
        self.add_csv_btn.setToolTip("Load a local CSV file")
        self.add_scan_btn.setToolTip("Choose and scan a local library folder")
        for btn in (self.add_spotify_btn, self.add_soundcloud_btn, self.add_bandcamp_btn, self.add_soulseek_btn,
                    self.add_csv_btn, self.add_scan_btn):
            btn.setObjectName("sourceTile")
            btn.setMinimumHeight(44)
        self.add_spotify_btn.clicked.connect(self._on_add_spotify)
        self.add_soundcloud_btn.clicked.connect(self._on_add_soundcloud)
        if FEATURE_BANDCAMP_SOURCE:
            self.add_bandcamp_btn.setToolTip("Load a Bandcamp album or track URL")
            self.add_bandcamp_btn.clicked.connect(self._on_add_bandcamp)
        else:
            self.add_bandcamp_btn.setVisible(False)
            self.add_bandcamp_btn.setEnabled(False)
        if FEATURE_SOULSEEK_ASSIST:
            self.add_soulseek_btn.setToolTip("Search Soulseek via a configured slskd server")
            self.add_soulseek_btn.clicked.connect(self._on_add_soulseek)
        else:
            self.add_soulseek_btn.setVisible(False)
            self.add_soulseek_btn.setEnabled(False)
        self.add_csv_btn.clicked.connect(self._on_add_csv)
        self.add_scan_btn.clicked.connect(self._choose_library_root)
        add_grid.addWidget(self.add_spotify_btn, 0, 0)
        add_grid.addWidget(self.add_soundcloud_btn, 0, 1)
        row = 1
        if FEATURE_BANDCAMP_SOURCE or FEATURE_SOULSEEK_ASSIST:
            add_grid.addWidget(self.add_bandcamp_btn, row, 0)
            add_grid.addWidget(self.add_soulseek_btn, row, 1)
            row += 1
        add_grid.addWidget(self.add_csv_btn, row, 0)
        add_grid.addWidget(self.add_scan_btn, row, 1)
        sb.addLayout(add_grid)
        sb.addSpacing(14)

        sep1 = QFrame()
        sep1.setFixedHeight(1)
        sep1.setStyleSheet("background:#242424;")
        sb.addWidget(sep1)
        sb.addSpacing(10)

        lib_hdr = QHBoxLayout()
        lib_kicker = QLabel("Your library")
        lib_kicker.setObjectName("kicker")
        lib_hdr.addWidget(lib_kicker)
        lib_hdr.addStretch()
        sb.addLayout(lib_hdr)
        sb.addSpacing(8)

        library_actions = QGridLayout()
        library_actions.setContentsMargins(0, 0, 0, 0)
        library_actions.setHorizontalSpacing(6)
        library_actions.setVerticalSpacing(6)

        self.sync_btn = QPushButton("Sync selected")
        self.sync_btn.setObjectName("libraryAction")
        self.sync_btn.setMinimumHeight(28)
        self.sync_btn.setToolTip("Sync the selected playlist from its saved source")
        self.sync_btn.clicked.connect(self._sync_selected_library_playlist)
        library_actions.addWidget(self.sync_btn, 0, 0)

        self.sync_all_btn = QPushButton("Sync all")
        self.sync_all_btn.setObjectName("libraryAction")
        self.sync_all_btn.setMinimumHeight(28)
        self.sync_all_btn.setToolTip("Sync every playlist that has a saved source")
        self.sync_all_btn.clicked.connect(self._sync_all_library_playlists)
        library_actions.addWidget(self.sync_all_btn, 0, 1)

        self.library_scan_btn = QPushButton("Rescan folders")
        self.library_scan_btn.setObjectName("libraryAction")
        self.library_scan_btn.setMinimumHeight(28)
        self.library_scan_btn.setToolTip("Rescan the library folder for local playlists")
        self.library_scan_btn.clicked.connect(self._scan_library_root)
        library_actions.addWidget(self.library_scan_btn, 1, 0)

        self.library_cleanup_btn = QPushButton("Clean library")
        self.library_cleanup_btn.setObjectName("libraryAction")
        self.library_cleanup_btn.setMinimumHeight(28)
        self.library_cleanup_btn.setToolTip("Find orphan files, duplicate entries, and nested playlists")
        self.library_cleanup_btn.clicked.connect(self._start_library_cleanup)
        library_actions.addWidget(self.library_cleanup_btn, 1, 1)
        sb.addLayout(library_actions)
        sb.addSpacing(8)

        self.needs_attention_btn = QPushButton("Needs attention · 0")
        self.needs_attention_btn.setObjectName("attentionButton")
        self.needs_attention_btn.setMinimumHeight(30)
        self.needs_attention_btn.setToolTip("Show failed tracks, missing files, and matches to review")
        self.needs_attention_btn.clicked.connect(self._show_needs_attention)
        sb.addWidget(self.needs_attention_btn)
        sb.addSpacing(8)

        # Scrollable playlist list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea { border:none; background:transparent; }"
            "QWidget#playlistContainer { background:transparent; }"
        )

        self._playlist_container = QWidget()
        self._playlist_container.setObjectName("playlistContainer")
        self._playlist_container.setStyleSheet("background:transparent;")
        self._playlist_layout = QVBoxLayout(self._playlist_container)
        self._playlist_layout.setContentsMargins(0, 0, 4, 0)
        self._playlist_layout.setSpacing(2)
        self._playlist_layout.addStretch()
        scroll.setWidget(self._playlist_container)
        sb.addWidget(scroll, 1)
        sb.addSpacing(10)

        # Root dir box
        root_box = QFrame()
        root_box.setObjectName("rootDirBox")
        root_box_layout = QVBoxLayout(root_box)
        root_box_layout.setContentsMargins(10, 8, 10, 8)
        root_box_layout.setSpacing(3)
        rk = QLabel("Library folder")
        rk.setObjectName("kicker")
        root_box_layout.addWidget(rk)
        rp_row = QHBoxLayout()
        self.library_root_lbl = QLabel("not set")
        self.library_root_lbl.setStyleSheet(
            "font-size:11px; font-family:'SF Mono','Menlo',monospace;"
            " color:#b3b3b3; background:transparent;"
        )
        self.library_root_lbl.setTextFormat(Qt.TextFormat.PlainText)
        rp_row.addWidget(self.library_root_lbl, 1)
        self.library_choose_btn = QPushButton("…")
        self.library_choose_btn.setObjectName("ghost")
        self.library_choose_btn.setFixedSize(22, 22)
        self.library_choose_btn.setStyleSheet("padding:0; font-size:14px;")
        self.library_choose_btn.setToolTip("Choose library root folder")
        self.library_choose_btn.clicked.connect(self._choose_library_root)
        rp_row.addWidget(self.library_choose_btn)
        root_box_layout.addLayout(rp_row)
        sb.addWidget(root_box)

        body.addWidget(sidebar)

        # ── Workspace ────────────────────────────────────────────────────────
        workspace = QWidget()
        workspace.setStyleSheet("background:#121212;")
        ws = QVBoxLayout(workspace)
        ws.setContentsMargins(0, 0, 0, 0)
        ws.setSpacing(0)

        # Hero
        self.hero_widget = HeroWidget()
        hero_layout = QHBoxLayout(self.hero_widget)
        hero_layout.setContentsMargins(24, 18, 24, 18)
        hero_layout.setSpacing(18)

        self.hero_cover = QFrame()
        self.hero_cover.setObjectName("heroCover")
        self.hero_cover.setFixedSize(112, 112)
        cover_inner = QVBoxLayout(self.hero_cover)
        cover_inner.setContentsMargins(0, 0, 0, 0)
        cover_icon = QLabel("♪")
        cover_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover_icon.setStyleSheet("color:#1ed760; font-size:40px; font-weight:800; background:transparent;")
        cover_inner.addWidget(cover_icon)
        hero_layout.addWidget(self.hero_cover)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(5)
        self.hero_source_label = QLabel("No source selected")
        self.hero_source_label.setObjectName("heroSource")
        self.hero_title_label = QLabel("Ready to export")
        self.hero_title_label.setObjectName("heroTitle")
        self.hero_meta_label = QLabel(
            "Load Spotify, SoundCloud, CSV, or sync a manifest playlist"
        )
        self.hero_meta_label.setObjectName("heroMeta")
        hero_text.addStretch()
        hero_text.addWidget(self.hero_source_label)
        hero_text.addWidget(self.hero_title_label)
        hero_text.addWidget(self.hero_meta_label)
        hero_text.addStretch()
        hero_layout.addLayout(hero_text, 1)
        ws.addWidget(self.hero_widget)

        # ActionBar
        action_bar = QFrame()
        action_bar.setObjectName("actionBar")
        action_bar.setFixedHeight(58)
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(24, 10, 24, 10)
        action_layout.setSpacing(8)

        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setObjectName("accent")
        self.convert_btn.setMinimumWidth(136)
        self.convert_btn.setFixedHeight(36)
        self.convert_btn.setToolTip("Convert the loaded source into local audio files")
        self.convert_btn.clicked.connect(self._start_conversion)
        action_layout.addWidget(self.convert_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setMinimumWidth(90)
        self.stop_btn.setFixedHeight(36)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setToolTip("Stop the current conversion")
        self.stop_btn.clicked.connect(self._stop_conversion)
        action_layout.addWidget(self.stop_btn)

        action_layout.addStretch()

        self.action_output_lbl = QLabel("Choose output folder")
        self.action_output_lbl.setObjectName("outputPath")
        self.action_output_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_output_lbl.setToolTip("Choose output folder")
        self.action_output_lbl.mousePressEvent = lambda _e: self._choose_output_folder()
        action_layout.addWidget(self.action_output_lbl)

        open_out_btn = QPushButton("Open")
        open_out_btn.setObjectName("ghost")
        open_out_btn.setFixedHeight(34)
        open_out_btn.setToolTip("Open output folder")
        open_out_btn.clicked.connect(self._open_output_folder)
        action_layout.addWidget(open_out_btn)
        ws.addWidget(action_bar)

        # FlagsBar
        flags_bar = QFrame()
        flags_bar.setObjectName("flagsBar")
        flags_bar.setFixedHeight(44)
        flags_layout = QHBoxLayout(flags_bar)
        flags_layout.setContentsMargins(24, 8, 24, 8)
        flags_layout.setSpacing(6)

        flags_kicker = QLabel("Quick options")
        flags_kicker.setObjectName("kicker")
        flags_layout.addWidget(flags_kicker)
        flags_layout.addSpacing(4)

        self.flag_btns: dict[str, QPushButton] = {}
        for cfg_key in [
            "incremental_update",
            "safe_search",
            "ai_match_enabled",
            "generate_m3u",
            "prefix_numbers",
        ]:
            btn = QPushButton()
            btn.setObjectName("flagOff")
            btn.clicked.connect(lambda _checked=False, k=cfg_key: self._toggle_flag(k))
            self.flag_btns[cfg_key] = btn
            flags_layout.addWidget(btn)

        flags_layout.addStretch()

        self.format_pill = QPushButton("mp3 · t3")
        self.format_pill.setObjectName("formatPill")
        self.format_pill.setToolTip("Click to open settings")
        self.format_pill.clicked.connect(self._open_settings)
        flags_layout.addWidget(self.format_pill)
        ws.addWidget(flags_bar)

        # Track table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Track", "Format", "Match", "State"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.cellDoubleClicked.connect(self._on_table_double_click)
        self.table.cellClicked.connect(self._on_table_cell_clicked)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 46)
        self.table.setColumnWidth(2, 92)
        self.table.setColumnWidth(3, 72)
        self.table.setColumnWidth(4, 110)
        ws.addWidget(self.table, 1)

        # Footer progress (hidden when idle)
        self.footer_bar = QFrame()
        self.footer_bar.setObjectName("footerBar")
        self.footer_bar.setFixedHeight(46)
        footer_layout = QHBoxLayout(self.footer_bar)
        footer_layout.setContentsMargins(24, 0, 24, 0)
        footer_layout.setSpacing(12)

        self._footer_dot = QLabel()
        self._footer_dot.setFixedSize(8, 8)
        self._footer_dot.setStyleSheet("border-radius:4px; background:#6b7280;")
        footer_layout.addWidget(self._footer_dot)

        self.footer_status_lbl = QLabel("idle")
        self.footer_status_lbl.setObjectName("footerStatus")
        footer_layout.addWidget(self.footer_status_lbl)

        self.global_progress = QProgressBar()
        self.global_progress.setRange(0, 100)
        self.global_progress.setValue(0)
        self.global_progress.setTextVisible(False)
        footer_layout.addWidget(self.global_progress, 1)

        self.footer_eta_lbl = QLabel("")
        self.footer_eta_lbl.setObjectName("footerEta")
        footer_layout.addWidget(self.footer_eta_lbl)

        ws.addWidget(self.footer_bar)
        self.footer_bar.hide()

        body.addWidget(workspace, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(root)

    # ── Source actions ─────────────────────────────────────────────────────────

    def _on_add_spotify(self):
        if self._worker or self._load_worker:
            QMessageBox.warning(self, "Busy", "Wait for current task to finish.")
            return
        dlg = AddSourceDialog("spotify", self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        url = dlg.url()
        if not SpotifyClient.extract_playlist_id(url):
            QMessageBox.warning(self, "Spotify", "Invalid Spotify playlist URL.")
            return
        if not self.config.get("spotify_client_id"):
            QMessageBox.warning(self, "Spotify", 'Missing "spotify_client_id" in config.')
            return
        self._start_source_loader("spotify", url)

    def _on_add_soundcloud(self):
        if self._worker or self._load_worker:
            QMessageBox.warning(self, "Busy", "Wait for current task to finish.")
            return
        dlg = AddSourceDialog("soundcloud", self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        url = dlg.url()
        if "soundcloud.com" not in url:
            QMessageBox.warning(self, "SoundCloud", "Please enter a valid SoundCloud URL.")
            return
        self._start_source_loader("soundcloud", url)

    def _on_add_bandcamp(self):
        if not FEATURE_BANDCAMP_SOURCE:
            QMessageBox.information(self, "Bandcamp", "Bandcamp source is parked in backlog for now.")
            return
        if self._worker or self._load_worker:
            QMessageBox.warning(self, "Busy", "Wait for current task to finish.")
            return
        dlg = AddSourceDialog("bandcamp", self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        url = dlg.url()
        if not self._is_bandcamp_url(url):
            QMessageBox.warning(self, "Bandcamp", "Please enter a valid Bandcamp album or track URL.")
            return
        self._start_source_loader("bandcamp", url)

    def _on_add_soulseek(self):
        if not FEATURE_SOULSEEK_ASSIST:
            QMessageBox.information(self, "Soulseek", "Soulseek assist is parked in backlog for now.")
            return
        if self._worker or self._load_worker:
            QMessageBox.warning(self, "Busy", "Wait for current task to finish.")
            return
        query, ok = QInputDialog.getText(self, "Soulseek search", "Search query")
        if not ok or not query.strip():
            return
        self._open_soulseek_search_dialog({"title": query.strip(), "artists": ""})

    @staticmethod
    def _is_bandcamp_url(url: str) -> bool:
        low = (url or "").strip().lower()
        return low.startswith(("http://", "https://")) and ".bandcamp.com/" in low

    def _on_add_csv(self):
        if self._worker or self._load_worker:
            QMessageBox.warning(self, "Busy", "Wait for current task to finish.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV", str(Path.home() / "Downloads"), "CSV files (*.csv)"
        )
        if path:
            self._load_csv_file(path)

    def _load_csv_file(self, path: str, source_label: str = "local file"):
        if not path or not path.lower().endswith(".csv") or not os.path.isfile(path):
            QMessageBox.warning(self, "CSV", "Select a valid CSV file.")
            return
        self._append_to_library_manifest = None
        self.csv_path = path
        self.loaded_playlist_name = Path(path).stem
        self.loaded_source_info = {"type": "csv", "url": path, "name": Path(path).stem}
        self._session_playlist = {
            "name": Path(path).stem,
            "source_type": "csv",
            "count": self._csv_track_count(path),
        }
        self._rebuild_playlist_sidebar()
        self._selected_playlist_idx = -1
        self._update_playlist_selection()
        self._update_hero()
        self._populate_table_for_selection()
        self._update_convert_state()
        self._set_footer_state("idle", "ready")

    @staticmethod
    def _csv_track_count(path: str) -> int:
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                return sum(1 for row in csv.DictReader(f) if any(str(v or "").strip() for v in row.values()))
        except Exception:
            return 0

    # ── Source loader ──────────────────────────────────────────────────────────

    def _start_source_loader(self, mode: str, url: str):
        self._source_load_failed = False
        if not self._sync_target_manifest:
            self._session_playlist = None
            self._selected_playlist_idx = -1
            self.loaded_playlist_name = None
            self.loaded_source_info = {"type": mode, "url": url, "name": ""}
            self.csv_path = None
            self._clear_download_rows()
            self._rebuild_playlist_sidebar()
            self._update_playlist_selection()
            self.hero_source_label.setText(f"Loading from {mode.title()}")
            self.hero_title_label.setText(f"Loading {mode.title()}")
            self.hero_meta_label.setText("Fetching source metadata")
            self._update_convert_state()
        self._set_footer_state("loading", f"Loading from {mode.title()}...")
        self.footer_bar.show()
        self._load_started_at = time.time()
        self.footer_eta_lbl.setText("")
        self.global_progress.setRange(0, 0)  # indeterminate spinner
        self._timer.start(1000)
        self._set_ui_enabled(False)
        self.convert_btn.setEnabled(False)
        self._restyle(self.convert_btn, "accentReady")  # hint: this is the next action

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

    @Slot(str)
    def _on_source_status(self, text: str):
        self.footer_status_lbl.setText((self._sync_queue_status_prefix() + text)[:80])

    def _sync_queue_status_prefix(self) -> str:
        if not self._sync_queue_active or not self._sync_queue_total:
            return ""
        done = len(self._sync_queue_results)
        current = min(self._sync_queue_total, done + 1)
        return f"sync all {current}/{self._sync_queue_total} · "

    @Slot(object)
    def _on_source_loaded(self, payload_obj: object):
        payload = payload_obj if isinstance(payload_obj, dict) else {}
        csv_path = str(payload.get("csv_path", "")).strip()
        if not csv_path or not os.path.isfile(csv_path):
            self._source_load_failed = True
            msg = "Source loaded but no CSV was produced."
            log.error(msg)
            if self._sync_queue_active and self._sync_target_manifest:
                self._record_sync_queue_result(self._sync_target_manifest, "load_failed", msg)
                self._pending_sync_manifest = None
                self._sync_target_manifest = None
            else:
                QMessageBox.warning(self, "Source", msg)
            return
        if not self._sync_target_manifest:
            self._append_to_library_manifest = None
        self.csv_path = csv_path
        self.loaded_playlist_name = str(payload.get("playlist_name") or "").strip() or None
        source = str(payload.get("source", "Source"))
        source_type = str(payload.get("source_type") or source).strip().lower()
        source_url = str(payload.get("source_url") or "").strip()
        self.loaded_source_info = {
            "type": source_type,
            "url": source_url,
            "name": self.loaded_playlist_name or "",
        }
        count = int(payload.get("count", 0))
        sync_manifest = self._sync_target_manifest
        if sync_manifest:
            # A sync reload is an implementation detail of the selected library item.
            # Showing it as a fresh session creates a duplicate sidebar entry.
            self._session_playlist = None
            self._selected_playlist_idx = self._library_index_for_manifest(sync_manifest)
        else:
            self._session_playlist = {
                "name": self.loaded_playlist_name or "Playlist",
                "source_type": source_type,
                "count": count,
            }
            self._prepare_single_track_append_if_possible(source_type, source_url, count)
            self._selected_playlist_idx = -1
        self._rebuild_playlist_sidebar()
        self._update_playlist_selection()
        self._update_hero()
        if not sync_manifest:
            self._populate_table_for_selection()
        self._update_convert_state()
        self._set_footer_state("idle", f"Loaded: {self.loaded_playlist_name} · {count} tracks")

    @Slot(str)
    def _on_source_failed(self, error_text: str):
        self._source_load_failed = True
        self._timer.stop()
        self._load_started_at = None
        self.global_progress.setRange(0, 100)
        self.global_progress.setValue(0)
        self._restyle(self.convert_btn, "accent")
        log.error("Source loading failed: %s", error_text)
        if self._sync_queue_active and self._sync_target_manifest:
            self._record_sync_queue_result(self._sync_target_manifest, "load_failed", error_text)
            self._pending_sync_manifest = None
            self._sync_target_manifest = None
            self._set_footer_state("warning", "sync all · source failed · continuing")
        else:
            QMessageBox.critical(self, "Source loading error", error_text)
            self._set_footer_state("error", "Source loading failed")

    def _prepare_single_track_append_if_possible(self, source_type: str, source_url: str, count: int):
        if source_type != "soundcloud" or count != 1:
            return
        if self._is_probable_soundcloud_playlist_url(source_url):
            return
        target = self._selected_library_manifest()
        if not target:
            return
        playlist_dir = str(target.get("playlist_dir") or "").strip()
        if not playlist_dir or not os.path.isdir(playlist_dir):
            return

        target_source = manifest_source(target)
        if not target_source.get("name"):
            target_source["name"] = str(target.get("playlist_name") or Path(playlist_dir).name)
        self.output_folder = playlist_dir
        self.loaded_playlist_name = None
        self.loaded_source_info = target_source
        self._append_to_library_manifest = target
        if self._session_playlist:
            self._session_playlist["name"] = f"+ {self._session_playlist.get('name') or 'track'}"
            self._session_playlist["source_type"] = "soundcloud track"
        self._refresh_action_context()
        log.info(
            "SoundCloud single track will be appended to playlist folder: %s",
            playlist_dir,
        )

    @staticmethod
    def _is_probable_soundcloud_playlist_url(url: str) -> bool:
        low = (url or "").lower()
        return "soundcloud.com" in low and ("/sets/" in low or "/playlists/" in low)

    def _on_source_loader_finished(self):
        source_load_failed = self._source_load_failed
        self._timer.stop()
        self._load_started_at = None
        self.global_progress.setRange(0, 100)
        self.global_progress.setValue(0)
        if self._load_thread:
            self._load_thread.deleteLater()
            self._load_thread = None
        self._load_worker = None
        self._restyle(self.convert_btn, "accent")  # restore normal style
        self._set_ui_enabled(True)
        self._update_convert_state()
        if source_load_failed:
            self._source_load_failed = False
            if self._sync_queue_active:
                self._advance_sync_queue()
            return
        if self._pending_sync_manifest and self.csv_path and self.output_folder and not self._worker:
            manifest = self._pending_sync_manifest
            self._pending_sync_manifest = None
            source = manifest_source(manifest)
            self.loaded_playlist_name = str(
                manifest.get("playlist_name") or source.get("name") or self.loaded_playlist_name or ""
            )
            self.loaded_source_info = source
            self._sync_target_manifest = manifest
            self._start_conversion()

    # ── Playlist sidebar ───────────────────────────────────────────────────────

    def _rebuild_playlist_sidebar(self):
        # Remove existing items (all but the trailing stretch)
        for w in self._playlist_item_widgets:
            self._playlist_layout.removeWidget(w)
            w.deleteLater()
        self._playlist_item_widgets.clear()

        items: list[tuple[str, str, int]] = []  # (name, source_type, count)

        # Session playlist first (index -1 mapped as 0 in widget list)
        if self._session_playlist:
            sp = self._session_playlist
            items.append((sp["name"], sp["source_type"], sp.get("count", 0)))

        for lib in self.library_items:
            source = manifest_source(lib)
            name = str(lib.get("playlist_name") or source.get("name") or "Untitled")
            src_type = str(source.get("type") or "library").lower()
            count = int(lib.get("track_count") or len(lib.get("tracks") or []))
            items.append((name, src_type, count))

        stretch_idx = self._playlist_layout.count() - 1  # last item is stretch

        for i, (name, src_type, count) in enumerate(items):
            widget_idx = i  # widget list index
            lib_idx = i - (1 if self._session_playlist else 0)  # -1 for session
            actual_idx = -1 if (self._session_playlist and i == 0) else lib_idx
            w = PlaylistItemWidget(actual_idx, name, src_type, count)
            w.item_clicked.connect(self._on_playlist_item_clicked)
            w.context_menu_requested.connect(self._show_playlist_context_menu)
            self._playlist_layout.insertWidget(stretch_idx + i, w)
            self._playlist_item_widgets.append(w)

    def _update_playlist_selection(self):
        for w in self._playlist_item_widgets:
            w.setSelected(w._index == self._selected_playlist_idx)

    @Slot(int)
    def _on_playlist_item_clicked(self, idx: int):
        self._selected_playlist_idx = idx
        self._update_playlist_selection()
        self._update_hero()
        self._populate_table_for_selection()
        self._update_convert_state()
        self._update_library_actions()

    def _populate_table_for_selection(self):
        if self._worker:
            return  # don't disrupt an active download
        self._clear_download_rows()

        manifest = self._selected_library_manifest()
        if manifest:
            tracks = manifest.get("tracks") or []
            if tracks:
                for t in tracks:
                    idx = int(t.get("idx", 0))
                    title = str(t.get("title") or f"Track {idx + 1}")
                    artist = str(t.get("artists") or "")
                    self._ensure_row(idx, title, artist)
                    file_name = str(t.get("file") or "").strip()
                    playlist_dir = str(manifest.get("playlist_dir") or "")
                    audio_path = Path(playlist_dir) / file_name if file_name and playlist_dir else None
                    if file_name and playlist_dir:
                        self._set_row_audio_path(idx, str(audio_path))
                    status = str(t.get("status") or "")
                    fmt = str(t.get("format") or "")
                    error = str(t.get("error") or "")
                    match = t.get("match") if isinstance(t.get("match"), dict) else {}
                    candidate_url = str(t.get("suggested_url") or match.get("url") or "")
                    if status == "done":
                        if audio_path and audio_path.is_file():
                            self._set_row_state(idx, "done")
                        else:
                            missing_error = f"Downloaded file is missing:\n{audio_path or file_name or title}"
                            self._set_row_state(idx, "failed")
                            self._set_row_error(
                                idx,
                                missing_error,
                                track_t=t,
                                out_dir=playlist_dir,
                            )
                        self._set_row_progress(idx, 100.0)
                        if fmt:
                            self._set_row_format(idx, fmt)
                    elif status == "failed":
                        self._set_row_state(idx, "failed")
                        if error:
                            self._set_row_error(
                                idx,
                                error,
                                best_url=candidate_url,
                                track_t=t,
                                out_dir=playlist_dir,
                            )
                    elif status == "skipped":
                        if audio_path and audio_path.is_file():
                            self._set_row_state(idx, "done")
                            if fmt:
                                self._set_row_format(idx, fmt)
                        else:
                            missing_error = f"Skipped track file is missing:\n{audio_path or file_name or title}"
                            self._set_row_state(idx, "failed")
                            self._set_row_error(
                                idx,
                                missing_error,
                                track_t=t,
                                out_dir=playlist_dir,
                            )
                        self._set_row_progress(idx, 100.0)
                    if match:
                        self._set_row_match_score(
                            idx,
                            float(match.get("score") or 0.0),
                            title=str(match.get("title") or ""),
                            channel=str(match.get("channel") or ""),
                            url=str(match.get("url") or ""),
                            score_details=match.get("score_details") if isinstance(match.get("score_details"), dict) else {},
                            ai_confidence=match.get("ai_confidence"),
                            ai_reason=str(match.get("ai_reason") or ""),
                        )
                return
            # Legacy playlist: no manifest tracks — scan the directory for audio files
            _AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".aiff", ".aif", ".opus", ".ogg", ".webm"}
            playlist_dir = str(manifest.get("playlist_dir") or "")
            if playlist_dir and os.path.isdir(playlist_dir):
                audio_files = sorted(
                    [p for p in Path(playlist_dir).iterdir() if p.is_file() and p.suffix.lower() in _AUDIO_EXTS],
                    key=lambda p: p.name.casefold(),
                )
                for i, p in enumerate(audio_files, start=1):
                    stem = p.stem
                    self._ensure_row(i, stem, "")
                    self._set_row_audio_path(i, str(p))
                    self._set_row_state(i, "done")
                    self._set_row_progress(i, 100.0)
                    self._set_row_format(i, p.suffix.lstrip(".").upper())
            return

        # Session playlist: read the CSV and show tracks in queued state
        if self._selected_playlist_idx == -1 and self.csv_path and os.path.isfile(self.csv_path):
            try:
                with open(self.csv_path, newline="", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for i, row in enumerate(reader, start=1):
                        title = str(
                            row.get("Track Name") or row.get("title") or f"Track {i + 1}"
                        ).strip()
                        artist = str(
                            row.get("Artist Name(s)") or row.get("artists") or ""
                        ).strip()
                        self._ensure_row(i, title, artist)
            except Exception as e:
                log.warning("Could not read CSV for preview: %s", e)

    def _open_logs(self):
        dlg = LogsDialog(_LOG_HANDLER, self)
        dlg.exec()

    def _selected_library_manifest(self) -> dict | None:
        idx = self._selected_playlist_idx
        if idx < 0:
            return None
        if idx >= len(self.library_items):
            return None
        return self.library_items[idx]

    def _library_index_for_manifest(self, manifest: dict | None) -> int:
        if not manifest:
            return self._selected_playlist_idx
        try:
            return self.library_items.index(manifest)
        except ValueError:
            pass
        wanted_source = manifest_source(manifest)
        wanted_dir = str(manifest.get("playlist_dir") or "").strip()
        for idx, item in enumerate(self.library_items):
            source = manifest_source(item)
            if wanted_source.get("type") and wanted_source == source:
                return idx
            if wanted_dir and wanted_dir == str(item.get("playlist_dir") or "").strip():
                return idx
        return self._selected_playlist_idx

    # ── Hero update ────────────────────────────────────────────────────────────

    def _update_hero(self):
        if not hasattr(self, "hero_title_label"):
            return

        manifest = self._selected_library_manifest()
        if manifest:
            source = manifest_source(manifest)
            title = str(manifest.get("playlist_name") or source.get("name") or "Untitled")
            source_type = str(source.get("type") or "library").lower()
            count = int(manifest.get("track_count") or len(manifest.get("tracks") or []))
            state = "syncable" if source.get("url") else "local"
            self.hero_source_label.setText(f"{source_type.title()} playlist")
            self.hero_title_label.setText(title)
            self.hero_meta_label.setText(
                f"{count} tracks · {source_type} · {state}"
            )
            return

        if self._selected_playlist_idx == -1 and self._session_playlist:
            sp = self._session_playlist
            src = str(sp.get("source_type") or "csv").lower()
            self.hero_source_label.setText(f"{src.title()} playlist")
            self.hero_title_label.setText(sp["name"])
            count = sp.get("count", 0)
            self.hero_meta_label.setText(
                f"{count} tracks · {src} · ready to convert"
            )
            return

        if self.loaded_playlist_name or self.csv_path:
            title = self.loaded_playlist_name or Path(self.csv_path or "").stem or "CSV loaded"
            source = self.loaded_source_info or {}
            src_type = str(source.get("type") or "csv").lower()
            self.hero_source_label.setText(f"Loaded from {src_type.title()}")
            self.hero_title_label.setText(title)
            self.hero_meta_label.setText("Source loaded · choose a destination")
            return

        self.hero_source_label.setText("No source selected")
        self.hero_title_label.setText("Ready to export")
        self.hero_meta_label.setText(
            "Load Spotify, SoundCloud, CSV, or sync a manifest playlist"
        )

    # ── Flag pills ─────────────────────────────────────────────────────────────

    def _toggle_flag(self, cfg_key: str):
        current = bool(self.config.get(cfg_key, False))
        self.config[cfg_key] = not current
        self._save_config()
        self._refresh_flag_pills()

    def _refresh_flag_pills(self):
        if not hasattr(self, "flag_btns"):
            return
        labels = {
            "deep_search": "Deep search",
            "incremental_update": "Incremental",
            "safe_search": "Safe search",
            "ai_match_enabled": "AI assist",
            "generate_m3u": "M3U",
            "prefix_numbers": "Number files",
            "strict_match": "Strict match",
            "exclude_instrumentals": "No instrumentals",
        }
        tooltips = {
            "deep_search": "Deep search: add an audio-focused query fallback",
            "incremental_update": "Incremental update: skip tracks already downloaded",
            "safe_search": "Safe search: reject long sets, live/remix variants, and bad durations",
            "ai_match_enabled": "AI match assist: propose candidates only when local matching is uncertain",
            "generate_m3u": "Generate M3U: write a playlist.m3u8 file",
            "prefix_numbers": "Number files: prefix filenames with 001, 002, ...",
            "strict_match": "Strict matching: require a higher local match score",
            "exclude_instrumentals": "Exclude instrumental versions",
        }
        for cfg_key, btn in self.flag_btns.items():
            enabled = bool(self.config.get(cfg_key, False))
            label_text = labels.get(cfg_key, cfg_key)
            state_label = "ON" if enabled else "OFF"
            btn.setText(f"{label_text}  {state_label}")
            state = "enabled" if enabled else "disabled"
            btn.setToolTip(f"{tooltips.get(cfg_key, label_text)} ({state})")
            btn.setObjectName("flagOn" if enabled else "flagOff")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        fmt = str(self.config.get("output_format_manual", self.config.get("output_format", "mp3")))
        threads = int(self.config.get("concurrency", 3))
        self.format_pill.setText(f"{fmt} · t{threads}")
        self.format_pill.setToolTip(f"Open settings: output format {fmt.upper()}, {threads} thread(s)")

    # ── Settings dialog ────────────────────────────────────────────────────────

    def _open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        values = dlg.get_values()
        api_key = str(values.pop("_ai_api_key", "")).strip()
        slskd_api_key = str(values.pop("_slskd_api_key", "")).strip()
        if api_key and not set_ai_api_key(api_key):
            QMessageBox.warning(
                self,
                "AI key",
                "Could not save the API key in the OS keychain. Check keyring setup.",
            )
        if FEATURE_SOULSEEK_ASSIST and slskd_api_key and not set_slskd_api_key(slskd_api_key):
            QMessageBox.warning(
                self,
                "slskd key",
                "Could not save the slskd API key in the OS keychain. Check keyring setup.",
            )
        self.config.update(values)
        # Update output folder if provided
        if "default_output_dir" in values and values["default_output_dir"]:
            self.output_folder = values["default_output_dir"]
            self._refresh_action_context()
        self._save_config()
        self._refresh_flag_pills()

    # ── Library ────────────────────────────────────────────────────────────────

    def _choose_library_root(self):
        initial = self.library_root or self.output_folder or str(Path.home() / "Music")
        path = QFileDialog.getExistingDirectory(self, "Select Library Root", initial)
        if not path:
            return
        self.library_root = path
        self.config["library_root"] = path
        self.output_folder = path
        self.config["default_output_dir"] = path
        self._save_config()
        self._update_root_label()
        self._refresh_action_context()
        self._update_convert_state()
        self._scan_library_root()

    def _update_root_label(self):
        if hasattr(self, "library_root_lbl"):
            root = self.library_root or ""
            if root:
                p = Path(root)
                short = f"~/{p.relative_to(Path.home())}" if root.startswith(str(Path.home())) else root
                self.library_root_lbl.setText(short)
            else:
                self.library_root_lbl.setText("not set")

    def _scan_library_root(self, show_empty: bool = True, select_playlist_dir: str | None = None):
        root = self.library_root
        if not root or not os.path.isdir(root):
            if show_empty:
                QMessageBox.warning(self, "Library", "Choose a valid library root first.")
            self.library_items = []
            self._refresh_needs_attention()
            self._rebuild_playlist_sidebar()
            return
        self.library_items = scan_library(root)
        self._refresh_needs_attention()
        log.info("Library scan: %s -> %d playlist(s)", root, len(self.library_items))
        self._rebuild_playlist_sidebar()
        selected_after_scan = False
        if select_playlist_dir:
            target_idx = self._library_index_for_playlist_dir(select_playlist_dir)
            if target_idx is not None:
                self._selected_playlist_idx = target_idx
                self._update_playlist_selection()
                self._update_hero()
                self._populate_table_for_selection()
                selected_after_scan = True
        if not selected_after_scan and self.library_items and (
            self._selected_playlist_idx < 0
            or self._selected_playlist_idx >= len(self.library_items)
        ):
            self._selected_playlist_idx = 0
            self._update_playlist_selection()
            self._update_hero()
            self._populate_table_for_selection()
        self._update_library_actions()

    def _refresh_needs_attention(self):
        self._attention_items = collect_attention_items(self.library_items)
        count = len(self._attention_items)
        if not hasattr(self, "needs_attention_btn"):
            return
        self.needs_attention_btn.setText(f"Needs attention · {count}")
        self._restyle(
            self.needs_attention_btn,
            "attentionButtonActive" if count else "attentionButton",
        )
        if count:
            counts = attention_counts(self._attention_items)
            self.needs_attention_btn.setToolTip(
                f"{counts['review']} to review · {counts['failed']} failed · {counts['missing']} missing"
            )
        else:
            self.needs_attention_btn.setToolTip("No failed tracks or missing files")

    def _show_needs_attention(self):
        self._refresh_needs_attention()
        if not self._attention_items:
            QMessageBox.information(
                self,
                "Needs attention",
                "Everything looks good. No failed tracks or missing files were found.",
            )
            return
        dialog = NeedsAttentionDialog(self._attention_items, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        item = dialog.selected_item()
        if not item:
            return
        playlist_idx = self._library_index_for_playlist_dir(str(item.get("playlist_dir") or ""))
        if playlist_idx is None:
            QMessageBox.warning(self, "Needs attention", "The playlist could not be found.")
            return
        self._on_playlist_item_clicked(playlist_idx)
        track_idx = int(item.get("track_idx") or 0)
        row_meta = self._rows.get(track_idx)
        if row_meta:
            row = int(row_meta.get("row") or 0)
            self.table.selectRow(row)
            state_item = self.table.item(row, 4)
            if state_item:
                self.table.scrollToItem(state_item)
        if item.get("kind") in {"failed", "review"} and track_idx in self._errors:
            self._show_error_dialog(track_idx)

    def _start_library_cleanup(self):
        if self._worker or self._load_worker or self._cleanup_worker or self._sync_queue_active:
            QMessageBox.warning(self, "Busy", "Wait for current work to finish.")
            return
        root = self.library_root
        if not root or not os.path.isdir(root):
            QMessageBox.warning(self, "Clean library", "Choose a valid library folder first.")
            return

        self._cleanup_report = None
        self._cleanup_error = ""
        self._set_ui_enabled(False)
        self.footer_bar.show()
        self.global_progress.setRange(0, 0)
        self._set_footer_state("loading", "Analyzing library...")

        self._cleanup_thread = QThread(self)
        self._cleanup_worker = LibraryCleanupWorker(root)
        self._cleanup_worker.moveToThread(self._cleanup_thread)
        self._cleanup_thread.started.connect(self._cleanup_worker.run)
        self._cleanup_worker.done.connect(self._on_cleanup_scan_done)
        self._cleanup_worker.failed.connect(self._on_cleanup_scan_failed)
        self._cleanup_worker.finished.connect(self._cleanup_thread.quit)
        self._cleanup_worker.finished.connect(self._cleanup_worker.deleteLater)
        self._cleanup_thread.finished.connect(self._on_cleanup_scan_finished)
        self._cleanup_thread.start()

    @Slot(object)
    def _on_cleanup_scan_done(self, report_obj: object):
        self._cleanup_report = report_obj if isinstance(report_obj, dict) else None

    @Slot(str)
    def _on_cleanup_scan_failed(self, error_text: str):
        self._cleanup_error = error_text or "Unknown cleanup analysis error."

    @Slot()
    def _on_cleanup_scan_finished(self):
        if self._cleanup_thread:
            self._cleanup_thread.deleteLater()
        self._cleanup_thread = None
        self._cleanup_worker = None
        self.global_progress.setRange(0, 100)
        self.global_progress.setValue(0)
        self._set_ui_enabled(True)
        self._set_footer_state("idle", "idle")

        if self._cleanup_error:
            QMessageBox.critical(self, "Clean library", self._cleanup_error)
            return
        if not self._cleanup_report:
            QMessageBox.warning(self, "Clean library", "The analysis did not return a report.")
            return
        self._present_library_cleanup_report(self._cleanup_report)

    @staticmethod
    def _format_cleanup_size(size_bytes: int) -> str:
        size = max(0, int(size_bytes))
        if size >= 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024 * 1024):.1f} GiB"
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MiB"
        if size >= 1024:
            return f"{size / 1024:.1f} KiB"
        return f"{size} B"

    @classmethod
    def _library_cleanup_summary(cls, report: dict) -> tuple[str, str]:
        orphan_files = list(report.get("orphan_files") or [])
        loose_files = list(report.get("loose_root_files") or [])
        duplicate_entries = sum(
            len(item.get("indexes") or [])
            for item in report.get("duplicate_track_entries") or []
        )
        nested = list(report.get("nested_playlists") or [])
        flattenable = sum(1 for item in nested if item.get("can_flatten"))
        conflicts = len(nested) - flattenable
        shared_copies = int(report.get("exact_duplicate_copies") or 0)
        shared_size = cls._format_cleanup_size(int(report.get("exact_duplicate_bytes") or 0))
        duplicate_sources = len(report.get("duplicate_sources") or [])
        errors = list(report.get("errors") or [])

        headline = (
            f"{cleanup_action_count(report)} safe cleanup action(s) found\n\n"
            f"Orphan audio files: {len(orphan_files)}\n"
            f"Loose files at library root: {len(loose_files)}\n"
            f"Duplicate manifest entries: {duplicate_entries}\n"
            f"Nested playlists ready to flatten: {flattenable}"
        )
        if conflicts:
            headline += f"\nNested playlist conflicts: {conflicts} (manual review)"
        headline += (
            f"\nShared copies kept: {shared_copies} ({shared_size})"
            f"\nDuplicate playlist sources: {duplicate_sources} (manual review)"
        )

        detail_lines: list[str] = []
        for label, paths in (
            ("ORPHAN FILES", orphan_files),
            ("LOOSE ROOT FILES", loose_files),
        ):
            if paths:
                detail_lines.append(label)
                detail_lines.extend(str(path) for path in paths)
                detail_lines.append("")
        if nested:
            detail_lines.append("NESTED PLAYLISTS")
            for item in nested:
                state = "ready" if item.get("can_flatten") else "conflict"
                detail_lines.append(
                    f"[{state}] {item.get('playlist_dir')} -> {item.get('target_dir')}"
                )
            detail_lines.append("")
        if report.get("duplicate_track_entries"):
            detail_lines.append("DUPLICATE MANIFEST ENTRIES")
            for item in report["duplicate_track_entries"]:
                detail_lines.append(
                    f"{item.get('playlist_name')}: {len(item.get('indexes') or [])}"
                )
            detail_lines.append("")
        if errors:
            detail_lines.append("ANALYSIS WARNINGS")
            detail_lines.extend(str(error) for error in errors)
        return headline, "\n".join(detail_lines).strip()

    def _present_library_cleanup_report(self, report: dict):
        headline, details = self._library_cleanup_summary(report)
        action_count = cleanup_action_count(report)
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Clean library")
        dialog.setText(headline)
        if action_count:
            dialog.setInformativeText(
                "Safe items will be moved to a recovery folder inside the library. "
                "Tracks shared by multiple playlists will not be removed."
            )
        else:
            dialog.setInformativeText(
                "No safe automatic cleanup is needed. Shared tracks are expected when they belong to several playlists."
            )
        if details:
            dialog.setDetailedText(details)

        clean_button = None
        if action_count:
            clean_button = dialog.addButton("Clean safe items", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("Cancel" if action_count else "Close", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if clean_button is None or dialog.clickedButton() is not clean_button:
            return

        try:
            result = apply_library_cleanup(report)
        except Exception as exc:
            QMessageBox.critical(self, "Clean library", str(exc))
            return

        self._scan_library_root(show_empty=False)
        moved = int(result.get("moved_files") or 0)
        removed_entries = int(result.get("removed_track_entries") or 0)
        flattened = int(result.get("flattened_playlists") or 0)
        backup_dir = str(result.get("backup_dir") or "")
        errors = list(result.get("errors") or [])
        summary = (
            f"Cleanup complete.\n\n"
            f"Files moved to recovery: {moved}\n"
            f"Duplicate entries removed: {removed_entries}\n"
            f"Playlists flattened: {flattened}"
        )
        if backup_dir:
            summary += f"\n\nRecovery folder:\n{backup_dir}"
        if errors:
            summary += "\n\nWarnings:\n" + "\n".join(str(error) for error in errors[:8])
        QMessageBox.information(self, "Clean library", summary)

    def _library_index_for_playlist_dir(self, playlist_dir: str) -> int | None:
        if not playlist_dir:
            return None
        try:
            wanted = Path(playlist_dir).expanduser().resolve()
        except Exception:
            wanted = Path(playlist_dir).expanduser()
        for i, manifest in enumerate(self.library_items):
            raw = str(manifest.get("playlist_dir") or "").strip()
            if not raw:
                continue
            try:
                current = Path(raw).expanduser().resolve()
            except Exception:
                current = Path(raw).expanduser()
            if current == wanted:
                return i
        return None

    def _update_library_actions(self):
        manifest = self._selected_library_manifest()
        has_selection = manifest is not None
        busy = (
            self._worker is not None
            or self._load_worker is not None
            or self._cleanup_worker is not None
            or self._sync_queue_active
        )
        source = manifest_source(manifest or {})
        syncable = (
            source.get("type") in SYNCABLE_REMOTE_SOURCE_TYPES and bool(source.get("url"))
        ) or (
            source.get("type") == "csv"
            and bool(source.get("url"))
            and os.path.isfile(source.get("url", ""))
        )
        self.sync_btn.setEnabled(has_selection and syncable and not busy)
        if busy:
            self.sync_btn.setToolTip("Sync selected playlist: wait for current work to finish")
        elif not has_selection:
            self.sync_btn.setToolTip("Sync selected playlist: select a library playlist first")
        elif not syncable:
            self.sync_btn.setToolTip("Sync selected playlist: needs a Spotify, SoundCloud, or CSV source")
        else:
            self.sync_btn.setToolTip("Sync selected playlist")
        syncable_count = sum(
            1 for m in self.library_items
            if self._manifest_is_syncable(m)
        )
        self.sync_all_btn.setEnabled(syncable_count > 0 and not busy)
        if busy:
            self.sync_all_btn.setToolTip("Sync all playlists: wait for current work to finish")
        elif syncable_count > 0:
            self.sync_all_btn.setToolTip(f"Sync all {syncable_count} playlists with a saved URL")
        else:
            self.sync_all_btn.setToolTip("Sync all playlists: no playlists with a saved URL")
        self.library_cleanup_btn.setEnabled(bool(self.library_root) and not busy)
        self.needs_attention_btn.setEnabled(bool(self.library_root) and not busy)

    def _manifest_is_syncable(self, manifest: dict) -> bool:
        source = manifest_source(manifest)
        return (
            source.get("type") in SYNCABLE_REMOTE_SOURCE_TYPES and bool(source.get("url"))
        ) or (
            source.get("type") == "csv"
            and bool(source.get("url"))
            and os.path.isfile(source.get("url", ""))
        )

    def _sync_all_library_playlists(self):
        if self._worker or self._load_worker:
            QMessageBox.warning(self, "Busy", "Wait for current work to finish.")
            return
        queue = [m for m in self.library_items if self._manifest_is_syncable(m)]
        if not queue:
            QMessageBox.information(self, "Sync All", "No playlists with a saved URL found.")
            return
        self._sync_queue = queue
        self._sync_queue_total = len(queue)
        self._sync_queue_active = True
        self._sync_queue_cancel_requested = False
        self._sync_queue_results = []
        self._set_footer_state("running", f"sync all · 0 / {self._sync_queue_total}")
        self.footer_bar.show()
        log.info("Sync All: %d playlists queued", self._sync_queue_total)
        self._advance_sync_queue()

    def _advance_sync_queue(self):
        if not self._sync_queue:
            self._finish_sync_queue()
            return
        manifest = self._sync_queue.pop(0)
        remaining = len(self._sync_queue)
        done = self._sync_queue_total - remaining - 1
        self._set_footer_state(
            "running",
            f"sync all · {done + 1} / {self._sync_queue_total} · {manifest.get('playlist_name', '?')}",
        )
        log.info(
            "Sync All: starting %s (%d/%d)",
            manifest.get("playlist_name", "?"),
            done + 1,
            self._sync_queue_total,
        )
        # Auto-select this playlist in the sidebar
        try:
            idx = self.library_items.index(manifest)
            self._selected_playlist_idx = idx
            self._update_playlist_selection()
            self._update_hero()
        except ValueError:
            pass
        source = manifest_source(manifest)
        source_type = source.get("type", "")
        source_url = source.get("url", "")
        output_parent = playlist_output_parent(manifest)
        if not output_parent:
            log.warning("Sync All: skipping %s — no output parent", manifest.get("playlist_name"))
            self._record_sync_queue_result(manifest, "skipped", "missing output parent")
            self._advance_sync_queue()
            return
        self.output_folder = output_parent
        self.config["default_output_dir"] = output_parent
        self._refresh_action_context()
        self._pending_sync_manifest = manifest
        self._sync_target_manifest = manifest
        if source_type in SYNCABLE_REMOTE_SOURCE_TYPES and source_url:
            self._start_source_loader(source_type, source_url)
            return
        if source_type == "csv" and source_url and os.path.isfile(source_url):
            self._load_csv_file(source_url, source_label="library CSV")
            self.loaded_playlist_name = str(
                manifest.get("playlist_name") or source.get("name") or Path(source_url).stem
            )
            self.loaded_source_info = source
            self._pending_sync_manifest = None
            self._sync_target_manifest = manifest
            self._start_conversion()
            return
        log.warning("Sync All: skipping %s — unsupported source type %s", manifest.get("playlist_name"), source_type)
        self._record_sync_queue_result(manifest, "skipped", f"unsupported source type {source_type or '?'}")
        self._pending_sync_manifest = None
        self._sync_target_manifest = None
        self._advance_sync_queue()

    def _record_sync_queue_result(
        self,
        manifest: dict,
        status: str,
        message: str = "",
        error_count: int = 0,
    ):
        name = str(manifest.get("playlist_name") or manifest_source(manifest).get("name") or "?")
        result = {
            "name": name,
            "status": status,
            "message": message,
            "error_count": error_count,
        }
        self._sync_queue_results.append(result)
        detail = f" ({message})" if message else ""
        log.info("Sync All: %s -> %s%s", name, status, detail)

    def _finish_sync_queue(self):
        if not self._sync_queue_active:
            self._scan_library_root(show_empty=False)
            return

        results = list(self._sync_queue_results)
        total = self._sync_queue_total or len(results)
        ok_count = sum(1 for r in results if r.get("status") == "done")
        warning_count = sum(1 for r in results if r.get("status") == "done_with_errors")
        failed_count = sum(1 for r in results if r.get("status") in {"failed", "load_failed", "skipped"})
        cancelled = self._sync_queue_cancel_requested

        self._sync_queue.clear()
        self._sync_queue_total = 0
        self._sync_queue_active = False
        self._sync_queue_cancel_requested = False
        self._pending_sync_manifest = None
        self._sync_target_manifest = None
        self._scan_library_root(show_empty=False)

        summary = (
            f"sync all · {ok_count} ok"
            + (f" · {warning_count} with errors" if warning_count else "")
            + (f" · {failed_count} failed/skipped" if failed_count else "")
        )
        if cancelled:
            self._set_footer_state("cancelled", f"{summary} · cancelled")
            return
        if failed_count or warning_count:
            self._set_footer_state("warning", summary)
        else:
            self._set_footer_state("done", f"sync all · {total} playlist(s)")

    # ── Playlist context menu ──────────────────────────────────────────────────

    @Slot(int)
    def _show_playlist_context_menu(self, idx: int):
        if idx < 0 or idx >= len(self.library_items):
            return
        manifest = self.library_items[idx]
        source = manifest_source(manifest)
        busy = self._worker is not None or self._load_worker is not None or self._sync_queue_active

        menu = QMenu(self)
        if self._manifest_is_syncable(manifest) and not busy:
            menu.addAction("↻  Sync", lambda: self._ctx_sync(manifest))
            menu.addSeparator()
        menu.addAction("✎  Rename", lambda: self._ctx_rename(idx, manifest))
        menu.addAction("Open folder", lambda: self._ctx_open_folder(manifest))
        menu.addSeparator()
        merge_act = menu.addAction("⇄  Merge into…", lambda: self._ctx_merge(idx, manifest))
        merge_act.setEnabled(len(self.library_items) > 1 and not busy)
        menu.addSeparator()
        menu.addAction("Export CSV", lambda: self._ctx_export_csv(manifest))
        menu.addSeparator()
        del_act = menu.addAction("Delete", lambda: self._ctx_delete(idx, manifest))
        del_act.setEnabled(not busy)
        menu.exec(self.cursor().pos())

    def _ctx_sync(self, manifest: dict):
        # Select and sync
        try:
            idx = self.library_items.index(manifest)
            self._selected_playlist_idx = idx
            self._update_playlist_selection()
        except ValueError:
            pass
        self._sync_selected_library_playlist()

    def _ctx_rename(self, idx: int, manifest: dict):
        current = str(manifest.get("playlist_name") or "")
        new_name, ok = QInputDialog.getText(
            self, "Rename playlist", "New name:", text=current
        )
        if not ok or not new_name.strip() or new_name.strip() == current:
            return
        new_name = new_name.strip()
        manifest_file = str(manifest.get("_manifest_path") or "")
        if manifest_file and os.path.isfile(manifest_file):
            try:
                import json as _json
                with open(manifest_file, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                data["playlist_name"] = new_name
                with open(manifest_file, "w", encoding="utf-8") as f:
                    _json.dump(data, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                manifest["playlist_name"] = new_name
                log.info("Renamed playlist to %r", new_name)
            except Exception as e:
                QMessageBox.warning(self, "Rename failed", str(e))
                return
        else:
            manifest["playlist_name"] = new_name
        self._rebuild_playlist_sidebar()
        self._selected_playlist_idx = idx
        self._update_playlist_selection()
        self._update_hero()

    @staticmethod
    def _merge_playlist_audio_files(src_dir: str, dst_dir: str) -> tuple[int, int, list[str]]:
        audio_exts = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".aiff", ".aif", ".opus", ".ogg", ".webm"}
        moved, skipped, errors = 0, 0, []
        for p in Path(src_dir).iterdir():
            if not p.is_file() or p.suffix.lower() not in audio_exts:
                continue
            dst_path = Path(dst_dir) / p.name
            if dst_path.exists():
                skipped += 1
                continue
            try:
                shutil.move(str(p), str(dst_path))
                moved += 1
            except Exception as e:
                errors.append(f"{p.name}: {e}")
        return moved, skipped, errors

    @staticmethod
    def _delete_playlist_folder(playlist_dir: str) -> None:
        shutil.rmtree(playlist_dir)

    @staticmethod
    def _remove_manifest_file(manifest_file: str) -> None:
        path = Path(manifest_file)
        os.remove(path)
        (path.parent / IGNORE_FILENAME).write_text(
            "Removed from Music2MP3 library. Delete this file or resync/reconvert to show it again.\n",
            encoding="utf-8",
        )

    def _ctx_open_folder(self, manifest: dict):
        playlist_dir = str(manifest.get("playlist_dir") or "")
        if playlist_dir and os.path.isdir(playlist_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(playlist_dir))
        else:
            QMessageBox.warning(self, "Open folder", "Playlist folder not found.")

    def _ctx_merge(self, src_idx: int, src_manifest: dict):
        src_dir = str(src_manifest.get("playlist_dir") or "")
        if not src_dir or not os.path.isdir(src_dir):
            QMessageBox.warning(self, "Merge", "Source folder not found.")
            return

        # Build list of other playlists
        targets = [
            (i, m) for i, m in enumerate(self.library_items)
            if i != src_idx and os.path.isdir(str(m.get("playlist_dir") or ""))
        ]
        if not targets:
            QMessageBox.information(self, "Merge", "No other playlists to merge into.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Merge into…")
        dlg.resize(360, 300)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(8)
        lay.addWidget(QLabel(f'Move all files from  "{src_manifest.get("playlist_name")}"  into:'))
        lst = QListWidget()
        lst.setStyleSheet(
            "QListWidget { background:#181818; border:1px solid #2a2a2a;"
            " border-radius:7px; color:#f5f5f5; font-size:12px; }"
            "QListWidget::item:selected { background:#2a2a2a; color:#f5f5f5; }"
        )
        for i, m in targets:
            item = QListWidgetItem(str(m.get("playlist_name") or f"Playlist {i}"))
            item.setData(Qt.ItemDataRole.UserRole, i)
            lst.addItem(item)
        lay.addWidget(lst)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dlg.reject)
        merge_btn = QPushButton("⇄  Merge")
        merge_btn.setObjectName("accent")
        merge_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(merge_btn)
        lay.addLayout(btn_row)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sel = lst.currentItem()
        if not sel:
            return
        dst_idx = sel.data(Qt.ItemDataRole.UserRole)
        dst_manifest = self.library_items[dst_idx]
        dst_dir = str(dst_manifest.get("playlist_dir") or "")

        moved, skipped, errors = self._merge_playlist_audio_files(src_dir, dst_dir)
        if errors:
            QMessageBox.warning(self, "Merge", f"Moved {moved}, skipped {skipped}.\nErrors:\n" + "\n".join(errors[:5]))
        else:
            dst_name = dst_manifest.get("playlist_name") or "target"
            QMessageBox.information(self, "Merge done", f'Moved {moved} file(s) to "{dst_name}".\nSkipped {skipped} duplicate(s).')
        log.info("Merge: moved %d files from %s → %s", moved, src_dir, dst_dir)
        self._scan_library_root(show_empty=False)

    def _ctx_export_csv(self, manifest: dict):
        name = str(manifest.get("playlist_name") or "playlist")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", f"{name}.csv", "CSV files (*.csv)"
        )
        if not path:
            return
        tracks = manifest.get("tracks") or []
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)", "Status", "Format"],
                )
                writer.writeheader()
                for t in tracks:
                    writer.writerow({
                        "Track Name": t.get("title") or "",
                        "Artist Name(s)": t.get("artists") or "",
                        "Album Name": t.get("album") or "",
                        "Duration (ms)": t.get("duration_ms") or "",
                        "Status": t.get("status") or "",
                        "Format": t.get("format") or "",
                    })
            log.info("Exported CSV: %s (%d tracks)", path, len(tracks))
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def _ctx_delete(self, idx: int, manifest: dict):
        name = str(manifest.get("playlist_name") or "this playlist")
        playlist_dir = str(manifest.get("playlist_dir") or "")
        manifest_file = str(manifest.get("_manifest_path") or "")

        dlg = QMessageBox(self)
        dlg.setWindowTitle(f'Delete "{name}"')
        dlg.setText(f'What do you want to delete for "{name}"?')
        dlg.setInformativeText(
            "• Remove from library — keeps your MP3s on disk, just removes the manifest\n"
            "• Delete everything — deletes the playlist folder and all audio files"
        )
        remove_btn = dlg.addButton("Remove from library", QMessageBox.ButtonRole.AcceptRole)
        delete_btn = dlg.addButton("Delete everything", QMessageBox.ButtonRole.DestructiveRole)
        dlg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dlg.exec()
        clicked = dlg.clickedButton()
        if clicked is None or clicked.text() == "Cancel":
            return

        if clicked is delete_btn:
            if not playlist_dir or not os.path.isdir(playlist_dir):
                QMessageBox.warning(self, "Delete", "Playlist folder not found.")
                return
            confirm = QMessageBox.question(
                self, "Confirm delete",
                f'This will permanently delete the folder:\n{playlist_dir}\n\nContinue?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
            try:
                self._delete_playlist_folder(playlist_dir)
                log.info("Deleted playlist folder: %s", playlist_dir)
            except Exception as e:
                QMessageBox.critical(self, "Delete failed", str(e))
                return
        else:
            # Remove from library = delete manifest only
            if manifest_file and os.path.isfile(manifest_file):
                try:
                    self._remove_manifest_file(manifest_file)
                    log.info("Removed manifest: %s", manifest_file)
                except Exception as e:
                    QMessageBox.critical(self, "Delete failed", str(e))
                    return

        # Deselect if this was selected
        if self._selected_playlist_idx == idx:
            self._selected_playlist_idx = -1
        self._scan_library_root(show_empty=False)

    def _sync_selected_library_playlist(self):
        manifest = self._selected_library_manifest()
        if not manifest:
            QMessageBox.warning(self, "Library", "Select a library playlist first.")
            return
        if self._worker or self._load_worker:
            QMessageBox.warning(self, "Busy", "Wait for current work to finish.")
            return
        source = manifest_source(manifest)
        source_type = source.get("type", "")
        source_url = source.get("url", "")
        output_parent = playlist_output_parent(manifest)
        if not output_parent:
            QMessageBox.warning(self, "Library", "Manifest does not contain a valid playlist folder.")
            return
        self.output_folder = output_parent
        self.config["default_output_dir"] = output_parent
        self._refresh_action_context()
        self._append_to_library_manifest = None
        self._pending_sync_manifest = manifest
        self._sync_target_manifest = manifest
        if source_type in SYNCABLE_REMOTE_SOURCE_TYPES and source_url:
            self._start_source_loader(source_type, source_url)
            return
        if source_type == "csv" and source_url and os.path.isfile(source_url):
            self._load_csv_file(source_url, source_label="library CSV")
            self.loaded_playlist_name = str(
                manifest.get("playlist_name") or source.get("name") or Path(source_url).stem
            )
            self.loaded_source_info = source
            self._pending_sync_manifest = None
            self._sync_target_manifest = manifest
            self._start_conversion()
            return
        self._pending_sync_manifest = None
        self._sync_target_manifest = None
        QMessageBox.warning(self, "Library", "This playlist source cannot be synced yet.")

    # ── Conversion ─────────────────────────────────────────────────────────────

    def _start_conversion(self):
        if self._load_worker:
            QMessageBox.warning(self, "Busy", "Wait for source loading to finish.")
            return
        if not (self.csv_path and self.output_folder):
            QMessageBox.warning(self, "Conversion", "Select source and output folder first.")
            return

        # Apply config from flag pills / settings
        self._save_config()

        self._clear_download_rows()
        self._errors.clear()
        self._total_tracks = 0
        self._was_cancelled = False
        self.global_progress.setRange(0, 100)
        self.global_progress.setValue(0)
        self._started_at = time.time()
        self._timer.start(1000)
        self._set_ui_enabled(False)
        self.convert_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._restyle(self.stop_btn, "dangerActive")  # stop is now the primary action
        self.footer_bar.show()
        self._set_footer_state("running", "running · 0 / ?")
        self.footer_eta_lbl.setText("")

        worker_config = self.config.copy()
        playlist_hint = self.loaded_playlist_name
        sync_manifest = self._sync_target_manifest
        if sync_manifest:
            playlist_dir = str(sync_manifest.get("playlist_dir") or "").strip()
            if playlist_dir:
                self.output_folder = playlist_dir
                playlist_hint = None
                self.loaded_playlist_name = str(sync_manifest.get("playlist_name") or self.loaded_playlist_name or "")
                source = manifest_source(sync_manifest)
                if source.get("type") and source.get("url"):
                    self.loaded_source_info = source
                worker_config["sync_existing_playlist"] = True
        if self._append_to_library_manifest:
            worker_config["append_to_existing_playlist"] = True
            playlist_hint = None

        self._thread = QThread(self)
        self._worker = ConverterWorker(
            worker_config,
            self.csv_path,
            self.output_folder,
            playlist_hint,
            self.loaded_source_info,
        )
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
    def _on_status(self, text: str):
        if self._worker:
            prefix = self._sync_queue_status_prefix()
            self.footer_status_lbl.setText((prefix + text)[:80])

    @Slot(str, object)
    def _on_item(self, ev: str, data_obj: object):
        data = data_obj if isinstance(data_obj, dict) else {}

        if ev == "conv_init":
            total = int(data.get("new", data.get("total", 0)))
            self._total_tracks = total
            self._perc.clear()
            self.global_progress.setRange(0, max(1, total * 100))
            self.global_progress.setValue(0)
            self._set_footer_state("running", f"running · 0 / {total}")
            return

        if ev == "cancel_all":
            self._was_cancelled = True
            self._set_footer_state("cancelled", "cancelled")
            self._mark_inflight_rows_cancelled()
            return

        if ev == "init":
            idx = int(data.get("idx", 0))
            raw_title = str(data.get("title", f"Track {idx}"))
            artist, title = "", raw_title
            if " - " in raw_title:
                parts = raw_title.split(" - ", 1)
                artist, title = parts[0].strip(), parts[1].strip()
            self._ensure_row(idx, title, artist)
            self._set_row_state(idx, "queued")
            fmt = str(data.get("format", "")).strip()
            if fmt:
                self._set_row_format(idx, fmt)
            return

        if ev == "progress":
            idx = int(data.get("idx", 0))
            pct = float(data.get("percent", 0.0))
            self._set_row_progress(idx, pct)
            self._set_row_state(idx, "downloading")
            done_count = sum(1 for r in self._rows.values() if r.get("state") == "done")
            self._set_footer_state("running", f"running · {done_count} / {self._total_tracks}")
            return

        if ev == "match":
            idx = int(data.get("idx", 0))
            score = data.get("score")
            if isinstance(score, (int, float)):
                self._set_row_match_score(
                    idx,
                    float(score),
                    title=str(data.get("title") or ""),
                    channel=str(data.get("channel") or ""),
                    url=str(data.get("url") or ""),
                    score_details=data.get("score_details") if isinstance(data.get("score_details"), dict) else {},
                    ai_confidence=data.get("ai_confidence"),
                    ai_reason=str(data.get("ai_reason") or ""),
                )
            return

        if ev == "converting":
            idx = int(data.get("idx", 0))
            self._set_row_state(idx, "converting")
            return

        if ev == "done":
            idx = int(data.get("idx", 0))
            fmt = str(data.get("format", "")).strip()
            audio_path = str(data.get("path") or "").strip()
            file_name = str(data.get("file") or "").strip()
            if not audio_path and file_name:
                base_dir = self.last_output_dir or self.output_folder or ""
                if base_dir:
                    audio_path = str(Path(base_dir) / file_name)
            self._set_row_state(idx, "done")
            if fmt:
                self._set_row_format(idx, fmt)
            if audio_path:
                self._set_row_audio_path(idx, audio_path)
            self._set_row_progress(idx, 100.0)
            done_count = sum(1 for r in self._rows.values() if r.get("state") == "done")
            self._set_footer_state("running", f"running · {done_count} / {self._total_tracks}")
            return

        if ev == "error":
            idx = int(data.get("idx", 0))
            msg = str(data.get("message", "Unknown error"))
            best_url = str(data.get("best_url") or "").strip()
            track_t = data.get("track") or {}
            out_dir = str(data.get("out_dir") or "").strip()
            self._set_row_state(idx, "failed")
            self._set_row_progress(idx, 100.0)
            self._set_row_error(idx, msg, best_url=best_url, track_t=track_t, out_dir=out_dir)
            return

    @Slot(str)
    def _on_done(self, out_dir: str):
        sync_manifest = self._sync_target_manifest
        appended_to_library = self._append_to_library_manifest is not None
        self.last_output_dir = out_dir
        self._refresh_action_context()
        elapsed = int(time.time() - self._started_at) if self._started_at else 0
        self._timer.stop()
        self.footer_eta_lbl.setText(f"total {self._format_duration(elapsed)}")
        if self._total_tracks > 0:
            self.global_progress.setValue(self._total_tracks * 100)
        if self._was_cancelled:
            self._set_footer_state("cancelled", "cancelled")
        elif self._errors:
            self._set_footer_state("warning", f"done · {len(self._errors)} error(s)")
        else:
            self._set_footer_state("done", f"done · {self._total_tracks} tracks")
        if sync_manifest or appended_to_library:
            self._session_playlist = None
            self._selected_playlist_idx = self._library_index_for_manifest(
                sync_manifest or self._append_to_library_manifest
            )
        else:
            self._session_playlist = None
            self._selected_playlist_idx = -1
        if self._sync_queue_active and sync_manifest:
            if self._was_cancelled:
                self._record_sync_queue_result(sync_manifest, "cancelled", "stopped by user")
            elif self._errors:
                self._record_sync_queue_result(
                    sync_manifest,
                    "done_with_errors",
                    f"{len(self._errors)} track error(s)",
                    error_count=len(self._errors),
                )
            else:
                self._record_sync_queue_result(sync_manifest, "done")
        self._scan_library_root(show_empty=False, select_playlist_dir=out_dir)

    @Slot(str)
    def _on_failed(self, error_text: str):
        self._timer.stop()
        self._set_footer_state("error", "failed")
        if self._sync_queue_active and self._sync_target_manifest:
            self._record_sync_queue_result(self._sync_target_manifest, "failed", error_text)
            self._set_footer_state("warning", "sync all · conversion failed · continuing")
        else:
            QMessageBox.critical(self, "Conversion error", error_text)

    def _on_worker_finished(self):
        sync_was_active = self._sync_target_manifest is not None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None
        self._worker = None
        self._sync_target_manifest = None
        self._restyle(self.stop_btn, "danger")  # restore normal stop style
        self._set_ui_enabled(True)
        self.stop_btn.setEnabled(False)
        self._update_convert_state()
        if sync_was_active and self._sync_queue_active:
            self._advance_sync_queue()

    def _stop_conversion(self):
        if self._worker:
            if self._sync_queue_active:
                self._sync_queue_cancel_requested = True
                self._sync_queue.clear()  # abort any pending sync-all queue
            else:
                self._sync_queue.clear()
                self._sync_queue_total = 0
            self._worker.stop()
            self._restyle(self.stop_btn, "danger")
            self._set_footer_state("cancelled", "sync all · cancelling..." if self._sync_queue_active else "cancelling...")
            self.stop_btn.setEnabled(False)

    # ── Table helpers ──────────────────────────────────────────────────────────

    def _ensure_row(self, idx: int, title: str, artist: str = ""):
        if idx in self._rows:
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, 46)

        n_item = QTableWidgetItem(f"{idx:02d}")
        n_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        n_item.setForeground(QColor(232, 244, 255, 90))
        f = QFont("SF Mono, Menlo, Courier New", 11)
        f.setStyleHint(QFont.StyleHint.Monospace)
        n_item.setFont(f)
        self.table.setItem(row, 0, n_item)

        cell = TrackCellWidget(title, artist)
        self.table.setCellWidget(row, 1, cell)

        fmt_item = QTableWidgetItem("—")
        fmt_item.setForeground(QColor("#9aa8ba"))
        fmt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 2, fmt_item)

        match_item = QTableWidgetItem("—")
        match_item.setForeground(QColor("#9aa8ba"))
        match_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 3, match_item)

        state_item = QTableWidgetItem("○ queued")
        state_item.setForeground(QColor("#9aa8ba"))
        self.table.setItem(row, 4, state_item)

        self._rows[idx] = {"row": row, "state": "queued"}

    def _set_row_audio_path(self, idx: int, path: str):
        row = self._rows.get(idx)
        if not row:
            return
        row["audio_path"] = path
        for col in (1, 4):
            item = self.table.item(row["row"], col)
            if item:
                item.setToolTip(f"Double-click to play:\n{path}")
        cell = self.table.cellWidget(row["row"], 1)
        if cell:
            cell.setToolTip(f"Double-click to play:\n{path}")

    def _set_row_state(self, idx: int, state: str):
        row = self._rows.get(idx)
        if not row:
            return
        item = self.table.item(row["row"], 4)
        if not item:
            return
        states = {
            "queued":      ("○ queued",       "#9aa8ba"),
            "downloading": ("↓ {pct}%",       "#3be477"),
            "converting":  ("↺ converting",   "#f5b942"),
            "done":        ("● done",         "#1ed760"),
            "skipped":     ("↷ skipped",      "#9aa8ba"),
            "failed":      ("✕ failed",       "#e85d75"),
            "cancelled":   ("■ cancelled",    "#9aa8ba"),
        }
        template, color = states.get(state, states["queued"])
        pct = int(self._perc.get(idx, 0))
        text = template.replace("{pct}", str(pct))
        item.setText(text)
        item.setForeground(QColor(color))
        row["state"] = state

    def _set_row_format(self, idx: int, fmt: str):
        row = self._rows.get(idx)
        if not row:
            return
        item = self.table.item(row["row"], 2)
        if not item:
            return
        value = fmt.strip().lower() or "—"
        item.setText(value)
        item.setForeground(QColor("#f5f5f5") if value != "—" else QColor("#9aa8ba"))

    def _set_row_progress(self, idx: int, pct: float):
        p = max(0.0, min(100.0, pct))
        self._perc[idx] = p
        if self._total_tracks:
            total = int(sum(self._perc.values()))
            self.global_progress.setValue(total)
        # Refresh state text to show updated percentage
        row = self._rows.get(idx)
        if row and row.get("state") == "downloading":
            item = self.table.item(row["row"], 4)
            if item:
                item.setText(f"↓ {int(p)}%")

    def _set_row_match_score(
        self,
        idx: int,
        score: float,
        *,
        title: str = "",
        channel: str = "",
        url: str = "",
        score_details: dict | None = None,
        ai_confidence=None,
        ai_reason: str = "",
    ):
        row = self._rows.get(idx)
        if not row:
            return
        item = self.table.item(row["row"], 3)
        if not item:
            return
        v = max(0.0, min(1.0, score))
        item.setText(f"{v * 100:.0f}")
        if v >= 0.85:
            item.setForeground(QColor("#1ed760"))
        elif v >= 0.70:
            item.setForeground(QColor("#f5f5f5"))
        elif v >= 0.58:
            item.setForeground(QColor("#f5b942"))
        else:
            item.setForeground(QColor("#e85d75"))
        details = score_details or {}
        tooltip = [f"Match score: {v * 100:.0f}%"]
        if title:
            tooltip.append(f"Candidate: {title}")
        if channel:
            tooltip.append(f"Channel: {channel}")
        if url:
            tooltip.append(f"URL: {url}")
        if details:
            tooltip.extend([
                "",
                "Score details:",
                f"- title ratio: {float(details.get('title_ratio', 0.0)) * 100:.0f}%",
                f"- title coverage: {float(details.get('title_coverage', 0.0)) * 100:.0f}%",
                f"- artist: {float(details.get('artist_score', 0.0)) * 100:.0f}%",
                f"- duration: {float(details.get('duration_score', 0.0)) * 100:.0f}%",
                f"- bonus: {float(details.get('bonus', 0.0)):.2f}",
                f"- penalties: {float(details.get('penalties', 0.0)):.2f}",
            ])
        if isinstance(ai_confidence, (int, float)):
            item.setText(f"{v * 100:.0f} AI")
            tooltip.extend(["", f"AI impact: accepted with {float(ai_confidence) * 100:.0f}% confidence"])
            if ai_reason:
                tooltip.append(f"AI reason: {ai_reason}")
        item.setToolTip("\n".join(tooltip))
        row["match_detail"] = {
            "score": v,
            "title": title,
            "channel": channel,
            "url": url,
            "score_details": details,
            "ai_confidence": ai_confidence if isinstance(ai_confidence, (int, float)) else None,
            "ai_reason": ai_reason,
        }

    def _set_row_error(self, idx: int, msg: str, *, best_url: str = "", track_t: dict | None = None, out_dir: str = ""):
        row = self._rows.get(idx)
        if not row:
            return
        log.error("Track %d failed: %s", idx, msg)
        item = self.table.item(row["row"], 4)
        if item:
            first_line = msg.split("\n")[0].strip()[:72]
            item.setText(f"✕ {first_line}")
            item.setToolTip(f"{msg[:3000]}\n\nClick here for full details")
        t_item = self.table.item(row["row"], 0)
        if t_item:
            t_item.setToolTip("Click the status cell for error details")
        cell_widget = self.table.cellWidget(row["row"], 1)
        if cell_widget:
            cell_widget.setToolTip("Click the status cell for error details")
        title_text = ""
        tw = self.table.cellWidget(row["row"], 1)
        if tw:
            lbl = tw.findChild(QLabel)
            title_text = lbl.text() if lbl else f"Track {idx}"
        self._errors[idx] = (title_text or f"Track {idx}", msg, best_url or "", track_t or {}, out_dir or "")

    def _show_error_dialog(self, idx: int):
        error_data = self._errors.get(idx, (f"Track {idx}", "No details.", "", {}, ""))
        title, msg, best_url, track_t, out_dir = error_data
        is_ai_proposal = "AI suggested candidate" in msg

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Match failed — {title}")
        dlg.resize(700, 460)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # ── Rejection reason ──
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(msg)
        txt.setStyleSheet(
            "QTextEdit { background:#181818; color:#e85d75;"
            " font-family:'SF Mono','Menlo','Courier New',monospace;"
            " font-size:11px; border:1px solid #4a2b32; border-radius:7px; }"
        )
        layout.addWidget(txt)

        # ── Best candidate link (if available) ──
        if best_url:
            link_row = QHBoxLayout()
            link_lbl = QLabel("AI proposal" if is_ai_proposal else "Best candidate")
            link_lbl.setObjectName("kicker")
            link_row.addWidget(link_lbl)
            link_row.addSpacing(6)
            url_lbl = QLabel(f'<a href="{best_url}" style="color:#1ed760;">{best_url}</a>')
            url_lbl.setOpenExternalLinks(True)
            url_lbl.setTextFormat(Qt.TextFormat.RichText)
            url_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            link_row.addWidget(url_lbl)
            link_row.addStretch()
            open_btn = QPushButton("Open in browser")
            open_btn.setObjectName("ghost")
            open_btn.setFixedHeight(28)
            open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(best_url)))
            link_row.addWidget(open_btn)
            layout.addLayout(link_row)

        # ── Custom URL input ──
        url_sep = QLabel("Validate URL" if is_ai_proposal else "Use another URL")
        url_sep.setObjectName("kicker")
        layout.addWidget(url_sep)
        url_row = QHBoxLayout()
        url_input = QLineEdit()
        url_input.setPlaceholderText("Paste a YouTube URL to download instead…")
        if best_url:
            url_input.setText(best_url)
        url_input.setStyleSheet(
            "QLineEdit { background:#181818; border:1px solid #3a3a3a;"
            " border-radius:7px; padding:4px 8px; color:#f5f5f5; font-size:12px; }"
            "QLineEdit:focus { border-color:#1ed760; }"
        )
        url_row.addWidget(url_input)
        retry_btn = QPushButton("Validate + Download" if is_ai_proposal else "Download")
        retry_btn.setObjectName("accent")
        retry_btn.setFixedHeight(32)
        retry_btn.setMinimumWidth(110)
        retry_btn.setEnabled(bool(best_url or track_t))
        url_input.textChanged.connect(lambda t: retry_btn.setEnabled(bool(t.strip())))

        def _do_retry():
            chosen_url = url_input.text().strip()
            if not chosen_url:
                return
            dlg.accept()
            self._retry_single_track(idx, chosen_url, track_t, out_dir)

        retry_btn.clicked.connect(_do_retry)
        url_row.addWidget(retry_btn)
        layout.addLayout(url_row)

        # ── Bottom row ──
        btn_row = QHBoxLayout()
        if track_t and FEATURE_SOULSEEK_ASSIST:
            soulseek_btn = QPushButton("Search Soulseek")
            soulseek_btn.setObjectName("ghost")
            soulseek_btn.setToolTip("Search this track via configured slskd server")
            soulseek_btn.clicked.connect(lambda: self._open_soulseek_search_dialog(track_t))
            btn_row.addWidget(soulseek_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        dlg.exec()

    def _open_soulseek_search_dialog(self, track_t: dict):
        if not FEATURE_SOULSEEK_ASSIST:
            QMessageBox.information(self, "Soulseek", "Soulseek assist is parked in backlog for now.")
            return
        try:
            client = build_slskd_client(self.config)
        except Exception as e:
            QMessageBox.critical(self, "Soulseek setup failed", str(e))
            return
        if not client:
            QMessageBox.warning(
                self,
                "Soulseek",
                "Enable slskd in Settings and save a slskd API key first.",
            )
            return
        query = self._soulseek_query_from_track(track_t)
        if not query:
            QMessageBox.warning(self, "Soulseek", "No search query available for this track.")
            return
        try:
            results = client.search_audio(
                query,
                limit=int(self.config.get("slskd_result_limit", 12)),
                timeout_ms=int(self.config.get("slskd_search_timeout_ms", 8000)),
            )
        except Exception as e:
            QMessageBox.critical(self, "Soulseek search failed", str(e))
            return
        if not results:
            QMessageBox.information(self, "Soulseek", f"No slskd results for:\n{query}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Soulseek results — {query}")
        dlg.resize(760, 460)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        kicker = QLabel("Soulseek results")
        kicker.setObjectName("kicker")
        layout.addWidget(kicker)

        result_list = QListWidget()
        result_list.setStyleSheet(
            "QListWidget { background:#181818; color:#f5f5f5;"
            " border:1px solid #2a2a2a; border-radius:7px; }"
            "QListWidget::item { padding:8px; border-bottom:1px solid #242424; }"
            "QListWidget::item:selected { background:#2a2a2a; }"
        )
        for result in results:
            item = QListWidgetItem(format_slskd_result(result))
            item.setToolTip(result.filename)
            result_list.addItem(item)
        result_list.setCurrentRow(0)
        layout.addWidget(result_list, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        open_btn = QPushButton("Open slskd")
        open_btn.setObjectName("ghost")
        open_btn.setToolTip("Open the slskd web interface")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(str(self.config.get("slskd_host") or ""))))
        btn_row.addWidget(open_btn)

        enqueue_btn = QPushButton("Enqueue selected")
        enqueue_btn.setObjectName("accent")
        enqueue_btn.setToolTip("Ask slskd to download the selected result")

        def _enqueue_selected():
            row = result_list.currentRow()
            if row < 0 or row >= len(results):
                return
            try:
                client.enqueue(results[row])
            except Exception as e:
                QMessageBox.critical(dlg, "Soulseek enqueue failed", str(e))
                return
            QMessageBox.information(dlg, "Soulseek", "Result enqueued in slskd.")

        enqueue_btn.clicked.connect(_enqueue_selected)
        btn_row.addWidget(enqueue_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        dlg.exec()

    @staticmethod
    def _soulseek_query_from_track(track_t: dict) -> str:
        title = str(track_t.get("title") or track_t.get("Track Name") or "").strip()
        artists = track_t.get("artists") or track_t.get("Artist Name(s)") or ""
        if isinstance(artists, list):
            artist_text = " ".join(str(a) for a in artists if a)
        else:
            artist_text = str(artists)
        parts = [artist_text.strip(), title]
        return " ".join(part for part in parts if part).strip()

    def _retry_single_track(self, idx: int, url: str, track_t: dict, out_dir: str):
        if self._worker:
            QMessageBox.warning(self, "Busy", "Wait for current conversion to finish before retrying.")
            return
        if not out_dir or not os.path.isdir(out_dir):
            # Try to fall back to last known output dir
            out_dir = self.last_output_dir or self.output_folder or ""
        if not out_dir:
            QMessageBox.warning(self, "Retry", "Cannot determine output folder for this track.")
            return

        # Build a single-row CSV with the chosen URL as Source URL
        fd, tmp_csv = tempfile.mkstemp(prefix="retry_track_", suffix=".csv")
        os.close(fd)
        try:
            with open(tmp_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "Track Name", "Artist Name(s)", "Album Name",
                        "Duration (ms)", "Source URL", "Track URI",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "Track Name": str(track_t.get("title") or f"Track {idx}"),
                    "Artist Name(s)": str(track_t.get("artists") or ""),
                    "Album Name": str(track_t.get("album") or ""),
                    "Duration (ms)": str(track_t.get("duration_ms") or ""),
                    "Source URL": url,
                    "Track URI": str(track_t.get("track_uri") or ""),
                })
        except Exception as e:
            log.error("Retry: failed to create temp CSV: %s", e)
            QMessageBox.critical(self, "Retry error", str(e))
            return

        # Reset the row to downloading state
        self._set_row_state(idx, "queued")
        self._set_row_progress(idx, 0.0)
        if idx in self._errors:
            del self._errors[idx]

        retry_config = self.config.copy()
        retry_config["incremental_update"] = False
        retry_config["append_to_existing_playlist"] = True
        # Use out_dir directly as output folder with no playlist subdirectory
        self._thread = QThread(self)
        self._worker = ConverterWorker(
            retry_config,
            tmp_csv,
            out_dir,          # output_folder = the already-named playlist dir
            None,             # playlist_hint = None so no subdir is created
            self.loaded_source_info,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.status.connect(self._on_status)
        self._worker.item.connect(lambda ev, data, target_idx=idx: self._on_retry_item(target_idx, ev, data))
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_worker_finished)
        self._restyle(self.stop_btn, "dangerActive")
        self.stop_btn.setEnabled(True)
        self._set_ui_enabled(False)
        self._started_at = time.time()
        self._timer.start(1000)
        self._thread.start()
        log.info("Retry track %d with URL: %s", idx, url)

    def _on_retry_item(self, target_idx: int, ev: str, data_obj: object):
        if isinstance(data_obj, dict):
            data = dict(data_obj)
            if "idx" in data:
                data["idx"] = target_idx
        else:
            data = data_obj
        self._on_item(ev, data)

    @Slot(int, int)
    def _on_table_cell_clicked(self, row: int, col: int):
        if col == 3:
            for idx, meta in self._rows.items():
                if meta["row"] == row and meta.get("match_detail"):
                    self._show_match_detail_dialog(idx)
                    return
        if col != 4:
            return
        for idx, meta in self._rows.items():
            if meta["row"] == row and meta.get("state") == "failed":
                self._show_error_dialog(idx)
                return

    def _show_match_detail_dialog(self, idx: int):
        detail = (self._rows.get(idx) or {}).get("match_detail")
        if not isinstance(detail, dict):
            return
        parts = [
            f"Track #{idx}",
            "",
            f"Score: {float(detail.get('score') or 0.0) * 100:.0f}%",
        ]
        if detail.get("title"):
            parts.append(f"Candidate: {detail['title']}")
        if detail.get("channel"):
            parts.append(f"Channel: {detail['channel']}")
        if detail.get("url"):
            parts.append(f"URL: {detail['url']}")
        score_details = detail.get("score_details")
        if isinstance(score_details, dict):
            parts.extend([
                "",
                "Score details",
                f"- Title ratio: {float(score_details.get('title_ratio', 0.0)) * 100:.0f}%",
                f"- Title coverage: {float(score_details.get('title_coverage', 0.0)) * 100:.0f}%",
                f"- Artist: {float(score_details.get('artist_score', 0.0)) * 100:.0f}%",
                f"- Duration: {float(score_details.get('duration_score', 0.0)) * 100:.0f}%",
                f"- Bonus: {float(score_details.get('bonus', 0.0)):.2f}",
                f"- Penalties: {float(score_details.get('penalties', 0.0)):.2f}",
            ])
        if isinstance(detail.get("ai_confidence"), (int, float)):
            parts.extend([
                "",
                f"AI impact: accepted with {float(detail['ai_confidence']) * 100:.0f}% confidence",
            ])
            if detail.get("ai_reason"):
                parts.append(f"AI reason: {detail['ai_reason']}")
        QMessageBox.information(self, "Match score details", "\n".join(parts))

    def _on_table_double_click(self, row: int, _col: int):
        for idx, meta in self._rows.items():
            if meta["row"] != row:
                continue
            if meta.get("state") == "failed":
                self._show_error_dialog(idx)
                return
            if self._open_row_audio(idx):
                return

    def _open_row_audio(self, idx: int) -> bool:
        meta = self._rows.get(idx) or {}
        path = str(meta.get("audio_path") or "").strip()
        if not path or not os.path.isfile(path):
            return False
        if platform.system() == "Darwin":
            if self._open_audio_in_macos_player(path, "Music") or self._open_audio_in_macos_player(path, "iTunes"):
                return True
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        log.info("Open audio file: %s%s", path, "" if ok else " (failed)")
        if not ok:
            QMessageBox.warning(self, "Open track", f"Could not open:\n{path}")
        return ok

    def _open_audio_in_macos_player(self, path: str, app_name: str) -> bool:
        try:
            subprocess.run(["open", "-a", app_name, path], check=True, timeout=5)
            subprocess.Popen([
                "osascript",
                "-e", f'tell application "{app_name}" to activate',
                "-e", f'tell application "{app_name}" to play',
            ])
            log.info("Open and play in %s: %s", app_name, path)
            return True
        except Exception:
            log.info("Could not open in %s: %s", app_name, path)
            return False

    def _mark_inflight_rows_cancelled(self):
        for idx, row in self._rows.items():
            if row.get("state") not in {"done", "skipped", "failed", "cancelled"}:
                self._set_row_state(idx, "cancelled")

    def _clear_download_rows(self):
        self.table.setRowCount(0)
        self._rows.clear()
        self._perc.clear()

    # ── Footer ─────────────────────────────────────────────────────────────────

    def _set_footer_state(self, state: str, status_text: str):
        dot_colors = {
            "idle":      "#6b7280",
            "loading":   "#1ed760",
            "running":   "#1ed760",
            "done":      "#1ed760",
            "warning":   "#f5b942",
            "cancelled": "#9aa8ba",
            "error":     "#e85d75",
        }
        color = dot_colors.get(state, dot_colors["idle"])
        self._footer_dot.setStyleSheet(f"border-radius:4px; background:{color};")
        self.footer_status_lbl.setText(status_text)
        if state == "idle":
            self.footer_bar.hide()
        else:
            self.footer_bar.show()

    # ── Config / persistence ───────────────────────────────────────────────────

    def _load_from_config(self):
        if self.output_folder and os.path.isdir(self.output_folder):
            self._refresh_action_context()
        if self.library_root and os.path.isdir(self.library_root):
            self._update_root_label()
            self._scan_library_root(show_empty=False)
        self._refresh_flag_pills()
        self._update_hero()

    def _save_config(self):
        try:
            cfg_dir = os.path.dirname(CONFIG_FILE)
            if cfg_dir:
                os.makedirs(cfg_dir, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception:
            log.exception("Failed to save config to %s", CONFIG_FILE)

    def _refresh_action_context(self):
        if not hasattr(self, "action_output_lbl"):
            return
        p = self.output_folder or ""
        if p:
            try:
                short = f"~/{Path(p).relative_to(Path.home())}"
            except ValueError:
                short = p
            self.action_output_lbl.setText(short)
            tip = f"Output root: {p}\nNew playlists are saved as subfolders inside this folder."
            if self.last_output_dir:
                tip = f"Last output: {self.last_output_dir}\n{tip}"
            self.action_output_lbl.setToolTip(tip)
        else:
            self.action_output_lbl.setText("Choose output folder")
            self.action_output_lbl.setToolTip("Choose output root folder")

    def _choose_output_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", str(Path.home() / "Downloads")
        )
        if not path:
            return
        self.output_folder = path
        self.config["default_output_dir"] = path
        self.library_root = path
        self.config["library_root"] = path
        self._save_config()
        self._update_root_label()
        self._refresh_action_context()
        self._scan_library_root(show_empty=False)
        self._update_convert_state()

    def _open_output_folder(self):
        target = self.last_output_dir or self.output_folder
        if not _open_folder(target):
            QMessageBox.warning(self, "Open Folder", "No valid folder to open.")

    def _update_convert_state(self):
        ok = bool(self.csv_path and os.path.isfile(self.csv_path) and self.output_folder)
        busy = (
            self._worker is not None
            or self._load_worker is not None
            or self._cleanup_worker is not None
            or self._sync_queue_active
        )
        self.convert_btn.setEnabled(ok and not busy)
        self._update_library_actions()

    @staticmethod
    def _restyle(btn: QPushButton, name: str):
        btn.setObjectName(name)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _set_ui_enabled(self, enabled: bool):
        for btn in (
            self.add_spotify_btn, self.add_soundcloud_btn, self.add_bandcamp_btn,
            self.add_soulseek_btn, self.add_csv_btn, self.add_scan_btn,
            self.library_scan_btn, self.library_cleanup_btn, self.needs_attention_btn,
            self.library_choose_btn,
        ):
            btn.setEnabled(enabled)
        if not FEATURE_BANDCAMP_SOURCE:
            self.add_bandcamp_btn.setEnabled(False)
        if not FEATURE_SOULSEEK_ASSIST:
            self.add_soulseek_btn.setEnabled(False)
        for btn in self.flag_btns.values():
            btn.setEnabled(enabled)
        self.format_pill.setEnabled(enabled)
        if enabled:
            self._update_library_actions()
        else:
            self.sync_btn.setEnabled(False)
            self.sync_all_btn.setEnabled(False)

    # ── Timer ──────────────────────────────────────────────────────────────────

    def _tick_timer(self):
        if self._load_started_at:
            elapsed = int(time.time() - self._load_started_at)
            self.footer_eta_lbl.setText(f"loading {self._format_duration(elapsed)}")
            return
        if not self._started_at:
            return
        elapsed = int(time.time() - self._started_at)
        self.footer_eta_lbl.setText(f"elapsed {self._format_duration(elapsed)}")

    @staticmethod
    def _format_duration(sec: int) -> str:
        h, rem = divmod(int(sec), 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    # ── Drag & drop ────────────────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if self._worker or self._load_worker:
            event.ignore()
            return
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".csv") and os.path.isfile(path):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".csv") and os.path.isfile(path):
                self._load_csv_file(path, source_label="dropped file")
                event.acceptProposedAction()
                return
        event.ignore()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyle(VisibleCheckStyle(app.style()))
    app.setStyleSheet(APP_QSS)
    w = QtMusic2MP3Window()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
