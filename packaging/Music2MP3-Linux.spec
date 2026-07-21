# -*- mode: python ; coding: utf-8 -*-
import os
import shutil
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))


def _repo_path(path: str) -> str:
    return os.path.join(PROJECT_ROOT, path)


def _pick_binary(local_path: str, fallback_name: str) -> tuple[str, str]:
    """
    Return (source_path, dest_dir_name) for bundled binaries.
    Priority: local repo path, then PATH lookup.
    """
    source_path = _repo_path(local_path)
    if os.path.isfile(source_path):
        return (source_path, os.path.dirname(local_path))
    found = shutil.which(fallback_name)
    if found:
        return (found, os.path.dirname(local_path))
    raise SystemExit(
        f"Missing required binary: {fallback_name}. "
        f"Provide {local_path} or install `{fallback_name}` in PATH."
    )


datas = [
    _pick_binary("ffmpeg/ffmpeg", "ffmpeg"),
    _pick_binary("yt-dlp/yt-dlp", "yt-dlp"),
    (_repo_path("config.json"), "."),
    (_repo_path("icon.png"), "."),
]

a = Analysis(
     [_repo_path('app.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=['zlib'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

a.binaries = [b for b in a.binaries if 'libz' not in b[0].lower()]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Music2MP3',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=_repo_path('icon.png'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Music2MP3'
)
