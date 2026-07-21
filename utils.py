# utils.py
import os
import platform
import shutil
import subprocess
import sys
import tkinter as tk

YTDLP_COOKIE_BROWSERS = ("", "safari", "chrome", "firefox", "brave", "edge", "chromium", "opera", "vivaldi", "whale")


def find_ytdlp_cmd(resource_path_func=None) -> list[str]:
    """
    Resolve yt-dlp as a command prefix.

    Priority:
    - bundled binary next to the packaged app,
    - executable next to the current Python interpreter,
    - executable available on PATH,
    - installed Python module in the current interpreter.
    """
    exe = "yt-dlp.exe" if platform.system() == "Windows" else "yt-dlp"
    candidates: list[str] = []
    if resource_path_func:
        candidates.extend([
            os.path.join(resource_path_func("yt-dlp"), exe),
            resource_path_func(exe),
        ])
    candidates.append(os.path.join(os.path.dirname(sys.executable), exe))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return [candidate]

    for name in ("yt-dlp", "yt-dlp.exe"):
        found = shutil.which(name)
        if found:
            return [found]

    return [sys.executable, "-m", "yt_dlp"]


def build_ytdlp_cookie_args(config: dict | None) -> list[str]:
    """
    Build yt-dlp cookie/auth arguments from config.

    Prefer browser cookies when configured because they avoid manual cookies.txt
    exports. Fall back to a Netscape cookies file for portable builds.
    """
    cfg = config or {}
    browser = str(cfg.get("cookies_from_browser") or "").strip().lower()
    profile = str(cfg.get("cookies_browser_profile") or "").strip()
    if browser:
        spec = f"{browser}:{profile}" if profile else browser
        return ["--cookies-from-browser", spec]
    cookies_path = str(cfg.get("cookies_path") or "").strip()
    if cookies_path:
        return ["--cookies", cookies_path]
    return []


# -----------------------------
# UI helpers
# -----------------------------
class Tooltip:
    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind('<Enter>', self._show)
        widget.bind('<Leave>', self._hide)

    def _show(self, _):
        if self.tip or not self.text:
            return
        try:
            x, y, _cx, cy = self.widget.bbox('insert')
        except Exception:
            x, y, cy = 0, 0, 0
        x += self.widget.winfo_rootx() + 24
        y += cy + self.widget.winfo_rooty() + 24
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f'+{x}+{y}')
        lbl = tk.Label(
            self.tip,
            text=self.text,
            bg='#fff8dc',
            fg='#111827',
            relief='solid',
            bd=1,
            padx=8,
            pady=4,
            justify='left',
            wraplength=360,
        )
        lbl.pack()

    def _hide(self, _):
        if self.tip:
            self.tip.destroy()
            self.tip = None


# -----------------------------
# OS open helpers
# -----------------------------
def open_folder(path: str | None) -> bool:
    """Open a folder in the OS file browser."""
    if not path or not os.path.isdir(path):
        return False
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(path)  # noqa: P204
        elif system == "Darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
        return True
    except Exception:
        return False


def open_path(path: str | None) -> bool:
    """Open a file or folder with the default OS handler."""
    if not path or not os.path.exists(path):
        return False
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(path)  # noqa: P204
        elif system == "Darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
        return True
    except Exception:
        return False


# -----------------------------
# Subprocess helpers (NO console windows)
# -----------------------------
def _win_no_window_kwargs():
    """Return kwargs preventing console popups on Windows."""
    if platform.system() == "Windows":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si, "creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def run_quiet(cmd, *, text=False, capture_output=False, **kwargs) -> subprocess.CompletedProcess:
    """
    Wrapper around subprocess.run that never pops a console on Windows.
    """
    kw = _win_no_window_kwargs()
    if capture_output:
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
    kw.update(kwargs)
    return subprocess.run(cmd, text=text, **kw)


def popen_quiet(cmd, **kwargs) -> subprocess.Popen:
    """
    Wrapper around subprocess.Popen that never opens a console on Windows,
    and pipes stdout/stderr by default (handy for progress parsing).
    """
    kw = _win_no_window_kwargs()
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kw.update(kwargs)
    return subprocess.Popen(cmd, **kw)
