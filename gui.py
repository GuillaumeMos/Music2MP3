# gui.py
import os, csv, platform, tempfile, threading, queue, time, tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk

from config import load_config, resource_path
from utils import Tooltip, DEFAULT_DROP_BG, LOADED_DROP_BG, open_folder
from converter import Converter
from spotify_api import SpotifyClient
from spotify_auth import PKCEAuth


class Spotify2MP3GUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('Spotify2MP3')
        self.root.geometry('780x760')
        self.root.minsize(580, 600)

        # state
        self.csv_path = None
        self.output_folder = None
        self.last_output_dir = None
        self._loaded_playlist_name_from_spotify = None
        self.config = load_config()

        # workers
        self._conv_thread = None
        self._conv_q: queue.Queue | None = None
        self._conv_done = False

        self._sp_thread = None
        self._sp_q: queue.Queue | None = None
        self._sp_done = False

        # per-item UI
        self._rows = {}         # idx -> {'label':Label, 'bar':Progressbar, 'title':str}
        self._perc = {}         # idx -> float percent
        self._total_tracks = 0  # fixé par conv_init (nouveaux uniquement)

        # chrono
        self._t0 = None
        self._timer_running = False

        # options UI
        self.prefix_numbers_var = tk.BooleanVar(value=bool(self.config.get("prefix_numbers", True)))

        # default dir
        if platform.system() == "Windows":
            self.last_directory = os.path.join(os.path.expanduser("~"), "Downloads")
        else:
            self.last_directory = os.path.expanduser("~/Downloads")

        self._build_ui()
        self._load_icons()

    # ---------- icons ----------
    def _load_icons(self):
        try:
            if platform.system() == 'Darwin':
                icon_path = resource_path('icon.icns')
                img = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, img)
            else:
                icon_path = resource_path('icon.ico')
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

    # ---------- UI ----------
    def _build_ui(self):
        # Styles ttk
        self.style = ttk.Style(self.root)
        try:
            self.style.configure('Active.Horizontal.TProgressbar', thickness=10, background='#3498db')  # bleu
            self.style.configure('Ok.Horizontal.TProgressbar',      thickness=10, background='#2ecc71')  # vert
            self.style.configure('Error.Horizontal.TProgressbar',   thickness=10, background='#e74c3c')  # rouge
        except Exception:
            pass

        instr = tk.Label(self.root, text='1) Glissez un CSV ou collez un lien Spotify', font=("Arial", 12))
        instr.pack(fill='x', padx=20, pady=(12, 0))

        # CSV drop/browse
        tk.Label(self.root, text='CSV de playlist :', anchor='w').pack(fill='x', padx=20)
        self.drop_frame = tk.Frame(self.root, bg=DEFAULT_DROP_BG, height=64, width=540)
        self.drop_frame.pack(pady=6, padx=20)
        self.drop_frame.pack_propagate(False)
        self.drop_label = tk.Label(self.drop_frame, text='CSV file: None', bg=DEFAULT_DROP_BG,
                                   font=("Arial", 12), wraplength=520, justify='center', cursor='hand2')
        self.drop_label.pack(expand=True, fill='both')
        self.drop_label.bind('<Button-1>', self.browse_csv)
        Tooltip(self.drop_label, 'Dépose ton CSV ici ou clique pour parcourir.')

        self.clear_button = tk.Button(self.root, text='Effacer CSV', command=self.clear_selection, state=tk.DISABLED)
        self.clear_button.pack()

        # output folder
        tk.Label(self.root, text='2) Dossier de sortie :', anchor='w').pack(fill='x', padx=20)
        self.folder_button = tk.Button(self.root, text='Choisir le dossier', command=self.select_output_folder, font=('Arial', 12))
        self.folder_button.pack(pady=5)
        self.output_label = tk.Label(self.root, text='Output folder: Not selected', anchor='w')
        self.output_label.pack(fill='x', padx=20)

        # Spotify link
        tk.Label(self.root, text='ou lien de playlist Spotify :', anchor='w').pack(fill='x', padx=20, pady=(10, 0))
        row = tk.Frame(self.root); row.pack(fill='x', padx=20)
        tk.Label(row, text='URL:').pack(side='left')
        self.spotify_entry = tk.Entry(row); self.spotify_entry.pack(side='left', fill='x', expand=True, padx=(5, 8))
        self.spotify_load_btn = tk.Button(row, text='Charger depuis Spotify', command=self.load_from_spotify_link_wrapper)
        self.spotify_load_btn.pack(side='left')

        # options
        opt = tk.Frame(self.root); opt.pack(fill='x', padx=20, pady=(10, 0))
        cb = tk.Checkbutton(opt, text='Numéroter les fichiers (001, 002…)', variable=self.prefix_numbers_var)
        cb.pack(side='left')
        Tooltip(cb, "Quand coché, les fichiers seront préfixés par 001 -, 002 -, etc.\nQuand décoché, pas de numérotation dans les noms de fichiers.")

        # convert
        self.convert_button = tk.Button(self.root, text='3) Convertir', command=self.start_conversion, state=tk.DISABLED, font=('Arial', 14))
        self.convert_button.pack(pady=10)

        # status + global progress
        tk.Label(self.root, text='4) Téléchargements :', anchor='w').pack(fill='x', padx=20, pady=(10, 0))
        self.status_label = tk.Label(self.root, text='Status: Waiting...', anchor='w', font=('Arial', 12))
        self.status_label.pack(fill='x', padx=20)

        # infos avant démarrage (N nouveaux titres)
        self.info_label = tk.Label(self.root, text='', anchor='w', font=("Arial", 11))
        self.info_label.pack(fill='x', padx=20, pady=(2, 2))

        self.progress = ttk.Progressbar(
            self.root, orient='horizontal', length=720, mode='determinate',
            style='Active.Horizontal.TProgressbar'
        )
        self.progress.pack(pady=6)

        # temps total (et chrono live)
        self.time_label = tk.Label(self.root, text='', anchor='w', font=("Arial", 10))
        self.time_label.pack(fill='x', padx=20, pady=(0, 6))

        # liste scrollable des pistes
        wrap = tk.Frame(self.root); wrap.pack(fill='both', expand=True, padx=20, pady=(4, 10))
        self.canvas = tk.Canvas(wrap, highlightthickness=0)
        vscroll = ttk.Scrollbar(wrap, orient='vertical', command=self.canvas.yview)
        self.list_frame = tk.Frame(self.canvas)

        self.list_frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.create_window((0,0), window=self.list_frame, anchor='nw')
        self.canvas.configure(yscrollcommand=vscroll.set)

        self.canvas.pack(side='left', fill='both', expand=True)
        vscroll.pack(side='right', fill='y')

        # open output folder
        self.open_folder_btn = tk.Button(self.root, text='Ouvrir le dossier de sortie', command=self.open_output_folder)
        self.open_folder_btn.pack(pady=5)

    # ---------- Spotify loader (PKCE) ----------
    def load_from_spotify_link_wrapper(self):
        url = self.spotify_entry.get().strip()
        pid = SpotifyClient.extract_playlist_id(url)
        if not pid:
            messagebox.showerror('Erreur', 'Lien de playlist invalide.')
            return

        client_id = self.config.get('spotify_client_id')
        if not client_id:
            messagebox.showerror('Manque Client ID', 'Ajoute "spotify_client_id" dans config.json (PKCE).')
            return

        self._sp_q = queue.Queue(); self._sp_done = False
        self._set_controls(False)
        self._start_indeterminate("Ouverture du navigateur pour autorisation Spotify…")

        def _spotify_worker():
            try:
                auth = PKCEAuth(client_id=client_id, redirect_uri="http://127.0.0.1:8765/callback",
                                scopes=["playlist-read-private", "playlist-read-collaborative"])
                sp = SpotifyClient(token_supplier=auth.get_token)
                self._sp_q.put(('status', 'Récupération de la playlist Spotify…'))
                rows, name = sp.fetch_playlist(pid)
                if not rows:
                    self._sp_q.put(('error', 'Aucune piste trouvée.')); return
                fd, tmp = tempfile.mkstemp(prefix='spotify_playlist_', suffix='.csv'); os.close(fd)
                with open(tmp, 'w', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=["Track Name","Artist Name(s)","Album Name","Duration (ms)"])
                    w.writeheader(); w.writerows(rows)
                self._sp_q.put(('done', (tmp, name, len(rows))))
            except Exception as e:
                self._sp_q.put(('error', str(e)))

        self._sp_thread = threading.Thread(target=_spotify_worker, daemon=True)
        self._sp_thread.start()
        self.root.after(100, self._poll_spotify_queue)

    def _poll_spotify_queue(self):
        if not self._sp_q: return
        try:
            while True:
                kind, payload = self._sp_q.get_nowait()
                if kind == 'status':
                    self.status_label.config(text=payload)
                elif kind == 'done':
                    tmp, name, n = payload
                    self.csv_path = tmp
                    self._loaded_playlist_name_from_spotify = name or "SpotifyPlaylist"
                    self.drop_label.config(text=f'CSV (généré) : {os.path.basename(tmp)}')
                    self.drop_frame.config(bg=LOADED_DROP_BG); self.drop_label.config(bg=LOADED_DROP_BG)
                    self.status_label.config(text=f'Playlist chargée : {self._loaded_playlist_name_from_spotify} ({n} titres)')
                    self._stop_indeterminate(); self._set_controls(True)
                    self.update_convert_button_state(); self._sp_done = True
                elif kind == 'error':
                    self._stop_indeterminate(); self._set_controls(True)
                    messagebox.showerror('Erreur Spotify', payload); self._sp_done = True
        except queue.Empty:
            pass
        if self._sp_thread and self._sp_thread.is_alive() and not self._sp_done:
            self.root.after(100, self._poll_spotify_queue)

    # ---------- File handlers ----------
    def browse_csv(self, _=None):
        path = filedialog.askopenfilename(initialdir=self.last_directory, filetypes=[('CSV files','*.csv')])
        if path:
            self.csv_path = path; self.last_directory = os.path.dirname(path)
            self.drop_label.config(text=f'CSV file: {os.path.basename(path)}')
            self.drop_frame.config(bg=LOADED_DROP_BG); self.drop_label.config(bg=LOADED_DROP_BG)
            self.status_label.config(text='CSV chargé.'); self._loaded_playlist_name_from_spotify = None
            self.update_convert_button_state()

    def clear_selection(self):
        self.csv_path = None; self.drop_label.config(text='CSV file: None')
        self.status_label.config(text='Status: Waiting...')
        self.drop_frame.config(bg=DEFAULT_DROP_BG); self.drop_label.config(bg=DEFAULT_DROP_BG)
        self.progress['value'] = 0; self._loaded_playlist_name_from_spotify = None
        self._clear_track_list()
        self.info_label.config(text='')
        self.time_label.config(text='')
        self._stop_timer()
        self.update_convert_button_state()

    def select_output_folder(self):
        path = filedialog.askdirectory(initialdir=self.last_directory)
        if path:
            self.output_folder = path; self.last_directory = path
            self.output_label.config(text=f'Output folder: {path}')
            self.status_label.config(text='Dossier de sortie sélectionné.')
            self.update_convert_button_state()

    def open_output_folder(self):
        target = self.last_output_dir or self.output_folder
        if not open_folder(target):
            messagebox.showerror('Erreur', 'Aucun dossier valide à ouvrir.')

    def update_convert_button_state(self):
        ok = (self.csv_path and os.path.isfile(self.csv_path) and self.csv_path.lower().endswith('.csv') and self.output_folder)
        self.convert_button.config(state=tk.NORMAL if ok else tk.DISABLED)
        self.clear_button.config(state=tk.NORMAL if self.csv_path else tk.DISABLED)

    # ---------- Conversion (thread) ----------
    def start_conversion(self):
        if not (self.csv_path and self.output_folder):
            messagebox.showerror('Erreur', 'Sélectionne un CSV et un dossier de sortie.'); return

        # pousse l’option dans la config passée au converter
        self.config['prefix_numbers'] = bool(self.prefix_numbers_var.get())

        # start chrono
        self._t0 = time.time()
        self.time_label.config(text='')
        self._start_timer()  # chrono live

        try: self.progress.configure(style='Active.Horizontal.TProgressbar')
        except Exception: pass

        self._set_controls(False)
        self.status_label.config(text='Démarrage de la conversion…')
        self.progress.configure(value=0, maximum=100, mode='determinate')
        self._clear_track_list()

        self._conv_q = queue.Queue(); self._conv_done = False
        self._conv_thread = threading.Thread(target=self._run_conversion_worker, daemon=True)
        self._conv_thread.start()
        self.root.after(80, self._poll_conversion_queue)

    def _run_conversion_worker(self):
        try:
            conv = Converter(
                config=self.config,
                status_cb=lambda s: self._conv_q.put(('status', s)),
                progress_cb=lambda cur, maxi: self._conv_q.put(('progress', (cur, maxi))),
                item_cb=lambda k, d: self._conv_q.put(('item', (k, d))),
            )
            playlist_hint = getattr(self, '_loaded_playlist_name_from_spotify', None)
            out_dir = conv.convert_from_csv(self.csv_path, self.output_folder, playlist_hint)
            self._conv_q.put(('done', out_dir))
        except Exception as e:
            self._conv_q.put(('error', str(e)))

    def _poll_conversion_queue(self):
        if not self._conv_q: return
        try:
            while True:
                kind, payload = self._conv_q.get_nowait()
                if kind == 'status':
                    self.status_label.config(text=payload)
                elif kind == 'progress':
                    _cur, _maxi = payload  # barre globale lissée via per-item
                elif kind == 'item':
                    ev, data = payload
                    self._handle_item_event(ev, data)
                elif kind == 'done':
                    self.last_output_dir = payload
                    if self._total_tracks > 0:
                        self.progress.configure(maximum=self._total_tracks * 100, value=self._total_tracks * 100)
                    elapsed = 0
                    if self._t0:
                        elapsed = int(time.time() - self._t0)
                    self._stop_timer(final_text=f"⏱ Temps total de téléchargement : {self._format_duration(elapsed)}")
                    self.status_label.config(text='✅ Conversion terminée')
                    try: self.progress.configure(style='Ok.Horizontal.TProgressbar')
                    except Exception: pass
                    self._set_controls(True); self._conv_done = True; self.root.bell()
                elif kind == 'error':
                    self._stop_timer()
                    try: self.progress.configure(style='Error.Horizontal.TProgressbar')
                    except Exception: pass
                    messagebox.showerror('Erreur', f'Erreur inattendue: {payload}')
                    self._set_controls(True); self._conv_done = True
        except queue.Empty:
            pass
        if self._conv_thread and self._conv_thread.is_alive() and not self._conv_done:
            self.root.after(80, self._poll_conversion_queue)

    # ---------- per-item UI ----------
    def _handle_item_event(self, ev: str, d: dict):
        if ev == 'conv_init':
            total = int(d.get('new', d.get('total', 0)))  # nouveaux uniquement
            self._total_tracks = total
            self._perc.clear()
            self.progress.configure(mode='determinate', maximum=max(1, total * 100), value=0)
            if total == 0:
                self.info_label.config(text="0 nouveau titre à télécharger (playlist déjà à jour)")
            elif total == 1:
                self.info_label.config(text="1 nouveau titre à télécharger")
            else:
                self.info_label.config(text=f"{total} nouveaux titres à télécharger")
            return

        if ev == 'init':
            idx = int(d['idx']); title = d.get('title') or f"Track {idx}"
            self._ensure_row(idx, title); self._set_percent(idx, 0.0)
            return

        if ev == 'progress':
            idx = int(d['idx']); p = float(d.get('percent', 0.0))
            self._set_percent(idx, p)
            row = self._rows.get(idx)
            if row:
                eta = d.get('eta'); sp = d.get('speed')
                extra = []
                if sp: extra.append(sp)
                if eta: extra.append(f"ETA {eta}")
                suffix = f" — {', '.join(extra)}" if extra else ""
                row['label'].config(text=f"{idx:03d}. {row['title']}  ({p:.0f} %){suffix}")
            return

        if ev == 'done':
            idx = int(d['idx']); self._set_percent(idx, 100.0)
            row = self._rows.get(idx)
            if row:
                row['label'].config(text=f"{idx:03d}. {row['title']}  (100 %)")
                try: row['bar'].configure(style='Ok.Horizontal.TProgressbar')
                except Exception: pass
            return

        if ev == 'error':
            idx = int(d['idx'])
            row = self._rows.get(idx)
            if row:
                row['bar'].configure(value=100)
                row['label'].config(text=f"{idx:03d}. {row['title']}  (Erreur)")
                try: row['bar'].configure(style='Error.Horizontal.TProgressbar')
                except Exception: pass
            self._set_percent(idx, 100.0)
            return

    def _ensure_row(self, idx: int, title: str):
        if idx in self._rows:
            return
        frame = tk.Frame(self.list_frame)
        frame.pack(fill='x', padx=2, pady=2)
        lbl = tk.Label(frame, text=f"{idx:03d}. {title}", anchor='w')
        lbl.pack(fill='x')
        bar = ttk.Progressbar(
            frame, orient='horizontal', length=720, mode='determinate',
            maximum=100, value=0, style='Active.Horizontal.TProgressbar'
        )
        bar.pack(fill='x', pady=(1, 0))
        self._rows[idx] = {'label': lbl, 'bar': bar, 'title': title}

    def _set_percent(self, idx: int, p: float):
        self._perc[idx] = p
        row = self._rows.get(idx)
        if row:
            row['bar'].configure(value=max(0, min(100, p)))
        if self._total_tracks:
            s = sum(self._perc.get(i, 0.0) for i in self._perc)
            self.progress.configure(value=s)  # maximum déjà = total*100

    def _clear_track_list(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._rows.clear()
        self._perc.clear()
        self._total_tracks = 0

    # ---------- chrono ----------
    def _start_timer(self):
        self._timer_running = True
        self._tick_timer()

    def _stop_timer(self, final_text: str | None = None):
        self._timer_running = False
        if final_text is not None:
            self.time_label.config(text=final_text)

    def _tick_timer(self):
        if not self._timer_running or not self._t0:
            return
        elapsed = int(time.time() - self._t0)
        self.time_label.config(text=f"⏱ Écoulé : {self._format_duration(elapsed)}")
        self.root.after(1000, self._tick_timer)

    # ---------- misc ----------
    def _set_controls(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        for w in (self.convert_button, self.clear_button, self.folder_button,
                  self.spotify_load_btn, self.drop_label, self.spotify_entry):
            try: w.config(state=state)
            except Exception: pass

    def _start_indeterminate(self, text: str):
        self.status_label.config(text=text)
        self.progress.configure(mode='indeterminate')
        try:
            self.progress.configure(style='Active.Horizontal.TProgressbar')
            self.progress.start(80)
        except tk.TclError:
            pass

    def _stop_indeterminate(self):
        try: self.progress.stop()
        except tk.TclError: pass
        self.progress.configure(mode='determinate')

    def _format_duration(self, sec: int) -> str:
        h, rem = divmod(int(sec), 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


if __name__ == '__main__':
    root = tk.Tk()
    app = Spotify2MP3GUI(root)
    root.mainloop()
