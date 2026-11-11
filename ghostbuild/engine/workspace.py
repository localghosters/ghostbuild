"""Temporary build workspaces and source copying.

The original project is only ever read. GhostBuild deletes only directories it
created itself, identified by a marker file.
"""

from __future__ import annotations

import fnmatch
import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from ghostbuild.errors import PathError, UnsafeDeletionError
from ghostbuild.utils.filesystem import validate_directory

WORKSPACE_MARKER = ".ghostbuild-workspace"
WORKSPACE_PREFIX = "ghostbuild-"

# Left out of the copy only at the project root: generated output and results.
ROOT_ONLY_EXCLUDES = ("build", "dist", "ghostbuild-results", ".eggs")
# Left out at any depth: caches and metadata that build tools regenerate.
ANYWHERE_EXCLUDES = ("__pycache__", "*.egg-info", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                     ".tox", ".nox", ".venv", "venv")  # fmt: skip
VCS_EXCLUDES = (".git", ".hg", ".svn")


@dataclass(frozen=True)
class BuildDirs:
    """Directories for one build: a private source copy and an output directory."""

    source: Path
    output: Path


class Workspace:
    """A temporary directory tree, removed on exit.

    Use as a context manager. ``base_dir`` selects the parent directory
    (default: the system temporary directory).
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base = validate_directory(base_dir, "temporary directory") if base_dir else None
        self.root: Path | None = None

    def __enter__(self) -> Workspace:
        self.root = Path(tempfile.mkdtemp(prefix=WORKSPACE_PREFIX, dir=self._base)).resolve()
        (self.root / WORKSPACE_MARKER).write_text("Created by GhostBuild.\n", encoding="utf-8")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.cleanup()

    def new_build_dirs(self, label: str) -> BuildDirs:
        """Create ``<root>/<label>/out`` and return paths for the build."""
        if self.root is None:
            raise RuntimeError("Workspace is not active")
        base = self.root / label
        output = base / "out"
        output.mkdir(parents=True)
        return BuildDirs(source=base / "src", output=output)

    def cleanup(self) -> None:
        if self.root is not None:
            remove_workspace(self.root)
            self.root = None


def remove_workspace(path: Path) -> None:
    """Delete a workspace directory, but only if GhostBuild created it."""
    if path.is_symlink() or not path.is_dir():
        raise UnsafeDeletionError(f"Refusing to delete {path}: not a plain directory.")
    if not path.name.startswith(WORKSPACE_PREFIX) or not (path / WORKSPACE_MARKER).is_file():
        raise UnsafeDeletionError(f"Refusing to delete {path}: it is not a GhostBuild workspace.")
    shutil.rmtree(path)


def copy_source(
    project_dir: Path,
    destination: Path,
    *,
    include_vcs: bool = False,
    extra_excludes: Iterable[str] = (),
    skip_paths: Iterable[Path] = (),
) -> None:
    """Copy a project into a fresh ``destination`` without generated build output.

    Symlinks are copied as symlinks, never followed. ``skip_paths`` are absolute
    paths (for example the report output directory) to leave out.
    """
    if destination.exists():
        raise PathError(f"Destination already exists: {destination}")
    root = project_dir.resolve()
    skipped = {p.resolve() for p in skip_paths}
    anywhere = [*ANYWHERE_EXCLUDES, *extra_excludes]
    if not include_vcs:
        anywhere.extend(VCS_EXCLUDES)

    def ignore(directory: str, names: list[str]) -> set[str]:
        here = Path(directory).resolve()
        ignored = {n for n in names if any(fnmatch.fnmatch(n, pat) for pat in anywhere)}
        if here == root:
            ignored |= {n for n in names if n in ROOT_ONLY_EXCLUDES}
        ignored |= {n for n in names if (here / n).resolve() in skipped}
        return ignored

    shutil.copytree(root, destination, symlinks=True, ignore=ignore)
