# CLAUDE.md — Music2MP3

> Guide pour Claude Code (et tout autre agent IA) qui contribue à ce repo.
> **Lis ce fichier en entier avant toute modification.**
> Si tu modifies l'archi ou la direction visuelle, **mets à jour ce fichier d'abord**.

---

## 1. Le projet en 30 secondes

**Music2MP3** est une app desktop Python (macOS) qui permet à un DJ d'importer ses playlists Spotify / SoundCloud / CSV, de les télécharger en MP3 propres et de les exporter au format DJ-ready (M3U + tags ID3 + filtres anti-long-sets).

**Public cible** : DJs / passionnés de musique qui veulent une bibliothèque locale propre à partir de leurs playlists streaming.

**Statut** : MVP fonctionnel. Refonte UI en cours vers une identité visuelle cyberpunk.

---

## 2. Stack technique (état actuel du projet)

| Composant | Choix | Notes |
|---|---|---|
| **Langage** | Python 3.14 | Très récent — attention à la compat des libs |
| **UI** | PySide6 (Qt6) | Pas PyQt. Licence LGPL ok pour distrib |
| **Download engine** | yt-dlp | Bundled dans le `.app` |
| **Audio processing** | ffmpeg | Bundled (libmp3lame, libavcodec…) |
| **Credentials** | keyring 25.7+ | Pour stocker les tokens Spotify |
| **Bundle macOS** | PyInstaller + mypyc | Compilation native partielle pour perfs/protection |
| **Format de sortie** | `.app` macOS arm64 | Single-file bundle |

### Dépendances tierces présentes dans le bundle
- `yt-dlp` (download YouTube/SoundCloud)
- `certifi`, `charset_normalizer` (réseau)
- `setuptools`, `shiboken6` (Qt bindings runtime)
- `ffmpeg` + libs (`libmp3lame`, `libavcodec`, `libx264`, `libopus`, etc.)

### Configuration par défaut (`config.json`)
```json
{
  "spotify_client_id": "<CLIENT_ID>",
  "variants": [],
  "duration_min": 30,
  "duration_max": 600,
  "output_format": "mp3",
  "transcode_mp3": false,
  "generate_m3u": true,
  "exclude_instrumentals": false,
  "concurrency": 6,
  "deep_search": true,
  "incremental_update": true,
  "prefix_numbers": false
}
```

### ⚠️ Sécurité — points d'attention

- **`spotify_client_id`** est embedded dans le bundle. C'est OK pour Spotify (les Client IDs sont semi-publics dans le flow OAuth PKCE).
- **PAS de `client_secret`** côté client. Si l'app utilise OAuth, c'est obligatoirement le flow **Authorization Code with PKCE** (sans secret), pas le Client Credentials Flow.
- Les **tokens utilisateur** vont dans `keyring` (Keychain macOS), jamais dans `config.json` ou les logs.

---

## 3. Identité visuelle — Cyberpunk / Synthwave

L'app a une identité visuelle **forte et assumée** : cyberpunk néon. C'est un choix volontaire pour se démarquer des outils musicaux génériques (vert Spotify, gris Apple Music). **Ne pas dévier de cette direction sans validation.**

### Palette

| Rôle | Couleur | Hex | Usage |
|---|---|---|---|
| **Primary / Action** | Magenta néon | `#FF006E` | Bouton Convert, état "en cours", playlist sélectionnée |
| **Secondary / Accent** | Cyan électrique | `#00F5FF` | Flags actifs, navigation, séparateurs, labels tech |
| **Success** | Vert mint | `#4FE6BF` | État Done, scores ≥ 90% |
| **Warning** | Jaune néon | `#FFC857` | Scores 60-89%, alertes non bloquantes |
| **Error** | Rouge | `#FF3355` | Erreurs, échecs (rare, distinct du magenta) |
| **Background primary** | Quasi-noir bleuté | `#06070D` | Fond principal |
| **Background sidebar** | Plus sombre | `#03040A` | Sidebar gauche |
| **Background elevated** | `rgba(0,245,255,0.04)` | — | Cards, root folder box |
| **Text primary** | Blanc bleuté | `#E8F4FF` | Texte principal (jamais blanc pur) |
| **Text secondary** | `rgba(232,244,255,0.55)` | — | Texte secondaire |
| **Text tech / mono** | Cyan dimmed | `rgba(0,245,255,0.55)` | Labels uppercase, monospace |

### Gradients signature

- **Action gradient** : `linear-gradient(135deg, #FF006E, #00F5FF)` — bouton Convert, artwork de la playlist sélectionnée, barre de progression
- **Hero gradient** : `linear-gradient(135deg, rgba(255,0,110,0.32) 0%, rgba(123,0,255,0.18) 45%, rgba(0,245,255,0.22) 100%)` — header de la playlist active

### Effets

- **Glow** : `QGraphicsDropShadowEffect` néon sur les éléments actifs (magenta `0 0 20px rgba(255,0,110,0.4)`, cyan idem)
- **Grid overlay** : grille subtile dans le hero (32px × 32px, opacité 0.05) — peinte au `paintEvent`
- **Orbes** : radial-gradients décoratifs en arrière-plan du hero — peints au `paintEvent` avec `QRadialGradient`
- **Pas de drop shadow classique** (pas réaliste, casse le feel néon)

### Typographie

- **Famille principale** : système (San Francisco sur macOS, Segoe UI sur Windows, Inter en fallback)
- **Famille mono** : SF Mono / JetBrains Mono / Menlo — pour paths, scores, timings, formats
- **Tailles** :
  - Hero title : 36px / weight 500 / letter-spacing -0.5px
  - Section labels : 10px / uppercase / letter-spacing 1.5px
  - Body : 13px
  - Tech values : 11px mono
- **Casse** : UPPERCASE pour les labels système, sentence case pour le contenu user
- **Préfixes `//`** : pour les labels de section style commentaire de code — `// library`, `// flags`, `// add_source`

### Coins (border-radius)

- Cards et boutons : **4px** (angulaire, tech)
- Pills d'options : **3px**
- **Pas** de pills full-rounded (999px) — trop "soft", casse le feel cyberpunk
- **Exception** : barre de progression et indicateurs ronds (dots de status)

### Checkboxes / pills d'options

Style "CLI" : `[x] flag_name` (activé) / `[ ] flag_name` (désactivé), en UPPERCASE letter-spaced, avec border cyan si actif.

---

## 4. Architecture UI

### Layout général

```
┌────────────────────────────────────────────────────────┐
│  TopBar (logo + status online + logs + settings)       │
├──────────────┬─────────────────────────────────────────┤
│              │  HeroHeader (gradient, artwork, infos)  │
│   Sidebar    ├─────────────────────────────────────────┤
│   (240px)    │  ActionBar (Convert · Stop · Sync)      │
│              ├─────────────────────────────────────────┤
│  - Add from  │  OptionsBar (pills cyan)                │
│    (4 cards) ├─────────────────────────────────────────┤
│  - Library   │                                         │
│  - Root dir  │  TrackList                              │
│              │                                         │
│              ├─────────────────────────────────────────┤
│              │  FooterProgress (sticky, gradient bar)  │
└──────────────┴─────────────────────────────────────────┘
```

### Composants principaux à créer/maintenir

- **`MainWindow`** (`QMainWindow`) — conteneur principal, applique le QSS global
- **`Sidebar`** (`QWidget`, 240px fixe) — navigation et sources
- **`AddSourceGrid`** — 4 cartes cliquables (Spotify / SoundCloud / CSV / Local scan) qui ouvrent une `AddSourceDialog`
- **`PlaylistList`** — liste verticale de `PlaylistItem` avec artwork généré
- **`PlaylistArtwork`** (`QWidget` custom) — `paintEvent` qui peint un `QLinearGradient` dont les 2 couleurs sont dérivées d'un `hashlib.md5(playlist.name)` → vibrancy stable et reproductible
- **`HeroHeader`** — `paintEvent` custom : gradient principal + grid pattern + 2 orbes radiaux
- **`GlowButton`** — `QPushButton` avec `QGraphicsDropShadowEffect` magenta
- **`OptionPill`** — `QPushButton` checkable, style `[x]`/`[ ]` selon état
- **`TrackTable`** — `QTableView` + modèle custom + delegate pour les badges de match score colorés
- **`NeonProgressBar`** — `QProgressBar` avec QSS gradient magenta→cyan
- **`AddSourceDialog`** (`QDialog`) — modal qui apparaît au click sur une source, contient le QLineEdit pour l'URL et un bouton "Load"

### Structure de fichiers recommandée

```
music2mp3/
├── __main__.py                 # entry point
├── main_window.py
├── ui/
│   ├── sidebar.py
│   ├── hero_header.py
│   ├── track_table.py
│   ├── widgets/
│   │   ├── playlist_artwork.py
│   │   ├── glow_button.py
│   │   ├── option_pill.py
│   │   └── neon_progress.py
│   └── dialogs/
│       └── add_source.py
├── core/                       # logique métier
│   ├── sources/
│   │   ├── spotify.py          # spotipy + OAuth PKCE
│   │   ├── soundcloud.py
│   │   ├── csv_source.py
│   │   └── local_scan.py
│   ├── downloader.py           # wrapper yt-dlp
│   ├── library.py              # gestion bibliothèque locale
│   ├── matching.py             # algo de match score
│   └── m3u.py                  # génération M3U
├── models/                     # dataclasses
│   ├── playlist.py
│   ├── track.py
│   └── status.py               # enum DownloadStatus
├── styles/
│   ├── theme.qss               # QSS global
│   └── colors.py               # constantes Python des couleurs
├── resources/
│   ├── icons/
│   └── icon.icns
├── config.json                 # config par défaut
├── pyproject.toml
└── Music2MP3.spec              # PyInstaller
```

---

## 5. Modèle de données

### Dataclasses

```python
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from datetime import datetime

class DownloadStatus(Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

class Source(Enum):
    SPOTIFY = "spotify"
    SOUNDCLOUD = "soundcloud"
    CSV = "csv"
    LOCAL = "local"

@dataclass
class Track:
    artist: str
    title: str
    album: str | None = None
    duration_s: int | None = None
    isrc: str | None = None        # International Standard Recording Code
    spotify_id: str | None = None
    match_score: int | None = None  # 0-100
    status: DownloadStatus = DownloadStatus.QUEUED
    file_path: Path | None = None
    error: str | None = None

@dataclass
class Playlist:
    id: str
    name: str
    source: Source
    source_url: str | None
    tracks: list[Track]
    last_synced: datetime | None = None
```

### État applicatif

- **`LibraryManager`** (singleton) — détient toutes les playlists, émet des signaux Qt à chaque changement
- **`DownloadManager`** — gère les workers `QThread`, émet `track_status_changed`, `progress_updated`
- **L'UI ne stocke jamais d'état métier**, elle s'abonne aux signaux

---

## 6. Comportement attendu

### Au démarrage
1. Charger `config.json` (créer avec defaults si absent)
2. Scanner le `root_dir` configuré (si défini) pour reconstruire la library locale
3. Afficher la sidebar avec les playlists trouvées

### Quand l'utilisateur clique "Add from Spotify"
1. Ouvrir `AddSourceDialog` avec un champ URL
2. Au submit, valider l'URL (regex `open.spotify.com/playlist/...`)
3. Si pas de token Spotify en cache : lancer le flow OAuth PKCE
4. Fetcher la playlist via spotipy
5. Créer un objet `Playlist`, l'ajouter à la library, l'afficher dans la sidebar
6. La sélectionner automatiquement

### Quand l'utilisateur sélectionne une playlist
1. Le `HeroHeader` se met à jour avec un gradient dérivé de l'artwork de la playlist (mêmes 2 couleurs)
2. La `TrackTable` se peuple avec les tracks
3. Le bouton Convert affiche `Convert · N`
4. Si la playlist a déjà été partiellement téléchargée (incremental), les tracks Done s'affichent direct avec leur badge vert mint

### Quand l'utilisateur clique Convert
1. Le bouton se transforme en "Pause" (gradient cyan→magenta inversé)
2. La `FooterProgress` apparaît / s'active
3. Le `DownloadManager` lance N workers (`concurrency` de la config, default 6)
4. Pour chaque track :
   - **Recherche** : query yt-dlp avec `f"ytsearch:{artist} {title}"`
   - **Filtre durée** : skip si durée hors [`duration_min`, `duration_max`] (anti-long-sets)
   - **Filtre instrumental** : si `exclude_instrumentals=true`, skip si "instrumental" dans le titre
   - **Score de match** : pondération sur titre, artiste, durée (algo dans `core/matching.py`)
   - **Deep search** : si `deep_search=true` et premier résultat < 70% de match, essayer SoundCloud en fallback
   - **Download** : yt-dlp avec post-processor mp3 320kbps
   - **Tag ID3** : mutagen — title, artist, album, track number si `prefix_numbers`
   - **Status** : émettre signal pour mettre à jour l'UI
5. Une fois fini, si `generate_m3u=true` : créer le `.m3u8` dans le root dir

### Stop
- Annule immédiatement les workers (pas de "soft stop")
- Les tracks `DOWNLOADING` repassent en `QUEUED`
- Le fichier partiel est supprimé

---

## 7. Règles de code

### PySide6 — bonnes pratiques

```python
# Bon
from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import Signal, Slot, QThread

# Mauvais
from PyQt5.QtWidgets import QPushButton  # pas PyQt
import PySide6  # import du package entier
```

### Threading

- **Toute opération > 50ms** passe par `QThread` + worker `QObject`
- yt-dlp est **synchrone et lent** → toujours dans un worker
- Utiliser `QtConcurrent` ou un `QThreadPool` pour les downloads parallèles
- Communication worker → UI via signals/slots uniquement (jamais d'accès direct aux widgets depuis un thread)

```python
class DownloadWorker(QObject):
    progress = Signal(str, int)        # track_id, percent
    finished = Signal(str, Path)       # track_id, file_path
    failed = Signal(str, str)          # track_id, error

    @Slot(Track)
    def download(self, track: Track) -> None:
        ...
```

### QSS

- Tout le styling passe par `styles/theme.qss`
- **Pas de `setStyleSheet()` inline** sauf cas exceptionnels (états dynamiques type "playlist sélectionnée")
- Les couleurs sont **aussi** dans `styles/colors.py` pour les usages Python (`QColor`, `QLinearGradient` dans paintEvents)
- Si tu changes une couleur, change-la dans **les deux fichiers** (sinon désynchro)

### Naming

- Classes : `PascalCase` (`PlaylistArtwork`)
- Fonctions / variables : `snake_case` (`load_playlist`)
- Constantes : `UPPER_SNAKE` (`PRIMARY_MAGENTA`)
- Signals : `verb_noun` (`playlist_selected`, `download_finished`)
- Fichiers : `snake_case.py`

### Logging

- **Pas de `print()`** en prod — utiliser `logging`
- Le panel "Logs" en haut à droite affiche le `logging` handler en temps réel
- Niveaux : `DEBUG` pour le détail, `INFO` pour les events utilisateur, `WARNING` pour les retry, `ERROR` pour les échecs
- Activer `DEBUG` via `MUSIC2MP3_DEBUG=1`

---

## 8. Build & distribution

### Dev local
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m music2mp3
```

### Build macOS (.app)
```bash
pyinstaller Music2MP3.spec
# génère dist/Music2MP3.app
```

Le `.spec` doit inclure :
- `--windowed` (pas de console)
- Bundle de `ffmpeg` dans `Frameworks/`
- Bundle de yt-dlp + ses dépendances
- Icon `.icns`
- `Info.plist` avec `NSHighResolutionCapable=true`

### Compilation mypyc (optionnel)

Pour la prod, compilation des modules `core/` avec mypyc → speedup + protection light du code.
**Ne pas** mypyc-compiler les modules UI (incompatibilités fréquentes avec Qt).

```bash
mypyc music2mp3/core/
```

---

## 9. Anti-patterns à éviter

- **Pas** de vert Spotify (`#1DB954`) ailleurs que sur le petit dot indiquant "source = Spotify". C'est la marque de Spotify, pas l'identité de l'app.
- **Pas** de `border-radius > 8px` (sauf pills de progression ronds) — casse le feel angulaire/tech.
- **Pas** de `#FFFFFF` blanc pur — toujours `#E8F4FF` (blanc bleuté).
- **Pas** de `print()` pour le debug en prod — `logging` only.
- **Pas** d'appels réseau ou yt-dlp dans le main thread — bloque l'UI et casse les animations néon.
- **Pas** d'emojis dans l'UI — préférer des SVG icons ou caractères ASCII (`▸`, `●`, `○`, `↓`, `■`).
- **Pas** de gradients pastel ou couleurs douces — la palette est saturée et contrastée par design.
- **Pas** de Title Case pour les labels — soit UPPERCASE (système) soit sentence case (contenu).
- **Pas** de tokens / secrets dans `config.json` ou les logs — `keyring` only.
- **Pas** de PyQt5 ou PyQt6 — `PySide6` only (cohérence + licence LGPL).
- **Pas** de mypyc sur les modules `ui/` — bugs Qt fréquents, peu de gain perf.

---

## 10. Quand tu n'es pas sûr

- **Sur le design** : reste fidèle aux mockups et à la palette section 3. Demande validation avant d'introduire une nouvelle couleur ou un nouveau pattern.
- **Sur l'archi** : préfère ajouter un widget custom plutôt que polluer un widget existant.
- **Sur les perfs** : si une opération peut bloquer > 50ms, elle passe en `QThread`.
- **Sur les libs** : ne pas ajouter de dépendance lourde sans valider — on reste sur **PySide6 + stdlib + libs métier déjà en place** (yt-dlp, mutagen, spotipy, keyring).
- **Sur la sécu** : tout ce qui touche aux tokens / OAuth / credentials passe par `keyring`. Si tu hésites, demande.
- **Sur Python 3.14** : c'est très récent. Si une lib pose problème, vérifier le support 3.14 avant de fight avec.

---

## 11. Workflow de contribution

1. **Avant de coder** : relire la section concernée de ce fichier
2. **Si tu changes l'archi ou la direction visuelle** : update ce fichier **en premier**
3. **Commits** : préfixe le scope (`ui:`, `core:`, `build:`, `docs:`)
4. **Tests** : pour `core/`, pytest avec mocks de yt-dlp / spotipy
5. **Avant un build** : `python -m music2mp3` doit fonctionner en dev sans erreur

---

## 12. Variables d'env

- `SPOTIFY_CLIENT_ID` — override le Client ID du `config.json`
- `MUSIC2MP3_DEBUG=1` — active le logging DEBUG
- `MUSIC2MP3_CONFIG=/path/to/config.json` — utilise un autre fichier de config
- `MUSIC2MP3_ROOT=/path/to/library` — override le root dir

---

*Direction visuelle cyberpunk validée — voir `/docs/mockup-cyberpunk.png` pour la référence.*
*Stack actuelle : Python 3.14 + PySide6 + yt-dlp + ffmpeg, build PyInstaller + mypyc.*
*Dernière mise à jour : refonte UI v2 — sidebar avec sources, hero header, palette néon.*