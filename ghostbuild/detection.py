"""Project detection: choose the adapter that recognises a project."""

from __future__ import annotations

from pathlib import Path

from ghostbuild.adapters import BuildAdapter, get_adapters
from ghostbuild.errors import UnsupportedProjectError
from ghostbuild.models import ProjectInfo
from ghostbuild.utils.filesystem import validate_directory


def detect_project(path: Path | str) -> tuple[BuildAdapter, ProjectInfo]:
    """Return the adapter and metadata for the project at ``path``.

    Only reads files; no project code is executed.
    """
    root = validate_directory(path, "project directory")
    for adapter in get_adapters():
        if adapter.detect(root):
            return adapter, adapter.inspect(root)
    supported = ", ".join(a.language for a in get_adapters())
    raise UnsupportedProjectError(
        f"No supported project found in {root}. Supported ecosystems: {supported}. "
        "For Python, GhostBuild looks for pyproject.toml (with [build-system], [project] or "
        "[tool.poetry]), setup.py or setup.cfg."
    )
