"""Prepare the local PySide6 runtime for reliable development launches."""

from __future__ import annotations

import logging
import platform
import subprocess
import sys
from pathlib import Path


log = logging.getLogger(__name__)


def prepare_qt_runtime() -> None:
    """Make macOS Qt plugins visible to Qt's directory scanner.

    Some local environments can carry the macOS ``hidden`` file flag across a
    wheel extraction. Qt's plugin loader excludes hidden directory entries, so
    valid platform plugins then appear to be missing. Only the PySide6 plugin
    directory inside the active virtual environment is modified.
    """

    if platform.system() != "Darwin":
        return

    from PySide6.QtCore import QDir, QLibraryInfo

    plugin_dir = Path(
        QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
    ).resolve()
    venv_root = Path(sys.prefix).resolve()
    if not plugin_dir.is_relative_to(venv_root):
        raise RuntimeError(
            f"Refusing to modify Qt plugins outside the active venv: {plugin_dir}"
        )
    if not plugin_dir.is_dir():
        raise RuntimeError(f"Qt plugin directory does not exist: {plugin_dir}")

    subprocess.run(
        ["chflags", "-R", "nohidden", str(plugin_dir)],
        check=True,
    )

    platforms_dir = plugin_dir / "platforms"
    directory = QDir(str(platforms_dir))
    directory.refresh()
    visible_plugins = set(directory.entryList(QDir.Filter.Files))
    if "libqcocoa.dylib" not in visible_plugins:
        raise RuntimeError(
            f"Qt Cocoa plugin is still not visible after repair: {platforms_dir}"
        )
    log.info("Qt runtime ready: %s", platforms_dir)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    prepare_qt_runtime()
