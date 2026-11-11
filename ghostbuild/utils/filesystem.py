"""Path validation helpers."""

from __future__ import annotations

import re
from pathlib import Path

from ghostbuild.errors import PathError

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def validate_directory(path: Path | str, what: str = "directory") -> Path:
    """Resolve ``path`` and require it to be an existing directory."""
    resolved = Path(path).expanduser()
    if not resolved.exists():
        raise PathError(f"The {what} does not exist: {path}")
    if not resolved.is_dir():
        raise PathError(f"The {what} is not a directory: {path}")
    return resolved.resolve()


def is_safe_relative_path(name: str) -> bool:
    """Return True if ``name`` is a relative path that cannot escape its root.

    Rejects empty names, NUL bytes, absolute paths (POSIX, UNC and Windows
    drive forms) and any ``..`` component, treating both ``/`` and ``\\`` as
    separators.
    """
    if not name or "\x00" in name:
        return False
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or _WINDOWS_DRIVE.match(normalized):
        return False
    return ".." not in normalized.split("/")
