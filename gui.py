import os, platform, tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk

from config import load_config, resource_path
from utils import Tooltip, DEFAULT_DROP_BG, LOADED_DROP_BG, open_folder
from converter import Converter
from spotify_api import SpotifyClient

class Spotify2MP3GUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('Spotify2MP3')
        self.root.geometry('540x650')
        self.root.minsize(300, 500)

        self.csv_path = None
        self.output_folder = None
        self.last_output_dir = None
        self.config = load_config()
        self._loaded_playlist_name_from_spotify = None

        # dossier par défaut
        if platform.system() == "Windows":
            self.last_directory = os.path.join(os.path.expanduser("~"), "Downloads")
        else:
            self.last_directory = os.path.expanduser("~/Downloads")

        self._build_ui()
        self._load_icons()

    def _load_icons(self):
        try:
            icon_path = resource_path('icon.icns') if platform.system()== 'Darwin' else resource_path('icon.ico')
            if platform.system()== 'Darwin':
                img = tk.PhotoImage(file=icon_path); self.root.iconphoto(True, img)
            else:
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

    def _build_ui(self):
        instr = tk.Label(self.root, text='1) Glissez un CSV (Exportify, TuneMyMusic) ou collez un lien Spotify', font=("Arial", 12))
        instr.pack(fill='x', padx=20, pady=(10,0))

        # Zone drop CSV
        tk.Label(self.root, text='CSV de playlist :', anchor='w').pack(fill='x', padx=20)
        self.drop_frame = tk.Frame(self.root, bg=DEFAULT_DROP_BG, height=60, width=400)
        self.drop_frame.pack(pady=5, padx=20)
        self.drop_frame.pack_propagate(False)
        self.drop_label = tk.Label(self.drop_frame, text='CSV file: None', bg=DEFAULT_DROP_BG, font=("Arial", 12), wraplength=380, justify='center')
        self.drop_label.pack(expand=True, fill='both')
        self.drop_label.bind('<Button-1>', self.browse_csv)
        Tooltip(self.drop_label, 'Dépose ton CSV ici ou clique pour parcourir.')

        # Bouton clear
        self.clear_button = tk.Button(self.root, text='Effacer CSV', command=self.clear_selection, state=tk.DISABLED)
        self.clear_button.pack()

        # Sortie
        tk.Label(self.root, text='2) Dossier de sortie :', anchor='w').pack(fill='x', padx=20)
        self.folder_button = tk.Button(self.root, text='Choisir le dossier', command=self.select_output_folder, font=('Arial', 12))
        self.folder_button.pack(pady=5)
        self.output_label = tk.Label(self.root, text='Output folder: Not selected', anchor='w')
        self.output_label.pack(fill='x', padx=20)

        # Lien Spotify
        tk.Label(self.root, text='ou lien de playlist Spotify :', anchor='w').pack(fill='x', padx=20, pady=(10,0))
        row = tk.Frame(self.root); row.pack(fill='x', padx=20)
        tk.Label(row, text='URL:').pack(side='left')
        self.spotify_entry = tk.Entry(row)
        self.spotify_entry.pack(side='left', fill='x', expand=True, padx=(5,8))
        tk.Button(row, text='Charger depuis Spotify', command=self.load_from_spotify_link_wrapper).pack(side='left')

        # Bouton Convertir
        self.convert_button = tk.Button(self.root, text='3) Convertir', command=self.start_conversion, state=tk.DISABLED, font=('Arial', 14))
        self.convert_button.pack(pady=10)

        # Statut + Progress
        tk.Label(self.root, text='4) Actions :', anchor='w').pack(fill='x', padx=20, pady=(10,0))
        self.status_label = tk.Label(self.root, text='Status: Waiting...', anchor='w', font=('Arial', 12))
        self.status_label.pack(fill='x', padx=20)
        self.progress = ttk.Progressbar(self.root, orient='horizontal', length=500, mode='determinate')
        self.progress.pack(pady=10)

        # Ouvrir dossier
        tk.Button(self.root, text='Ouvrir le dossier de sortie', command=self.open_output_folder).pack(pady=5)

    # --- Handlers ---
    def browse_csv(self, event=None):
        path = filedialog.askopenfilename(initialdir=self.last_directory, filetypes=[('CSV files','*.csv')])
        if path:
            self.csv_path = path
            self.last_directory = os.path.dirname(path)
            self.drop_label.config(text=f'CSV file: {os.path.basename(path)}')
            self.drop_frame.config(bg=LOADED_DROP_BG)
            self.drop_label.config(bg=LOADED_DROP_BG)
            self.status_label.config(text='CSV chargé.')
            self.update_convert_button_state()

    def clear_selection(self):
        self.csv_path = None
        self.drop_label.config(text='CSV file: None')
        self.status_label.config(text='Status: Waiting...')
        self.drop_frame.config(bg=DEFAULT_DROP_BG)
        self.drop_label.config(bg=DEFAULT_DROP_BG)
        self.progress['value'] = 0
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

    def load_from_spotify_link_wrapper(self):
        url = self.spotify_entry.get().strip()
        if not url:
            messagebox.showerror('Erreur', 'Colle un lien de playlist Spotify.'); return
        cid = self.config.get('spotify_client_id'); sec = self.config.get('spotify_client_secret')
        if not (cid and sec):
            messagebox.showerror('Manque Client ID/Secret', 'Renseigne spotify_client_id et spotify_client_secret dans config.json'); return
        pid = SpotifyClient.extract_playlist_id(url)
        if not pid:
            messagebox.showerror('Erreur', 'Lien de playlist invalide.'); return

        try:
            self.root.config(cursor='watch'); self.convert_button.config(state=tk.DISABLED); self.clear_button.config(state=tk.DISABLED)
            self.status_label.config(text='Récupération de la playlist Spotify…')
            client = SpotifyClient(cid, sec)
            rows, name = client.fetch_playlist(pid)
            if not rows:
                messagebox.showerror('Erreur', 'Aucune piste trouvée (playlist privée ?).'); return
            # Écrit un CSV temporaire minimal
            import tempfile, csv
            fd, tmp = tempfile.mkstemp(prefix='spotify_playlist_', suffix='.csv'); os.close(fd)
            with open(tmp, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=["Track Name","Artist Name(s)","Album Name","Duration (ms)"])
                w.writeheader(); w.writerows(rows)
            self.csv_path = tmp
            self._loaded_playlist_name_from_spotify = name
            self.drop_label.config(text=f'CSV (généré) : {os.path.basename(tmp)}')
            self.drop_frame.config(bg=LOADED_DROP_BG); self.drop_label.config(bg=LOADED_DROP_BG)
            self.status_label.config(text=f'Playlist chargée : {name} ({len(rows)} titres)')
            self.update_convert_button_state()
        except Exception as e:
            messagebox.showerror('Erreur Spotify', str(e))
        finally:
            self.root.config(cursor=''); self.clear_button.config(state=tk.NORMAL)

    def update_convert_button_state(self):
        ok = self.csv_path and os.path.isfile(self.csv_path) and self.csv_path.lower().endswith('.csv') and self.output_folder
        self.convert_button.config(state=tk.NORMAL if ok else tk.DISABLED)
        self.clear_button.config(state=tk.NORMAL if self.csv_path else tk.DISABLED)

    def start_conversion(self):
        if not (self.csv_path and self.output_folder):
            messagebox.showerror('Erreur', 'Sélectionne un CSV et un dossier de sortie.'); return
        self.convert_button.config(state=tk.DISABLED); self.clear_button.config(state=tk.DISABLED); self.root.config(cursor='watch')
        try:
            conv = Converter(
                config=self.config,
                status_cb=lambda s: self.status_label.config(text=s),
                progress_cb=lambda cur,maxi: (self.progress.configure(maximum=maxi, value=cur), self.root.update_idletasks())
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
            self.root.config(cursor=''); self.convert_button.config(state=tk.NORMAL); self.clear_button.config(state=tk.NORMAL)