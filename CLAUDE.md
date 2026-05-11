# CLAUDE.md — Music2MP3

> Guide pour Claude Code (et tout autre agent IA) qui contribue à ce repo.
> **Lis ce fichier en entier avant toute modification.**
> Si tu modifies l'archi ou la direction visuelle, **mets à jour ce fichier d'abord**.

---

## 1. Le projet en 30 secondes

**Music2MP3** est une app desktop Python (macOS / Windows / Linux) qui permet à un DJ d'importer ses playlists Spotify / SoundCloud / Bandcamp / CSV, de les télécharger en audio propre et de les exporter au format DJ-ready (M3U + tags ID3 + filtres anti-long-sets).

**Public cible** : DJs / passionnés de musique qui veulent une bibliothèque locale propre à partir de leurs playlists streaming.

**Statut** : MVP fonctionnel avec UI Qt cyberpunk. L'UI Tkinter legacy (`app.py` + `gui.py`) reste présente mais n'est plus le défaut — le build par défaut cible Qt (`qt_app.py`).

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
- `PySide6>=6.7.0`

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
  "ai_match_enabled": false,
  "ai_match_provider": "vertex",
  "ai_match_model": "gemini-2.5-flash",
  "ai_match_gray_min": 0.30,
  "ai_match_min_confidence": 0.72,
  "ai_match_accept_margin": 0.12,
  "ai_match_prompt": "<prompt métier éditable depuis Settings>",
  "incremental_update": true,
  "prefix_numbers": false
}
```

**Champs clés :**
- `output_mode` : `"auto"` (yt-dlp choisit la meilleure source) ou `"manual"` (force `output_format_manual`)
- `safe_search` : filtre les variantes indésirables (live, remix, nightcore…) — actif par défaut
- `strict_match` : seuil de score plus élevé (0.58 vs 0.42) avant d'accepter un résultat
- `ai_match_enabled` : active l'aide Google/Vertex quand le matcher local ne trouve pas de résultat fiable ou quand la première recherche ne retourne rien; clé API stockée dans le keychain depuis Settings, jamais dans `config.json`
- `ai_match_min_confidence` : confiance minimale pour qu'une proposition IA soit affichée; défaut 0.72
- `ai_match_accept_margin` : marge maximale sous le seuil heuristique pour afficher une proposition IA; défaut 0.12
- `ai_match_prompt` : consignes métier passées à Gemini pour juger accept/reject/retry; `accept` signifie proposer à l'utilisateur, pas télécharger automatiquement

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

### Composants Qt (état actuel)

La fenêtre principale reste dans `qt_app.py` (~3178 lignes), mais les workers Qt sont maintenant isolés dans `qt_workers.py`. Les classes clés :

- **`QtMusic2MP3Window`** (`QMainWindow`) — conteneur principal, QSS global inline (`APP_QSS`)
- **`ArtworkWidget`** (`QWidget`) — `paintEvent` avec `QLinearGradient` dérivé du nom via `hashlib.md5`
- **`PlaylistItemWidget`** (`QFrame`) — item sidebar, méthode `setSelected()`
- **`HeroWidget`** (`QFrame`) — `paintEvent` custom : gradient + grid 32×32 + orbes radiaux
- **`ConverterWorker`** (`QObject`, `qt_workers.py`) — worker Qt pour la conversion, signaux `status/item/done/failed/finished`
- **`PlaylistLoadWorker`** (`QObject`, `qt_workers.py`) — worker pour le fetch Spotify/SoundCloud/Bandcamp
- **`AddSourceDialog`** (`QDialog`) — modal URL pour Spotify / SoundCloud / Bandcamp
- **`SettingsDialog`** (`QDialog`) — panneau de configuration
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
│   └── ui_preview.py       # outil de preview UI hors app
├── tests/
│   ├── test_ai_matcher.py
│   ├── test_converter_helpers.py
│   ├── test_library_manifest.py
│   ├── test_qt_app_smoke.py
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

Le QSS global (`APP_QSS`) actuellement inline dans `qt_app.py` devrait migrer vers `styles/theme.qss` lors de ce découpage.

---

## 5. Logique métier (converter.py)

### Classe `Converter`

Gère l'ensemble du pipeline de téléchargement :
- **Résolution du format** : `output_mode` = `"auto"` ou `"manual"` → `_resolve_output_mode()`
- **Match scoring** : `SequenceMatcher` sur titre + artiste + durée. Seuil 0.58 si `strict_match`, 0.42 sinon
- **AI match assist** : si `ai_match_enabled=True` et une clé Google/Gemini est configurée, Gemini intervient seulement quand le matcher local ne trouve pas de résultat fiable ou quand la première recherche ne retourne rien. L'IA peut proposer une URL ou une requête alternative, mais le téléchargement reste bloqué jusqu'à validation manuelle dans le détail du track échoué.
- **Détail score** : chaque match réussi stocke `match.score_details` dans le manifest; clic sur la colonne MATCH pour voir title/artist/duration/penalties + impact IA
- **Safe search** : quand `safe_search=True` (défaut), filtre les variantes `_BAD_VARIANTS` (live, remix, nightcore, karaoke…)
- **Deep search** : si score < seuil et `deep_search=True`, fallback SoundCloud
- **Formats supportés** : mp3 / m4a / aac / wav / flac / aiff (aiff = download WAV + post-conversion ffmpeg)
- **Incremental** : skip les tracks déjà présents dans le manifest
- **M3U** : généré en fin de batch si `generate_m3u=True`

### Library manifest

`library_manifest.py` gère un fichier `music2mp3.manifest.json` par dossier de playlist, qui permet l'update incrémental. Le scan est récursif, trouve les dossiers audio legacy, et déduplique les manifests qui partagent la même source URL en gardant la playlist la plus complète.

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

# Vérification syntaxe
task compile
```

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

- **Pas** de vert Spotify (`#1DB954`) ailleurs que sur le petit dot indiquant "source = Spotify".
- **Pas** de `border-radius > 8px` (sauf pills de progression ronds) — casse le feel angulaire/tech.
- **Pas** de `#FFFFFF` blanc pur — toujours `#E8F4FF` (blanc bleuté).
- **Pas** de `print()` pour le debug en prod — `logging` only.
- **Pas** d'appels réseau ou yt-dlp dans le main thread — bloque l'UI.
- **Pas** d'emojis dans l'UI — préférer des caractères ASCII (`▸`, `●`, `○`, `↓`, `■`).
- **Pas** de gradients pastel ou couleurs douces — la palette est saturée et contrastée par design.
- **Pas** de Title Case pour les labels — soit UPPERCASE (système) soit sentence case (contenu).
- **Pas** de tokens / secrets dans `config.json` ou les logs — `keyring` only.
- **Pas** de PyQt5 ou PyQt6 — `PySide6` only (cohérence + licence LGPL).
- **Ne pas toucher** à `gui.py` / `app.py` (Tk legacy) pour des features Qt — les deux UIs coexistent mais évoluent séparément.

---

## 10. Quand tu n'es pas sûr

- **Sur le design** : reste fidèle à la palette section 3. Demande validation avant d'introduire une nouvelle couleur ou un nouveau pattern.
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
| Sources | ✅ MVP+ | Spotify OAuth PKCE, SoundCloud URL/secret, Bandcamp, CSV |
| Library locale | ✅ Avancé | manifest par playlist, scan root, sync selected, sync all avec erreurs partielles |
| UI Qt cyberpunk | ✅ Avancé | hero, sidebar, track table, settings, logs, dialogs |
| Actions library | ✅ Avancé | rename, open folder, merge, export CSV, delete |
| Gestion erreurs | ✅ Avancé | dialog d'erreur, meilleur candidat, retry manuel par URL |
| Build | ✅ OK | Taskfile + PyInstaller Qt par défaut |
| Tests | ✅ Base solide | converter, manifest, Bandcamp, Spotify/SoundCloud/auth, smoke Qt offscreen |

### Backlog terminé

| Item | Statut |
|---|---:|
| Refonte Qt comme UI par défaut | ✅ |
| Direction visuelle cyberpunk documentée | ✅ |
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

### Backlog futur priorisé

| Priorité | Item | Pourquoi |
|---:|---|---|
| P0 | Étendre smoke tests Qt | Couvrir settings, logs, source dialogs sans réseau |
| P0 | Valider AI matching en réel | Tester avec clé Google/Gemini sur playlists difficiles |
| P1 | Valider sync all en réel | Playlists Spotify/SoundCloud/Bandcamp mixtes, erreurs partielles, stop/reprise |
| P2 | Continuer refactor UI modules | `dialogs/`, `widgets/`, puis `ui/main_window.py` |
| P2 | Export Rekordbox | M3U déjà là, pousser vers workflow DJ plus complet |
| P2 | Auto-pull planifié | À faire après sync all stable |
| P3 | Soulseek via slskd | Puissant mais dépendance lourde à assumer |

### Décision produit actuelle

| Option | Verdict | Raison |
|---|---|---|
| Agent IA matching | ✅ MVP intégré | Google/Vertex via Settings + keychain |
| Bandcamp | ✅ Intégré | Source DJ naturelle, via yt-dlp |
| Soulseek/slskd | ⚠️ Plus tard | Très utile pour raretés/FLAC, mais setup lourd |

---

## 12. Workflow de contribution

1. **Avant de coder** : relire la section concernée de ce fichier
2. **Si tu changes l'archi ou la direction visuelle** : update ce fichier **en premier**
3. **Commits** : préfixe le scope (`ui:`, `core:`, `build:`, `docs:`)
4. **Tests** : `task test` — les tests couvrent converter, library_manifest, IA matching, Qt smoke, bandcamp_api, spotify_api, soundcloud_api, spotify_auth
5. **Avant un build** : `task run` ou `task run:qt` doit fonctionner sans erreur

---

## 13. Variables d'env

- `SPOTIFY_CLIENT_ID` — override le Client ID du `config.json`
- `GOOGLE_API_KEY` / `GEMINI_API_KEY` — override optionnel de la clé IA; Settings stocke sinon dans le keychain
- `GEMINI_MODEL` / `GOOGLE_AI_MODEL` — override le modèle IA, défaut `gemini-2.5-flash`
- `APP_LOG_LEVEL=DEBUG` — active le logging DEBUG

---

*Direction visuelle cyberpunk validée dans ce guide.*
*Stack actuelle : Python 3.14 + PySide6 + yt-dlp + ffmpeg, build PyInstaller via Taskfile et GitHub Actions.*
*Dernière mise à jour : synchronisation repo/docs/CI (2026-05-11).*
