# Music2MP3 - Takeover Audit

## 1) Snapshot

Application desktop Tkinter qui:
- charge une playlist depuis Spotify (OAuth PKCE), SoundCloud (sans auth), CSV, ou liste texte,
- convertit les pistes via `yt-dlp` + `ffmpeg` en audio local (mp3/m4a/aac/wav/flac/aiff),
- affiche progression globale + par piste, avec logs live et annulation.

## 2) Module Cartography

### Core to keep (production path)

- `app.py`
  - Entrypoint, init logging, init fenêtre, bind F12 pour la console de logs.
- `gui.py`
  - UI principale, orchestration des loaders (Spotify/SoundCloud/texte/CSV), lancement conversion, polling queue, rendu progrès/erreurs.
- `converter.py`
  - Pipeline métier de conversion, workers parallèles, commandes `yt-dlp`, conversion AIFF via `ffmpeg`, génération M3U.
- `spotify_api.py`
  - Client Spotify API robuste (retries + pagination), fetch playlist -> rows CSV.
- `spotify_auth.py`
  - OAuth PKCE local callback `127.0.0.1:8765`.
- `soundcloud_api.py`
  - Extraction métadonnées playlist/track SoundCloud via `yt-dlp --dump-single-json`.
- `config.py`
  - Chargement config par défaut + merge `config.json`.
- `utils.py`
  - utilitaires UI/tooltips, ouverture dossiers/fichiers, wrappers subprocess.
- `logging_setup.py`, `log_viewer.py`
  - logging fichier/stdout + viewer live dans l’app.
- `Music2MP3-*.spec`
  - packaging Windows/macOS/Linux.

### Keep but refactor soon

- `config.json`
  - utile pour defaults et `spotify_client_id`, mais stratégie de persistance actuelle fragile en binaire packagé.
- `requirements.txt`
  - fonctionne pour dev, mais contient des dépendances non utilisées aujourd’hui.

### Legacy / currently unused (candidats suppression)

- `spotify_public_scraper.py`
  - vide.
- `live_subprocess.py`
  - helper non référencé.
- `artwork.py`
  - non référencé dans le flux actuel.
- `token_store.py`
  - prévu pour persistance refresh token, mais jamais branché dans `gui.py`.
- `utils_net.py`
  - non utilisé (duplicata partiel du retry de `spotify_api.py`).
- `ui_preview.py`
  - utile seulement pour preview dev (à garder en outil interne ou déplacer dans dossier `devtools/`).

## 3) Gaps and inconsistencies (important)

- README != comportement réel sur 2 points:
  - Drag & drop CSV annoncé, mais pas de binding DnD effectif dans `gui.py`.
  - `manifest.json` et dédup avancée annoncés, mais le code fait surtout un skip si le fichier final existe.
- Persistance config potentiellement cassée en build packagé:
  - `CONFIG_FILE = resource_path("config.json")` vise un chemin bundle/temp, pas un dossier utilisateur stable.
- Génération M3U non déterministe:
  - `self._made_files` est alimenté par des workers en parallèle, donc l’ordre peut dépendre de la fin des threads.
- Aucune suite de tests (unitaires/intégration) sur le cœur métier (`converter`, parsers API).

## 4) Prioritized improvement backlog

## P0 - Stabilize behavior/documentation contract

1. Corriger la persistance de config utilisateur (critique)
- Impact: élevé
- Effort: moyen
- Action:
  - Introduire un chemin user-data par OS (ex: `~/.music2mp3/config.json` sur Linux/macOS, `%APPDATA%\\Music2MP3\\config.json` sur Windows).
  - Utiliser ce chemin pour lecture/écriture; garder `config.json` du repo comme template de defaults.

2. Aligner README avec le code (ou implémenter les features promises)
- Impact: élevé
- Effort: faible à moyen
- Action:
  - Soit implémenter vrai drag-and-drop CSV + manifest/dédup avancée,
  - soit documenter honnêtement le comportement actuel.

3. Rendre l’ordre M3U déterministe
- Impact: moyen/élevé (UX)
- Effort: faible
- Action:
  - Stocker `(idx, filename)` puis trier avant écriture M3U.

## P1 - Reduce technical debt and regressions

4. Brancher `token_store.py` (ou le supprimer)
- Impact: moyen
- Effort: faible
- Action:
  - soit intégrer `RefreshTokenStore` dans `PKCEAuth` depuis `gui.py`,
  - soit retirer le module et simplifier.

5. Nettoyer dépendances non utilisées
- Impact: moyen (maintenance, sécurité supply chain)
- Effort: faible
- Action:
  - retirer `selenium`, `webdriver-manager`, `beautifulsoup4` si non requis.

6. Ajouter tests minimaux sur le cœur
- Impact: élevé
- Effort: moyen
- Scope initial:
  - `converter._sanitize_filename`, `_looks_instrumental`, `_build_search_query`, `_rows_to_jobs`
  - parsing progression `yt-dlp`
  - `SpotifyClient.extract_playlist_id`

## P2 - Product quality improvements

7. Implémenter vrai drag-and-drop CSV
- Impact: moyen
- Effort: faible/moyen
- Action:
  - exploiter `tkinterdnd2` quand dispo et fallback browse.

8. Améliorer annulation/robustesse auth
- Impact: moyen
- Effort: moyen
- Action:
  - timeout/cancel dans boucle d’attente PKCE,
  - gestion port callback déjà occupé.

9. Factoriser réseau/réessais
- Impact: faible/moyen
- Effort: faible
- Action:
  - supprimer `utils_net.py` ou l’utiliser réellement partout.

## 5) Suggested execution plan (short)

Sprint 1 (safe + high ROI):
1. Fix persistance config user-dir.
2. Fix ordre M3U déterministe.
3. README sync avec comportement réel.
4. Supprimer code/dépendances mortes évidentes.

Sprint 2 (fiabilité):
1. Brancher token store + harden PKCE timeout/port.
2. Ajouter test suite de base + CI simple.
3. Implémenter vrai DnD CSV.

## 6) Removal candidates checklist

Supprimer après validation finale:
- `spotify_public_scraper.py`
- `live_subprocess.py`
- `utils_net.py`
- `artwork.py` (si pas de plan d’embed cover en roadmap)

Garder comme devtool:
- `ui_preview.py` (déplacer dans `devtools/` + noter usage)

