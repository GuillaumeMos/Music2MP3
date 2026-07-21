# AGENTS.md — Music2MP3

> Guide pour Codex (et tout autre agent IA) qui contribue à ce repo.
> **Lis ce fichier en entier avant toute modification.**
> Si tu modifies l'archi ou la direction visuelle, **mets à jour ce fichier d'abord**.

---

## 1. Le projet en 30 secondes

**Music2MP3** est une app desktop Python (macOS / Windows / Linux) qui permet à un DJ d'importer ses playlists Spotify / SoundCloud / CSV, de les télécharger en audio propre et de les exporter au format DJ-ready (M3U + tags ID3 + filtres anti-long-sets).

**Décision produit actuelle** : Bandcamp et Soulseek/slskd restent dans le codebase comme pistes backlog, mais ne font plus partie du chemin produit actif. Ne pas les remettre visibles dans l'UI ou syncables sans validation explicite.

**Public cible** : DJs / passionnés de musique qui veulent une bibliothèque locale propre à partir de leurs playlists streaming.

**Statut** : MVP fonctionnel avec UI Qt sombre, épurée et orientée bibliothèque musicale. L'UI Tkinter legacy (`app.py` + `gui.py`) reste présente mais n'est plus le défaut — le build par défaut cible Qt (`qt_app.py`).

---

## 2. Stack technique (état actuel du projet)

| Composant | Choix | Notes |
|---|---|---|
| **Langage** | Python 3.14 | Très récent — attention à la compat des libs |
| **UI active** | PySide6 (Qt6) — `qt_app.py` | Pas PyQt. Licence LGPL ok pour distrib |
| **UI legacy** | Tkinter — `app.py` + `gui.py` | Maintenu mais non priorisé (`task run:tk`) |
| **Download engine** | yt-dlp | Bundled dans le `.app` |
| **Audio processing** | ffmpeg | Bundled (libmp3lame, libavcodec…) |
| **Credentials** | keyring 25.7+ | Pour stocker les tokens Spotify |
| **Build system** | Taskfile (`Taskfile.yml`) | `task run`, `task build:macos`, etc. |
| **Bundle** | PyInstaller | macOS + Windows + Linux, specs dans `packaging/` |
| **Formats de sortie** | mp3, m4a, aac, wav, flac, aiff | Mode "auto" = meilleure qualité disponible |

### Dépendances (requirements.txt)
- `requests>=2.31.0`
- `tkinterdnd2>=0.3.0` (legacy Tk)
- `keyring>=25.6.0`
- `PySide6>=6.10.3,<6.11` (6.11.1 casse le chargement du plugin Cocoa avec Python 3.14 sur macOS)
- `yt-dlp>=2026.3.17`

### Configuration par défaut (`config.json`)
```json
{
  "spotify_client_id": "<CLIENT_ID>",
  "variants": [],
  "duration_min": 30,
  "duration_max": 600,
  "output_format": "mp3",
  "output_format_manual": "mp3",
  "output_mode": "manual",
  "transcode_mp3": false,
  "generate_m3u": true,
  "exclude_instrumentals": false,
  "concurrency": 6,
  "deep_search": true,
  "safe_search": true,
  "strict_match": false,
  "cookies_path": "",
  "cookies_from_browser": "",
  "cookies_browser_profile": "",
  "ai_match_enabled": false,
  "ai_match_provider": "vertex",
  "ai_match_model": "gemini-2.5-flash",
  "ai_match_gray_min": 0.30,
  "ai_match_min_confidence": 0.72,
  "ai_match_accept_margin": 0.12,
  "ai_match_prompt": "<prompt métier éditable depuis Settings>",
  "slskd_enabled": false,
  "slskd_host": "http://127.0.0.1:5030",
  "slskd_timeout_s": 12.0,
  "slskd_search_timeout_ms": 8000,
  "slskd_result_limit": 12,
  "incremental_update": true,
  "prefix_numbers": false
}
```

**Champs clés :**
- `output_mode` : `"auto"` (yt-dlp choisit la meilleure source) ou `"manual"` (force `output_format_manual`)
- `safe_search` : filtre les variantes indésirables (live, remix, nightcore…) — actif par défaut
- `strict_match` : seuil de score plus élevé (0.58 vs 0.42) avant d'accepter un résultat
- `match_candidates` : nombre max de résultats YouTube à analyser après le fast path; défaut 4
- `youtube_search_timeout_s` : timeout court pour la recherche YouTube; défaut 12s
- `cookies_path` : chemin optionnel vers un `cookies.txt` Netscape transmis à `yt-dlp` pour SoundCloud/YouTube
- `cookies_from_browser` : navigateur optionnel pour `yt-dlp --cookies-from-browser` (`safari`, `chrome`, `firefox`, `brave`, `edge`, etc.)
- `cookies_browser_profile` : profil navigateur optionnel pour `--cookies-from-browser`
- `ai_match_enabled` : active l'aide Google/Vertex quand le matcher local ne trouve pas de résultat fiable ou quand la première recherche ne retourne rien; clé API stockée dans le keychain depuis Settings, jamais dans `config.json`
- `ai_match_min_confidence` : confiance minimale pour qu'une proposition IA soit affichée; défaut 0.72
- `ai_match_accept_margin` : marge maximale sous le seuil heuristique pour afficher une proposition IA; défaut 0.12
- `ai_match_timeout_s` : timeout court pour l'appel Gemini; défaut 6s
- `ai_match_prompt` : consignes métier passées à Gemini pour juger accept/reject/retry; `accept` signifie proposer à l'utilisateur, pas télécharger automatiquement
- `slskd_*` : champs conservés pour backlog Soulseek/slskd; non exposés dans l'UI active.

### ⚠️ Sécurité — points d'attention

- **`spotify_client_id`** est embedded dans le bundle. C'est OK pour Spotify (les Client IDs sont semi-publics dans le flow OAuth PKCE).
- **PAS de `client_secret`** côté client. Si l'app utilise OAuth, c'est obligatoirement le flow **Authorization Code with PKCE** (sans secret), pas le Client Credentials Flow.
- Les **tokens utilisateur** vont dans `keyring` (Keychain macOS), jamais dans `config.json` ou les logs.

---

## 3. Identité visuelle — Sombre, musicale et épurée

La direction validée est une interface **sobre inspirée des applications de streaming musical**, sans reproduire leur marque ni leurs assets. La hiérarchie, la lisibilité et le contenu passent avant les effets décoratifs. L'app utilise des surfaces noires/grises, un accent vert unique et des libellés naturels. **Ne pas réintroduire l'esthétique cyberpunk ou une seconde couleur d'accent sans validation.**

### Palette

| Rôle | Couleur | Hex | Usage |
|---|---|---|---|
| **Primary / Action** | Vert musical | `#1ED760` | Convert, sélection active, progression, focus |
| **Primary hover** | Vert clair | `#3BE477` | Hover des actions principales |
| **Background primary** | Noir doux | `#121212` | Fond principal |
| **Background sidebar** | Noir profond | `#090909` | Sidebar gauche |
| **Background elevated** | Gris sombre | `#181818` | Hero, cards, barres d'action |
| **Background hover** | Gris moyen | `#242424` | Survol et sélection secondaire |
| **Border subtle** | Gris | `#2A2A2A` | Séparateurs discrets uniquement |
| **Text primary** | Blanc doux | `#F5F5F5` | Titres et contenu principal |
| **Text secondary** | Gris clair | `#B3B3B3` | Métadonnées, aide, labels secondaires |
| **Success** | Vert musical | `#1ED760` | Done, scores élevés |
| **Warning** | Ambre | `#F5B942` | Scores moyens, alertes non bloquantes |
| **Error** | Rouge doux | `#E85D75` | Échecs et actions destructives |

### Principes visuels

- **Un seul accent** : le vert signale une action, une sélection ou un succès. Les sources Spotify/SoundCloud/CSV restent neutres hors métadonnées.
- **Pas de décor gratuit** : aucun glow, aucune grille, aucun orbe, aucun dégradé multicolore. Un dégradé noir/gris très subtil est accepté dans le hero pour séparer les niveaux.
- **Hiérarchie calme** : une seule action primaire visible à la fois; les actions secondaires sont grisées et sans bordure forte.
- **Couleur sémantique** : ambre et rouge sont réservés aux warnings/erreurs. Ils ne servent pas à décorer.
- **Respiration** : marges de 12–24 px, lignes plus aérées, séparateurs rares et contraste porté par les surfaces.

### Typographie

- **Famille principale** : système (San Francisco sur macOS, Segoe UI sur Windows, Inter en fallback)
- **Famille mono** : SF Mono / JetBrains Mono / Menlo uniquement pour paths, scores et timings
- **Tailles** :
  - Hero title : 30–34px / weight 700 / letter-spacing -0.4px
  - Section labels : 11–12px / weight 700
  - Body : 13px
  - Valeurs techniques : 11px mono
- **Casse** : sentence case par défaut. Les headers de table peuvent rester courts, mais pas de labels façon terminal.
- **Pas de préfixes `//`**, de snake_case visible, ni de `[x]` / `[ ]` dans les libellés utilisateur.

### Formes et contrôles

- Bouton principal : rayon **18px** environ, fond vert, texte noir, largeur clairement identifiable.
- Boutons secondaires : rayon **6–8px**, fond gris ou transparent, bordures très discrètes.
- Options compactes : rayon **12–14px**, fond gris; état actif vert sombre/vert, sans syntaxe CLI.
- Cards et champs : rayon **6–8px**.
- Les indicateurs ronds sont réservés aux statuts et à la progression.

---

## 4. Architecture UI

### Layout général

```
┌────────────────────────────────────────────────────────┐
│  TopBar (logo + état + logs + settings)                │
├──────────────┬─────────────────────────────────────────┤
│              │  HeroHeader (surface sombre + artwork)  │
│   Sidebar    ├─────────────────────────────────────────┤
│   (240px)    │  ActionBar (Convert · Stop · Sync)      │
│              ├─────────────────────────────────────────┤
│  - Add from  │  OptionsBar (contrôles neutres/verts)   │
│    (4 cards) ├─────────────────────────────────────────┤
│  - Library   │                                         │
│  - Root dir  │  TrackList                              │
│              │                                         │
│              ├─────────────────────────────────────────┤
│              │  FooterProgress (sticky, barre verte)   │
└──────────────┴─────────────────────────────────────────┘
```

### Composants Qt (état actuel)

La fenêtre principale reste dans `qt_app.py` (~3490 lignes), mais les workers Qt sont maintenant isolés dans `qt_workers.py`. Les classes clés :

- **`QtMusic2MP3Window`** (`QMainWindow`) — conteneur principal, QSS global inline (`APP_QSS`)
- **`ArtworkWidget`** (`QWidget`) — artwork de fallback sobre dérivé du nom via `hashlib.md5`
- **`PlaylistItemWidget`** (`QFrame`) — item sidebar, méthode `setSelected()`
- **`HeroWidget`** (`QFrame`) — header de playlist sur surface sombre, sans décor peint
- **`ConverterWorker`** (`QObject`, `qt_workers.py`) — worker Qt pour la conversion, signaux `status/item/done/failed/finished`
- **`PlaylistLoadWorker`** (`QObject`, `qt_workers.py`) — worker pour le fetch Spotify/SoundCloud; Bandcamp est conservé en backlog.
- **`AddSourceDialog`** (`QDialog`) — modal URL pour Spotify / SoundCloud; Bandcamp est conservé en backlog.
- **`SettingsDialog`** (`QDialog`) — panneau de configuration
- **Soulseek/slskd assist** (`slskd_client.py`) — code conservé pour backlog, non exposé dans l'UI active.
- **`VisibleCheckStyle`** (`QProxyStyle`) — style custom pour les checkboxes

### Structure de fichiers actuelle (plate, à la racine)

```
Music2MP3/
├── qt_app.py               # UI Qt principale (~3178 lignes)
├── qt_workers.py           # workers Qt conversion + chargement sources
├── app.py                  # entry point UI Tk (legacy)
├── gui.py                  # UI Tkinter (~1085 lignes, legacy)
├── converter.py            # logique download + matching (~1260 lignes)
├── spotify_api.py          # client Spotify API REST
├── spotify_auth.py         # OAuth PKCE flow
├── soundcloud_api.py       # client SoundCloud via yt-dlp
├── bandcamp_api.py         # client Bandcamp via yt-dlp
├── slskd_client.py         # client slskd API + keychain API key
├── library_attention.py    # agrégation globale des tracks à vérifier
├── library_cleanup.py      # analyse + nettoyage réversible de la bibliothèque
├── library_manifest.py     # scan + manifest JSON de la bibliothèque locale
├── token_store.py          # wrapper keyring
├── config.py               # chargement/sauvegarde config.json
├── logging_setup.py        # configuration du logging
├── log_viewer.py           # widget live log (Tk, utilisé par legacy)
├── utils.py                # utilitaires divers
├── config.json             # config utilisateur
├── requirements.txt        # dépendances Python
├── Taskfile.yml            # build system (task run, task build:macos…)
├── packaging/              # specs PyInstaller (Qt + Tk × macOS/Windows/Linux)
│   ├── Music2MP3-Qt-macOS.spec
│   ├── Music2MP3-Qt-Windows.spec
│   ├── Music2MP3-Qt-Linux.spec
│   ├── Music2MP3-macOS.spec  (Tk legacy)
│   ├── Music2MP3-Windows.spec
│   └── Music2MP3-Linux.spec
├── devtools/
│   ├── ui_preview.py       # outil de preview UI hors app
│   └── prepare_qt_runtime.py # rend les plugins PySide6 visibles sur macOS en dev
├── tests/
│   ├── test_ai_matcher.py
│   ├── test_converter_helpers.py
│   ├── test_library_attention.py
│   ├── test_library_cleanup.py
│   ├── test_library_manifest.py
│   ├── test_qt_app_smoke.py
│   ├── test_slskd_client.py
│   ├── test_soundcloud_api.py
│   ├── test_spotify_api.py
│   └── test_spotify_auth.py
├── icon.icns / icon.ico / icon.png
└── docs/
```

### Structure cible (refactoring futur de qt_app.py)

Si `qt_app.py` est découpé en modules, respecter cette organisation :

```
ui/
├── main_window.py
├── sidebar.py
├── hero_header.py
├── track_table.py
├── widgets/
│   ├── playlist_artwork.py
│   ├── option_pill.py
│   └── neon_progress.py
└── dialogs/
    ├── add_source.py
    └── settings.py
```

Le QSS global (`APP_QSS`) actuellement inline dans `qt_app.py` devrait migrer vers `styles/theme.qss` lors de ce découpage. Le nom `neon_progress.py` de l'ancienne cible est désormais obsolète; préférer `progress.py` lors de l'extraction.

---

## 5. Logique métier (converter.py)

### Classe `Converter`

Gère l'ensemble du pipeline de téléchargement :
- **Résolution du format** : `output_mode` = `"auto"` ou `"manual"` → `_resolve_output_mode()`
- **Match scoring** : `SequenceMatcher` sur titre + artiste + durée. Seuil 0.58 si `strict_match`, 0.42 sinon
- **Fast YouTube path** : lance d'abord `ytsearch1`; si le premier résultat est cohérent, il est accepté sans recherche large
- **AI match assist** : si `ai_match_enabled=True` et une clé Google/Gemini est configurée, Gemini intervient seulement quand le matcher local ne trouve pas de résultat fiable ou quand la première recherche ne retourne rien. L'IA peut proposer une URL ou une requête alternative, mais le téléchargement reste bloqué jusqu'à validation manuelle dans le détail du track échoué.
- **Détail score** : chaque match réussi stocke `match.score_details` dans le manifest; clic sur la colonne MATCH pour voir title/artist/duration/penalties + impact IA
- **Safe search** : quand `safe_search=True` (défaut), filtre les variantes `_BAD_VARIANTS` (live, remix, nightcore, karaoke…)
- **Deep search** : si score < seuil et `deep_search=True`, fallback SoundCloud
- **SoundCloud direct-only** : si un lien direct SoundCloud échoue côté `yt-dlp` (403 metadata, private, indispo), l'erreur est remontée telle quelle; pas de fallback YouTube automatique
- **SoundCloud auth** : Settings expose un `cookies.txt` et `Browser auth`; les deux passent par les options natives `yt-dlp --cookies` / `--cookies-from-browser`
- **Formats supportés** : mp3 / m4a / aac / wav / flac / aiff (aiff = download WAV + post-conversion ffmpeg)
- **Incremental** : skip les tracks déjà présents dans le manifest
- **M3U** : généré en fin de batch si `generate_m3u=True`

### Library manifest

`library_manifest.py` gère un fichier `music2mp3.manifest.json` par dossier de playlist, qui permet l'update incrémental. Le scan est récursif, trouve les dossiers audio legacy, et déduplique les manifests qui partagent la même source URL en gardant la playlist la plus complète.

`library_cleanup.py` analyse la bibliothèque depuis un worker Qt avant toute mutation. Le nettoyage automatique est limité aux actions réversibles et sûres : fichiers audio orphelins ou posés à la racine, entrées de manifest qui référencent deux fois le même fichier, et playlists imbriquées sans conflit de nom. Les fichiers retirés sont déplacés sous `.music2mp3-cleanup/` avec un journal `cleanup.json`. Les morceaux binaires identiques partagés entre plusieurs playlists et les sources de playlist dupliquées sont signalés, jamais supprimés automatiquement.

`library_attention.py` construit la vue globale **Needs attention** depuis les manifests : tracks en échec, fichiers attendus mais absents et propositions de match à valider. L'UI peut ouvrir directement la playlist concernée; les retries restent déclenchés depuis le détail du track, jamais automatiquement.

---

## 6. Comportement attendu

### Au démarrage
1. Charger `config.json` (créer avec defaults si absent)
2. Scanner le `root_dir` configuré (si défini) pour reconstruire la library locale via `scan_library()`
3. Afficher la sidebar avec les playlists trouvées

### Quand l'utilisateur clique "Add from Spotify"
1. Ouvrir `AddSourceDialog` avec un champ URL
2. Au submit, valider l'URL (regex `open.spotify.com/playlist/...`)
3. Si pas de token Spotify en cache : lancer le flow OAuth PKCE (port local 8765)
4. Fetcher la playlist via `SpotifyClient`
5. Écrire un CSV temporaire, l'ajouter à la sidebar
6. La sélectionner automatiquement

### Quand l'utilisateur clique Convert
1. `ConverterWorker` lancé dans un `QThread`
2. La `FooterProgress` s'active
3. Pour chaque track :
   - Filtre durée hors `[duration_min, duration_max]` (anti-long-sets)
   - Filtre variantes si `safe_search=True`
   - Score de match (SequenceMatcher)
   - Deep search SoundCloud si score insuffisant
   - Download yt-dlp + post-processing ffmpeg
   - Signaux Qt pour update UI ligne par ligne
4. Une fois fini : manifest mis à jour + M3U si configuré

### Stop
- `ConverterWorker.stop()` lève un événement — annulation immédiate
- Les tracks en cours repassent à l'état annulé dans l'UI

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
- yt-dlp est **synchrone et lent** → toujours dans un worker (`ConverterWorker`)
- Communication worker → UI via signals/slots uniquement (jamais d'accès direct aux widgets depuis un thread)

### QSS

- Le QSS global est actuellement inline dans `qt_app.py` (`APP_QSS`). Pas de `setStyleSheet()` inline sur les widgets sauf états dynamiques.
- Les couleurs Python (pour `QColor`, `QLinearGradient` dans les `paintEvent`) sont directement dans `qt_app.py` — si on extrait un fichier `colors.py`, synchroniser les deux.

### Naming

- Classes : `PascalCase` (`PlaylistItemWidget`)
- Fonctions / variables : `snake_case` (`load_playlist`)
- Constantes : `UPPER_SNAKE` (`PRIMARY_MAGENTA`)
- Signals : `verb_noun` (`playlist_selected`, `download_finished`)
- Fichiers : `snake_case.py`

### Logging

- **Pas de `print()`** en prod — utiliser `logging`
- Le panel "Logs" (bouton dans la TopBar) affiche le logging en temps réel
- Niveaux : `DEBUG` pour le détail, `INFO` pour les events utilisateur, `WARNING` pour les retry, `ERROR` pour les échecs
- Activer `DEBUG` via `APP_LOG_LEVEL=DEBUG`

---

## 8. Build & distribution

### Dev local (Taskfile)
```bash
# Installation
task install         # crée .venv + installe requirements.txt

# Lancement
task run             # UI Qt (défaut)
task run:qt          # UI Qt explicite
task run:tk          # UI Tkinter (legacy)

# Tests
task test            # unittest discover -s tests
task test:live-downloads  # live SoundCloud/Spotify download tests, opt-in

# Vérification syntaxe
task compile
```

Tests live download :
- `MUSIC2MP3_LIVE_DOWNLOADS=1` active [tests/test_live_downloads.py](tests/test_live_downloads.py)
- SoundCloud utilise par défaut `https://soundcloud.com/guiggz-1/sets/dl-playlist/s-CgcmK2MGhwO?...`
- `MUSIC2MP3_COOKIES_FROM_BROWSER=safari|chrome|firefox|...` ou `MUSIC2MP3_COOKIES_PATH=/path/cookies.txt` permet de tester les URLs SoundCloud bloquées
- Spotify nécessite `SPOTIFY_ACCESS_TOKEN`; override URL via `MUSIC2MP3_LIVE_SPOTIFY_URL`

### Build par plateforme
```bash
task build:macos     # → dist/Music2MP3.app  (Qt, nécessite ffmpeg + yt-dlp locaux)
task build:windows   # → dist/Music2MP3.exe  (Qt)
task build:linux     # → dist/Music2MP3      (Qt)

# Builds Tk legacy
task build:macos:tk
task build:windows:tk
task build:linux:tk
```

Les specs PyInstaller sont dans `packaging/`. Chaque plateforme a une variante Qt et une variante Tk.

### macOS : outils requis avant build
```bash
task tools:install:macos   # brew install ffmpeg yt-dlp python-tk@3.14
```

### Signing + notarization macOS
```bash
export MACOS_SIGN_IDENTITY="Developer ID Application: ..."
task sign:macos      # codesign

export APPLE_ID=... APPLE_TEAM_ID=... APPLE_APP_PASSWORD=...
task notarize:macos  # notarytool + staple
```

---

## 9. Anti-patterns à éviter

- **Pas** de magenta/cyan néon, de glow, de grille ou d'orbes décoratifs.
- **Pas** de gradients multicolores; privilégier les surfaces `#090909` / `#121212` / `#181818`.
- **Pas** de copie d'assets, de logo ou de wording Spotify; l'inspiration porte sur la sobriété et la hiérarchie.
- **Pas** de seconde couleur d'accent pour distinguer des contrôles ordinaires.
- **Pas** de `print()` pour le debug en prod — `logging` only.
- **Pas** d'appels réseau ou yt-dlp dans le main thread — bloque l'UI.
- **Pas** d'emojis dans l'UI — préférer des caractères ASCII (`▸`, `●`, `○`, `↓`, `■`).
- **Pas** de labels techniques visibles (`//`, `snake_case`, `[x]`) — utiliser un langage naturel et sentence case.
- **Pas** de tokens / secrets dans `config.json` ou les logs — `keyring` only.
- **Pas** de PyQt5 ou PyQt6 — `PySide6` only (cohérence + licence LGPL).
- **Ne pas toucher** à `gui.py` / `app.py` (Tk legacy) pour des features Qt — les deux UIs coexistent mais évoluent séparément.

---

## 10. Quand tu n'es pas sûr

- **Sur le design** : reste fidèle à la palette section 3. Demande validation avant d'introduire une nouvelle couleur d'accent ou un effet décoratif.
- **Sur l'archi** : si `qt_app.py` grossit encore, proposer un découpage en modules (voir structure cible section 4) plutôt que d'ajouter inline.
- **Sur les perfs** : si une opération peut bloquer > 50ms, elle passe en `QThread`.
- **Sur les libs** : ne pas ajouter de dépendance lourde sans valider — on reste sur **PySide6 + stdlib + libs métier déjà en place** (yt-dlp, mutagen, spotipy, keyring).
- **Sur la sécu** : tout ce qui touche aux tokens / OAuth / credentials passe par `keyring`. Si tu hésites, demande.
- **Sur Python 3.14** : c'est très récent. Si une lib pose problème, vérifier le support 3.14 avant de fight avec.

---

## 11. Planning courant

### Topo d'avancement

| Zone | État | Notes |
|---|---:|---|
| Core download | ✅ Fonctionnel | yt-dlp + ffmpeg, formats manual/auto, M3U, incrémental |
| Matching sécurisé | ✅ Fonctionnel | multi-candidats YouTube, durée, safe/strict/deep search |
| Sources | ✅ MVP | Spotify OAuth PKCE, SoundCloud URL/secret, CSV |
| Library locale | ✅ Avancé | manifest par playlist, scan root, sync selected/all, nettoyage réversible avec prévisualisation |
| UI Qt épurée | 🔄 Refonte en cours | thème sombre musical validé; simplification progressive des écrans |
| Actions library | ✅ Avancé | rename, open folder, merge, export CSV, delete, clean library |
| Gestion erreurs | ✅ Avancé | vue globale Needs attention, fichiers manquants, meilleur candidat, retry manuel par URL |
| Build | ✅ OK | Taskfile + PyInstaller Qt par défaut |
| Tests | ✅ Base solide | converter, manifest, backlog Bandcamp/slskd, Spotify/SoundCloud/auth, smoke Qt offscreen |

### Backlog terminé

| Item | Statut |
|---|---:|
| Refonte Qt comme UI par défaut | ✅ |
| Direction visuelle sombre et épurée documentée | ✅ |
| Safe search anti-sets longs | ✅ |
| Manifest `music2mp3.manifest.json` | ✅ |
| Scan bibliothèque + playlists legacy | ✅ |
| Sync manuel + sync all | ✅ |
| Sync all robuste | ✅ |
| Logs panel Qt | ✅ |
| Menu contextuel library | ✅ |
| Retry manuel sur track en erreur | ✅ |
| Packaging déplacé sous `packaging/` | ✅ |
| Tests UI smoke Qt | ✅ |
| Normalisation LF de `converter.py` | ✅ |
| Agent IA de matching avec validation manuelle | ✅ |
| Vue globale `Needs attention` | ✅ |
| Soulseek/slskd assist MVP | ⏸️ Backlog |

### Backlog futur priorisé

| Priorité | Item | Pourquoi |
|---:|---|---|
| P0 | Étendre smoke tests Qt | Couvrir settings, logs, source dialogs sans réseau |
| P0 | Valider AI matching en réel | Tester avec clé Google/Gemini sur playlists difficiles |
| P1 | Valider sync all en réel | Playlists Spotify/SoundCloud/CSV mixtes, erreurs partielles, stop/reprise |
| P2 | Continuer refactor UI modules | `dialogs/`, `widgets/`, puis `ui/main_window.py` |
| P2 | Export Rekordbox | M3U déjà là, pousser vers workflow DJ plus complet |
| P2 | Auto-pull planifié | À faire après sync all stable |
| P3 | Bandcamp | Source DJ naturelle, mais hors chemin actif pour garder l'app simple |
| P3 | Soulseek/slskd | Reprendre l'assistant après stabilisation SoundCloud/Spotify/CSV |

### Décision produit actuelle

| Option | Verdict | Raison |
|---|---|---|
| Agent IA matching | ✅ MVP intégré | Google/Vertex via Settings + keychain |
| Bandcamp | ⏸️ Backlog | Code conservé, UI désactivée |
| Soulseek/slskd | ⏸️ Backlog | Code conservé, UI/settings désactivés |

---

## 12. Workflow de contribution

1. **Avant de coder** : relire la section concernée de ce fichier
2. **Si tu changes l'archi ou la direction visuelle** : update ce fichier **en premier**
3. **Commits** : préfixe le scope (`ui:`, `core:`, `build:`, `docs:`)
4. **Tests** : `task test` — les tests couvrent converter, library_manifest, IA matching, Qt smoke, bandcamp/slskd backlog, spotify_api, soundcloud_api, spotify_auth
5. **Avant un build** : `task run` ou `task run:qt` doit fonctionner sans erreur

---

## 13. Variables d'env

- `SPOTIFY_CLIENT_ID` — override le Client ID du `config.json`
- `GOOGLE_API_KEY` / `GEMINI_API_KEY` — override optionnel de la clé IA; Settings stocke sinon dans le keychain
- `SLSKD_API_KEY` — override conservé pour backlog slskd; non utilisé par l'UI active
- `GEMINI_MODEL` / `GOOGLE_AI_MODEL` — override le modèle IA, défaut `gemini-2.5-flash`
- `APP_LOG_LEVEL=DEBUG` — active le logging DEBUG

---

*Direction visuelle sombre, musicale et épurée validée dans ce guide.*
*Stack actuelle : Python 3.14 + PySide6 + yt-dlp + ffmpeg, build PyInstaller via Taskfile et GitHub Actions.*
*Dernière mise à jour : refonte visuelle épurée (2026-07-21).*
