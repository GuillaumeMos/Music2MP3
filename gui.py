# gui.py
import os, csv, platform, tempfile, threading, queue, time, tkinter as tk, json
from tkinter import filedialog, messagebox
from tkinter import ttk

import logging
log = logging.getLogger(__name__)

from config import load_config, resource_path
from utils import Tooltip, open_folder, open_path
from converter import Converter
from spotify_api import SpotifyClient
from soundcloud_api import SoundCloudClient
from token_store import RefreshTokenStore

try:
    from config import CONFIG_FILE
except Exception:
    def resource_path(relative_path):
        return os.path.join(os.path.abspath('.'), relative_path)
    CONFIG_FILE = resource_path("config.json")


class Music2MP3GUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('Music2MP3')
        self.root.geometry('980x760')
        self.root.minsize(820, 560)
        log.info("GUI: Music2MP3 window created")

        # state
        self.csv_path = None
        self.output_folder = None
        self.last_output_dir = None
        self._loaded_playlist_name_from_spotify = None
        self.config = load_config()
        log.debug("GUI: Config loaded: %s", self.config)

        # background threads/queues
        self._conv_thread = None
        self._conv_q: queue.Queue | None = None
        self._conv_done = False
        self._conv_obj: Converter | None = None
        self._cancel_event: threading.Event | None = None

        self._sp_thread = None
        self._sp_q: queue.Queue | None = None
        self._sp_done = False

        self._sc_thread = None
        self._sc_q: queue.Queue | None = None
        self._sc_done = False

        # per-item UI + errors
        self._rows = {}
        self._perc = {}
        self._errors = {}
        self._total_tracks = 0

        # chrono
        self._t0 = None
        self._timer_running = False

        # options
        self.prefix_numbers_var  = tk.BooleanVar(value=bool(self.config.get("prefix_numbers", False)))
        self.concurrency_var     = tk.IntVar(value=int(self.config.get("concurrency", 3)))
        self.deep_search_var     = tk.BooleanVar(value=bool(self.config.get("deep_search", True)))
        self.strict_match_var    = tk.BooleanVar(value=bool(self.config.get("strict_match", False)))
        mode_raw = str(self.config.get("output_mode", "")).strip().lower()
        fmt_raw = str(self.config.get("output_format", "mp3")).strip().lower()
        if mode_raw not in {"auto", "manual"}:
            mode_raw = "auto" if fmt_raw == "auto" else "manual"
        fmt_manual = str(self.config.get("output_format_manual", fmt_raw)).strip().lower()
        if fmt_manual not in {"mp3", "m4a", "aac", "wav", "flac", "aiff"}:
            fmt_manual = "mp3"
        self.output_mode_var     = tk.StringVar(value="Auto (best available)" if mode_raw == "auto" else "Manual")
        self.output_format_var   = tk.StringVar(value=fmt_manual)
        self.m3u_var             = tk.BooleanVar(value=bool(self.config.get("generate_m3u", True)))
        self.exclude_instr_var   = tk.BooleanVar(value=bool(self.config.get("exclude_instrumentals", False)))
        self.incremental_var     = tk.BooleanVar(value=bool(self.config.get("incremental_update", True)))

        # default dir (persisted automatically)
        self._apply_persisted_default_output()

        # default directory for file dialogs
        if platform.system() == "Windows":
            self.last_directory = os.path.join(os.path.expanduser("~"), "Downloads")
        else:
            self.last_directory = os.path.expanduser("~/Downloads")

        self._init_styles()
        self._build_ui()
        self._load_icons()
        self.update_convert_button_state()

    # ---------- persisted default output ----------
    def _apply_persisted_default_output(self):
        default_dir = self.config.get("default_output_dir")
        if default_dir and os.path.isdir(default_dir):
            self.output_folder = default_dir
            log.info("GUI: default output dir restored: %s", self.output_folder)

    def _save_config(self):
        try:
            cfg_dir = os.path.dirname(CONFIG_FILE)
            if cfg_dir:
                os.makedirs(cfg_dir, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            log.debug("GUI: config saved -> %s", CONFIG_FILE)
        except Exception:
            log.exception("GUI: failed to save config")

    # ---------- styles ----------
    def _init_styles(self):
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use('clam')
        except Exception:
            pass

        BG = '#f7f8fb'
        CARD_BG = '#ffffff'
        DL_BG = '#f8fafc'
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
        self.style.configure('Chip.TLabel', background='#e5edff', foreground='#1e3a8a', padding=(8, 2))

        self.style.configure('TButton', padding=(10, 6))
        self.style.configure('Accent.TButton', padding=(12, 8), foreground='white', background=PRIMARY)
        self.style.map('Accent.TButton', background=[('active', '#1d4ed8'), ('disabled', '#93c5fd')])

        self.style.configure('Danger.TButton', padding=(12, 8), foreground='white', background=ERR)
        self.style.map('Danger.TButton', background=[('active', '#be123c'), ('disabled', '#fda4af')])

        self.style.configure('Card.TLabelframe', background=CARD_BG, borderwidth=1, relief='solid')
        self.style.configure('Card.TLabelframe.Label', background=CARD_BG, foreground=SUB, padding=(6, 0))
        self.style.configure('CardBody.TFrame', background=CARD_BG)
        self.style.configure('Downloads.TFrame', background=DL_BG)
        self.style.configure('TrackRow.TFrame', background=DL_BG)
        self.style.configure('TrackRow.TLabel', background=DL_BG, foreground=TXT)

        self.style.configure('Active.Horizontal.TProgressbar', thickness=12, background=PRIMARY, troughcolor='#e5e7eb')
        self.style.configure('Ok.Horizontal.TProgressbar', thickness=12, background=OK, troughcolor='#e5e7eb')
        self.style.configure('Error.Horizontal.TProgressbar', thickness=12, background=ERR, troughcolor='#e5e7eb')

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
        self.root.grid_rowconfigure(0, weight=1)

        shell = ttk.Frame(self.root, style='CardBody.TFrame')
        shell.grid(row=0, column=0, sticky='nsew', padx=16, pady=12)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        # Vertical split: top controls + bottom downloads (resizable).
        self.main_pane = ttk.Panedwindow(shell, orient='vertical')
        self.main_pane.grid(row=0, column=0, sticky='nsew')

        top_host = ttk.Frame(self.main_pane, style='CardBody.TFrame')
        dl_host = ttk.Frame(self.main_pane, style='CardBody.TFrame')
        self.main_pane.add(top_host, weight=3)
        self.main_pane.add(dl_host, weight=2)
        self.root.after(120, self._set_initial_sash)

        # Scrollable top area for small windows.
        top_host.grid_columnconfigure(0, weight=1)
        top_host.grid_rowconfigure(0, weight=1)
        self.top_canvas = tk.Canvas(top_host, highlightthickness=0, bg='#f7f8fb', bd=0)
        top_scroll = ttk.Scrollbar(top_host, orient='vertical', command=self.top_canvas.yview)
        self.top_canvas.configure(yscrollcommand=top_scroll.set)
        self.top_canvas.grid(row=0, column=0, sticky='nsew')
        top_scroll.grid(row=0, column=1, sticky='ns')

        self.top_content = ttk.Frame(self.top_canvas, style='CardBody.TFrame')
        self._top_window = self.top_canvas.create_window((0, 0), window=self.top_content, anchor='nw')
        self.top_content.bind('<Configure>', self._on_top_content_configure)
        self.top_canvas.bind('<Configure>', self._on_top_canvas_configure)
        self.top_canvas.bind('<MouseWheel>', self._on_top_mousewheel)
        self.top_canvas.bind('<Button-4>', lambda _e: self.top_canvas.yview_scroll(-1, 'units'))
        self.top_canvas.bind('<Button-5>', lambda _e: self.top_canvas.yview_scroll(1, 'units'))

        top = self.top_content
        top.grid_columnconfigure(0, weight=1)

        header = ttk.Frame(top)
        header.grid(row=0, column=0, sticky='ew', padx=8, pady=(6, 10))
        ttk.Label(header, text="Music2MP3", font=("Segoe UI", 20, "bold")).pack(side='left')
        ttk.Label(header, text="Convert playlists to local audio (M4A/MP3)", style='Sub.TLabel').pack(side='left', padx=(12, 0))
        ttk.Button(header, text="Logs (F12)", command=self.show_logs).pack(side='right')

        cols = ttk.Frame(top)
        cols.grid(row=1, column=0, sticky='nsew', padx=8)
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
        ttk.Label(body_sc, text="Works with public playlists or private links (secret token). No login required.",
                  style='Muted.TLabel').pack(anchor='w', pady=(6, 0))

        # Left column: Manual text list
        lf_txt = ttk.Labelframe(cols, text="From text list", style='Card.TLabelframe')
        lf_txt.grid(row=2, column=0, sticky='nsew', padx=(0, 12), pady=(6, 6))
        body_txt = ttk.Frame(lf_txt, style='CardBody.TFrame'); body_txt.pack(fill='both', expand=True, padx=12, pady=10)
        ttk.Label(body_txt, text="One track per line. Format: Artist - Title or just Title.", style='Muted.TLabel').pack(anchor='w')

        txt_wrap = ttk.Frame(body_txt, style='CardBody.TFrame')
        txt_wrap.pack(fill='both', expand=True, pady=(6, 6))
        txt_wrap.grid_columnconfigure(0, weight=1)
        self.manual_text = tk.Text(txt_wrap, height=4, wrap='word', bg='#f9fafb', relief='flat',
                                   highlightthickness=1, highlightbackground='#e5e7eb')
        self.manual_text.grid(row=0, column=0, sticky='nsew')
        txt_scroll = ttk.Scrollbar(txt_wrap, orient='vertical', command=self.manual_text.yview)
        txt_scroll.grid(row=0, column=1, sticky='ns')
        self.manual_text.configure(yscrollcommand=txt_scroll.set)

        btn_txt = ttk.Frame(body_txt, style='CardBody.TFrame'); btn_txt.pack(fill='x')
        self.manual_load_btn = ttk.Button(btn_txt, text='Load from text', command=self.load_from_manual_list)
        self.manual_load_btn.pack(side='right')

        # Right column: CSV
        lf_csv = ttk.Labelframe(cols, text="From CSV file", style='Card.TLabelframe')
        lf_csv.grid(row=0, column=1, rowspan=3, sticky='nsew', padx=(12, 0), pady=(6, 6))
        body_csv = ttk.Frame(lf_csv, style='CardBody.TFrame'); body_csv.pack(fill='both', expand=True, padx=12, pady=10)

        self.drop_frame = tk.Frame(body_csv, bg='#eef2ff', height=58, cursor='hand2', highlightthickness=0)
        self.drop_frame.pack(fill='x'); self.drop_frame.pack_propagate(False)
        self.drop_label = tk.Label(self.drop_frame, text='Drop a CSV here or click to browse',
                                   bg='#eef2ff', fg='#1f2937', font=("Segoe UI", 11))
        self.drop_label.pack(expand=True, fill='both')
        self.drop_label.bind('<Button-1>', self._click_csv_label)
        Tooltip(self.drop_label, 'Click to select a CSV. Once loaded, click again to open it.')

        self.clear_button = ttk.Button(body_csv, text='Clear CSV', command=self.clear_selection, state=tk.DISABLED)
        self.clear_button.pack(pady=(8, 0))

        # Output card
        lf_out = ttk.Labelframe(top, text="Output", style='Card.TLabelframe')
        lf_out.grid(row=2, column=0, sticky='ew', padx=8, pady=(4, 8))
        body_out = ttk.Frame(lf_out, style='CardBody.TFrame'); body_out.pack(fill='both', expand=True, padx=12, pady=10)

        row_out = ttk.Frame(body_out, style='CardBody.TFrame'); row_out.pack(fill='x', pady=(0, 6))
        ttk.Label(row_out, text='Folder:', style='Sub.TLabel').pack(side='left')
        self.out_entry = ttk.Entry(row_out, state='readonly', width=80)
        self.out_entry.pack(side='left', fill='x', expand=True, padx=(8, 10))
        self.folder_button = ttk.Button(row_out, text='Choose…', command=self.select_output_folder)
        self.folder_button.pack(side='left')
        self.open_folder_btn = ttk.Button(row_out, text='Open', command=self.open_output_folder)
        self.open_folder_btn.pack(side='left', padx=(6, 0))

        # Pre-fill from persisted default (if any)
        if self.output_folder and os.path.isdir(self.output_folder):
            self.out_entry.config(state='normal'); self.out_entry.delete(0, 'end')
            self.out_entry.insert(0, self.output_folder); self.out_entry.config(state='readonly')

        # Options group
        opt = ttk.Frame(body_out, style='CardBody.TFrame'); opt.pack(fill='x', pady=(4, 0))
        ttk.Checkbutton(opt, text='Number files (001, 002…)', variable=self.prefix_numbers_var).grid(row=0, column=0, sticky='w')
        ttk.Checkbutton(opt, text='Deep search (more accurate, slower)', variable=self.deep_search_var).grid(row=0, column=1, sticky='w', padx=(20,0))
        self.strict_match_chk = ttk.Checkbutton(opt, text='Strict matching (safer, slower)', variable=self.strict_match_var)
        self.strict_match_chk.grid(row=0, column=2, sticky='w', padx=(20,0))
        ttk.Label(opt, text='Format mode').grid(row=1, column=0, sticky='w', pady=(4,0))
        self.output_mode_combo = ttk.Combobox(
            opt,
            textvariable=self.output_mode_var,
            values=['Auto (best available)', 'Manual'],
            state='readonly',
            width=22,
        )
        self.output_mode_combo.grid(row=1, column=1, sticky='w', padx=(20,0))
        self.output_mode_combo.bind('<<ComboboxSelected>>', self._on_output_mode_changed)

        self.format_label = ttk.Label(opt, text='Output format (manual, 44.1 kHz)')
        self.format_label.grid(row=2, column=0, sticky='w', pady=(4,0))
        self.format_combo = ttk.Combobox(opt, textvariable=self.output_format_var,
                                         values=['mp3','m4a','aac','wav','flac','aiff'],
                                         state='readonly', width=10)
        self.format_combo.grid(row=2, column=1, sticky='w', padx=(20,0))
        ttk.Checkbutton(opt, text='Generate M3U', variable=self.m3u_var).grid(row=3, column=0, sticky='w')
        ttk.Checkbutton(opt, text='Exclude "instrumental" matches', variable=self.exclude_instr_var).grid(row=3, column=1, sticky='w', padx=(20,0))
        ttk.Checkbutton(opt, text='Only add new tracks (incremental)', variable=self.incremental_var).grid(row=4, column=0, sticky='w')

        # Threads + Convert/Stop
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

        btns = ttk.Frame(row_actions, style='CardBody.TFrame'); btns.grid(row=0, column=1, sticky='e')
        self.convert_button = ttk.Button(btns, text='Convert', style='Accent.TButton',
                                         command=self.start_conversion, state=tk.DISABLED)
        self.convert_button.pack(side='left', padx=(0, 8))
        self.stop_button = ttk.Button(btns, text='Stop', style='Danger.TButton',
                                      command=self.stop_conversion, state=tk.DISABLED)
        self.stop_button.pack(side='left')

        # Downloads card (always visible in bottom pane)
        dl_host.grid_columnconfigure(0, weight=1)
        dl_host.grid_rowconfigure(0, weight=1)
        lf_dl = ttk.Labelframe(dl_host, text="Downloads", style='Card.TLabelframe')
        lf_dl.grid(row=0, column=0, sticky='nsew', padx=8, pady=(8, 0))

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

        list_wrap = ttk.Frame(body_dl, style='Downloads.TFrame')
        list_wrap.grid(row=4, column=0, sticky='nsew')
        body_dl.grid_rowconfigure(4, weight=1)

        self.canvas = tk.Canvas(list_wrap, highlightthickness=0, bg='#f8fafc', bd=0)
        vscroll = ttk.Scrollbar(list_wrap, orient='vertical', command=self.canvas.yview)
        self.list_frame = ttk.Frame(self.canvas, style='Downloads.TFrame')

        self.list_frame.bind('<Configure>', self._on_list_frame_configure)
        self._list_window = self.canvas.create_window((0, 0), window=self.list_frame, anchor='nw')
        self.canvas.bind('<Configure>', self._on_canvas_configure)
        self.canvas.bind('<MouseWheel>', self._on_download_mousewheel)
        self.canvas.bind('<Button-4>', lambda _e: self.canvas.yview_scroll(-1, 'units'))
        self.canvas.bind('<Button-5>', lambda _e: self.canvas.yview_scroll(1, 'units'))
        self.canvas.configure(yscrollcommand=vscroll.set)

        self.canvas.pack(side='left', fill='both', expand=True)
        vscroll.pack(side='right', fill='y')
        self._sync_output_mode_ui()

    # ---------- click CSV label ----------
    def _click_csv_label(self, _=None):
        if self.csv_path and os.path.isfile(self.csv_path):
            if not open_path(self.csv_path):
                messagebox.showerror('Error', 'Unable to open CSV.')
        else:
            self.browse_csv()

    # ---------- Spotify loader ----------
    def load_from_spotify_link_wrapper(self):
        log.info("UI: Spotify load button clicked")
        try:
            from spotify_auth import PKCEAuth
        except Exception as e:
            log.exception("UI: PKCEAuth import failed")
            messagebox.showerror('Missing dependency', f'spotify_auth.PKCEAuth not available:\n{e}')
            return

        url = self.spotify_entry.get().strip()
        log.debug("UI: Spotify URL entered = %s", url)
        pid = SpotifyClient.extract_playlist_id(url)
        if not pid:
            log.warning("UI: Invalid Spotify playlist link")
            messagebox.showerror('Error', 'Invalid Spotify playlist link.')
            return
        log.info("UI: Detected Spotify playlist id=%s", pid)

        client_id = self.config.get('spotify_client_id')
        if not client_id:
            log.warning('UI: Missing spotify_client_id in config.json')
            messagebox.showerror('Missing Client ID', 'Add "spotify_client_id" in config.json (PKCE).')
            return

        self._sp_q = queue.Queue(); self._sp_done = False
        self._set_controls(False)
        self._start_indeterminate("Opening browser for Spotify authorization…")

        def _spotify_worker():
            log.info("BG: Spotify worker started for playlist %s", pid)
            try:
                token_store = RefreshTokenStore(service="Music2MP3", user="spotify_pkce")
                auth = PKCEAuth(client_id=client_id, redirect_uri="http://127.0.0.1:8765/callback",
                                scopes=["playlist-read-private", "playlist-read-collaborative"],
                                refresh_token_store=token_store)
                sp = SpotifyClient(token_supplier=auth.get_token)
                self._sp_q.put(('status', 'Fetching playlist from Spotify…'))
                rows, name = sp.fetch_playlist(pid)
                log.info("BG: Spotify fetched %s items for '%s'", len(rows), name)
                fd, tmp = tempfile.mkstemp(prefix='spotify_playlist_', suffix='.csv'); os.close(fd)
                with open(tmp, 'w', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=["Track Name","Artist Name(s)","Album Name","Duration (ms)"])
                    w.writeheader(); w.writerows(rows)
                self._sp_q.put(('done', (tmp, name, len(rows))))
            except Exception as e:
                log.exception("BG: Spotify worker failed")
                self._sp_q.put(('error', str(e)))

        self._sp_thread = threading.Thread(target=_spotify_worker, daemon=True)
        self._sp_thread.start()
        self.root.after(100, self._poll_spotify_queue)

    def _poll_spotify_queue(self):
        if not self._sp_q: return
        try:
            while True:
                kind, payload = self._sp_q.get_nowait()
                log.debug("UI: _poll_spotify_queue got %s", kind)
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
        log.info("UI: SoundCloud load button clicked (url=%s)", url)
        if not url or "soundcloud.com" not in url:
            messagebox.showerror('Error', 'Please paste a valid SoundCloud playlist/track URL.')
            return

        self._sc_q = queue.Queue(); self._sc_done = False
        self._set_controls(False)
        self._start_indeterminate("Fetching SoundCloud playlist…")

        cookies_path = self.config.get("cookies_path")  # optional

        def _sc_worker():
            log.info("BG: SoundCloud worker started")
            try:
                sc = SoundCloudClient()
                rows, name = sc.fetch_playlist(url, cookies_path=cookies_path)
                log.info("BG: SoundCloud fetched %s items for '%s'", len(rows), name)
                fd, tmp = tempfile.mkstemp(prefix='soundcloud_playlist_', suffix='.csv'); os.close(fd)
                with open(tmp, 'w', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=[
                        "Track Name","Artist Name(s)","Album Name","Duration (ms)","Source URL","Track URI"
                    ])
                    w.writeheader(); w.writerows(rows)
                self._sc_q.put(('done', (tmp, name, len(rows))))
            except Exception as e:
                log.exception("BG: SoundCloud worker failed")
                self._sc_q.put(('error', str(e)))

        self._sc_thread = threading.Thread(target=_sc_worker, daemon=True)
        self._sc_thread.start()
        self.root.after(100, self._poll_sc_queue)

    def _poll_sc_queue(self):
        if not self._sc_q: return
        try:
            while True:
                kind, payload = self._sc_q.get_nowait()
                log.debug("UI: _poll_sc_queue got %s", kind)
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

    # ---------- Manual text list ----------
    def load_from_manual_list(self):
        raw = self.manual_text.get("1.0", "end")
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not lines:
            messagebox.showerror('Error', 'Paste at least one line (Artist - Title or Title).')
            return

        rows = []
        for ln in lines:
            if " - " in ln:
                artist, title = ln.split(" - ", 1)
                artist = artist.strip()
                title = title.strip()
            else:
                artist, title = "", ln
            rows.append({
                "Track Name": title or "Unknown",
                "Artist Name(s)": artist,
                "Album Name": "",
                "Duration (ms)": "",
                "Source URL": "",
                "Track URI": "",
            })

        fd, tmp = tempfile.mkstemp(prefix='manual_tracks_', suffix='.csv'); os.close(fd)
        with open(tmp, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=[
                "Track Name","Artist Name(s)","Album Name","Duration (ms)","Source URL","Track URI"
            ])
            w.writeheader(); w.writerows(rows)

        self.csv_path = tmp
        self._loaded_playlist_name_from_spotify = "ManualList"
        self._style_drop_loaded(os.path.basename(tmp))
        self.status_label.config(text=f'Loaded text list ({len(rows)} tracks)')
        self.update_convert_button_state()

    # ---------- File handlers ----------
    def _style_drop_loaded(self, name: str):
        self.drop_label.config(text=f'CSV: {name}  (click to open)', bg='#dcfce7', fg='#065f46')
        self.drop_frame.config(bg='#dcfce7')

    def browse_csv(self, _=None):
        path = filedialog.askopenfilename(initialdir=self.last_directory, filetypes=[('CSV files','*.csv')])
        if path:
            self.csv_path = path; self.last_directory = os.path.dirname(path)
            self._style_drop_loaded(os.path.basename(path))
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
            self.out_entry.config(state='normal'); self.out_entry.delete(0, 'end')
            self.out_entry.insert(0, path); self.out_entry.config(state='readonly')
            self.status_label.config(text='Output folder selected.')
            # Always persist the last selected output folder
            self.config['default_output_dir'] = path
            self._save_config()
            self.update_convert_button_state()

    def open_output_folder(self):
        target = self.last_output_dir or self.output_folder
        if not open_folder(target):
            messagebox.showerror('Error', 'No valid folder to open.')

    def update_convert_button_state(self):
        ok = (self.csv_path and os.path.isfile(self.csv_path) and self.csv_path.lower().endswith('.csv') and self.output_folder)
        self.convert_button.config(state=tk.NORMAL if ok else tk.DISABLED)
        self.clear_button.config(state=tk.NORMAL if self.csv_path else tk.DISABLED)

    # ---------- Conversion ----------
    def start_conversion(self):
        log.info("UI: Start conversion (csv=%s, out=%s)", self.csv_path, self.output_folder)
        if not (self.csv_path and self.output_folder):
            messagebox.showerror('Error', 'Select a CSV and an output folder.'); return

        # persist options from UI
        self.config['prefix_numbers']        = bool(self.prefix_numbers_var.get())
        self.config['deep_search']           = bool(self.deep_search_var.get())
        self.config['strict_match']          = bool(self.strict_match_var.get())
        mode = self._current_output_mode()
        fmt = str(self.output_format_var.get()).lower() or "mp3"
        self.config['output_mode']           = mode
        self.config['output_format_manual']  = fmt
        self.config['output_format']         = fmt if mode == "manual" else "auto"
        self.config['generate_m3u']          = bool(self.m3u_var.get())
        self.config['exclude_instrumentals'] = bool(self.exclude_instr_var.get())
        self.config['incremental_update']    = bool(self.incremental_var.get())
        self.config['concurrency']           = int(self.concurrency_var.get())

        # always persist last output folder
        if self.output_folder:
            self.config['default_output_dir'] = self.output_folder
        self._save_config()

        self._t0 = time.time()
        self.time_label.config(text='')
        self._start_timer()

        try: self.progress.configure(style='Active.Horizontal.TProgressbar')
        except Exception: pass

        self._set_controls(False)
        self.stop_button.config(state=tk.NORMAL)
        self.status_label.config(text='Starting conversion…')
        self.progress.configure(value=0, maximum=100, mode='determinate')
        self._clear_track_list()
        self._errors.clear()

        self._cancel_event = threading.Event()

        self._conv_q = queue.Queue(); self._conv_done = False
        def _worker():
            log.info("BG: Converter worker started")
            try:
                conv = Converter(
                    config=self.config,
                    status_cb=lambda s: self._conv_q.put(('status', s)),
                    progress_cb=lambda cur, maxi: self._conv_q.put(('progress', (cur, maxi))),
                    item_cb=lambda k, d: self._conv_q.put(('item', (k, d))),
                    cancel_event=self._cancel_event
                )
                self._conv_obj = conv
                playlist_hint = getattr(self, '_loaded_playlist_name_from_spotify', None)
                out_dir = conv.convert_from_csv(self.csv_path, self.output_folder, playlist_hint)
                log.info("BG: Converter finished -> out_dir=%s", out_dir)
                self._conv_q.put(('done', out_dir))
            except Exception as e:
                log.exception("BG: Converter crashed")
                self._conv_q.put(('error', str(e)))
            finally:
                self._conv_obj = None

        self._conv_thread = threading.Thread(target=_worker, daemon=True)
        self._conv_thread.start()
        self.root.after(80, self._poll_conversion_queue)

    def stop_conversion(self):
        if self._cancel_event and not self._cancel_event.is_set():
            self._cancel_event.set()
            self.stop_button.config(state=tk.DISABLED)
            self.status_label.config(text='Cancelling…')

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
                    if ev == 'cancel_all':
                        self._stop_timer()
                        try: self.progress.configure(style='Error.Horizontal.TProgressbar')
                        except Exception: pass
                        self.status_label.config(text='⛔ Cancelled')
                        self.stop_button.config(state=tk.DISABLED)
                    else:
                        self._handle_item_event(ev, data)
                elif kind == 'done':
                    self.last_output_dir = payload
                    if self._total_tracks > 0:
                        self.progress.configure(maximum=self._total_tracks * 100, value=self._total_tracks * 100)
                    elapsed = int(time.time() - self._t0) if self._t0 else 0
                    if self._cancel_event and self._cancel_event.is_set():
                        self._stop_timer(final_text=f"⏱ Cancelled after: {self._format_duration(elapsed)}")
                        self.status_label.config(text='⛔ Cancelled')
                        try: self.progress.configure(style='Error.Horizontal.TProgressbar')
                        except Exception: pass
                    else:
                        self._stop_timer(final_text=f"⏱ Total download time: {self._format_duration(elapsed)}")
                        self.status_label.config(text='✅ Conversion complete')
                        try: self.progress.configure(style='Ok.Horizontal.TProgressbar')
                        except Exception: pass
                        if self._errors:
                            n = len(self._errors)
                            self._write_error_report(payload)
                            messagebox.showwarning("Completed with errors",
                                f"Finished with {n} failed track(s). See errors.txt in the output folder or click 'View error' next to the red items.")
                    self._set_controls(True); self.stop_button.config(state=tk.DISABLED)
                    self._conv_done = True; self.root.bell()
                    self._cancel_event = None
                elif kind == 'error':
                    self._stop_timer()
                    try: self.progress.configure(style='Error.Horizontal.TProgressbar')
                    except Exception: pass
                    messagebox.showerror('Error', f'Unexpected error: {payload}')
                    self._set_controls(True); self.stop_button.config(state=tk.DISABLED)
                    self._conv_done = True
                    self._cancel_event = None
        except queue.Empty:
            pass
        if self._conv_thread and self._conv_thread.is_alive() and not self._conv_done:
            self.root.after(80, self._poll_conversion_queue)

    # ---------- per-item UI ----------
    def _handle_item_event(self, ev: str, d: dict):
        log.debug("UI: item_event %s %s", ev, {k: d.get(k) for k in ("idx","percent","message","title") if k in d})
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
            msg = d.get('message') or 'Unknown error'
            title = self._rows.get(idx, {}).get('title', f"Track {idx}")
            self._errors[idx] = (title, msg)

            row = self._rows.get(idx)
            if row:
                row['bar'].configure(value=100)
                row['label'].config(text=f"{idx:03d}. {row['title']}  (Error)")
                try: row['bar'].configure(style='Error.Horizontal.TProgressbar')
                except Exception: pass
                # Show "View error" button
                try: row['btn'].pack(side='right')
                except Exception: pass
                Tooltip(row['label'], msg[:3000])
            self._set_percent(idx, 100.0)
            return

    def _ensure_row(self, idx: int, title: str):
        if idx in self._rows:
            return
        frame = ttk.Frame(self.list_frame, style='TrackRow.TFrame', padding=(8, 6))
        frame.pack(fill='x', padx=2, pady=3)

        top = ttk.Frame(frame, style='TrackRow.TFrame')
        top.pack(fill='x')
        lbl = ttk.Label(top, text=f"{idx:03d}. {title}", style='TrackRow.TLabel')
        lbl.pack(side='left', fill='x', expand=True)

        # Hidden until an error happens:
        btn = ttk.Button(top, text="View error", command=lambda i=idx: self._show_error(i))
        btn.pack(side='right'); btn.pack_forget()

        bar = ttk.Progressbar(
            frame, orient='horizontal', mode='determinate',
            maximum=100, value=0, style='Active.Horizontal.TProgressbar'
        )
        bar.pack(fill='x', pady=(4, 0))

        self._rows[idx] = {'frame': frame, 'label': lbl, 'bar': bar, 'btn': btn, 'title': title}

    def _show_error(self, idx: int):
        err = self._errors.get(idx, ("Track", "No details"))
        if isinstance(err, tuple):
            title, msg = err
        else:
            title, msg = f"Track {idx}", str(err)
        win = tk.Toplevel(self.root)
        win.title(f"Error details - Track {idx:03d}")
        win.geometry("720x420")
        win.transient(self.root)
        win.grab_set()

        frm = ttk.Frame(win); frm.pack(fill='both', expand=True, padx=10, pady=10)
        txt = tk.Text(frm, wrap='word')
        txt.pack(fill='both', expand=True)
        txt.insert('1.0', f"{title}\n\n{msg}")
        txt.configure(state='disabled')

        btns = ttk.Frame(frm); btns.pack(fill='x', pady=(8,0))
        def _copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(f"{title}\n{msg}")
        ttk.Button(btns, text="Copy to clipboard", command=_copy).pack(side='left')
        ttk.Button(btns, text="Close", command=win.destroy).pack(side='right')

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
        self._errors.clear()
        self._total_tracks = 0

    def _write_error_report(self, out_dir: str):
        if not (out_dir and os.path.isdir(out_dir) and self._errors):
            return
        path = os.path.join(out_dir, "errors.txt")
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("# Failed tracks\n")
                for idx in sorted(self._errors):
                    err = self._errors[idx]
                    if isinstance(err, tuple):
                        title, msg = err
                    else:
                        title, msg = f"Track {idx}", str(err)
                    f.write(f"{idx:03d} | {title} | {msg}\n")
            log.info("GUI: error report written -> %s", path)
        except Exception:
            log.exception("GUI: failed to write errors.txt")

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
    def _current_output_mode(self) -> str:
        val = str(self.output_mode_var.get()).strip().lower()
        return "auto" if val.startswith("auto") else "manual"

    def _sync_output_mode_ui(self):
        manual = self._current_output_mode() == "manual"
        if manual:
            self.format_label.grid()
            self.format_combo.grid()
            try:
                if str(self.format_combo.cget("state")) != str(tk.DISABLED):
                    self.format_combo.config(state='readonly')
            except Exception:
                pass
        else:
            self.format_label.grid_remove()
            self.format_combo.grid_remove()

    def _on_output_mode_changed(self, _event=None):
        self._sync_output_mode_ui()

    def _set_controls(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        for w in (self.convert_button, self.clear_button, self.folder_button,
                  self.spotify_load_btn, self.drop_label, self.spotify_entry,
                  self.open_folder_btn, self.sc_load_btn, self.sc_entry,
                  self.thread_spin, getattr(self, "manual_load_btn", None),
                  getattr(self, "manual_text", None), getattr(self, "output_mode_combo", None),
                  getattr(self, "strict_match_chk", None)):
            try: w.config(state=state)
            except Exception: pass
        try:
            if enabled and self._current_output_mode() == "manual":
                self.format_combo.config(state='readonly')
            else:
                self.format_combo.config(state=state)
        except Exception:
            pass
        self._sync_output_mode_ui()
        if enabled:
            self.stop_button.config(state=tk.DISABLED)

    def _set_initial_sash(self):
        try:
            total = self.main_pane.winfo_height()
            if total > 0:
                # Keep downloads visible by default; user can drag handle.
                self.main_pane.sashpos(0, int(total * 0.58))
        except Exception:
            pass

    def _on_top_content_configure(self, _event=None):
        try:
            self.top_canvas.configure(scrollregion=self.top_canvas.bbox('all'))
        except Exception:
            pass

    def _on_top_canvas_configure(self, event):
        try:
            self.top_canvas.itemconfigure(self._top_window, width=event.width)
        except Exception:
            pass

    def _on_top_mousewheel(self, event):
        try:
            if event.delta > 0:
                self.top_canvas.yview_scroll(-1, 'units')
            elif event.delta < 0:
                self.top_canvas.yview_scroll(1, 'units')
        except Exception:
            pass
        return "break"

    def _on_list_frame_configure(self, _event=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        except Exception:
            pass

    def _on_canvas_configure(self, event):
        try:
            self.canvas.itemconfigure(self._list_window, width=event.width)
        except Exception:
            pass

    def _on_download_mousewheel(self, event):
        try:
            if event.delta > 0:
                self.canvas.yview_scroll(-1, 'units')
            elif event.delta < 0:
                self.canvas.yview_scroll(1, 'units')
        except Exception:
            pass
        return "break"

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

    def show_logs(self, event=None):
        try:
            lw = getattr(self.root, "_log_window", None)
            if lw:
                lw.deiconify(); lw.lift()
        except Exception:
            pass
        return "break"


if __name__ == '__main__':
    root = tk.Tk()
    app = Music2MP3GUI(root)
    root.mainloop()
