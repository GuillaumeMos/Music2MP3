"""
Qt frontend (PySide6) for Music2MP3 — Cyberpunk redesign.
"""

from __future__ import annotations

import hashlib
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
from library_manifest import manifest_source, playlist_output_parent, scan_library
from soundcloud_api import SoundCloudClient
from spotify_api import SpotifyClient
from spotify_auth import PKCEAuth
from token_store import RefreshTokenStore

try:
    from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
    from PySide6.QtGui import (
        QColor, QPainter, QPen, QBrush,
        QLinearGradient, QRadialGradient, QFont,
    )
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QDialog,
        QFileDialog, QFrame, QGridLayout, QHBoxLayout,
        QHeaderView, QLabel, QLineEdit, QMainWindow,
        QMessageBox, QPushButton, QProgressBar, QProxyStyle,
        QScrollArea, QSizePolicy, QSpinBox, QStyle,
        QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    )
except ImportError as e:
    print("PySide6 is required. Install with: pip install PySide6")
    raise


APP_QSS = """
QWidget {
  font-family: "SF Pro Text", "Segoe UI", "Inter", "Arial";
  font-size: 13px;
  color: #e8f4ff;
  outline: none;
}
QMainWindow, QDialog { background: #06070d; }

QFrame#topBar {
  background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
      stop:0 rgba(255,0,110,16), stop:1 rgba(0,245,255,14));
  border-bottom: 1px solid rgba(0,245,255,30);
}
QFrame#brandMark {
  background: #06070d;
  border: 1px solid #00f5ff;
  border-radius: 6px;
}
QLabel#brandTitle {
  color: #e8f4ff; font-size: 15px; font-weight: 700; letter-spacing: 0.5px;
}
QLabel#brandSub {
  color: rgba(0,245,255,140); font-size: 10px; letter-spacing: 1px;
}
QLabel#chip {
  color: #4fe6bf;
  background: rgba(79,230,191,22);
  border: 1px solid rgba(79,230,191,80);
  border-radius: 4px;
  padding: 4px 10px;
  font-size: 11px;
  letter-spacing: 0.8px;
}

QFrame#sidebar {
  background: #03040a;
  border-right: 1px solid rgba(0,245,255,26);
}
QFrame#rootDirBox {
  background: rgba(0,245,255,10);
  border: 1px solid rgba(0,245,255,38);
  border-radius: 4px;
}

QPushButton#sourceTile {
  background: rgba(255,255,255,8);
  border: 1px solid rgba(232,244,255,28);
  border-radius: 4px;
  color: rgba(232,244,255,178);
  padding: 9px 4px;
  font-size: 11px;
  font-weight: 600;
}
QPushButton#sourceTile:hover {
  background: rgba(0,245,255,18);
  border-color: rgba(0,245,255,110);
  color: #00f5ff;
}
QPushButton#sourceTile:disabled {
  background: rgba(255,255,255,4);
  color: rgba(232,244,255,60);
}

QFrame#hero {
  background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
      stop:0 rgba(255,0,110,82), stop:0.45 rgba(123,0,255,46), stop:1 rgba(0,245,255,56));
  border-bottom: 1px solid rgba(0,245,255,40);
}
QFrame#heroCover {
  background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ff006e, stop:1 #00f5ff);
  border-radius: 4px;
  border: 1px solid rgba(232,244,255,50);
}
QLabel#heroSource {
  color: #00f5ff; font-size: 10px; font-weight: 700; letter-spacing: 1.8px;
}
QLabel#heroTitle {
  color: #e8f4ff; font-size: 32px; font-weight: 500; letter-spacing: -0.5px;
}
QLabel#heroMeta {
  color: rgba(232,244,255,185); font-size: 11px; letter-spacing: 0.8px;
}

QFrame#actionBar {
  background: rgba(0,0,0,120);
  border-bottom: 1px solid rgba(0,245,255,26);
}
QFrame#flagsBar {
  background: rgba(0,0,0,80);
  border-bottom: 1px solid rgba(0,245,255,20);
}
QFrame#footerBar {
  background: rgba(0,0,0,190);
  border-top: 1px solid rgba(0,245,255,38);
}

QPushButton {
  border: 1px solid rgba(232,244,255,34);
  border-radius: 4px;
  background: rgba(255,255,255,8);
  color: rgba(232,244,255,205);
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 600;
}
QPushButton:hover {
  background: rgba(0,245,255,18);
  border-color: rgba(0,245,255,90);
  color: #00f5ff;
}
QPushButton#accent {
  background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ff006e, stop:1 #00f5ff);
  color: white;
  border: none;
  letter-spacing: 1px;
}
QPushButton#accent:hover { border: 1px solid rgba(0,245,255,160); }
QPushButton#accent:disabled {
  background: rgba(255,255,255,18);
  color: rgba(232,244,255,80);
}
QPushButton#danger {
  background: rgba(255,0,110,22);
  color: #ff4d9e;
  border: 1px solid rgba(255,0,110,100);
  letter-spacing: 1px;
}
QPushButton#danger:hover { background: rgba(255,0,110,40); }
QPushButton#danger:disabled {
  background: transparent;
  color: rgba(255,77,158,80);
  border-color: rgba(255,0,110,35);
}
QPushButton#ghost {
  background: transparent;
  border: 1px solid rgba(232,244,255,20);
  color: rgba(232,244,255,160);
  letter-spacing: 1px;
}
QPushButton#ghost:hover {
  background: rgba(0,245,255,14);
  border-color: rgba(0,245,255,70);
  color: #00f5ff;
}
QPushButton#flagOff {
  background: rgba(255,255,255,6);
  border: 1px solid rgba(232,244,255,22);
  border-radius: 3px;
  color: rgba(232,244,255,100);
  padding: 3px 9px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.6px;
}
QPushButton#flagOn {
  background: rgba(0,245,255,16);
  border: 1px solid rgba(0,245,255,100);
  border-radius: 3px;
  color: #00f5ff;
  padding: 3px 9px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.6px;
}
QPushButton#flagOff:hover, QPushButton#flagOn:hover {
  background: rgba(0,245,255,24);
  border-color: rgba(0,245,255,140);
  color: #00f5ff;
}
QPushButton#flagOff:disabled, QPushButton#flagOn:disabled {
  opacity: 0.4;
}
QPushButton#formatPill {
  background: rgba(255,0,110,18);
  border: 1px solid rgba(255,0,110,70);
  border-radius: 3px;
  color: #ff4d9e;
  padding: 3px 9px;
  font-size: 10px;
  font-weight: 600;
}
QPushButton#formatPill:hover {
  background: rgba(255,0,110,32);
  border-color: rgba(255,0,110,120);
}

QLabel#kicker {
  color: rgba(0,245,255,140);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1.5px;
}
QLabel#muted { color: rgba(232,244,255,130); font-size: 11px; }
QLabel#outputPath { color: rgba(232,244,255,120); font-size: 11px; }
QLabel#footerStatus {
  color: #ff4d9e; font-size: 11px; letter-spacing: 1px; font-weight: 600;
}
QLabel#footerEta {
  color: #00f5ff; font-size: 11px;
  font-family: "SF Mono", "Menlo", "Courier New", monospace;
  letter-spacing: 0.8px;
}

QTableWidget {
  background: #03040a;
  color: #e8f4ff;
  border: none;
  gridline-color: rgba(232,244,255,14);
  selection-background-color: rgba(255,0,110,55);
  selection-color: #e8f4ff;
  outline: none;
}
QHeaderView::section {
  background: #06070d;
  color: rgba(0,245,255,130);
  border: none;
  border-bottom: 1px solid rgba(0,245,255,28);
  padding: 7px 16px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1.5px;
}
QTableWidget::item {
  border-bottom: 1px solid rgba(232,244,255,10);
}
QTableWidget::item:selected { background: rgba(255,0,110,50); }

QScrollBar:vertical {
  background: transparent; width: 6px; margin: 0;
}
QScrollBar::handle:vertical {
  background: rgba(0,245,255,55); border-radius: 3px; min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: rgba(0,245,255,110); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
  background: transparent; height: 6px;
}
QScrollBar::handle:horizontal {
  background: rgba(0,245,255,55); border-radius: 3px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QProgressBar {
  border: none; border-radius: 2px;
  background: rgba(232,244,255,14);
  min-height: 3px; max-height: 3px;
}
QProgressBar::chunk {
  border-radius: 2px;
  background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #ff006e, stop:1 #00f5ff);
}

QLineEdit, QComboBox, QSpinBox {
  border: 1px solid rgba(0,245,255,48);
  border-radius: 4px;
  background: rgba(3,4,10,210);
  color: #e8f4ff;
  padding: 7px 10px;
  selection-background-color: #ff006e;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
  border-color: #00f5ff;
  background: #06070d;
}
QComboBox::drop-down { border-left: 1px solid rgba(0,245,255,44); width: 22px; }
QComboBox QAbstractItemView {
  background: #06070d; color: #e8f4ff;
  border: 1px solid rgba(0,245,255,90);
  selection-background-color: rgba(255,0,110,100);
  outline: 0;
}
QCheckBox { spacing: 8px; color: rgba(232,244,255,205); }
QCheckBox::indicator { width: 16px; height: 16px; }
"""


class VisibleCheckStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            return super().drawPrimitive(element, option, painter, widget)
        rect = option.rect.adjusted(0, 0, -1, -1)
        checked = bool(option.state & QStyle.StateFlag.State_On)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        border = QColor("#35556b")
        fill = QColor("#03040a")
        if checked:
            border = QColor("#00f5ff"); fill = QColor("#ff006e")
        elif hovered:
            border = QColor("#00f5ff")
        if not enabled:
            border = QColor("#2a3441"); fill = QColor("#06070d")
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


# ── Workers (unchanged logic) ──────────────────────────────────────────────────

class ConverterWorker(QObject):
    status = Signal(str)
    progress = Signal(int, int)
    item = Signal(str, object)
    done = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, config, csv_path, output_folder, playlist_hint, source_info=None):
        super().__init__()
        self._config = config
        self._csv_path = csv_path
        self._output_folder = output_folder
        self._playlist_hint = playlist_hint
        self._source_info = source_info
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
            out_dir = conv.convert_from_csv(
                self._csv_path, self._output_folder,
                self._playlist_hint, source_info=self._source_info,
            )
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
                raise RuntimeError(f"Unsupported mode: {self.mode}")
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
        tmp = self._write_temp_csv(rows, ["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)"], "spotify_playlist_")
        return {"csv_path": tmp, "playlist_name": name or "SpotifyPlaylist", "count": len(rows),
                "source": "Spotify", "source_type": "spotify", "source_url": self.url}

    def _load_soundcloud(self) -> dict:
        self.status.emit("Fetching playlist from SoundCloud...")
        sc = SoundCloudClient()
        cookies_path = self.config.get("cookies_path")
        rows, name = sc.fetch_playlist(self.url, cookies_path=cookies_path)
        tmp = self._write_temp_csv(
            rows,
            ["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)", "Source URL", "Track URI"],
            "soundcloud_playlist_",
        )
        return {"csv_path": tmp, "playlist_name": name or "SoundCloud", "count": len(rows),
                "source": "SoundCloud", "source_type": "soundcloud", "source_url": self.url}

    @staticmethod
    def _write_temp_csv(rows, fieldnames, prefix) -> str:
        fd, tmp = tempfile.mkstemp(prefix=prefix, suffix=".csv")
        os.close(fd)
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return tmp


# ── UI Components ──────────────────────────────────────────────────────────────

class ArtworkWidget(QWidget):
    """Gradient square whose colors are deterministically derived from a name."""

    def __init__(self, name: str, size: int = 32, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        h = hashlib.md5(name.encode("utf-8", errors="replace")).hexdigest()
        hue1 = int(h[:4], 16) % 360
        hue2 = (hue1 + 130 + int(h[4:8], 16) % 90) % 360
        self._c1 = QColor.fromHsv(hue1, 200, 210)
        self._c2 = QColor.fromHsv(hue2, 220, 180)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0.0, 0.0, float(self.width()), float(self.height()))
        grad.setColorAt(0.0, self._c1)
        grad.setColorAt(1.0, self._c2)
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 3.0, 3.0)
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
            "font-size:13px; font-weight:500; color:#e8f4ff; background:transparent;"
        )
        self._artist_lbl = QLabel(artist or "")
        self._artist_lbl.setStyleSheet(
            "font-size:11px; color:rgba(232,244,255,0.45); background:transparent;"
        )
        layout.addWidget(self._title_lbl)
        if artist:
            layout.addWidget(self._artist_lbl)
        self.setStyleSheet("background:transparent;")


class PlaylistItemWidget(QFrame):
    """One playlist entry in the sidebar."""

    item_clicked = Signal(int)

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
            "font-size:13px; font-weight:500; color:#e8f4ff; background:transparent;"
        )
        self._name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        source_text = (f"{count} · {source_type}" if count else source_type).upper()
        self._meta_lbl = QLabel(source_text)
        self._meta_lbl.setStyleSheet(
            "font-size:10px; color:rgba(0,245,255,0.5); letter-spacing:0.6px; background:transparent;"
        )
        text.addWidget(self._name_lbl)
        text.addWidget(self._meta_lbl)
        outer.addLayout(text, 1)

        self.setSelected(False)

    def setSelected(self, selected: bool):
        if selected:
            self.setStyleSheet(
                "QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 rgba(255,0,110,46),stop:1 rgba(255,0,110,8));"
                "border:1px solid #ff006e; border-radius:4px; }"
            )
            self._indicator.setStyleSheet("background:#ff006e; border-radius:1px;")
            self._name_lbl.setStyleSheet(
                "font-size:13px; font-weight:500; color:#ff4d9e; background:transparent;"
            )
            self._meta_lbl.setStyleSheet(
                "font-size:10px; color:rgba(255,77,158,0.8); letter-spacing:0.6px; background:transparent;"
            )
        else:
            self.setStyleSheet(
                "QFrame { background:transparent; border:1px solid transparent; border-radius:4px; }"
                "QFrame:hover { background:rgba(0,245,255,0.04); border:1px solid rgba(0,245,255,0.06); }"
            )
            self._indicator.setStyleSheet("background:transparent; border-radius:1px;")
            self._name_lbl.setStyleSheet(
                "font-size:13px; font-weight:500; color:#e8f4ff; background:transparent;"
            )
            self._meta_lbl.setStyleSheet(
                "font-size:10px; color:rgba(0,245,255,0.5); letter-spacing:0.6px; background:transparent;"
            )

    def mousePressEvent(self, event):
        self.item_clicked.emit(self._index)
        super().mousePressEvent(event)


class HeroWidget(QFrame):
    """Hero header with painted grid overlay and radial orbs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hero")
        self.setFixedHeight(152)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Grid
        grid_pen = QPen(QColor(0, 245, 255, 13))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        step = 32
        for x in range(0, w + step, step):
            painter.drawLine(x, 0, x, h)
        for y in range(0, h + step, step):
            painter.drawLine(0, y, w, y)

        # Orb 1 — top-right magenta
        painter.setPen(Qt.PenStyle.NoPen)
        orb1 = QRadialGradient(float(w - 30), -50.0, 200.0)
        orb1.setColorAt(0.0, QColor(255, 0, 110, 90))
        orb1.setColorAt(1.0, QColor(255, 0, 110, 0))
        painter.setBrush(QBrush(orb1))
        painter.drawEllipse(w - 230, -150, 400, 400)

        # Orb 2 — bottom-left cyan
        orb2 = QRadialGradient(180.0, float(h + 80), 200.0)
        orb2.setColorAt(0.0, QColor(0, 245, 255, 72))
        orb2.setColorAt(1.0, QColor(0, 245, 255, 0))
        painter.setBrush(QBrush(orb2))
        painter.drawEllipse(-20, h - 20, 400, 400)

        painter.end()


class AddSourceDialog(QDialog):
    """Minimal modal for entering a playlist URL."""

    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        titles = {"spotify": "Add Spotify Playlist", "soundcloud": "Add SoundCloud Playlist"}
        self.setWindowTitle(titles.get(mode, "Add Source"))
        self.setMinimumWidth(460)
        self.setStyleSheet("background:#06070d;")
        self._url = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        kicker = QLabel(f"// add_{mode}_source")
        kicker.setObjectName("kicker")
        layout.addWidget(kicker)

        placeholders = {
            "spotify": "https://open.spotify.com/playlist/...",
            "soundcloud": "https://soundcloud.com/.../sets/...",
        }
        lbl_texts = {"spotify": "Spotify playlist URL", "soundcloud": "SoundCloud playlist URL"}
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
        self.setStyleSheet("background:#06070d;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        kicker = QLabel("// settings")
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

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:rgba(0,245,255,0.12);")
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
        sep2.setStyleSheet("background:rgba(0,245,255,0.12);")
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
        }
        for key, cb in self.checks.items():
            values[key] = cb.isChecked()
        return values


# ── Main window ────────────────────────────────────────────────────────────────

class QtMusic2MP3Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Music2MP3")
        self.resize(1160, 800)
        self.setMinimumSize(900, 600)

        self.config = load_config()
        self.csv_path: str | None = None
        self.output_folder: str | None = self.config.get("default_output_dir")
        self.last_output_dir: str | None = None
        self.loaded_playlist_name: str | None = None
        self.loaded_source_info: dict | None = None
        self.library_root: str | None = (
            self.config.get("library_root") or self.config.get("default_output_dir")
        )
        self.library_items: list[dict] = []
        self._pending_sync_manifest: dict | None = None
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

        # Sidebar playlist items
        self._playlist_item_widgets: list[PlaylistItemWidget] = []
        self._selected_playlist_idx: int = -1  # -1 = session, 0+ = library_items

        # Session playlist entry (freshly loaded from Spotify/SC/CSV)
        self._session_playlist: dict | None = None

        self._build_ui()
        self.setAcceptDrops(True)
        self._load_from_config()
        self._update_convert_state()

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
        mark_lbl.setStyleSheet("color:#00f5ff; font-weight:800; font-size:11px;")
        mark_inner.addWidget(mark_lbl)
        header.addWidget(mark)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(0)
        brand_title = QLabel("MUSIC<span style='color:#FF006E'>2</span>MP3")
        brand_title.setObjectName("brandTitle")
        brand_title.setTextFormat(Qt.TextFormat.RichText)
        brand_sub = QLabel("// dj_ready.export")
        brand_sub.setObjectName("brandSub")
        brand_col.addWidget(brand_title)
        brand_col.addWidget(brand_sub)
        header.addLayout(brand_col)
        header.addStretch()

        self.online_chip = QLabel("online")
        self.online_chip.setObjectName("chip")
        header.addWidget(self.online_chip)

        self.logs_btn = QPushButton("logs")
        self.logs_btn.setObjectName("ghost")
        self.logs_btn.setEnabled(False)
        header.addWidget(self.logs_btn)

        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("ghost")
        settings_btn.setFixedSize(34, 34)
        settings_btn.setStyleSheet("padding:0; font-size:16px;")
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

        add_kicker = QLabel("// add_source")
        add_kicker.setObjectName("kicker")
        sb.addWidget(add_kicker)
        sb.addSpacing(8)

        add_grid = QGridLayout()
        add_grid.setHorizontalSpacing(6)
        add_grid.setVerticalSpacing(6)
        self.add_spotify_btn = QPushButton("Spotify")
        self.add_soundcloud_btn = QPushButton("SoundCloud")
        self.add_csv_btn = QPushButton("CSV file")
        self.add_scan_btn = QPushButton("Local scan")
        for btn in (self.add_spotify_btn, self.add_soundcloud_btn,
                    self.add_csv_btn, self.add_scan_btn):
            btn.setObjectName("sourceTile")
            btn.setMinimumHeight(44)
        self.add_spotify_btn.clicked.connect(self._on_add_spotify)
        self.add_soundcloud_btn.clicked.connect(self._on_add_soundcloud)
        self.add_csv_btn.clicked.connect(self._on_add_csv)
        self.add_scan_btn.clicked.connect(self._scan_library_root)
        add_grid.addWidget(self.add_spotify_btn, 0, 0)
        add_grid.addWidget(self.add_soundcloud_btn, 0, 1)
        add_grid.addWidget(self.add_csv_btn, 1, 0)
        add_grid.addWidget(self.add_scan_btn, 1, 1)
        sb.addLayout(add_grid)
        sb.addSpacing(14)

        sep1 = QFrame()
        sep1.setFixedHeight(1)
        sep1.setStyleSheet("background:rgba(0,245,255,0.1);")
        sb.addWidget(sep1)
        sb.addSpacing(10)

        lib_hdr = QHBoxLayout()
        lib_kicker = QLabel("// library")
        lib_kicker.setObjectName("kicker")
        lib_hdr.addWidget(lib_kicker)
        lib_hdr.addStretch()
        self.library_scan_btn = QPushButton("↻")
        self.library_scan_btn.setObjectName("ghost")
        self.library_scan_btn.setFixedSize(22, 22)
        self.library_scan_btn.setStyleSheet("padding:0; font-size:13px; color:rgba(0,245,255,0.55);")
        self.library_scan_btn.setToolTip("Scan library root")
        self.library_scan_btn.clicked.connect(self._scan_library_root)
        lib_hdr.addWidget(self.library_scan_btn)
        sb.addLayout(lib_hdr)
        sb.addSpacing(6)

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
        rk = QLabel("// root_dir")
        rk.setObjectName("kicker")
        root_box_layout.addWidget(rk)
        rp_row = QHBoxLayout()
        self.library_root_lbl = QLabel("not set")
        self.library_root_lbl.setStyleSheet(
            "font-size:11px; font-family:'SF Mono','Menlo',monospace;"
            " color:rgba(232,244,255,0.75); background:transparent;"
        )
        self.library_root_lbl.setTextFormat(Qt.TextFormat.PlainText)
        rp_row.addWidget(self.library_root_lbl, 1)
        self.library_choose_btn = QPushButton("…")
        self.library_choose_btn.setObjectName("ghost")
        self.library_choose_btn.setFixedSize(22, 22)
        self.library_choose_btn.setStyleSheet("padding:0; font-size:14px;")
        self.library_choose_btn.clicked.connect(self._choose_library_root)
        rp_row.addWidget(self.library_choose_btn)
        root_box_layout.addLayout(rp_row)
        sb.addWidget(root_box)

        body.addWidget(sidebar)

        # ── Workspace ────────────────────────────────────────────────────────
        workspace = QWidget()
        workspace.setStyleSheet("background:#06070d;")
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
        cover_icon.setStyleSheet("color:#ffffff; font-size:40px; font-weight:800; background:transparent;")
        cover_inner.addWidget(cover_icon)
        hero_layout.addWidget(self.hero_cover)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(5)
        self.hero_source_label = QLabel("// source_pending")
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

        self.convert_btn = QPushButton("▸  Convert")
        self.convert_btn.setObjectName("accent")
        self.convert_btn.setMinimumWidth(136)
        self.convert_btn.setFixedHeight(36)
        self.convert_btn.clicked.connect(self._start_conversion)
        action_layout.addWidget(self.convert_btn)

        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setMinimumWidth(90)
        self.stop_btn.setFixedHeight(36)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_conversion)
        action_layout.addWidget(self.stop_btn)

        self.sync_btn = QPushButton("↻  Sync")
        self.sync_btn.setObjectName("ghost")
        self.sync_btn.setMinimumWidth(80)
        self.sync_btn.setFixedHeight(36)
        self.sync_btn.clicked.connect(self._sync_selected_library_playlist)
        action_layout.addWidget(self.sync_btn)

        action_layout.addStretch()

        self.action_output_lbl = QLabel("→ no output folder")
        self.action_output_lbl.setObjectName("outputPath")
        self.action_output_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_output_lbl.mousePressEvent = lambda _e: self._choose_output_folder()
        action_layout.addWidget(self.action_output_lbl)

        open_out_btn = QPushButton("⤢")
        open_out_btn.setObjectName("ghost")
        open_out_btn.setFixedSize(34, 34)
        open_out_btn.setStyleSheet("padding:0; font-size:15px;")
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

        flags_kicker = QLabel("// flags")
        flags_kicker.setObjectName("kicker")
        flags_layout.addWidget(flags_kicker)
        flags_layout.addSpacing(4)

        self.flag_btns: dict[str, QPushButton] = {}
        for cfg_key, label in [
            ("deep_search", "deep"),
            ("incremental_update", "incremental"),
            ("safe_search", "safe"),
            ("generate_m3u", "m3u"),
            ("prefix_numbers", "numbered"),
            ("strict_match", "strict"),
            ("exclude_instrumentals", "no_instrumental"),
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
        self.table.setHorizontalHeaderLabels(["#", "TRACK", "FORMAT", "MATCH", "STATE"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
        self.csv_path = path
        self.loaded_playlist_name = Path(path).stem
        self.loaded_source_info = {"type": "csv", "url": path, "name": Path(path).stem}
        self._session_playlist = {
            "name": Path(path).stem,
            "source_type": "csv",
            "count": 0,
        }
        self._rebuild_playlist_sidebar()
        self._selected_playlist_idx = -1
        self._update_playlist_selection()
        self._update_convert_state()
        self._update_hero()
        self._set_footer_state("idle", "ready")

    # ── Source loader ──────────────────────────────────────────────────────────

    def _start_source_loader(self, mode: str, url: str):
        self._set_footer_state("loading", f"Loading from {mode.title()}...")
        self.footer_bar.show()
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

    @Slot(str)
    def _on_source_status(self, text: str):
        self.footer_status_lbl.setText(text)

    @Slot(object)
    def _on_source_loaded(self, payload_obj: object):
        payload = payload_obj if isinstance(payload_obj, dict) else {}
        csv_path = str(payload.get("csv_path", "")).strip()
        if not csv_path or not os.path.isfile(csv_path):
            QMessageBox.warning(self, "Source", "Source loaded but no CSV was produced.")
            return
        self.csv_path = csv_path
        self.loaded_playlist_name = str(payload.get("playlist_name") or "").strip() or None
        source = str(payload.get("source", "Source"))
        self.loaded_source_info = {
            "type": str(payload.get("source_type") or source).strip().lower(),
            "url": str(payload.get("source_url") or "").strip(),
            "name": self.loaded_playlist_name or "",
        }
        count = int(payload.get("count", 0))
        self._session_playlist = {
            "name": self.loaded_playlist_name or "Playlist",
            "source_type": str(payload.get("source_type") or source).strip().lower(),
            "count": count,
        }
        self._rebuild_playlist_sidebar()
        self._selected_playlist_idx = -1
        self._update_playlist_selection()
        self._update_hero()
        self._update_convert_state()
        self._set_footer_state("idle", f"Loaded: {self.loaded_playlist_name} · {count} tracks")

    @Slot(str)
    def _on_source_failed(self, error_text: str):
        QMessageBox.critical(self, "Source loading error", error_text)
        self._set_footer_state("error", "Source loading failed")

    def _on_source_loader_finished(self):
        if self._load_thread:
            self._load_thread.deleteLater()
            self._load_thread = None
        self._load_worker = None
        self._set_ui_enabled(True)
        self._update_convert_state()
        if self._pending_sync_manifest and self.csv_path and self.output_folder and not self._worker:
            manifest = self._pending_sync_manifest
            self._pending_sync_manifest = None
            source = manifest_source(manifest)
            self.loaded_playlist_name = str(
                manifest.get("playlist_name") or source.get("name") or self.loaded_playlist_name or ""
            )
            self.loaded_source_info = source
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
        self._update_convert_state()
        self._update_library_actions()

    def _selected_library_manifest(self) -> dict | None:
        idx = self._selected_playlist_idx
        if idx < 0:
            return None
        if idx >= len(self.library_items):
            return None
        return self.library_items[idx]

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
            self.hero_source_label.setText(f"// {source_type}_playlist")
            self.hero_title_label.setText(title)
            self.hero_meta_label.setText(
                f"{count} tracks  ▸  {source_type}  ▸  {state}"
            )
            return

        if self._selected_playlist_idx == -1 and self._session_playlist:
            sp = self._session_playlist
            src = str(sp.get("source_type") or "csv").lower()
            self.hero_source_label.setText(f"// {src}_playlist")
            self.hero_title_label.setText(sp["name"])
            count = sp.get("count", 0)
            self.hero_meta_label.setText(
                f"{count} tracks  ▸  {src}  ▸  ready to convert"
            )
            return

        if self.loaded_playlist_name or self.csv_path:
            title = self.loaded_playlist_name or Path(self.csv_path or "").stem or "CSV loaded"
            source = self.loaded_source_info or {}
            src_type = str(source.get("type") or "csv").lower()
            self.hero_source_label.setText(f"// {src_type}_source")
            self.hero_title_label.setText(title)
            self.hero_meta_label.setText("ready  ▸  source loaded  ▸  choose destination")
            return

        self.hero_source_label.setText("// source_pending")
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
            "deep_search": "deep",
            "incremental_update": "incremental",
            "safe_search": "safe",
            "generate_m3u": "m3u",
            "prefix_numbers": "numbered",
            "strict_match": "strict",
            "exclude_instrumentals": "no_instrumental",
        }
        for cfg_key, btn in self.flag_btns.items():
            enabled = bool(self.config.get(cfg_key, False))
            label_text = labels.get(cfg_key, cfg_key)
            btn.setText(f"[x] {label_text}" if enabled else f"[ ] {label_text}")
            btn.setObjectName("flagOn" if enabled else "flagOff")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        fmt = str(self.config.get("output_format_manual", self.config.get("output_format", "mp3")))
        threads = int(self.config.get("concurrency", 3))
        self.format_pill.setText(f"{fmt} · t{threads}")

    # ── Settings dialog ────────────────────────────────────────────────────────

    def _open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        values = dlg.get_values()
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
        self._save_config()
        self._update_root_label()
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

    def _scan_library_root(self, show_empty: bool = True):
        root = self.library_root
        if not root or not os.path.isdir(root):
            if show_empty:
                QMessageBox.warning(self, "Library", "Choose a valid library root first.")
            self.library_items = []
            self._rebuild_playlist_sidebar()
            return
        self.library_items = scan_library(root)
        self._rebuild_playlist_sidebar()
        if self.library_items:
            # Auto-select first library item if nothing is selected
            if self._selected_playlist_idx >= 0:
                self._update_playlist_selection()
        self._update_library_actions()

    def _update_library_actions(self):
        manifest = self._selected_library_manifest()
        has_selection = manifest is not None
        busy = self._worker is not None or self._load_worker is not None
        source = manifest_source(manifest or {})
        syncable = (
            source.get("type") in {"spotify", "soundcloud"} and bool(source.get("url"))
        ) or (
            source.get("type") == "csv"
            and bool(source.get("url"))
            and os.path.isfile(source.get("url", ""))
        )
        self.sync_btn.setEnabled(has_selection and syncable and not busy)
        if has_selection and not syncable:
            self.sync_btn.setToolTip("Sync needs a Spotify, SoundCloud, or CSV source.")
        else:
            self.sync_btn.setToolTip("")

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
        self._pending_sync_manifest = manifest
        if source_type in {"spotify", "soundcloud"} and source_url:
            self._start_source_loader(source_type, source_url)
            return
        if source_type == "csv" and source_url and os.path.isfile(source_url):
            self._load_csv_file(source_url, source_label="library CSV")
            self.loaded_playlist_name = str(
                manifest.get("playlist_name") or source.get("name") or Path(source_url).stem
            )
            self.loaded_source_info = source
            self._pending_sync_manifest = None
            self._start_conversion()
            return
        self._pending_sync_manifest = None
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
        self.footer_bar.show()
        self._set_footer_state("running", "running · 0 / ?")
        self.footer_eta_lbl.setText("")

        self._thread = QThread(self)
        self._worker = ConverterWorker(
            self.config.copy(),
            self.csv_path,
            self.output_folder,
            self.loaded_playlist_name,
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
            self.footer_status_lbl.setText(text[:60])

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
                self._set_row_match_score(idx, float(score))
            return

        if ev == "converting":
            idx = int(data.get("idx", 0))
            self._set_row_state(idx, "converting")
            return

        if ev == "done":
            idx = int(data.get("idx", 0))
            fmt = str(data.get("format", "")).strip()
            self._set_row_state(idx, "done")
            if fmt:
                self._set_row_format(idx, fmt)
            self._set_row_progress(idx, 100.0)
            done_count = sum(1 for r in self._rows.values() if r.get("state") == "done")
            self._set_footer_state("running", f"running · {done_count} / {self._total_tracks}")
            return

        if ev == "error":
            idx = int(data.get("idx", 0))
            msg = str(data.get("message", "Unknown error"))
            self._set_row_state(idx, "failed")
            self._set_row_progress(idx, 100.0)
            self._set_row_error(idx, msg)
            return

    @Slot(str)
    def _on_done(self, out_dir: str):
        self.last_output_dir = out_dir
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
        self._scan_library_root(show_empty=False)

    @Slot(str)
    def _on_failed(self, error_text: str):
        self._timer.stop()
        self._set_footer_state("error", "failed")
        QMessageBox.critical(self, "Conversion error", error_text)

    def _on_worker_finished(self):
        if self._thread:
            self._thread.deleteLater()
            self._thread = None
        self._worker = None
        self._set_ui_enabled(True)
        self.stop_btn.setEnabled(False)
        self._update_convert_state()

    def _stop_conversion(self):
        if self._worker:
            self._worker.stop()
            self._set_footer_state("cancelled", "cancelling...")
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

    def _set_row_state(self, idx: int, state: str):
        row = self._rows.get(idx)
        if not row:
            return
        item = self.table.item(row["row"], 4)
        if not item:
            return
        states = {
            "queued":      ("○ queued",       "#9aa8ba"),
            "downloading": ("↓ {pct}%",       "#ff4d9e"),
            "converting":  ("↺ converting",   "#ffc857"),
            "done":        ("● done",         "#4fe6bf"),
            "failed":      ("✕ failed",       "#ff3355"),
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
        item.setForeground(QColor("#e8f4ff") if value != "—" else QColor("#9aa8ba"))

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

    def _set_row_match_score(self, idx: int, score: float):
        row = self._rows.get(idx)
        if not row:
            return
        item = self.table.item(row["row"], 3)
        if not item:
            return
        v = max(0.0, min(1.0, score))
        item.setText(f"{v * 100:.0f}")
        if v >= 0.85:
            item.setForeground(QColor("#4fe6bf"))
        elif v >= 0.70:
            item.setForeground(QColor("#00f5ff"))
        elif v >= 0.58:
            item.setForeground(QColor("#ffc857"))
        else:
            item.setForeground(QColor("#ff4d9e"))

    def _set_row_error(self, idx: int, msg: str):
        row = self._rows.get(idx)
        if not row:
            return
        item = self.table.item(row["row"], 4)
        if item:
            item.setToolTip(msg[:3000])
        t_item = self.table.item(row["row"], 1)
        title_text = t_item.text() if t_item else f"Track {idx}"
        self._errors[idx] = (title_text, msg)

    def _mark_inflight_rows_cancelled(self):
        for idx, row in self._rows.items():
            if row.get("state") not in {"done", "failed", "cancelled"}:
                self._set_row_state(idx, "cancelled")

    def _clear_download_rows(self):
        self.table.setRowCount(0)
        self._rows.clear()
        self._perc.clear()

    # ── Footer ─────────────────────────────────────────────────────────────────

    def _set_footer_state(self, state: str, status_text: str):
        dot_colors = {
            "idle":      "#6b7280",
            "loading":   "#00f5ff",
            "running":   "#ff006e",
            "done":      "#4fe6bf",
            "warning":   "#ffc857",
            "cancelled": "#9aa8ba",
            "error":     "#ff3355",
        }
        color = dot_colors.get(state, dot_colors["idle"])
        self._footer_dot.setStyleSheet(f"border-radius:4px; background:{color};")
        self.footer_status_lbl.setText(status_text.upper())
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
            pass

    def _refresh_action_context(self):
        if not hasattr(self, "action_output_lbl"):
            return
        p = self.output_folder or ""
        if p:
            try:
                short = f"~/{Path(p).relative_to(Path.home())}"
            except ValueError:
                short = p
            self.action_output_lbl.setText(f"→ {short}")
        else:
            self.action_output_lbl.setText("→ no output folder")

    def _choose_output_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", str(Path.home() / "Downloads")
        )
        if not path:
            return
        self.output_folder = path
        self.config["default_output_dir"] = path
        self._save_config()
        self._refresh_action_context()
        self._update_convert_state()

    def _open_output_folder(self):
        target = self.last_output_dir or self.output_folder
        if not _open_folder(target):
            QMessageBox.warning(self, "Open Folder", "No valid folder to open.")

    def _update_convert_state(self):
        ok = bool(self.csv_path and os.path.isfile(self.csv_path) and self.output_folder)
        busy = self._worker is not None or self._load_worker is not None
        self.convert_btn.setEnabled(ok and not busy)
        self._update_library_actions()

    def _set_ui_enabled(self, enabled: bool):
        for btn in (
            self.add_spotify_btn, self.add_soundcloud_btn,
            self.add_csv_btn, self.add_scan_btn,
            self.library_scan_btn, self.library_choose_btn,
        ):
            btn.setEnabled(enabled)
        for btn in self.flag_btns.values():
            btn.setEnabled(enabled)
        self.format_pill.setEnabled(enabled)
        if enabled:
            self._update_library_actions()
        else:
            self.sync_btn.setEnabled(False)

    # ── Timer ──────────────────────────────────────────────────────────────────

    def _tick_timer(self):
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
