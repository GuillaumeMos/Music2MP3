# -*- mode: python ; coding: utf-8 -*-
import os
import shutil


def _pick_binary(local_path: str, fallback_name: str) -> tuple[str, str]:
    """
    Return (source_path, dest_dir_name) for bundled binaries.
    Priority: local repo path, then PATH lookup.
    """
    if os.path.isfile(local_path):
        return (local_path, os.path.dirname(local_path))
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
    ("config.json", "."),
    ("icon.png", "."),
]

a = Analysis(
    ["qt_app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Music2MP3",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="icon.png",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Music2MP3",
)
