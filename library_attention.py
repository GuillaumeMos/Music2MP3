from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


def _candidate_url(track: dict[str, Any]) -> str:
    suggested = str(track.get("suggested_url") or "").strip()
    if suggested:
        return suggested
    match = track.get("match") if isinstance(track.get("match"), dict) else {}
    return str(match.get("url") or "").strip()


def _failed_issue(track: dict[str, Any]) -> tuple[str, str]:
    error = str(track.get("error") or "").strip()
    low = error.casefold()
    suggested_url = str(track.get("suggested_url") or "").strip()
    if suggested_url and ("manual validation" in low or "ai suggested" in low):
        return "review", "Review suggested match"
    if "403" in low or "forbidden" in low:
        return "failed", "Download blocked"
    if "drm" in low or "private" in low or "not available" in low:
        return "failed", "Source unavailable"
    if "no youtube results" in low or "no safe youtube match" in low:
        return "failed", "No reliable match"
    return "failed", "Download failed"


def collect_attention_items(playlists: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return actionable failed/missing tracks across manifest playlists."""

    items: list[dict[str, Any]] = []
    for playlist in playlists:
        if not isinstance(playlist, dict) or playlist.get("_legacy"):
            continue
        playlist_name = str(playlist.get("playlist_name") or "Playlist")
        playlist_dir = str(playlist.get("playlist_dir") or "").strip()
        manifest_path = str(playlist.get("_manifest_path") or "").strip()
        tracks = playlist.get("tracks") if isinstance(playlist.get("tracks"), list) else []
        for track in tracks:
            if not isinstance(track, dict):
                continue
            status = str(track.get("status") or "").strip().casefold()
            file_name = str(track.get("file") or "").strip()
            file_exists = bool(
                file_name and playlist_dir and (Path(playlist_dir) / file_name).is_file()
            )
            if status == "failed":
                kind, issue = _failed_issue(track)
            elif status in {"done", "skipped"} and file_name and not file_exists:
                kind, issue = "missing", "Downloaded file is missing"
            else:
                continue

            items.append({
                "playlist_name": playlist_name,
                "playlist_dir": playlist_dir,
                "manifest_path": manifest_path,
                "track_idx": int(track.get("idx") or 0),
                "title": str(track.get("title") or f"Track {track.get('idx') or '?'}"),
                "artists": str(track.get("artists") or ""),
                "status": status,
                "kind": kind,
                "issue": issue,
                "error": str(track.get("error") or ""),
                "candidate_url": _candidate_url(track),
                "track": dict(track),
            })

    priority = {"review": 0, "failed": 1, "missing": 2}
    items.sort(key=lambda item: (
        priority.get(str(item.get("kind")), 9),
        str(item.get("playlist_name") or "").casefold(),
        int(item.get("track_idx") or 0),
    ))
    return items


def attention_counts(items: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {"total": 0, "review": 0, "failed": 0, "missing": 0}
    for item in items:
        counts["total"] += 1
        kind = str(item.get("kind") or "")
        if kind in counts:
            counts[kind] += 1
    return counts
