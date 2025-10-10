# entrypoint.py
import os, sys, logging
from pathlib import Path
import tkinter as tk
from tkinter import messagebox as mb

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

    # --- root ---
    if DND_AVAILABLE:
        try:
            root = TkinterDnD.Tk()
        except Exception:
            root = tk.Tk()
    else:
        root = tk.Tk()

    # --- log window: rien dans gui.py ---
    handler, q, log_win = attach_live_log_handler(root)

    # Raccourci clavier (n'interfère pas avec gui.py)
    root.bind("<F12>", lambda e: (log_win.deiconify(), log_win.lift(), "break"))

    # (Optionnel) n’ajoute un menu que s’il n’y en a pas déjà un
    try:
        current_menu = root.nametowidget(root["menu"]) if root["menu"] else None
    except Exception:
        current_menu = None
    if current_menu is None:
        from tkinter import Menu
        menubar = Menu(root)
        view_menu = Menu(menubar, tearoff=0)
        view_menu.add_command(label="Console des logs (F12)", command=lambda: (log_win.deiconify(), log_win.lift()))
        menubar.add_cascade(label="Affichage", menu=view_menu)
        root.config(menu=menubar)

    app = Music2MP3GUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
