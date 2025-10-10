# log_viewer.py
import logging
import tkinter as tk
from tkinter import ttk
from queue import Queue, Empty
from datetime import datetime

_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
_LEVEL_TO_NO = {name: getattr(logging, name) for name in _LEVELS}

class _TkLogHandler(logging.Handler):
    """Handler thread-safe: push les records dans une Queue lue par la GUI."""
    def __init__(self, q: Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        try:
            self.q.put_nowait(record)
        except Exception:
            # on ne casse pas l'appli si la queue est pleine/fermée
            pass

class LogWindow(tk.Toplevel):
    """Fenêtre Toplevel affichant les logs en temps réel avec filtres et autoscroll."""
    _instance = None  # singleton par root

    @classmethod
    def get_or_create(cls, root, queue: Queue):
        if cls._instance is None or not cls._instance.winfo_exists():
            cls._instance = cls(root, queue)
        else:
            cls._instance.deiconify()
            cls._instance.lift()
        return cls._instance

    def __init__(self, root, queue: Queue):
        super().__init__(root)
        self.title("Console des logs")
        self.geometry("900x360")
        self.minsize(600, 240)

        self.queue = queue
        self.paused = tk.BooleanVar(value=False)
        self.autoscroll = tk.BooleanVar(value=True)
        self.level = tk.StringVar(value="INFO")
        self.search_var = tk.StringVar(value="")

        # UI
        top = ttk.Frame(self); top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Niveau").pack(side="left")
        ttk.OptionMenu(top, self.level, self.level.get(), *_LEVELS).pack(side="left", padx=(6, 12))
        ttk.Checkbutton(top, text="Pause", variable=self.paused).pack(side="left")
        ttk.Checkbutton(top, text="Autoscroll", variable=self.autoscroll).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Effacer", command=self._clear).pack(side="left", padx=(12, 0))

        ttk.Label(top, text="Rechercher").pack(side="left", padx=(16, 4))
        search_entry = ttk.Entry(top, textvariable=self.search_var, width=28)
        search_entry.pack(side="left")
        ttk.Button(top, text="Suivant", command=self._find_next).pack(side="left", padx=(6, 0))

        body = ttk.Frame(self); body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.text = tk.Text(body, wrap="none", state="disabled", undo=False)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        hsb = ttk.Scrollbar(body, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        # tags couleurs par niveau (restent sobres)
        self.text.tag_config("DEBUG", foreground="#6b7280")     # gris
        self.text.tag_config("INFO", foreground="#111827")      # noir
        self.text.tag_config("WARNING", foreground="#b45309")   # orange
        self.text.tag_config("ERROR", foreground="#b91c1c")     # rouge
        self.text.tag_config("CRITICAL", foreground="#7f1d1d", underline=1)

        # fermeture → juste masquer
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # polling queue
        self._poll()

        # Bind Ctrl+F pour focus recherche
        self.bind("<Control-f>", lambda e: (search_entry.focus_set(), "break"))

    def _on_close(self):
        self.withdraw()

    def _clear(self):
        self.text.config(state="normal"); self.text.delete("1.0", "end"); self.text.config(state="disabled")

    def _append_line(self, line: str, levelname: str):
        self.text.config(state="normal")
        self.text.insert("end", line + "\n", levelname)
        if self.autoscroll.get():
            self.text.see("end")
        self.text.config(state="disabled")

    def _format_record(self, r: logging.LogRecord) -> str:
        # 2025-10-10 12:34:56 INFO module: message
        ts = datetime.fromtimestamp(r.created).strftime("%Y-%m-%d %H:%M:%S")
        msg = r.getMessage()
        return f"{ts} {r.levelname} {r.name}: {msg}"

    def _passes_filter(self, r: logging.LogRecord) -> bool:
        try:
            current = _LEVEL_TO_NO[self.level.get()]
        except KeyError:
            current = logging.INFO
        return r.levelno >= current

    def _poll(self):
        if not self.paused.get():
            try:
                while True:
                    r = self.queue.get_nowait()
                    if self._passes_filter(r):
                        line = self._format_record(r)
                        self._append_line(line, r.levelname)
            except Empty:
                pass
        self.after(100, self._poll)  # 10 Hz

    def _find_next(self):
        q = self.search_var.get()
        if not q:
            return
        idx = self.text.search(q, self.text.index("insert +1c"), nocase=True, stopindex="end")
        if not idx:
            # wrap to start
            idx = self.text.search(q, "1.0", nocase=True, stopindex="end")
            if not idx:
                return
        end = f"{idx}+{len(q)}c"
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", idx, end)
        self.text.mark_set("insert", end)
        self.text.see(idx)

def attach_live_log_handler(root) -> tuple[_TkLogHandler, Queue, LogWindow]:
    """
    Crée la Queue, un handler logging thread-safe, et la fenêtre (cachée par défaut).
    Retourne (handler, queue, window).
    """
    q = Queue(maxsize=1000)
    handler = _TkLogHandler(q)
    # on laisse la mise en forme à la fenêtre (pas de Formatter ici)
    handler.setLevel(logging.DEBUG)  # on envoie tout, filtrage côté fenêtre
    logging.getLogger().addHandler(handler)
    win = LogWindow.get_or_create(root, q)
    win.withdraw()  # démarre caché; on l’affiche à la demande
    return handler, q, win
