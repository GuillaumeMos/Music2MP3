# gui.py
import os
import csv
import platform
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk

from config import load_config, resource_path
from utils import Tooltip, DEFAULT_DROP_BG, LOADED_DROP_BG, open_folder
from converter import Converter
from spotify_api import SpotifyClient
from spotify_auth import PKCEAuth  # PKCE: login utilisateur (pas de secret)


class Spotify2MP3GUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('Spotify2MP3')
        self.root.geometry('540x650')
        self.root.minsize(300, 500)

        # state
        self.csv_path: str | None = None
        self.output_folder: str | None = None
        self.last_output_dir: str | None = None
        self._loaded_playlist_name_from_spotify: str | None = None
        self.config = load_config()

        # default directory (Downloads)
        if platform.system() == "Windows":
            self.last_directory = os.path.join(os.path.expanduser("~"), "Downloads")
        else:
            self.last_directory = os.path.expanduser("~/Downloads")

        # UI
        self._build_ui()
        self._load_icons()

    # ------------------ UI building ------------------

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
            # no icon available
            pass

    def _build_ui(self):
        instr = tk.Label(
            self.root,
            text='1) Glissez un CSV (Exportify/TuneMyMusic) ou collez un lien Spotify',
            font=("Arial", 12)
        )
        instr.pack(fill='x', padx=20, pady=(10, 0))

        # CSV drop/browse
        tk.Label(self.root, text='CSV de playlist :', anchor='w').pack(fill='x', padx=20)
        self.drop_frame = tk.Frame(self.root, bg=DEFAULT_DROP_BG, height=60, width=400)
        self.drop_frame.pack(pady=5, padx=20)
        self.drop_frame.pack_propagate(False)
        self.drop_label = tk.Label(
            self.drop_frame,
            text='CSV file: None',
            bg=DEFAULT_DROP_BG,
            font=("Arial", 12),
            wraplength=380,
            justify='center'
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
        self.progress = ttk.Progressbar(self.root, orient='horizontal', length=500, mode='determinate')
        self.progress.pack(pady=10)

        # open output folder
        self.open_folder_btn = tk.Button(self.root, text='Ouvrir le dossier de sortie', command=self.open_output_folder)
        self.open_folder_btn.pack(pady=5)
        Tooltip(self.open_folder_btn, 'Ouvre le dossier contenant les fichiers convertis.')

    # ------------------ Spotify loader (PKCE + CSV enrichi) ------------------

    def load_from_spotify_link_wrapper(self):
        """
        Auth PKCE (pas de secret), charge la playlist (privée/publique),
        génère un CSV TEMPORAIRE enrichi (colonnes complètes) et branche self.csv_path.
        Nécessite:
          - spotify_auth.PKCEAuth
          - spotify_api.SpotifyClient.fetch_playlist_detailed(...)
          - config.json avec "spotify_client_id"
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

        try:
            # UI: busy
            self.root.config(cursor='watch')
            self.convert_button.config(state=tk.DISABLED)
            self.clear_button.config(state=tk.DISABLED)
            self.spotify_load_btn.config(state=tk.DISABLED)
            self.status_label.config(text='Ouverture du navigateur pour autorisation Spotify…')

            # Auth PKCE (scopes pour playlists privées/collab)
            auth = PKCEAuth(
                client_id=client_id,
                redirect_uri="http://127.0.0.1:8765/callback",
                scopes=["playlist-read-private", "playlist-read-collaborative"]
            )
            sp = SpotifyClient(token_supplier=auth.get_token)

            # Récup détaillée (items + audio-features + genres artistes)
            self.status_label.config(text='Récupération détaillée de la playlist Spotify…')
            rows, name = sp.fetch_playlist_detailed(pid)
            if not rows:
                messagebox.showerror('Erreur', 'Aucune piste trouvée.')
                return

            # Écrire le CSV TEMPORAIRE avec les colonnes complètes (comme ton exemple)
            fd, tmp = tempfile.mkstemp(prefix='spotify_playlist_', suffix='.csv')
            os.close(fd)
            fieldnames = [
                "Track URI","Track Name","Album Name","Artist Name(s)","Release Date","Duration (ms)",
                "Popularity","Explicit","Added By","Added At","Genres","Record Label",
                "Danceability","Energy","Key","Loudness","Mode","Speechiness","Acousticness",
                "Instrumentalness","Liveness","Valence","Tempo","Time Signature"
            ]
            with open(tmp, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                w.writeheader()
                w.writerows(rows)

            # Brancher le CSV généré au pipeline existant
            self.csv_path = tmp
            self._loaded_playlist_name_from_spotify = name or "SpotifyPlaylist"
            self.drop_label.config(text=f'CSV (généré) : {os.path.basename(tmp)}')
            self.drop_frame.config(bg=LOADED_DROP_BG)
            self.drop_label.config(bg=LOADED_DROP_BG)
            self.status_label.config(
                text=f'Playlist chargée : {self._loaded_playlist_name_from_spotify} ({len(rows)} titres)'
            )
            self.update_convert_button_state()

        except Exception as e:
            messagebox.showerror('Erreur Spotify', str(e))
        finally:
            # UI: idle
            self.root.config(cursor='')
            self.clear_button.config(state=tk.NORMAL)
            self.spotify_load_btn.config(state=tk.NORMAL)

    # ------------------ Other handlers ------------------

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

    def start_conversion(self):
        if not (self.csv_path and self.output_folder):
            messagebox.showerror('Erreur', 'Sélectionne un CSV et un dossier de sortie.')
            return

        self.convert_button.config(state=tk.DISABLED)
        self.clear_button.config(state=tk.DISABLED)
        self.root.config(cursor='watch')

        try:
            conv = Converter(
                config=self.config,
                status_cb=lambda s: self.status_label.config(text=s),
                progress_cb=lambda cur, maxi: (
                    self.progress.configure(maximum=maxi, value=cur),
                    self.root.update_idletasks()
                )
            )
            playlist_hint = getattr(self, '_loaded_playlist_name_from_spotify', None)
            out_dir = conv.convert_from_csv(self.csv_path, self.output_folder, playlist_hint)
            self.last_output_dir = out_dir
            self.progress['value'] = self.progress['maximum']
            self.status_label.config(text='✅ Conversion terminée')
            self.root.bell()
        except Exception as e:
            messagebox.showerror('Erreur', f'Erreur inattendue: {e}')
        finally:
            self.root.config(cursor='')
            self.convert_button.config(state=tk.NORMAL)
            self.clear_button.config(state=tk.NORMAL)
