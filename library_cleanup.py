from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from library_manifest import IGNORE_FILENAME, MANIFEST_FILENAME, read_manifest


AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".aac", ".wav", ".flac",
    ".aiff", ".aif", ".opus", ".ogg", ".webm",
}
CLEANUP_DIRNAME = ".music2mp3-cleanup"


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _is_cleanup_path(path: Path, root: Path) -> bool:
    try:
        return CLEANUP_DIRNAME in path.relative_to(root).parts
    except ValueError:
        return False


def _canonical_source_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    return raw.casefold()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duplicate_track_indexes(tracks: list[dict[str, Any]]) -> list[int]:
    seen: set[str] = set()
    duplicate_indexes: list[int] = []
    for index, track in enumerate(tracks):
        file_name = Path(str(track.get("file") or "")).name.strip().casefold()
        if not file_name:
            continue
        if file_name in seen:
            duplicate_indexes.append(index)
        else:
            seen.add(file_name)
    return duplicate_indexes


def analyze_library_cleanup(root_dir: str | Path) -> dict[str, Any]:
    """Build a read-only cleanup report for one Music2MP3 library."""

    root = _resolved(root_dir)
    if not root.is_dir():
        raise ValueError(f"Library folder does not exist: {root}")

    report: dict[str, Any] = {
        "root": str(root),
        "audio_file_count": 0,
        "orphan_files": [],
        "loose_root_files": [],
        "duplicate_track_entries": [],
        "nested_playlists": [],
        "duplicate_sources": [],
        "exact_duplicate_groups": [],
        "exact_duplicate_copies": 0,
        "exact_duplicate_bytes": 0,
        "errors": [],
    }

    manifest_paths = sorted(
        path for path in root.rglob(MANIFEST_FILENAME)
        if not _is_cleanup_path(path, root)
    )
    source_groups: dict[str, list[str]] = defaultdict(list)

    for manifest_path in manifest_paths:
        manifest = read_manifest(manifest_path)
        if not manifest:
            report["errors"].append(f"Unreadable manifest: {manifest_path}")
            continue

        playlist_dir = manifest_path.parent.resolve()
        tracks = manifest.get("tracks") if isinstance(manifest.get("tracks"), list) else []
        referenced = {
            Path(str(track.get("file") or "")).name.casefold()
            for track in tracks
            if isinstance(track, dict) and track.get("file")
        }
        for path in playlist_dir.iterdir():
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                if path.name.casefold() not in referenced:
                    report["orphan_files"].append(str(path))

        duplicate_indexes = _duplicate_track_indexes(
            [track for track in tracks if isinstance(track, dict)]
        )
        if duplicate_indexes:
            report["duplicate_track_entries"].append({
                "manifest_path": str(manifest_path),
                "playlist_name": str(manifest.get("playlist_name") or playlist_dir.name),
                "indexes": duplicate_indexes,
            })

        relative_dir = playlist_dir.relative_to(root)
        if len(relative_dir.parts) > 1:
            target_dir = root / playlist_dir.name
            report["nested_playlists"].append({
                "playlist_dir": str(playlist_dir),
                "target_dir": str(target_dir),
                "playlist_name": str(manifest.get("playlist_name") or playlist_dir.name),
                "can_flatten": not target_dir.exists(),
            })

        source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
        source_type = str(source.get("type") or "").strip().casefold()
        source_url = _canonical_source_url(str(source.get("url") or ""))
        if source_type and source_url:
            source_groups[f"{source_type}:{source_url}"].append(str(playlist_dir))

    report["duplicate_sources"] = [
        paths for paths in source_groups.values() if len(paths) > 1
    ]
    report["loose_root_files"] = [
        str(path) for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    ]

    audio_files = [
        path for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in AUDIO_EXTENSIONS
        and not _is_cleanup_path(path, root)
    ]
    report["audio_file_count"] = len(audio_files)
    files_by_size: dict[int, list[Path]] = defaultdict(list)
    for path in audio_files:
        try:
            files_by_size[path.stat().st_size].append(path)
        except OSError as exc:
            report["errors"].append(f"Could not inspect {path}: {exc}")

    files_by_hash: dict[tuple[int, str], list[Path]] = defaultdict(list)
    for size, paths in files_by_size.items():
        if len(paths) < 2:
            continue
        for path in paths:
            try:
                files_by_hash[(size, _file_sha256(path))].append(path)
            except OSError as exc:
                report["errors"].append(f"Could not hash {path}: {exc}")

    exact_groups = [paths for paths in files_by_hash.values() if len(paths) > 1]
    report["exact_duplicate_groups"] = [
        [str(path) for path in paths] for paths in exact_groups
    ]
    report["exact_duplicate_copies"] = sum(len(paths) - 1 for paths in exact_groups)
    report["exact_duplicate_bytes"] = sum(
        (len(paths) - 1) * paths[0].stat().st_size for paths in exact_groups
    )
    return report


def cleanup_action_count(report: dict[str, Any]) -> int:
    duplicate_entries = sum(
        len(item.get("indexes") or [])
        for item in report.get("duplicate_track_entries") or []
    )
    flattenable = sum(
        1 for item in report.get("nested_playlists") or []
        if item.get("can_flatten")
    )
    return (
        len(report.get("orphan_files") or [])
        + len(report.get("loose_root_files") or [])
        + duplicate_entries
        + flattenable
    )


def _unique_backup_path(backup_dir: Path, source: Path, root: Path) -> Path:
    relative = source.relative_to(root)
    safe_name = " -- ".join(relative.parts)
    candidate = backup_dir / safe_name
    counter = 2
    while candidate.exists():
        candidate = backup_dir / f"{Path(safe_name).stem} ({counter}){source.suffix}"
        counter += 1
    return candidate


def apply_library_cleanup(report: dict[str, Any]) -> dict[str, Any]:
    """Apply only reversible/safe actions from a fresh cleanup report."""

    root = _resolved(str(report.get("root") or ""))
    if not root.is_dir():
        raise ValueError(f"Library folder does not exist: {root}")

    result: dict[str, Any] = {
        "moved_files": 0,
        "removed_track_entries": 0,
        "flattened_playlists": 0,
        "backup_dir": "",
        "errors": [],
    }
    candidates = list(dict.fromkeys(
        list(report.get("orphan_files") or [])
        + list(report.get("loose_root_files") or [])
    ))
    valid_files: list[Path] = []
    for raw_path in candidates:
        path = _resolved(raw_path)
        if path.is_file() and _is_inside(path, root) and not _is_cleanup_path(path, root):
            valid_files.append(path)

    backup_dir: Path | None = None
    move_records: list[dict[str, str]] = []
    if valid_files:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = root / CLEANUP_DIRNAME / stamp
        counter = 2
        while backup_dir.exists():
            backup_dir = root / CLEANUP_DIRNAME / f"{stamp}-{counter}"
            counter += 1
        backup_dir.mkdir(parents=True)
        (backup_dir / IGNORE_FILENAME).write_text(
            "Music2MP3 cleanup recovery folder.\n", encoding="utf-8"
        )
        result["backup_dir"] = str(backup_dir)
        for source in valid_files:
            destination = _unique_backup_path(backup_dir, source, root)
            try:
                shutil.move(str(source), str(destination))
                move_records.append({"from": str(source), "to": str(destination)})
                result["moved_files"] += 1
            except OSError as exc:
                result["errors"].append(f"Could not move {source}: {exc}")

    for item in report.get("duplicate_track_entries") or []:
        manifest_path = _resolved(str(item.get("manifest_path") or ""))
        if not manifest_path.is_file() or not _is_inside(manifest_path, root):
            continue
        manifest = read_manifest(manifest_path)
        if not manifest:
            result["errors"].append(f"Could not read {manifest_path}")
            continue
        tracks = manifest.get("tracks") if isinstance(manifest.get("tracks"), list) else []
        seen: set[str] = set()
        cleaned_tracks: list[dict[str, Any]] = []
        removed = 0
        for track in tracks:
            if not isinstance(track, dict):
                continue
            key = Path(str(track.get("file") or "")).name.strip().casefold()
            if key and key in seen:
                removed += 1
                continue
            if key:
                seen.add(key)
            cleaned_tracks.append(track)
        if removed:
            manifest["tracks"] = cleaned_tracks
            manifest["track_count"] = len(cleaned_tracks)
            manifest["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            manifest.pop("_manifest_path", None)
            try:
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                result["removed_track_entries"] += removed
            except OSError as exc:
                result["errors"].append(f"Could not update {manifest_path}: {exc}")

    nested_items = sorted(
        report.get("nested_playlists") or [],
        key=lambda item: len(Path(str(item.get("playlist_dir") or "")).parts),
        reverse=True,
    )
    for item in nested_items:
        if not item.get("can_flatten"):
            continue
        source = _resolved(str(item.get("playlist_dir") or ""))
        target = _resolved(str(item.get("target_dir") or ""))
        if (
            not source.is_dir()
            or not _is_inside(source, root)
            or target.parent != root
            or target.exists()
        ):
            continue
        try:
            shutil.move(str(source), str(target))
            manifest_path = target / MANIFEST_FILENAME
            manifest = read_manifest(manifest_path)
            if manifest:
                manifest["playlist_dir"] = str(target)
                manifest.pop("_manifest_path", None)
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            result["flattened_playlists"] += 1
        except OSError as exc:
            result["errors"].append(f"Could not flatten {source}: {exc}")

    if backup_dir:
        (backup_dir / "cleanup.json").write_text(
            json.dumps({"root": str(root), "moves": move_records}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return result
