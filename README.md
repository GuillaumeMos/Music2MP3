# Music2MP3

**Music2MP3** is a cross-platform, self-contained app (Windows `.exe`, macOS `.app`, Linux AppImage) that turns a playlist into local audio files.  
You can either **load a CSV** (Exportify / TuneMyMusic / others), **paste a Spotify playlist link** (OAuth PKCE – **no client secret**), or **paste a SoundCloud playlist link** (public or private _secret_ URL).

The app downloads each track via **yt-dlp**. In **Manual** mode it resamples to **44.1 kHz** and saves to your chosen format (MP3, WAV, FLAC, AIFF, AAC, M4A – default MP3). In **Auto** mode it keeps the best available audio format from the source.

Everything is bundled—no Python or external installs required.

---

## ✨ Highlights

- **Load from Spotify URL (public/private/collab)**  
  Uses **OAuth PKCE** in your browser (scopes: `playlist-read-private`, `playlist-read-collaborative`). No client secret stored.
- **Load from SoundCloud URL (no auth)**  
  Paste any **public playlist** or **private “secret link”** URL and it just works. No account login, no credentials.
- **CSV still supported**  
  Any CSV with the usual headers (`Track Name`, `Artist Name(s)`, `Album Name`, `Duration (ms)`…) works (Exportify, TuneMyMusic…).
- **Incremental updates**  
  If the target playlist folder already exists, the app skips tracks whose final output file already exists and is non-empty.
- **Parallel downloads (2–8 workers)**  
  Configurable **Threads** selector; 2–4 is a safe sweet spot.
- **Great live UI**
  - Global progress bar + **per-track progress bars**
  - Per-track **state column** (`Queued`, `Downloading`, `Converting`, `Done`, `Failed`)
  - **Speed & ETA** per track when available
  - **Elapsed time** while running and **total time** at the end
  - **Stop** button to cancel gracefully
- **Optional file numbering**  
  Toggle **“Number files (001, 002…)”** if you want filenames to reflect order.  
  (`playlist.m3u8` is generated in playlist order.)
- **Extras**
  - Generate **.m3u** playlist
  - Output format picker (MP3 / WAV / FLAC / AIFF / AAC / M4A; Manual mode resamples to 44.1 kHz)
  - **Exclude instrumental** versions
  - “Safe search”, “Deep search” and “Strict matching” modes for better matches

---

## ⬇️ Download

Grab the latest build from the **Releases** page:

- **Windows**: download the ZIP, extract, run `Music2MP3.exe`
- **macOS**: download the ZIP, unzip, open `Music2MP3.app`
- **Linux**: download `Music2MP3_Linux_x86-64.AppImage`, `chmod +x`, then run

---

## 🚀 How to Use

### Qt UI

The **PySide6 / Qt** frontend is the default build target.

- Run default app: `task run`
- Run: `task run:qt`
- Scope: Spotify/SoundCloud/CSV loading + output options + live downloads panel
- Library panel: choose a root folder, scan playlist manifests, open a playlist folder, or sync a selected Spotify/SoundCloud/CSV-backed playlist.
- Tk frontend is still available: `task run:tk`

### Option A — From a CSV

1. Export your playlist:
   - Spotify → [Exportify](https://exportify.net)
   - Apple/YouTube/others → [TuneMyMusic](https://tunemymusic.com)
2. Launch the app.
3. Drop a CSV on the CSV field/area, or click/browse to select one.
   _(Tip: after loading, click the CSV label to open it.)_
4. Choose an **output folder**.
5. (Optional) Toggle settings (see below).
6. Click **Convert**.

### Option B — From a Spotify playlist URL

1. Copy a playlist link from Spotify (e.g. `https://open.spotify.com/playlist/...`).
2. Paste it in the app and click **Load from Spotify**.
3. Your browser opens for **OAuth PKCE** sign-in (no secret; local redirect to `http://127.0.0.1:8765/callback`).
4. The app builds a temp CSV internally and shows the track count.
5. Choose an **output folder**, then click **Convert**.

> Supports **public**, **private**, and **collaborative** playlists after sign-in.

### Option C — From a SoundCloud playlist URL (no auth)

1. Copy a SoundCloud **public playlist** URL **or** a **private “secret link”** URL (it contains a token).
2. Paste it and click **Load from SoundCloud**.
3. The app parses the playlist and builds a temp CSV (with `Source URL` for each track).
4. Choose an **output folder**, then click **Convert**.

> Note: If SoundCloud returns 403/private/region errors, open Settings and choose a browser under **Browser auth**. Music2MP3 will let yt-dlp read your existing SoundCloud browser session. A Netscape `cookies.txt` file is still supported as a fallback.

---

## ⚙️ Settings (quick overview)

- **Number files (001, 002…)**  
  Adds a numeric prefix to filenames. Useful to enforce order.  
  If unchecked, files are named without the prefix.
- **Threads**  
  Number of parallel downloads (1–8). **2–4** recommended.
- **Output format**
  Choose MP3, WAV, FLAC, AIFF, AAC or M4A. Default is **MP3**; AIFF is produced by converting a WAV.
- **Format mode: Auto / Manual**  
  - **Auto (best available)**: keeps the best available audio format/quality from source (extension may vary).  
  - **Manual**: forces the selected output format and uses 44.1 kHz resample.
- **Generate M3U playlist**  
  Creates `playlist.m3u8` in the playlist folder, in playlist order.
- **Exclude instrumental versions**  
  Rejects videos with “instrumental” in title.
- **Deep search**  
  Adds an audio-focused search hint. For multi-candidate scoring, enable Strict matching.
- **Safe search**
  Enabled by default. Searches multiple YouTube candidates and rejects long mixes/sets or candidates whose duration is far from the source track.
- **cookies.txt**
  Optional yt-dlp cookies file for protected or blocked SoundCloud/YouTube links.
- **Browser auth**
  Optional yt-dlp `--cookies-from-browser` integration. Choose Safari, Chrome, Firefox, Brave, Edge, etc. to reuse your browser SoundCloud session without exporting cookies manually.
- **Strict matching (safer, slower)**  
  Tries multiple YouTube candidates and keeps only confident matches using title/artist/duration scoring.
- **Incremental update**  
  Skips tracks whose final output file already exists and is non-empty.

---

## 📂 Output

- Files are saved under:  
  `/<YourOutputFolder>/<PlaylistName>/`
- Filenames follow either:
  - `001 - Track Name - Artist.<ext>` (if numbering is enabled), or
  - `Track Name - Artist.<ext>` (if disabled).  
    `<ext>` is the chosen format: mp3 / wav / flac / aiff / aac / m4a (default mp3).
- Manual-format audio is resampled to **44.1 kHz**; Auto mode keeps the source's best available audio format. AIFF is produced from a WAV download when selected.
- Source metadata from yt-dlp is embedded when available.
- A `.m3u` playlist is generated if enabled.
- A `music2mp3.manifest.json` file is generated in each playlist folder. It stores the source URL/type, settings, track list, output files and per-track status so the app can build library scanning and sync features on top of it.

---

## 📚 Library Foundation

Each converted playlist now has a manifest. The core scanner can discover playlists under a root folder by reading these manifests, which is the base for upcoming manual sync, auto-pull and library views.

In the Qt app, the **Library** panel already supports:
- choosing/scanning a library root,
- listing converted playlists from `music2mp3.manifest.json`,
- opening the selected playlist folder,
- manually syncing selected Spotify, SoundCloud, or CSV-backed playlists,
- syncing all eligible playlists with progress and partial-error handling,
- cleaning orphan files, duplicate manifest entries, and nested playlists with a recovery folder,
- reviewing failed downloads, missing files, and suggested matches from the global **Needs attention** view.

Current repo organization:
- Root app entrypoints stay at the top level for PyInstaller compatibility.
- `packaging/` contains PyInstaller specs.
- `docs/` contains takeover/audit notes.
- `devtools/` contains local preview/debug helpers.
- `tests/` covers converter, auth/API helpers and library manifest behavior.

---

## 🔐 Privacy & Auth

- **Spotify** sign-in uses **OAuth PKCE**: no client secret, no data sent to any server we control.
  - Local redirect: `http://127.0.0.1:8765/callback`
  - Access token is kept in memory for the current session.
  - Refresh token is stored in your OS keychain when available (via `keyring`).
- **SoundCloud** usage requires **no authentication**:
  - Public playlists work out of the box.
  - SoundCloud private playlists shared via **secret links** also work (the token is in the URL).
- **AI match assist** is optional:
  - Enable it in Settings or the `ai` pill.
  - Paste your Google/Gemini API key in Settings; it is stored in the OS keychain, not in `config.json`.
  - It only runs when the local matcher cannot confidently select a YouTube result, or when the first query returns no result.
  - It can propose a candidate or a better query, but never downloads automatically.
  - You validate the AI proposal from the failed-track details before clicking Download.
  - AI proposals are gated by confidence and by the local title/artist/duration score.
  - The matching prompt is editable in Settings.
- When loading from URLs, the generated CSV is **temporary**, used internally by the converter.

---

## 💡 Notes

- This tool **does not rip Spotify directly**. Tracks are located on public sources (e.g. YouTube or direct SoundCloud links) via yt-dlp and then remuxed/re-encoded.
- Direct SoundCloud links are tried first when available. If SoundCloud returns a 403 or similar metadata error, Music2MP3 reports the SoundCloud error and does not retry through YouTube.
- For persistent SoundCloud 403 errors, use **Browser auth** in Settings first. If browser cookie extraction is blocked by the OS, export browser cookies as a Netscape `cookies.txt` file and set it in Settings.
- **FFmpeg** and **yt-dlp** are bundled in the releases; no installs needed.
- Runtime settings are persisted per user:
  - Windows: `%APPDATA%\\Music2MP3\\config.json`
  - macOS: `~/Library/Application Support/Music2MP3/config.json`
  - Linux: `~/.music2mp3/config.json`
- UI work is done in background threads; the app stays responsive and shows live progress.
- Local library scan is recursive, includes legacy audio folders, and hides duplicate manifests with the same source URL.
- Click a downloaded track's match score to inspect score details and AI impact.
- If a track fails, try:
  - **Safe search**, **Deep search**, **Strict matching**, or **AI match assist**,
  - choosing **Browser auth** or adding a browser-exported **cookies.txt** file in Settings,
  - checking the URL availability,
  - or providing a **cookies** file in `config.json` (helps with region locks, age restrictions, etc.).

### Backlog parked

Bandcamp import and Soulseek/slskd assist are kept in the codebase for later, but they are not part of the active product path right now.

---

## 🧰 Build from Source (optional)

> You don’t need this to use the app—releases are prebuilt.  
> For contributors:

1. Install Python 3.10+ and `pip`.
2. `pip install -r requirements.txt pyinstaller`
3. Place platform binaries:
   - Windows: `ffmpeg/ffmpeg.exe`, `yt-dlp/yt-dlp.exe`
   - macOS: `ffmpeg/ffmpeg`, `yt-dlp/yt-dlp`
   - Linux: same as macOS (or use the AppImage workflow)
4. Run the platform spec, e.g.:
   - Windows (Qt default): `pyinstaller packaging/Music2MP3-Qt-Windows.spec`
   - Windows (Tk legacy): `pyinstaller packaging/Music2MP3-Windows.spec`
   - macOS (Qt default): `pyinstaller packaging/Music2MP3-Qt-macOS.spec`
   - macOS (Tk legacy): `pyinstaller packaging/Music2MP3-macOS.spec`
   - Linux (Qt default): `pyinstaller packaging/Music2MP3-Qt-Linux.spec`
   - Linux (Tk legacy): `pyinstaller packaging/Music2MP3-Linux.spec` (AppImage packaging in CI)

The GitHub Actions release workflow builds the Qt specs by default.

Or with Taskfile:
- `task build:current` (build for your current OS, Qt default)
- `task build:windows` / `task build:windows:tk`
- `task build:macos` (Qt default)
- `task build:macos:tk` (Tk legacy)
- `task build:linux` / `task build:linux:tk`

Tests:
- `task test` runs the offline unit/smoke suite.
- `task test:live-downloads` runs opt-in SoundCloud/Spotify live download checks against real URLs.

Live download tests use the provided SoundCloud playlist URL by default. Spotify live tests require `SPOTIFY_ACCESS_TOKEN`.

```bash
MUSIC2MP3_LIVE_SOUNDCLOUD_URL="https://soundcloud.com/guiggz-1/sets/dl-playlist/s-CgcmK2MGhwO?si=8a9d42cfc9024436906dfe6ab3d08bb1&utm_source=clipboard&utm_medium=text&utm_campaign=social_sharing" \
MUSIC2MP3_COOKIES_FROM_BROWSER=safari task test:live-downloads

SPOTIFY_ACCESS_TOKEN="..." \
MUSIC2MP3_LIVE_SPOTIFY_URL="https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M" \
task test:live-downloads
```

macOS signing/notarization (optional):
- `task sign:macos` with `MACOS_SIGN_IDENTITY="Developer ID Application: ..."`
- `task notarize:macos` with `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD`

The specs include data files (ffmpeg, yt-dlp, icons, config) and produce the app in `dist/`.

---

## 🧩 Troubleshooting

- **Qt says the `cocoa` platform plugin cannot be found on macOS**
  Use `task run` or `task run:qt`: the Taskfile prepares the local PySide6 plugin directory automatically. For a direct Python launch, run `.venv/bin/python devtools/prepare_qt_runtime.py` immediately before `.venv/bin/python qt_app.py`.
- **“(Not Responding)” on Windows while downloading**  
  Long tasks run in worker threads; per-track progress should update. If you still see freezes, check GPU overlays/AV scanners.
- **Age-restricted / region-locked videos**  
  yt-dlp may refuse them without cookies. Add a cookies file to `config.json`.
- **Duplicates still appear**  
  The incremental mode only skips files that already exist with the exact expected final filename.  
  If naming options changed (format, numbering, artist/title text), new files may be created.
- **SoundCloud shows “Unknown – Unknown”**  
  Usually caused by missing page metadata or blocked access. Ensure the playlist/secret link is valid and reachable in your region; cookies can help.
- **No console popups**  
  All subprocesses are spawned hidden on Windows; progress is parsed and shown in the UI.

---

## 📜 License

MIT
