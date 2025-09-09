# ui_preview.py — preview the GUI with fake downloads
import os, csv, time, tempfile, tkinter as tk
import gui as appgui  # your gui.py

# --- Fake converter that simulates events ---
class FakeConverter:
    def __init__(self, config, status_cb, progress_cb, item_cb):
        self.status_cb = status_cb
        self.progress_cb = progress_cb
        self.item_cb = item_cb
        self.config = config or {}

    def convert_from_csv(self, csv_path, output_folder, playlist_name_hint=None):
        with open(csv_path, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        total = len(rows)
        name = playlist_name_hint or "Preview Playlist"

        # tell GUI how many "new" tracks
        self.item_cb('conv_init', {'total': total, 'new': total, 'playlist': name})
        self.status_cb(f"Starting fake download of {total} tracks…")

        for i, row in enumerate(rows, start=1):
            title = row.get("Track Name", f"Track {i}")
            artist = row.get("Artist Name(s)", "Artist")
            self.item_cb('init', {'idx': i, 'title': f"{title} — {artist}"})
            for p in range(0, 101, 5):
                self.item_cb('progress', {'idx': i, 'percent': p, 'speed': '1.2MB/s', 'eta': '00:10'})
                time.sleep(0.03)
            self.item_cb('done', {'idx': i})

        self.status_cb("✅ Done (fake)")
        # return a dummy folder
        out_dir = os.path.join(output_folder, name)
        os.makedirs(out_dir, exist_ok=True)
        return out_dir

# Monkey-patch the Converter used by gui.py
appgui.Converter = FakeConverter

# Create a tiny CSV in temp just for preview
fd, tmp_csv = tempfile.mkstemp(prefix="preview_", suffix=".csv"); os.close(fd)
sample = [
    {"Track Name": "Acid Base Reaction", "Artist Name(s)": "Mika Heggemann", "Album Name": "Preview", "Duration (ms)": "180000"},
    {"Track Name": "Hands Up In The Sky", "Artist Name(s)": "Marlon Hoffstadt", "Album Name": "Preview", "Duration (ms)": "180000"},
    {"Track Name": "Flashback", "Artist Name(s)": "Pegassi", "Album Name": "Preview", "Duration (ms)": "180000"},
    {"Track Name": "Spectral Bells", "Artist Name(s)": "Pegassi", "Album Name": "Preview", "Duration (ms)": "180000"},
]
with open(tmp_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["Track Name","Artist Name(s)","Album Name","Duration (ms)"])
    w.writeheader(); w.writerows(sample)

# Launch the real GUI class but prefill paths
root = tk.Tk()
app = appgui.Music2MP3GUI(root)

# Set the CSV and an output temp folder to enable the Convert button
app.csv_path = tmp_csv
app._style_drop_loaded(os.path.basename(tmp_csv))
tmp_out = tempfile.mkdtemp(prefix="preview_out_")
app.output_folder = tmp_out
app.out_entry.config(state='normal'); app.out_entry.delete(0,'end'); app.out_entry.insert(0, tmp_out); app.out_entry.config(state='readonly')
app.update_convert_button_state()

root.mainloop()
