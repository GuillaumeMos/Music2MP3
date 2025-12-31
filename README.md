# Music2MP3

**Music2MP3** is a cross-platform, self-contained app (Windows `.exe`, macOS `.app`, Linux AppImage) that turns a playlist into local audio files.  
You can either **drag & drop a CSV** (Exportify / TuneMyMusic / others), **paste a Spotify playlist link** (OAuth PKCE – **no client secret**), or **paste a SoundCloud playlist link** (public or private _secret_ URL — **no login needed**).

The app downloads each track via **yt-dlp**, resamples to **44.1 kHz**, and saves to your chosen format (MP3, WAV, FLAC, AIFF, AAC, M4A – default MP3).

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
  If the target playlist folder already exists, the app **adds only new tracks** (no duplicates).  
  Dedup uses (in order):
  - **Track URI** (when present),
  - **title + primary artist**,
  - then **filename** (ignoring any numeric prefix like `001 -`).  
    A small `manifest.json` helps future runs.
- **Parallel downloads (2–8 workers)**  
  Configurable **Threads** selector; 2–4 is a safe sweet spot.
- **Great live UI**
  - Global progress bar + **per-track progress bars**
  - **Speed & ETA** per track when available
  - **Elapsed time** while running and **total time** at the end
  - **Stop** button to cancel gracefully
- **Optional file numbering**  
  Toggle **“Number files (001, 002…)”** if you want filenames to reflect order.  
  (M3U is generated and sorted by number when present, otherwise by time.)
- **Extras**
  - Generate **.m3u** playlist
  - Output format picker (MP3 / WAV / FLAC / AIFF / AAC / M4A, resampled 44.1 kHz)
  - **Exclude instrumental** versions
  - “Deep search” mode for more accurate matches

---

## ⬇️ Download

Grab the latest build from the **Releases** page:

- **Windows**: download the ZIP, extract, run `Music2MP3.exe`
- **macOS**: download the ZIP, unzip, open `Music2MP3.app`
- **Linux**: download `Music2MP3_Linux_x86-64.AppImage`, `chmod +x`, then run

---

## 🚀 How to Use

### Option A — From a CSV

1. Export your playlist:
   - Spotify → [Exportify](https://exportify.net)
   - Apple/YouTube/others → [TuneMyMusic](https://tunemymusic.com)
2. Launch the app.
3. **Drag & drop** the CSV (or click to browse).  
   _(Tip: after loading, click the CSV label to open the file.)_
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

> Note: If some tracks are region-locked or not streamable, yt-dlp may fail those entries. You can optionally provide a cookies file in `config.json` to improve access when needed.

---

## ⚙️ Settings (quick overview)

- **Number files (001, 002…)**  
  Adds a numeric prefix to filenames. Useful to enforce order.  
  If unchecked, files are named without the prefix.
- **Threads**  
  Number of parallel downloads (1–8). **2–4** recommended.
- **Output format (44.1 kHz resample)**  
  Choose MP3, WAV, FLAC, AIFF, AAC or M4A. Default is **MP3**; AIFF is produced by converting a WAV.
- **Generate M3U playlist**  
  Creates a `.m3u` in the playlist folder (sorted by number if present, else by time).
- **Exclude instrumental versions**  
  Rejects videos with “instrumental” in title.
- **Deep search**  
  Slower but more accurate search (tries multiple candidates).
- **Incremental update**  
  Skips tracks that already exist using URI/tags/normalized filename matching. Maintains a `manifest.json`.

---

## 📂 Output

- Files are saved under:  
  `/<YourOutputFolder>/<PlaylistName>/`
- Filenames follow either:
  - `001 - Track Name - Artist.<ext>` (if numbering is enabled), or
  - `Track Name - Artist.<ext>` (if disabled).  
    `<ext>` is the chosen format: mp3 / wav / flac / aiff / aac / m4a (default mp3).
- Audio is resampled to **44.1 kHz**; AIFF is produced from a WAV download when selected.
- Basic tags are written (Title, Artist, Album, Track # when numbered).
- A `.m3u` playlist is generated if enabled.

---

## 🔐 Privacy & Auth

- **Spotify** sign-in uses **OAuth PKCE**: no client secret, no data sent to any server we control.
  - Local redirect: `http://127.0.0.1:8765/callback`
  - Tokens are kept in memory for the current session.
- **SoundCloud** usage requires **no authentication**:
  - Public playlists work out of the box.
  - Private playlists shared via **secret links** also work (the token is in the URL).
- When loading from URLs, the generated CSV is **temporary**, used internally by the converter.

---

## 💡 Notes

- This tool **does not rip Spotify or SoundCloud directly**. Tracks are located on public sources (e.g., YouTube) via yt-dlp and then remuxed/re-encoded.
- **FFmpeg** and **yt-dlp** are bundled in the releases; no installs needed.
- UI work is done in background threads; the app stays responsive and shows live progress.
- If a track fails, try:
  - **Deep search** (more candidates),
  - checking the URL availability,
  - or providing a **cookies** file in `config.json` (helps with region locks, age restrictions, etc.).

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
   - Windows: `pyinstaller Music2MP3-Windows.spec`
   - macOS: `pyinstaller Music2MP3-macOS.spec`
   - Linux: `pyinstaller Music2MP3-Linux.spec` (AppImage packaging in CI)

The specs include data files (ffmpeg, yt-dlp, icons, config) and produce the app in `dist/`.

---

## 🧩 Troubleshooting

- **“(Not Responding)” on Windows while downloading**  
  Long tasks run in worker threads; per-track progress should update. If you still see freezes, check GPU overlays/AV scanners.
- **Age-restricted / region-locked videos**  
  yt-dlp may refuse them without cookies. Add a cookies file to `config.json`.
- **Duplicates still appear**  
  We compare by URI → tags → normalized filename (ignores leading numbers and normalizes punctuation).  
  Delete `manifest.json` if you suspect it’s stale and retry.
- **SoundCloud shows “Unknown – Unknown”**  
  Usually caused by missing page metadata or blocked access. Ensure the playlist/secret link is valid and reachable in your region; cookies can help.
- **No console popups**  
  All subprocesses are spawned hidden on Windows; progress is parsed and shown in the UI.

---

## 📜 License

MIT
