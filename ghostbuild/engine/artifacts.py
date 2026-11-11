"""Artifact discovery."""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path

from ghostbuild.errors import PathError
from ghostbuild.models import ArtifactInfo
from ghostbuild.utils.filesystem import is_safe_relative_path
from ghostbuild.utils.hashing import sha256_file


def classify_artifact(name: str) -> str:
    """Return ``"wheel"``, ``"sdist"`` or ``"file"`` from the file name (Python conventions)."""
    lowered = name.lower()
    if lowered.endswith(".whl"):
        return "wheel"
    if lowered.endswith((".tar.gz", ".tgz")):
        return "sdist"
    return "file"


def discover_artifacts(root: Path, patterns: Iterable[str]) -> list[ArtifactInfo]:
    """Find, hash and describe artifacts under ``root`` matching ``patterns``.

    Symlinks are ignored. Results are sorted by name (relative POSIX path).
    """
    root = root.resolve()
    found: dict[str, ArtifactInfo] = {}
    for pattern in patterns:
        if not is_safe_relative_path(pattern):
            raise PathError(f"Unsafe artifact pattern: {pattern!r}")
        for path in root.glob(pattern):
            if path.is_symlink() or not path.is_file():
                continue
            name = path.relative_to(root).as_posix()
            if name in found:
                continue
            found[name] = ArtifactInfo(
                name=name,
                kind=classify_artifact(name),
                size=path.stat().st_size,
                sha256=sha256_file(path),
                path=str(path),
            )
    return [found[name] for name in sorted(found)]


def copy_artifacts(artifacts: Iterable[ArtifactInfo], destination: Path) -> None:
    """Copy artifacts into ``destination``, keeping their relative names."""
    for artifact in artifacts:
        target = destination / artifact.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(artifact.path, target)
