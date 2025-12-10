# app.py (entrypoint)
import os, sys, logging
from pathlib import Path
import tkinter as tk

try:
    from tkinterdnd2 import TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

from logging_setup import setup_logging
from gui import Music2MP3GUI
from log_viewer import attach_live_log_handler

def main():
    # --- logging early ---
    log_dir = Path.home() / ".spotify2mp3"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "music2mp3.log"
    setup_logging(log_path=str(log_path), level=os.getenv("APP_LOG_LEVEL", "INFO"))
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    log = logging.getLogger(__name__)
    log.info("App starting… DND_AVAILABLE=%s", DND_AVAILABLE)
    log.info("Log file -> %s", log_path)

    # --- root ---
    if DND_AVAILABLE:
        try:
            root = TkinterDnD.Tk()
        except Exception:
            log.warning("TkinterDnD init failed, fallback Tk()", exc_info=True)
            root = tk.Tk()
    else:
        root = tk.Tk()

    # --- live log window (F12) ---
    handler, q, log_win = attach_live_log_handler(root)
    def _show_logs(_=None):
        log_win.deiconify()
        log_win.lift()
        return "break"
    root.bind_all("<F12>", _show_logs)
    # expose to GUI for a "Logs" button
    root._log_window = log_win  # type: ignore[attr-defined]

    app = Music2MP3GUI(root)
    logging.getLogger(__name__).info("App UI ready")
    root.mainloop()

if __name__ == "__main__":
    main()
