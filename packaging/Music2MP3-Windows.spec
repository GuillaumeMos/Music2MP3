# -*- mode: python ; coding: utf-8 -*-
import os
import shutil

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
    _pick_binary("ffmpeg/ffmpeg.exe", "ffmpeg.exe"),
    _pick_binary("yt-dlp/yt-dlp.exe", "yt-dlp.exe"),
    (_repo_path("config.json"), "."),
    (_repo_path("icon.ico"), "."),
]

a = Analysis(
     [_repo_path('app.py')],
    pathex=[PROJECT_ROOT],
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
    a.binaries,
    a.datas,
    [],
    name='Music2MP3',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[_repo_path('icon.ico')],
)
