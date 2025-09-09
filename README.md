# Music2MP3

**Music2MP3** is a cross-platform, self-contained app (Windows `.exe`, macOS `.app`, Linux AppImage) that turns a playlist into local audio files.  
You can either **drag & drop a CSV** (Exportify / TuneMyMusic / others) **or paste a Spotify playlist link** and sign in (PKCE, **no client secret**).

The app downloads each track via **yt-dlp** as:

- **M4A** (remux; keeps source AAC when available), or
- **MP3 VBR0** (high quality re-encode via FFmpeg).

Everything is bundled—no Python or external installs required.

---

## ✨ Highlights

- **Load directly from a Spotify playlist URL**  
  Uses **OAuth PKCE** in your browser (scopes: `playlist-read-private`, `playlist-read-collaborative`). Works for **public, private, and collaborative** playlists. No client secret stored.
- **CSV still supported**  
  Any CSV with the usual headers (`Track Name`, `Artist Name(s)`, `Album Name`, `Duration (ms)`…) works (Exportify, TuneMyMusic…).
- **Incremental updates**  
  If the target playlist folder already exists, the app **adds only new tracks** (no duplicates).  
  Dedup uses (in order): **Track URI**, then **title+artist tags**, then **filename (title) ignoring any `001 -` prefix**. A small `manifest.json` helps future runs.
- **Parallel downloads (2–4 workers)**  
  Faster end-to-end with a safe concurrency level.
- **Great live UI**
  - Global progress bar + **per-track progress bars**
  - **Speed & ETA** per track when available
  - **Live elapsed time** and **total time** at the end
- **Optional file numbering**  
  Toggle **“Number files (001, 002…)”** if you want a fixed order in filenames.  
  (M3U is generated and sorted by number when present, otherwise by time.)
- **Extras**
  - Generate **.m3u** playlist
  - **MP3 VBR0** re-encode toggle
  - **Exclude instrumental** versions
  - “Deep search” mode for more accurate matches

---

## ⬇️ Download

Grab the latest build from the **Releases** page:

- **Windows**: download the ZIP, extract, run `Music2MP3.exe`
- **macOS**: download the ZIP, unzip, open `Music2MP3.app` - stanbdy
- **Linux**: download `Music2MP3_Linux_x86-64.AppImage`, `chmod +x`, then run - stanbdy

---

## 🚀 How to Use

### Option A — From a CSV

1. Export your playlist:
   - Spotify → [Exportify](https://exportify.net)
   - Apple/YouTube/others → [TuneMyMusic](https://tunemymusic.com)
2. Launch the app.
3. **Drag & drop** the CSV (or click to browse).
4. Choose an **output folder**.
5. (Optional) Toggle settings (see below).
6. Click **Convert**.

### Option B — From a Spotify playlist URL

1. Copy a playlist link from Spotify (e.g., `https://open.spotify.com/playlist/...`).
2. Paste it in the app and click **Load from Spotify**.
3. Your browser opens for **OAuth PKCE** sign-in (no secret; local redirect to `http://127.0.0.1:8765/callback`).
4. The app builds a temp CSV internally and shows the track count.
5. Choose an **output folder**, then click **Convert**.

> Tip: Public **and** private/collaborative playlists are supported after sign-in.

---

## ⚙️ Settings (quick overview)

- **Number files (001, 002…)**  
  Adds a numeric prefix to filenames. Useful to enforce order.  
  If unchecked, files are named without the prefix.
- **Transcode to MP3 (VBR 0)**  
  Re-encode for maximum compatibility. Otherwise M4A remux keeps the source AAC (commonly ~128 kbps).
- **Generate M3U playlist**  
  Creates a `.m3u` in the playlist folder (sorted by number if present, else by time).
- **Exclude instrumental versions**  
  Rejects videos with “instrumental” in title.
- **Deep search**  
  Slower but more accurate search (tries multiple candidates).
- **Incremental update** _(enabled internally)_  
  Skips tracks that already exist in the playlist folder using URI/tags/filename matching. Maintains a `manifest.json`.

---

## 📂 Output

- Files are saved under:  
  `/<YourOutputFolder>/<PlaylistName>/`
- Filenames follow either:
  - `001 - Track Name.m4a` (if numbering is enabled), or
  - `Track Name.m4a` (if disabled).
- Basic tags are written (Title, Artist, Album, Track # when numbered).
- A `.m3u` playlist is generated if enabled.

---

## 💡 Notes

- This tool **does not rip Spotify audio**. Tracks are located on public sources (e.g., YouTube) via yt-dlp and then remuxed/re-encoded.
- **FFmpeg** and **yt-dlp** are bundled in the releases; no installs needed.
- If a track fails, try toggling **Deep search** or adjusting query variants.

---

## 🔐 Privacy & Auth

- Spotify sign-in uses **OAuth PKCE**: no client secret, no data sent to any server we control.
- The local redirect runs on `http://127.0.0.1:8765/callback` just for the auth code exchange.
- Tokens are kept in memory for the current session.
- When loading from a playlist URL, the generated CSV is **temporary** (used internally by the converter).

---

## 🛠️ Build from Source (optional)

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
   - Linux: `pyinstaller Music2MP3-Linux.spec` (AppImage packaging script included in CI)

The specs include data files (ffmpeg, yt-dlp, icons, config) and produce the single-folder app in `dist/`.

---

## 🧰 Troubleshooting

- **“(Not Responding)” on Windows while downloading**  
  The UI now runs long tasks in worker threads; per-track progress bars keep updating. If you still see UI freezes, ensure GPU overlays/AV scanners aren’t throttling file writes.
- **Age-restricted videos on YouTube**  
  yt-dlp might refuse them without cookies. Add a cookies file to `config.json` if needed.
- **Too many duplicates**  
  Make sure you’re running the latest version. The app compares by URI → tags → filename (without numeric prefix) and keeps a `manifest.json`.
- **ffmpeg/yt-dlp missing (source builds)**  
  Confirm the platform-specific binaries are in `ffmpeg/` and `yt-dlp/` next to the executable/spec.

---

## 📜 License

MIT
