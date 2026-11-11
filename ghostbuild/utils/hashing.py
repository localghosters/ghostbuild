"""SHA-256 helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO

CHUNK_SIZE = 1024 * 1024
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    """Return the hex SHA-256 digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_stream(stream: BinaryIO, keep_up_to: int = 0) -> tuple[str, int, bytes | None]:
    """Hash a binary stream.

    Returns ``(sha256, size, data)``. ``data`` holds the full content when it is
    at most ``keep_up_to`` bytes, otherwise ``None``.
    """
    digest = hashlib.sha256()
    size = 0
    kept: bytearray | None = bytearray() if keep_up_to > 0 else None
    for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
        digest.update(chunk)
        size += len(chunk)
        if kept is not None:
            if size <= keep_up_to:
                kept.extend(chunk)
            else:
                kept = None
    return digest.hexdigest(), size, (bytes(kept) if kept is not None else None)
