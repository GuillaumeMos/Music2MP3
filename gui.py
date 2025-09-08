# gui.py
import os
import csv
import platform
import tempfile
import threading
import queue
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk

from config import load_config, resource_path
from utils import Tooltip, DEFAULT_DROP_BG, LOADED_DROP_BG, open_folder
from converter import Converter
from spotify_api import SpotifyClient
from spotify_auth import PKCEAuth  # PKCE: pas de secret, login utilisateur


class Spotify2MP3GUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('Spotify2MP3')
        self.root.geometry('560x680')
        self.root.minsize(340, 520)

        # state
        self.csv_path: str | None = None
        self.output_folder: str | None = None
        self.last_output_dir: str | None = None
        self._loaded_playlist_name_from_spotify: str | None = None
        self.config = load_config()

        # workers
        self._conv_thread: threading.Thread | None = None
        self._conv_q: queue.Queue | None = None
        self._conv_done = False

        self._sp_thread: threading.Thread | None = None
        self._sp_q: queue.Queue | None = None
        self._sp_done = False

        # last dir (Downloads)
        if platform.system() == "Windows":
            self.last_directory = os.path.join(os.path.expanduser("~"), "Downloads")
        else:
            self.last_directory = os.path.expanduser("~/Downloads")

        self._build_ui()
        self._load_icons()

    # ------------------ UI helpers ------------------

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
            pass  # pas d'icône dispo

    def _set_controls_enabled(self, enabled: bool):
        # Active/désactive les contrôles pendant un travail
        state = tk.NORMAL if enabled else tk.DISABLED
        for w in (
            self.convert_button,
            self.clear_button,
            self.folder_button,
            self.spotify_load_btn,
            self.drop_label,
            self.spotify_entry,
        ):
            try:
                w.config(state=state)
            except Exception:
                pass

    def _start_indeterminate(self, text: str):
        self.status_label.config(text=text)
        # configure en mode indéterminé (marquee)
        self.progress.configure(mode='indeterminate')
        # démarrer l'animation
        try:
            self.progress.start(80)  # interval ms
        except tk.TclError:
            pass

    def _stop_indeterminate(self):
        try:
            self.progress.stop()
        except tk.TclError:
            pass
        self.progress.configure(mode='determinate')

    # ------------------ UI building ------------------

    def _build_ui(self):
        instr = tk.Label(
            self.root,
            text='1) Glissez un CSV (Exportify/TuneMyMusic) ou collez un lien Spotify',
            font=("Arial", 12)
        )
        instr.pack(fill='x', padx=20, pady=(12, 0))

        # CSV drop/browse
        tk.Label(self.root, text='CSV de playlist :', anchor='w').pack(fill='x', padx=20)
        self.drop_frame = tk.Frame(self.root, bg=DEFAULT_DROP_BG, height=64, width=420)
        self.drop_frame.pack(pady=6, padx=20)
        self.drop_frame.pack_propagate(False)
        self.drop_label = tk.Label(
            self.drop_frame,
            text='CSV file: None',
            bg=DEFAULT_DROP_BG,
            font=("Arial", 12),
            wraplength=400,
            justify='center',
            cursor='hand2'
        )
        self.drop_label.pack(expand=True, fill='both')
        self.drop_label.bind('<Button-1>', self.browse_csv)
        Tooltip(self.drop_label, 'Dépose ton CSV ici ou clique pour parcourir.')

        # clear CSV
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
        row = tk.Frame(self.root)
        row.pack(fill='x', padx=20)
        tk.Label(row, text='URL:').pack(side='left')
        self.spotify_entry = tk.Entry(row)
        self.spotify_entry.pack(side='left', fill='x', expand=True, padx=(5, 8))
        self.spotify_load_btn = tk.Button(row, text='Charger depuis Spotify', command=self.load_from_spotify_link_wrapper)
        self.spotify_load_btn.pack(side='left')
        Tooltip(self.spotify_load_btn, "Ouvre le navigateur pour l'autorisation (PKCE), puis charge la playlist.")

        # convert
        self.convert_button = tk.Button(self.root, text='3) Convertir', command=self.start_conversion, state=tk.DISABLED, font=('Arial', 14))
        self.convert_button.pack(pady=10)

        # status + progress
        tk.Label(self.root, text='4) Actions :', anchor='w').pack(fill='x', padx=20, pady=(10, 0))
        self.status_label = tk.Label(self.root, text='Status: Waiting...', anchor='w', font=('Arial', 12))
        self.status_label.pack(fill='x', padx=20)
        self.progress = ttk.Progressbar(self.root, orient='horizontal', length=520, mode='determinate')
        self.progress.pack(pady=10)

        # open output folder
        self.open_folder_btn = tk.Button(self.root, text='Ouvrir le dossier de sortie', command=self.open_output_folder)
        self.open_folder_btn.pack(pady=5)
        Tooltip(self.open_folder_btn, 'Ouvre le dossier contenant les fichiers convertis.')

    # ------------------ Spotify loader (PKCE, CSV simple) ------------------

    def load_from_spotify_link_wrapper(self):
        """
        Auth PKCE (pas de secret), charge la playlist (privée/publique),
        génère un CSV TEMPORAIRE minimal et branche self.csv_path.
        Colonnes: Track Name, Artist Name(s), Album Name, Duration (ms)
        """
        url = self.spotify_entry.get().strip()
        pid = SpotifyClient.extract_playlist_id(url)
        if not pid:
            messagebox.showerror('Erreur', 'Lien de playlist invalide.')
            return

        client_id = self.config.get('spotify_client_id')
        if not client_id:
            messagebox.showerror(
                'Manque Client ID',
                'Ajoute "spotify_client_id" dans config.json (PKCE ne nécessite pas de secret).'
            )
            return

        # Lancer le worker Spotify (auth + fetch) en thread → UI fluide
        self._sp_q = queue.Queue()
        self._sp_done = False
        self._set_controls_enabled(False)
        self.progress.configure(value=0, maximum=100)
        self._start_indeterminate("Ouverture du navigateur pour autorisation Spotify…")

        def _spotify_worker():
            try:
                auth = PKCEAuth(
                    client_id=client_id,
                    redirect_uri="http://127.0.0.1:8765/callback",
                    scopes=["playlist-read-private", "playlist-read-collaborative"]
                )
                # Le get_token peut prendre un peu de temps → thread
                token_supplier = auth.get_token
                sp = SpotifyClient(token_supplier=token_supplier)

                self._sp_q.put(('status', 'Récupération de la playlist Spotify…'))
                rows, name = sp.fetch_playlist(pid)  # version simple (stable)
                if not rows:
                    self._sp_q.put(('error', 'Aucune piste trouvée.'))
                    return

                # écrire un CSV temporaire
                fd, tmp = tempfile.mkstemp(prefix='spotify_playlist_', suffix='.csv')
                os.close(fd)
                fieldnames = ["Track Name", "Artist Name(s)", "Album Name", "Duration (ms)"]
                with open(tmp, 'w', newline='', encoding='utf-8') as f:
                    w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                    w.writeheader()
                    w.writerows(rows)

                self._sp_q.put(('done', (tmp, name, len(rows))))
            except Exception as e:
                self._sp_q.put(('error', str(e)))

        self._sp_thread = threading.Thread(target=_spotify_worker, daemon=True)
        self._sp_thread.start()
        self.root.after(100, self._poll_spotify_queue)

    def _poll_spotify_queue(self):
        if not self._sp_q:
            return
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
                    self.drop_frame.config(bg=LOADED_DROP_BG)
                    self.drop_label.config(bg=LOADED_DROP_BG)
                    self.status_label.config(text=f'Playlist chargée : {self._loaded_playlist_name_from_spotify} ({n} titres)')
                    self._stop_indeterminate()
                    self._set_controls_enabled(True)
                    self.update_convert_button_state()
                    self._sp_done = True
                elif kind == 'error':
                    self._stop_indeterminate()
                    self._set_controls_enabled(True)
                    messagebox.showerror('Erreur Spotify', payload)
                    self._sp_done = True
        except queue.Empty:
            pass

        if self._sp_thread and self._sp_thread.is_alive() and not self._sp_done:
            self.root.after(100, self._poll_spotify_queue)

    # ------------------ File handlers ------------------

    def browse_csv(self, event=None):
        path = filedialog.askopenfilename(
            initialdir=self.last_directory,
            filetypes=[('CSV files', '*.csv')]
        )
        if path:
            self.csv_path = path
            self.last_directory = os.path.dirname(path)
            self.drop_label.config(text=f'CSV file: {os.path.basename(path)}')
            self.drop_frame.config(bg=LOADED_DROP_BG)
            self.drop_label.config(bg=LOADED_DROP_BG)
            self.status_label.config(text='CSV chargé.')
            self._loaded_playlist_name_from_spotify = None
            self.update_convert_button_state()

    def clear_selection(self):
        self.csv_path = None
        self.drop_label.config(text='CSV file: None')
        self.status_label.config(text='Status: Waiting...')
        self.drop_frame.config(bg=DEFAULT_DROP_BG)
        self.drop_label.config(bg=DEFAULT_DROP_BG)
        self.progress['value'] = 0
        self._loaded_playlist_name_from_spotify = None
        self.update_convert_button_state()

    def select_output_folder(self):
        path = filedialog.askdirectory(initialdir=self.last_directory)
        if path:
            self.output_folder = path
            self.last_directory = path
            self.output_label.config(text=f'Output folder: {path}')
            self.status_label.config(text='Dossier de sortie sélectionné.')
            self.update_convert_button_state()

    def open_output_folder(self):
        target = self.last_output_dir or self.output_folder
        if not open_folder(target):
            messagebox.showerror('Erreur', 'Aucun dossier valide à ouvrir.')

    def update_convert_button_state(self):
        ok = (
            self.csv_path
            and os.path.isfile(self.csv_path)
            and self.csv_path.lower().endswith('.csv')
            and self.output_folder
        )
        self.convert_button.config(state=tk.NORMAL if ok else tk.DISABLED)
        self.clear_button.config(state=tk.NORMAL if self.csv_path else tk.DISABLED)

    # ------------------ Non-blocking conversion (worker thread) ------------------

    def start_conversion(self):
        if not (self.csv_path and self.output_folder):
            messagebox.showerror('Erreur', 'Sélectionne un CSV et un dossier de sortie.')
            return

        # Prépare l’UI
        self._set_controls_enabled(False)
        self.status_label.config(text='Démarrage de la conversion…')
        self.progress.configure(value=0, maximum=100, mode='determinate')

        # Queue + thread
        self._conv_q = queue.Queue()
        self._conv_done = False
        self._conv_thread = threading.Thread(target=self._run_conversion_worker, daemon=True)
        self._conv_thread.start()
        self.root.after(100, self._poll_conversion_queue)

    def _run_conversion_worker(self):
        """
        Thread de fond : lance Converter.convert_from_csv et envoie des events dans la queue.
        NE JAMAIS toucher aux widgets Tk dans ce thread !
        """
        try:
            conv = Converter(
                config=self.config,
                status_cb=lambda s: self._conv_q.put(('status', s)),
                progress_cb=lambda cur, maxi: self._conv_q.put(('progress', (cur, maxi)))
            )
            playlist_hint = getattr(self, '_loaded_playlist_name_from_spotify', None)
            out_dir = conv.convert_from_csv(self.csv_path, self.output_folder, playlist_hint)
            self._conv_q.put(('done', out_dir))
        except Exception as e:
            self._conv_q.put(('error', str(e)))

    def _poll_conversion_queue(self):
        if not self._conv_q:
            return
        try:
            while True:
                kind, payload = self._conv_q.get_nowait()
                if kind == 'status':
                    self.status_label.config(text=payload)
                elif kind == 'progress':
                    cur, maxi = payload
                    if self.progress['maximum'] != maxi:
                        self.progress.configure(maximum=maxi)
                    self.progress.configure(value=cur)
                elif kind == 'done':
                    self.last_output_dir = payload
                    self.progress.configure(value=self.progress['maximum'])
                    self.status_label.config(text='✅ Conversion terminée')
                    self._set_controls_enabled(True)
                    self._conv_done = True
                    self.root.bell()
                elif kind == 'error':
                    messagebox.showerror('Erreur', f'Erreur inattendue: {payload}')
                    self._set_controls_enabled(True)
                    self._conv_done = True
        except queue.Empty:
            pass

        if self._conv_thread and self._conv_thread.is_alive() and not self._conv_done:
            self.root.after(100, self._poll_conversion_queue)
