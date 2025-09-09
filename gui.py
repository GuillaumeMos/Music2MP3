# gui.py
import os, csv, platform, tempfile, threading, queue, time, tkinter as tk, json
from tkinter import filedialog, messagebox
from tkinter import ttk

from config import load_config, resource_path
from utils import Tooltip, open_folder
from converter import Converter
from spotify_api import SpotifyClient
from soundcloud_api import SoundCloudClient

# IMPORTANT:
# - No import of spotify_auth at module level.
#   (PKCEAuth is imported lazily only inside the Spotify handler.)
try:
    from config import CONFIG_FILE
except Exception:
    CONFIG_FILE = resource_path("config.json")


class Spotify2MP3GUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('Spotify2MP3')
        self.root.geometry('980x860')
        self.root.minsize(880, 720)

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

        self._sc_thread = None
        self._sc_q: queue.Queue | None = None
        self._sc_done = False

        # per-item UI
        self._rows = {}
        self._perc = {}
        self._total_tracks = 0

        # chrono
        self._t0 = None
        self._timer_running = False

        # options UI (defaults from config)
        self.prefix_numbers_var  = tk.BooleanVar(value=bool(self.config.get("prefix_numbers", False)))
        self.concurrency_var     = tk.IntVar(value=int(self.config.get("concurrency", 3)))
        self.deep_search_var     = tk.BooleanVar(value=bool(self.config.get("deep_search", True)))
        self.transcode_mp3_var   = tk.BooleanVar(value=bool(self.config.get("transcode_mp3", False)))
        self.m3u_var             = tk.BooleanVar(value=bool(self.config.get("generate_m3u", True)))
        self.exclude_instr_var   = tk.BooleanVar(value=bool(self.config.get("exclude_instrumentals", False)))
        self.incremental_var     = tk.BooleanVar(value=bool(self.config.get("incremental_update", True)))

        # default dir
        if platform.system() == "Windows":
            self.last_directory = os.path.join(os.path.expanduser("~"), "Downloads")
        else:
            self.last_directory = os.path.expanduser("~/Downloads")

        self._init_styles()
        self._build_ui()
        self._load_icons()

    # ---------- styles ----------
    def _init_styles(self):
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use('clam')
        except Exception:
            pass

        BG = '#f7f8fb'
        CARD_BG = '#ffffff'
        TXT = '#111827'
        SUB = '#4b5563'
        PRIMARY = '#2563eb'
        OK = '#16a34a'
        ERR = '#e11d48'

        self.root.configure(bg=BG)
        self.style.configure('.', background=BG, foreground=TXT)
        self.style.configure('TFrame', background=BG)
        self.style.configure('TLabel', background=BG, foreground=TXT)
        self.style.configure('Sub.TLabel', foreground=SUB)
        self.style.configure('Muted.TLabel', foreground='#6b7280')
        self.style.configure('Chip.TLabel', background='#e6f4ea', foreground='#065f46', padding=(8, 2))

        self.style.configure('TButton', padding=(10, 6))
        self.style.configure('Accent.TButton', padding=(12, 8), foreground='white', background=PRIMARY)
        self.style.map('Accent.TButton', background=[('active', '#1d4ed8'), ('disabled', '#93c5fd')])

        self.style.configure('Card.TLabelframe', background=CARD_BG, borderwidth=1, relief='solid')
        self.style.configure('Card.TLabelframe.Label', background=CARD_BG, foreground=SUB, padding=(6, 0))
        self.style.configure('CardBody.TFrame', background=CARD_BG)

        self.style.configure('Active.Horizontal.TProgressbar', thickness=12, background=PRIMARY)
        self.style.configure('Ok.Horizontal.TProgressbar', thickness=12, background=OK)
        self.style.configure('Error.Horizontal.TProgressbar', thickness=12, background=ERR)

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
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(4, weight=1)

        header = ttk.Frame(self.root)
        header.grid(row=0, column=0, sticky='ew', padx=24, pady=(18, 10))
        ttk.Label(header, text="Spotify2MP3", font=("Segoe UI", 20, "bold")).pack(side='left')
        ttk.Label(header, text="Convert playlists to local audio (M4A/MP3)", style='Sub.TLabel').pack(side='left', padx=(12, 0))

        cols = ttk.Frame(self.root)
        cols.grid(row=1, column=0, sticky='nsew', padx=24)
        cols.grid_columnconfigure(0, weight=1, uniform='cols')
        cols.grid_columnconfigure(1, weight=1, uniform='cols')

        # Left column: Spotify
        lf_sp = ttk.Labelframe(cols, text="From Spotify link", style='Card.TLabelframe')
        lf_sp.grid(row=0, column=0, sticky='nsew', padx=(0, 12), pady=(6, 6))
        body_sp = ttk.Frame(lf_sp, style='CardBody.TFrame'); body_sp.pack(fill='both', expand=True, padx=12, pady=10)

        row = ttk.Frame(body_sp, style='CardBody.TFrame'); row.pack(fill='x')
        ttk.Label(row, text='URL:', style='Sub.TLabel').pack(side='left')
        self.spotify_entry = ttk.Entry(row); self.spotify_entry.pack(side='left', fill='x', expand=True, padx=(8, 10))
        self.spotify_load_btn = ttk.Button(row, text='Load from Spotify', command=self.load_from_spotify_link_wrapper)
        self.spotify_load_btn.pack(side='left')
        ttk.Label(body_sp, text="Sign-in opens in your browser (OAuth PKCE).", style='Muted.TLabel').pack(anchor='w', pady=(6, 0))

        # Left column: SoundCloud (NO auth)
        lf_sc = ttk.Labelframe(cols, text="From SoundCloud playlist", style='Card.TLabelframe')
        lf_sc.grid(row=1, column=0, sticky='nsew', padx=(0, 12), pady=(6, 6))
        body_sc = ttk.Frame(lf_sc, style='CardBody.TFrame'); body_sc.pack(fill='both', expand=True, padx=12, pady=10)

        row_sc = ttk.Frame(body_sc, style='CardBody.TFrame'); row_sc.pack(fill='x')
        ttk.Label(row_sc, text='URL:', style='Sub.TLabel').pack(side='left')
        self.sc_entry = ttk.Entry(row_sc); self.sc_entry.pack(side='left', fill='x', expand=True, padx=(8, 10))
        self.sc_load_btn = ttk.Button(row_sc, text='Load from SoundCloud', command=self.load_from_soundcloud_link)
        self.sc_load_btn.pack(side='left')
        ttk.Label(body_sc, text="Works with public playlists or private links that include a secret token. No login required.",
                  style='Muted.TLabel').pack(anchor='w', pady=(6, 0))

        # Right column: CSV
        lf_csv = ttk.Labelframe(cols, text="From CSV file", style='Card.TLabelframe')
        lf_csv.grid(row=0, column=1, rowspan=2, sticky='nsew', padx=(12, 0), pady=(6, 6))
        body_csv = ttk.Frame(lf_csv, style='CardBody.TFrame'); body_csv.pack(fill='both', expand=True, padx=12, pady=10)

        self.drop_frame = tk.Frame(body_csv, bg='#eef2ff', height=70, cursor='hand2', highlightthickness=0)
        self.drop_frame.pack(fill='x'); self.drop_frame.pack_propagate(False)
        self.drop_label = tk.Label(self.drop_frame, text='Drop a CSV here or click to browse',
                                   bg='#eef2ff', fg='#1f2937', font=("Segoe UI", 11))
        self.drop_label.pack(expand=True, fill='both')
        self.drop_label.bind('<Button-1>', self.browse_csv)
        Tooltip(self.drop_label, 'Export with Exportify/TuneMyMusic. Click to select.')

        self.clear_button = ttk.Button(body_csv, text='Clear CSV', command=self.clear_selection, state=tk.DISABLED)
        self.clear_button.pack(pady=(8, 0))

        # Output card
        lf_out = ttk.Labelframe(self.root, text="Output", style='Card.TLabelframe')
        lf_out.grid(row=2, column=0, sticky='ew', padx=24, pady=(4, 0))
        body_out = ttk.Frame(lf_out, style='CardBody.TFrame'); body_out.pack(fill='both', expand=True, padx=12, pady=10)

        row_out = ttk.Frame(body_out, style='CardBody.TFrame'); row_out.pack(fill='x', pady=(0, 6))
        ttk.Label(row_out, text='Folder:', style='Sub.TLabel').pack(side='left')
        self.out_entry = ttk.Entry(row_out, state='readonly', width=80)
        self.out_entry.pack(side='left', fill='x', expand=True, padx=(8, 10))
        self.folder_button = ttk.Button(row_out, text='Choose…', command=self.select_output_folder)
        self.folder_button.pack(side='left')
        self.open_folder_btn = ttk.Button(row_out, text='Open', command=self.open_output_folder)
        self.open_folder_btn.pack(side='left', padx=(6, 0))

        # Options group
        opt = ttk.Frame(body_out, style='CardBody.TFrame'); opt.pack(fill='x', pady=(4, 0))
        ttk.Checkbutton(opt, text='Number files (001, 002…)', variable=self.prefix_numbers_var).grid(row=0, column=0, sticky='w')
        ttk.Checkbutton(opt, text='Deep search (more accurate, slower)', variable=self.deep_search_var).grid(row=0, column=1, sticky='w', padx=(20,0))
        ttk.Checkbutton(opt, text='Transcode to MP3 (VBR 0)', variable=self.transcode_mp3_var).grid(row=1, column=0, sticky='w')
        ttk.Checkbutton(opt, text='Generate M3U', variable=self.m3u_var).grid(row=1, column=1, sticky='w', padx=(20,0))
        ttk.Checkbutton(opt, text='Exclude "instrumental" matches', variable=self.exclude_instr_var).grid(row=2, column=0, sticky='w')
        ttk.Checkbutton(opt, text='Only add new tracks (incremental)', variable=self.incremental_var).grid(row=2, column=1, sticky='w', padx=(20,0))

        # Threads + Convert
        row_actions = ttk.Frame(body_out, style='CardBody.TFrame')
        row_actions.pack(fill='x', pady=(10, 2))
        row_actions.grid_columnconfigure(0, weight=1)

        grp_threads = ttk.Frame(row_actions, style='CardBody.TFrame')
        grp_threads.grid(row=0, column=0, sticky='w')
        ttk.Label(grp_threads, text='Threads:', style='Sub.TLabel').pack(side='left')
        try:
            self.thread_spin = ttk.Spinbox(grp_threads, from_=1, to=8,
                                           textvariable=self.concurrency_var, width=5, wrap=False)
        except AttributeError:
            self.thread_spin = tk.Spinbox(grp_threads, from_=1, to=8,
                                          textvariable=self.concurrency_var, width=5, wrap=False)
        self.thread_spin.pack(side='left', padx=(8, 12))
        Tooltip(self.thread_spin, 'Number of parallel downloads (1–8). 2–4 recommended.')

        self.convert_button = ttk.Button(row_actions, text='Convert', style='Accent.TButton',
                                         command=self.start_conversion, state=tk.DISABLED)
        self.convert_button.grid(row=0, column=1, sticky='e')

        # Downloads card
        lf_dl = ttk.Labelframe(self.root, text="Downloads", style='Card.TLabelframe')
        lf_dl.grid(row=4, column=0, sticky='nsew', padx=24, pady=(10, 16))
        self.root.grid_rowconfigure(4, weight=1)

        body_dl = ttk.Frame(lf_dl, style='CardBody.TFrame'); body_dl.pack(fill='both', expand=True, padx=12, pady=10)
        body_dl.grid_columnconfigure(0, weight=1)

        self.status_label = ttk.Label(body_dl, text='Status: Waiting…')
        self.status_label.grid(row=0, column=0, sticky='w')

        self.info_label = ttk.Label(body_dl, text='', style='Chip.TLabel')
        self.info_label.grid(row=1, column=0, sticky='w', pady=(6, 6))

        self.progress = ttk.Progressbar(body_dl, orient='horizontal', mode='determinate',
                                        length=760, style='Active.Horizontal.TProgressbar')
        self.progress.grid(row=2, column=0, sticky='ew')
        self.time_label = ttk.Label(body_dl, text='', style='Muted.TLabel')
        self.time_label.grid(row=3, column=0, sticky='w', pady=(4, 6))

        list_wrap = ttk.Frame(body_dl, style='CardBody.TFrame')
        list_wrap.grid(row=4, column=0, sticky='nsew')
        body_dl.grid_rowconfigure(4, weight=1)

        self.canvas = tk.Canvas(list_wrap, highlightthickness=0, bg='#ffffff')
        vscroll = ttk.Scrollbar(list_wrap, orient='vertical', command=self.canvas.yview)
        self.list_frame = ttk.Frame(self.canvas, style='CardBody.TFrame')

        self.list_frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.create_window((0, 0), window=self.list_frame, anchor='nw')
        self.canvas.configure(yscrollcommand=vscroll.set)

        self.canvas.pack(side='left', fill='both', expand=True)
        vscroll.pack(side='right', fill='y')

    # ---------- Spotify loader (OAuth PKCE — only here) ----------
    def load_from_spotify_link_wrapper(self):
        # Lazy import so SoundCloud never touches OAuth code.
        try:
            from spotify_auth import PKCEAuth
        except Exception as e:
            messagebox.showerror('Missing dependency', f'spotify_auth.PKCEAuth not available:\n{e}')
            return

        url = self.spotify_entry.get().strip()
        pid = SpotifyClient.extract_playlist_id(url)
        if not pid:
            messagebox.showerror('Error', 'Invalid Spotify playlist link.')
            return

        client_id = self.config.get('spotify_client_id')
        if not client_id:
            messagebox.showerror('Missing Client ID', 'Add "spotify_client_id" in config.json (PKCE).')
            return

        self._sp_q = queue.Queue(); self._sp_done = False
        self._set_controls(False)
        self._start_indeterminate("Opening browser for Spotify authorization…")

        def _spotify_worker():
            try:
                auth = PKCEAuth(client_id=client_id, redirect_uri="http://127.0.0.1:8765/callback",
                                scopes=["playlist-read-private", "playlist-read-collaborative"])
                sp = SpotifyClient(token_supplier=auth.get_token)
                self._sp_q.put(('status', 'Fetching playlist from Spotify…'))
                rows, name = sp.fetch_playlist(pid)
                if not rows:
                    self._sp_q.put(('error', 'No tracks found.')); return
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
                    self._style_drop_loaded(os.path.basename(tmp))
                    self.status_label.config(text=f'Loaded: {self._loaded_playlist_name_from_spotify} ({n} tracks)')
                    self._stop_indeterminate(); self._set_controls(True)
                    self.update_convert_button_state(); self._sp_done = True
                elif kind == 'error':
                    self._stop_indeterminate(); self._set_controls(True)
                    messagebox.showerror('Spotify Error', payload); self._sp_done = True
        except queue.Empty:
            pass
        if self._sp_thread and self._sp_thread.is_alive() and not self._sp_done:
            self.root.after(100, self._poll_spotify_queue)

    # ---------- SoundCloud loader (NO auth) ----------
    def load_from_soundcloud_link(self):
        url = self.sc_entry.get().strip()
        if not url or "soundcloud.com" not in url:
            messagebox.showerror('Error', 'Please paste a valid SoundCloud playlist/track URL.')
            return

        self._sc_q = queue.Queue(); self._sc_done = False
        self._set_controls(False)
        self._start_indeterminate("Fetching SoundCloud playlist…")

        cookies_path = self.config.get("cookies_path")  # optional, for edge cases; NOT auth

        def _sc_worker():
            try:
                sc = SoundCloudClient()
                rows, name = sc.fetch_playlist(url, cookies_path=cookies_path)
                if not rows:
                    self._sc_q.put(('error', 'No tracks found.')); return
                fd, tmp = tempfile.mkstemp(prefix='soundcloud_playlist_', suffix='.csv'); os.close(fd)
                with open(tmp, 'w', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=[
                        "Track Name","Artist Name(s)","Album Name","Duration (ms)","Source URL","Track URI"
                    ])
                    w.writeheader(); w.writerows(rows)
                self._sc_q.put(('done', (tmp, name, len(rows))))
            except Exception as e:
                self._sc_q.put(('error', str(e)))

        self._sc_thread = threading.Thread(target=_sc_worker, daemon=True)
        self._sc_thread.start()
        self.root.after(100, self._poll_sc_queue)

    def _poll_sc_queue(self):
        if not self._sc_q: return
        try:
            while True:
                kind, payload = self._sc_q.get_nowait()
                if kind == 'done':
                    tmp, name, n = payload
                    self.csv_path = tmp
                    self._loaded_playlist_name_from_spotify = name or "SoundCloud"
                    self._style_drop_loaded(os.path.basename(tmp))
                    self.status_label.config(text=f'Loaded SoundCloud: {self._loaded_playlist_name_from_spotify} ({n} tracks)')
                    self._stop_indeterminate(); self._set_controls(True)
                    self.update_convert_button_state(); self._sc_done = True
                elif kind == 'error':
                    self._stop_indeterminate(); self._set_controls(True)
                    messagebox.showerror('SoundCloud Error', payload); self._sc_done = True
        except queue.Empty:
            pass
        if self._sc_thread and self._sc_thread.is_alive() and not self._sc_done:
            self.root.after(100, self._poll_sc_queue)

    # ---------- File handlers ----------
    def _style_drop_loaded(self, name: str):
        self.drop_label.config(text=f'CSV (generated): {name}', bg='#dcfce7', fg='#065f46')
        self.drop_frame.config(bg='#dcfce7')

    def browse_csv(self, _=None):
        path = filedialog.askopenfilename(initialdir=self.last_directory, filetypes=[('CSV files','*.csv')])
        if path:
            self.csv_path = path; self.last_directory = os.path.dirname(path)
            self.drop_label.config(text=f'CSV: {os.path.basename(path)}', bg='#dcfce7', fg='#065f46')
            self.drop_frame.config(bg='#dcfce7')
            self.status_label.config(text='CSV loaded.')
            self._loaded_playlist_name_from_spotify = None
            self.update_convert_button_state()

    def clear_selection(self):
        self.csv_path = None
        self.drop_label.config(text='Drop a CSV here or click to browse', bg='#eef2ff', fg='#1f2937')
        self.drop_frame.config(bg='#eef2ff')
        self.status_label.config(text='Status: Waiting…')
        self.progress['value'] = 0
        self._loaded_playlist_name_from_spotify = None
        self._clear_track_list()
        self.info_label.config(text='')
        self.time_label.config(text='')
        self._stop_timer()
        self.update_convert_button_state()

    def select_output_folder(self):
        path = filedialog.askdirectory(initialdir=self.last_directory)
        if path:
            self.output_folder = path
            self.last_directory = path
            self.out_entry.config(state='normal')
            self.out_entry.delete(0, 'end')
            self.out_entry.insert(0, path)
            self.out_entry.config(state='readonly')
            self.status_label.config(text='Output folder selected.')
            self.update_convert_button_state()

    def open_output_folder(self):
        target = self.last_output_dir or self.output_folder
        if not open_folder(target):
            messagebox.showerror('Error', 'No valid folder to open.')

    def update_convert_button_state(self):
        ok = (self.csv_path and os.path.isfile(self.csv_path) and self.csv_path.lower().endswith('.csv') and self.output_folder)
        self.convert_button.config(state=tk.NORMAL if ok else tk.DISABLED)
        self.clear_button.config(state=tk.NORMAL if self.csv_path else tk.DISABLED)

    # ---------- Conversion (thread) ----------
    def start_conversion(self):
        if not (self.csv_path and self.output_folder):
            messagebox.showerror('Error', 'Select a CSV and an output folder.'); return

        # persist options from UI
        self.config['prefix_numbers']        = bool(self.prefix_numbers_var.get())
        self.config['deep_search']           = bool(self.deep_search_var.get())
        self.config['transcode_mp3']         = bool(self.transcode_mp3_var.get())
        self.config['generate_m3u']          = bool(self.m3u_var.get())
        self.config['exclude_instrumentals'] = bool(self.exclude_instr_var.get())
        self.config['incremental_update']    = bool(self.incremental_var.get())

        # threads (bounded)
        try:
            threads = int(self.concurrency_var.get())
        except Exception:
            threads = int(self.config.get("concurrency", 3))
        threads = max(1, min(8, threads))
        self.concurrency_var.set(threads)
        self.config['concurrency'] = threads

        # save config
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        self._t0 = time.time()
        self.time_label.config(text='')
        self._start_timer()

        try: self.progress.configure(style='Active.Horizontal.TProgressbar')
        except Exception: pass

        self._set_controls(False)
        self.status_label.config(text='Starting conversion…')
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
                    _cur, _maxi = payload
                elif kind == 'item':
                    ev, data = payload
                    self._handle_item_event(ev, data)
                elif kind == 'done':
                    self.last_output_dir = payload
                    if self._total_tracks > 0:
                        self.progress.configure(maximum=self._total_tracks * 100, value=self._total_tracks * 100)
                    elapsed = int(time.time() - self._t0) if self._t0 else 0
                    self._stop_timer(final_text=f"⏱ Total download time: {self._format_duration(elapsed)}")
                    self.status_label.config(text='✅ Conversion complete')
                    try: self.progress.configure(style='Ok.Horizontal.TProgressbar')
                    except Exception: pass
                    self._set_controls(True); self._conv_done = True; self.root.bell()
                elif kind == 'error':
                    self._stop_timer()
                    try: self.progress.configure(style='Error.Horizontal.TProgressbar')
                    except Exception: pass
                    messagebox.showerror('Error', f'Unexpected error: {payload}')
                    self._set_controls(True); self._conv_done = True
        except queue.Empty:
            pass
        if self._conv_thread and self._conv_thread.is_alive() and not self._conv_done:
            self.root.after(80, self._poll_conversion_queue)

    # ---------- per-item UI ----------
    def _handle_item_event(self, ev: str, d: dict):
        if ev == 'conv_init':
            total = int(d.get('new', d.get('total', 0)))
            self._total_tracks = total
            self._perc.clear()
            self.progress.configure(mode='determinate', maximum=max(1, total * 100), value=0)
            if total == 0:
                self.info_label.config(text="0 new track (already up to date)")
            elif total == 1:
                self.info_label.config(text="1 new track to download")
            else:
                self.info_label.config(text=f"{total} new tracks to download")
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
                row['label'].config(text=f"{idx:03d}. {row['title']}  (Error)")
                try: row['bar'].configure(style='Error.Horizontal.TProgressbar')
                except Exception: pass
            self._set_percent(idx, 100.0)
            return

    def _ensure_row(self, idx: int, title: str):
        if idx in self._rows:
            return
        frame = ttk.Frame(self.list_frame, style='CardBody.TFrame')
        frame.pack(fill='x', padx=2, pady=4)
        lbl = ttk.Label(frame, text=f"{idx:03d}. {title}")
        lbl.pack(fill='x')
        bar = ttk.Progressbar(
            frame, orient='horizontal', length=820, mode='determinate',
            maximum=100, value=0, style='Active.Horizontal.TProgressbar'
        )
        bar.pack(fill='x', pady=(4, 0))
        self._rows[idx] = {'label': lbl, 'bar': bar, 'title': title}

    def _set_percent(self, idx: int, p: float):
        self._perc[idx] = p
        row = self._rows.get(idx)
        if row:
            row['bar'].configure(value=max(0, min(100, p)))
        if self._total_tracks:
            s = sum(self._perc.get(i, 0.0) for i in self._perc)
            self.progress.configure(value=s)

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
        self.time_label.config(text=f"⏱ Elapsed: {self._format_duration(elapsed)}")
        self.root.after(1000, self._tick_timer)

    # ---------- misc ----------
    def _set_controls(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        for w in (self.convert_button, self.clear_button, self.folder_button,
                  self.spotify_load_btn, self.drop_label, self.spotify_entry,
                  self.open_folder_btn, self.sc_load_btn, self.sc_entry,
                  self.thread_spin):
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
