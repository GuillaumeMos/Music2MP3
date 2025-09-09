# utils.py
import os
import platform
import subprocess
import tkinter as tk


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
        lbl = tk.Label(self.tip, text=self.text, bg='#FFF9C4', relief='solid', bd=1)
        lbl.pack()

    def _hide(self, _):
        if self.tip:
            self.tip.destroy()
            self.tip = None


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
