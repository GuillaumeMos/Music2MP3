import os, subprocess, platform, re
from mutagen.easyid3 import EasyID3
from mutagen.mp4 import MP4, MP4Tags

class Artwork:
    def __init__(self, ffmpeg_dir: str):
        self.ffmpeg = os.path.join(ffmpeg_dir, "ffmpeg" + (".exe" if platform.system()=="Windows" else ""))

    def embed_art(self, audio_file: str, jpg_file: str):
        audio_dir = os.path.dirname(audio_file)
        temp_output = os.path.join(audio_dir, "temp_" + os.path.basename(audio_file))
        cmd = [self.ffmpeg, '-i', audio_file, '-i', jpg_file, '-map', '0:a', '-map', '1:v', '-c:a', 'copy', '-c:v', 'mjpeg', '-disposition:v:0', 'attached_pic', temp_output]
        creationflags = subprocess.CREATE_NO_WINDOW if platform.system()=="Windows" else 0
        subprocess.run(cmd, check=True, capture_output=True, creationflags=creationflags)
        os.replace(temp_output, audio_file)

    @staticmethod
    def write_basic_tags_m4a(path: str, title: str, artist: str, album: str):
        audio = MP4(path)
        tags = audio.tags or MP4Tags()
        tags['\xa9nam'] = [title]
        tags['\xa9ART'] = [artist]
        tags['\xa9alb'] = [album]
        audio.save()

    @staticmethod
    def write_basic_tags_mp3(path: str, title: str, artist: str, album: str, trackno: int):
        try:
            audio = EasyID3(path)
        except Exception:
            audio = EasyID3()
        audio['title'] = title
        audio['artist'] = artist
        audio['album'] = album
        audio['tracknumber'] = str(trackno)
        audio.save()