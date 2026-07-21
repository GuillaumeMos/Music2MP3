# Music2MP3 - Repo Update Audit

Derniere mise a jour : 2026-05-23

## 1) Snapshot actuel

Music2MP3 est maintenant principalement une app desktop Python/PySide6. Le flux Tkinter existe encore (`app.py`, `gui.py`), mais le chemin produit actif est `qt_app.py`.

Fonctions confirmees dans le code et les tests :
- import Spotify via OAuth PKCE sans client secret,
- import SoundCloud public/secret link via `yt-dlp`,
- import CSV,
- conversion audio via `yt-dlp` + `ffmpeg`,
- formats manual/auto : mp3, m4a, aac, wav, flac, aiff,
- matching securise avec safe/strict/deep search,
- SoundCloud direct-only : pas de fallback YouTube automatique quand `yt-dlp` retourne un 403 metadata ou une erreur directe,
- auth SoundCloud/YouTube via `cookies.txt` ou `yt-dlp --cookies-from-browser`,
- aide IA Gemini optionnelle quand le matcher local ne trouve pas de résultat fiable, avec validation manuelle obligatoire,
- generation `playlist.m3u8`,
- manifest par playlist (`music2mp3.manifest.json`),
- scan de bibliotheque locale, sync selected et sync all avec erreurs partielles,
- UI Qt avec library panel, logs, settings, actions contextuelles.

Etat verifie localement :
- branche : `new-ui`,
- working tree propre avant les changements d'audit,
- Python local : 3.14.4,
- tests : `87` tests OK via `.venv/bin/python -m unittest discover -s tests -v` (`2` live download tests skipped by default).
- live downloads : `task test:live-downloads` active les tests réels SoundCloud/Spotify; Spotify nécessite `SPOTIFY_ACCESS_TOKEN`.

## 2) Cartographie des modules

### Chemin produit principal

- `qt_app.py` : UI PySide6 principale, orchestration sources, library, conversion, settings, logs.
- `qt_workers.py` : workers Qt pour conversion et chargement Spotify/SoundCloud. Le loader Bandcamp reste présent mais hors chemin produit actif.
- `converter.py` : pipeline de conversion, matching, workers paralleles, M3U, manifest.
- `library_manifest.py` : lecture/ecriture manifest, scan recursif, dedup des playlists.
- `spotify_auth.py` : OAuth PKCE + refresh token.
- `spotify_api.py` : client REST Spotify, extraction playlist.
- `soundcloud_api.py` : extraction SoundCloud via `yt-dlp`.
- `bandcamp_api.py` : extraction Bandcamp album/track via `yt-dlp`, conservée pour backlog.
- `slskd_client.py` : client API slskd, conservé pour backlog et non exposé dans l'UI active.
- `ai_matcher.py` : conseil Gemini optionnel, cle stockee via keyring ou variables d'env.
- `config.py` : defaults depuis le bundle + overrides utilisateur par OS.
- `token_store.py` : wrapper keyring pour refresh token Spotify.
- `logging_setup.py` : logging legacy Tk; Qt a aussi un handler en memoire.

### Legacy conserve

- `app.py` : entrypoint Tkinter.
- `gui.py` : UI Tk legacy.
- `log_viewer.py` : viewer de logs Tk.

### Build, docs et tests

- `Taskfile.yml` : commandes dev, test, build et packaging.
- `packaging/` : specs PyInstaller Qt et Tk par plateforme.
- `.github/workflows/build.yml` : workflow manuel de release multi-OS.
- `tests/` : couverture unittest core + smoke Qt offscreen.
- `devtools/ui_preview.py` : outil local de preview UI.

## 3) Points forts

- Base de tests solide pour un MVP desktop : converter, manifest, auth/API et smoke UI Qt.
- Separation fonctionnelle correcte entre conversion, API sources, manifest, workers Qt et UI, meme si `qt_app.py` reste gros.
- Les points critiques de l'ancien audit sont traites : config utilisateur stable, M3U ordonne, token store branche, manifests reels, tests presents.
- README et `CLAUDE.md` refletent globalement la direction actuelle : Qt par defaut, Tk legacy.

## 4) Risques et incoherences restantes

1. `qt_app.py` est tres gros (~3178 lignes).
   - Risque : evolution UI plus lente, tests plus difficiles a cibler.
   - Action : continuer l'extraction progressive `dialogs/`, `widgets/`, `library/`; `workers/` a demarre avec `qt_workers.py`.

2. Des artefacts de cache Python etaient encore suivis par Git.
   - Risque : bruit dans les diffs, confusion entre environnements Python.
   - Action : retirer les `__pycache__/*.pyc` de l'index et s'appuyer sur `.gitignore`.

3. `logo_test.png` etait suivi mais non reference.
   - Risque : asset lourd inutile dans le repo.
   - Action : retire de l'index; le fichier reste local et ignore.

4. Gestion d'erreurs parfois large.
   - Exemples : plusieurs `except Exception` dans l'UI et le converter.
   - Action : continuer a logger les echecs critiques et reduire les handlers larges quand le contexte est clair.

## 5) Backlog priorise

### P0 - Hygiene et coherence

1. Committer l'hygiene repo : ignores, retrait des caches, retrait de `logo_test.png` de l'index.
2. Verifier le premier build GitHub Actions en Python 3.14 sur les trois OS.
3. Garder `CLAUDE.md` synchronise quand `qt_app.py` sera decoupe.

### P1 - Fiabilite produit

1. Valider sync all en reel sur un mix Spotify/SoundCloud/CSV, avec erreurs partielles et stop/reprise.
2. Reprendre Bandcamp seulement apres stabilisation du chemin Spotify/SoundCloud/CSV.
3. Durcir encore les erreurs OAuth/navigateur apres le cas port local deja occupe.

### P2 - Architecture

1. Extraire les dialogs Qt : add source, settings, logs, match detail.
2. Extraire les widgets purs : artwork, hero, playlist item, progress/status cells.
3. Isoler la logique library UI dans un module dedie.

## 6) Commandes utiles

```bash
task run          # UI Qt par defaut
task run:qt       # UI Qt explicite
task run:tk       # UI Tk legacy
task test         # unittest
task compile      # compileall des modules source + tests
task check        # compile + tests
```
