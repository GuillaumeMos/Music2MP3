import os, csv, re, time, json, subprocess, platform
from datetime import timedelta
from mutagen.mp4 import MP4, MP4Tags
from mutagen.easyid3 import EasyID3

from utils import safe_name

class Converter:
    def __init__(self, config: dict, status_cb=lambda s: None, progress_cb=lambda cur,maxi: None):
        self.cfg = config
        self.status = status_cb
        self.progress = progress_cb

    def _binaries(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if platform.system() == "Darwin":
            ffmpeg = os.path.join(base_dir, "ffmpeg", "ffmpeg")
            ytdlp = os.path.join(base_dir, "yt-dlp", "yt-dlp")
        else:
            ffmpeg = os.path.join(base_dir, "ffmpeg", "ffmpeg.exe")
            ytdlp = os.path.join(base_dir, "yt-dlp", "yt-dlp.exe")
        return ffmpeg, ytdlp

    def _yt_cmd(self, ytdlp, ffmpeg_dir, cookies_path, extra_args, search_spec):
        cmd = [ytdlp, f"--ffmpeg-location={ffmpeg_dir}", "--no-config"]
        if cookies_path:
            cmd += ["--cookies", cookies_path]
        cmd += extra_args + [search_spec]
        return cmd

    def convert_from_csv(self, csv_path: str, output_folder: str, playlist_name_hint: str | None = None):
        start = time.time()
        rows = list(csv.DictReader(open(csv_path, newline='', encoding='utf-8')))
        total = len(rows)
        playlist_name = playlist_name_hint or os.path.splitext(os.path.basename(csv_path))[0]
        out_dir = os.path.join(output_folder, playlist_name)
        os.makedirs(out_dir, exist_ok=True)

        ffmpeg, ytdlp = self._binaries()
        if not (os.path.isfile(ffmpeg) and os.path.isfile(ytdlp)):
            raise RuntimeError("ffmpeg ou yt-dlp introuvable.")

        archive_file = os.path.join(out_dir, 'downloaded.txt')
        creationflags = subprocess.CREATE_NO_WINDOW if platform.system()== 'Windows' else 0
        duration_min = self.cfg.get("duration_min", 0)
        duration_max = self.cfg.get("duration_max", 10**9)
        deep_search = True  # tu peux exposer ce flag via l'UI
        cookies_path = self.cfg.get('cookies_path')

        downloaded = []
        not_found = []

        for i, row in enumerate(rows, start=1):
            title = row.get('Track Name') or row.get('Track name') or 'Unknown'
            artist_raw = row.get('Artist Name(s)') or row.get('Artist name') or 'Unknown'
            artist_primary = re.split(r'[,/&]| feat\.| ft\.', artist_raw, flags=re.I)[0].strip()
            album = row.get('Album Name') or row.get('Album') or playlist_name
            ms = row.get('Duration (ms)')
            spotify_sec = int(ms)/1000 if ms and str(ms).isdigit() else None

            safe_title = safe_name(title)
            variants = self.cfg.get('variants') or ['']
            if 'instrumental' in (title or '').lower():
                variants = ['instrumental'] + variants

            best_file = None
            for variant in variants:
                parts = [safe_title]
                if artist_primary and artist_primary.lower() != 'unknown':
                    parts.append(safe_name(artist_primary))
                if variant:
                    parts.append(variant)
                q = ' '.join(parts)
                self.status(f"[{i}/{total}] Recherche: {q}")

                def normalize(t: str):
                    import re
                    return re.sub(r"[^\w\s]", "", (t or "").lower())

                def contains_keywords_in_order(candidate: str, keywords: list[str]):
                    txt = normalize(candidate)
                    pos = 0
                    for kw in keywords:
                        idx = txt.find(kw, pos)
                        if idx < 0:
                            return False
                        pos = idx + len(kw)
                    return True

                def pick_download_spec():
                    ffdir = os.path.dirname(ffmpeg)
                    if deep_search:
                        # phase rapide 1
                        proc_q = subprocess.run(
                            self._yt_cmd(ytdlp, ffdir, cookies_path, ["--flat-playlist","--dump-single-json","--no-playlist"], f"ytsearch1:{q}"),
                            capture_output=True, text=True, creationflags=creationflags
                        )
                        try:
                            data_q = json.loads(proc_q.stdout) or {}
                        except Exception:
                            data_q = {}
                        entries_q = data_q.get('entries') if isinstance(data_q.get('entries'), list) else []
                        top = entries_q[0] if entries_q else {}
                        title_top = top.get('title','')
                        up = (top.get('uploader') or '').lower()
                        dur = top.get('duration') or 0
                        ok = (
                            safe_title.lower() in title_top.lower()
                            and (not artist_primary or artist_primary.lower() in up)
                            and (not spotify_sec or abs(dur-spotify_sec) <= 10)
                            and (duration_min <= dur <= duration_max)
                        )
                        if ok:
                            return top.get('webpage_url', f"https://www.youtube.com/watch?v={top.get('id','')}")

                        # phase approfondie 2
                        proc_ids = subprocess.run(
                            self._yt_cmd(ytdlp, ffdir, cookies_path, ["--flat-playlist","--dump-single-json","--no-playlist"], f"ytsearch3:{q}"),
                            capture_output=True, text=True, creationflags=creationflags
                        )
                        try:
                            data_ids = json.loads(proc_ids.stdout) or {}
                        except Exception:
                            data_ids = {}
                        entries_ids = data_ids.get('entries') if isinstance(data_ids.get('entries'), list) else []
                        ids = [e for e in entries_ids if isinstance(e, dict)][:3]

                        scored = []
                        first_words = normalize(title).split()[:5]
                        for entry in ids:
                            vid = entry.get('id')
                            if not vid:
                                continue
                            url = f"https://www.youtube.com/watch?v={vid}"
                            proc_i = subprocess.run(
                                self._yt_cmd(ytdlp, ffdir, cookies_path, ["--dump-single-json","--no-playlist"], url),
                                capture_output=True, text=True, creationflags=creationflags
                            )
                            if "Sign in to confirm your age" in (proc_i.stderr or ''):
                                continue
                            try:
                                info = json.loads(proc_i.stdout) or {}
                            except Exception:
                                continue
                            raw_title = info.get('title','')
                            up2 = (info.get('uploader') or '').lower()
                            dur2 = info.get('duration') or 0
                            if dur2 < duration_min or dur2 > duration_max:
                                continue
                            if 'shorts/' in info.get('webpage_url','') or '#shorts' in raw_title.lower():
                                continue
                            if artist_primary and artist_primary.lower() not in up2:
                                continue
                            if variant and variant.lower() not in raw_title.lower():
                                continue
                            if not contains_keywords_in_order(raw_title, first_words):
                                continue
                            score = 100 if raw_title.lower().startswith(safe_title.lower()) else 80
                            if spotify_sec:
                                score -= abs(dur2 - spotify_sec)
                            scored.append((score, url))
                        return scored and max(scored, key=lambda x: x[0])[1] or f"ytsearch1:{q}"
                    else:
                        return f"ytsearch1:{q}"

                download_spec = pick_download_spec()

                file_title = safe_name(title)
                base = f"{i:03d} - {file_title}" + (f" - {variant}" if variant else "")
                tmpl = base + ".%(ext)s"
                args = [
                    '--download-archive', archive_file,
                    '-f', 'bestaudio[ext=m4a]/bestaudio',
                    '--output', os.path.join(out_dir, tmpl),
                    '--no-playlist'
                ]
                if self.cfg.get('thumb', False):
                    args += ['--embed-thumbnail','--add-metadata']
                if self.cfg.get('transcode_mp3', False):
                    args += ['--extract-audio','--audio-format','mp3','--audio-quality','0']
                else:
                    args += ['--remux-video','m4a']
                if self.cfg.get('exclude_instrumentals', False):
                    args += ['--reject-title','instrumental']

                ret = subprocess.run(self._yt_cmd(ytdlp, os.path.dirname(ffmpeg), cookies_path, args, download_spec),
                                     capture_output=True, text=True, creationflags=creationflags)
                if ret.returncode != 0:
                    if 'Sign in to confirm your age' in (ret.stderr or ''):
                        not_found.append({"Track Name": title, "Artist Name(s)": artist_primary, "Album Name": album, "Track Number": i, "Error": "Age-restricted"})
                        break
                    continue

                out_ext = '.mp3' if self.cfg.get('transcode_mp3', False) else '.m4a'
                candidate = os.path.join(out_dir, base + out_ext)
                if os.path.isfile(candidate):
                    best_file = candidate
                    if out_ext == '.m4a':
                        audio = MP4(best_file); tags = audio.tags or MP4Tags()
                        tags['\xa9nam']=[title]; tags['\xa9ART']=[artist_primary]; tags['\xa9alb']=[album]; audio.save()
                    else:
                        audio = EasyID3()
                        try: audio.load(best_file)
                        except Exception: pass
                        audio.update({'artist':artist_primary,'title':title,'album':album,'tracknumber':str(i)}); audio.save()
                    downloaded.append(os.path.basename(best_file))
                    break

            if not best_file:
                not_found.append({'Track Name': title, 'Artist Name(s)': artist_primary, 'Album Name': album, 'Track Number': i, 'Error': 'No valid download'})

            elapsed = time.time() - start
            eta = timedelta(seconds=int((elapsed/i)*(total-i)))
            self.progress(i, total)
            self.status(f"Téléchargé {i}/{total}, ETA: {eta}")

        # Fichiers annexes
        if not_found:
            nf_path = os.path.join(out_dir, f"{playlist_name}_not_found.csv")
            with open(nf_path, 'w', newline='', encoding='utf-8') as cf:
                writer = csv.DictWriter(cf, fieldnames=['Track Name','Artist Name(s)','Album Name','Track Number','Error'])
                writer.writeheader(); writer.writerows(not_found)

        if self.cfg.get('generate_m3u', True):
            m3u_filename = playlist_name.replace('_',' ')
            m3u_path = os.path.join(out_dir, f"{m3u_filename}.m3u")
            with open(m3u_path,'w',encoding='utf-8') as m3u:
                m3u.write('#EXTM3U\n')
                audio_files = sorted([f for f in os.listdir(out_dir) if f.lower().endswith(('.mp3','.m4a'))], key=lambda x: os.path.getctime(os.path.join(out_dir,x)))
                for fn in audio_files:
                    m3u.write(f'#EXTINF:-1,{os.path.splitext(fn)[0]}\n')
                    m3u.write(f'{fn}\n')

        return out_dir