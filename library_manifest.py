from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_FILENAME = "music2mp3.manifest.json"
SCHEMA_VERSION = 1
_AUDIO_EXTS = {
    ".mp3",
    ".m4a",
    ".aac",
    ".wav",
    ".flac",
    ".aiff",
    ".aif",
    ".opus",
    ".ogg",
    ".webm",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def manifest_path(playlist_dir: str | os.PathLike[str]) -> Path:
    return Path(playlist_dir) / MANIFEST_FILENAME


def read_manifest(path_or_dir: str | os.PathLike[str]) -> dict[str, Any] | None:
    path = Path(path_or_dir)
    if path.is_dir():
        path = manifest_path(path)
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def write_manifest(playlist_dir: str | os.PathLike[str], manifest: dict[str, Any]) -> Path:
    path = manifest_path(playlist_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def build_manifest(
    *,
    playlist_name: str,
    playlist_dir: str | os.PathLike[str],
    source: dict[str, Any] | None,
    settings: dict[str, Any],
    tracks: list[dict[str, Any]],
    previous_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = previous_manifest if isinstance(previous_manifest, dict) else {}
    created_at = str(previous.get("created_at") or utc_now_iso())
    source_data = source if isinstance(source, dict) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "app": "Music2MP3",
        "playlist_name": playlist_name,
        "playlist_dir": str(Path(playlist_dir).resolve()),
        "source": {
            "type": source_data.get("type") or "unknown",
            "url": source_data.get("url") or "",
            "name": source_data.get("name") or playlist_name,
        },
        "settings": settings,
        "created_at": created_at,
        "updated_at": utc_now_iso(),
        "track_count": len(tracks),
        "tracks": tracks,
    }


def scan_library(root_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    root = Path(root_dir)
    if not root.is_dir():
        return []

    playlists: list[dict[str, Any]] = []
    manifest_dirs: set[Path] = set()
    for path in root.rglob(MANIFEST_FILENAME):
        data = read_manifest(path)
        if not data:
            continue
        data["_manifest_path"] = str(path)
        try:
            manifest_dirs.add(path.parent.resolve())
        except Exception:
            manifest_dirs.add(path.parent)
        playlists.append(data)

    legacy_dirs = [root]
    legacy_dirs.extend(p for p in root.rglob("*") if p.is_dir())
    for child in sorted(legacy_dirs, key=lambda p: str(p).casefold()):
        resolved = _resolve_path(child)
        if _is_under_any(resolved, manifest_dirs):
            continue
        try:
            direct_files = [p for p in child.iterdir() if p.is_file()]
        except Exception:
            continue
        audio_files = [p for p in direct_files if p.suffix.lower() in _AUDIO_EXTS]
        m3u_files = [p for p in direct_files if p.suffix.lower() in {".m3u", ".m3u8"}]
        if not audio_files and not m3u_files:
            continue
        playlists.append({
            "schema_version": 0,
            "app": "Music2MP3",
            "playlist_name": child.name,
            "playlist_dir": str(resolved),
            "source": {"type": "legacy", "url": "", "name": child.name},
            "settings": {},
            "created_at": "",
            "updated_at": "",
            "track_count": len(audio_files),
            "tracks": [],
            "_legacy": True,
        })

    return dedupe_playlists(playlists)


def dedupe_playlists(playlists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: dict[str, dict[str, Any]] = {}
    no_key: list[dict[str, Any]] = []
    for playlist in playlists:
        key = playlist_identity(playlist)
        if not key:
            no_key.append(playlist)
            continue
        current = kept.get(key)
        if current is None or _playlist_rank(playlist) > _playlist_rank(current):
            kept[key] = playlist

    out = list(kept.values()) + no_key
    out.sort(key=lambda item: str(item.get("playlist_name") or "").casefold())
    return out


def playlist_identity(manifest: dict[str, Any]) -> str:
    source = manifest_source(manifest)
    source_url = source.get("url", "").strip().lower()
    source_type = source.get("type", "").strip().lower()
    if source_url and source_type:
        return f"source:{source_type}:{source_url}"
    playlist_dir = str(manifest.get("playlist_dir") or "").strip()
    if playlist_dir:
        return f"path:{_resolve_path(Path(playlist_dir))}"
    name = _norm_name(str(manifest.get("playlist_name") or source.get("name") or ""))
    return f"name:{source_type}:{name}" if name else ""


def _playlist_rank(manifest: dict[str, Any]) -> tuple[int, int, str]:
    has_manifest = 0 if manifest.get("_legacy") else 1
    track_count = int(manifest.get("track_count") or len(manifest.get("tracks") or []))
    updated_at = str(manifest.get("updated_at") or manifest.get("created_at") or "")
    return has_manifest, track_count, updated_at


def _resolve_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except Exception:
        return path.expanduser()


def _is_under_any(path: Path, parents: set[Path]) -> bool:
    for parent in parents:
        if path == parent:
            return True
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            continue
    return False


def _norm_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def playlist_output_parent(manifest: dict[str, Any]) -> str:
    playlist_dir = str(manifest.get("playlist_dir") or "").strip()
    if not playlist_dir:
        return ""
    return str(Path(playlist_dir).expanduser().resolve().parent)


def manifest_source(manifest: dict[str, Any]) -> dict[str, str]:
    raw = manifest.get("source")
    source = raw if isinstance(raw, dict) else {}
    return {
        "type": str(source.get("type") or "").strip().lower(),
        "url": str(source.get("url") or "").strip(),
        "name": str(source.get("name") or manifest.get("playlist_name") or "").strip(),
    }
