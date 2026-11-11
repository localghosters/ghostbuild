"""Read-only inspection of wheel (zip) and sdist (tar) archives.

Archives are never extracted to disk. Members are streamed and hashed in
memory, so a hostile archive cannot write files anywhere. Member names that
could escape a directory are still rejected, and size limits guard against
decompression bombs.
"""

from __future__ import annotations

import tarfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ghostbuild.errors import ArchiveError, UnsafeArchiveError
from ghostbuild.utils.filesystem import is_safe_relative_path
from ghostbuild.utils.hashing import EMPTY_SHA256, hash_stream, sha256_bytes

MAX_MEMBERS = 100_000
MAX_TOTAL_BYTES = 2 * 1024**3
SMALL_FILE_LIMIT = 64 * 1024  # contents kept for diffs and metadata parsing
SMALL_FILES_BUDGET = 16 * 1024**2


@dataclass(frozen=True)
class ArchiveMember:
    name: str
    size: int
    sha256: str
    is_dir: bool
    mtime: str
    mode: int | None
    owner: str | None = None


@dataclass
class ArchiveManifest:
    """Everything the comparator needs to know about one archive."""

    members: list[ArchiveMember] = field(default_factory=list)
    small_files: dict[str, bytes] = field(default_factory=dict)
    container_metadata: dict[str, str] = field(default_factory=dict)
    duplicates: list[str] = field(default_factory=list)


def _check_name(name: str, archive: Path) -> None:
    if not is_safe_relative_path(name):
        raise UnsafeArchiveError(f"{archive.name} contains an unsafe member path: {name!r}")


def _check_limits(count: int, total_bytes: int, archive: Path) -> None:
    if count > MAX_MEMBERS:
        raise ArchiveError(f"{archive.name} has more than {MAX_MEMBERS} members; not inspecting.")
    if total_bytes > MAX_TOTAL_BYTES:
        raise ArchiveError(
            f"{archive.name} would expand to more than {MAX_TOTAL_BYTES} bytes; not inspecting."
        )


def _format_time(timestamp: float) -> str:
    """Format a UTC timestamp, keeping sub-second precision (tar PAX headers can carry it)."""
    moment = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    text = moment.strftime("%Y-%m-%d %H:%M:%S")
    return f"{text}.{moment.microsecond:06d}" if moment.microsecond else text


def _gzip_header_metadata(path: Path) -> dict[str, str]:
    with open(path, "rb") as handle:
        header = handle.read(10)
    if len(header) < 10 or header[:2] != b"\x1f\x8b":
        return {}
    mtime = int.from_bytes(header[4:8], "little")
    return {"gzip header mtime": _format_time(mtime) + " UTC" if mtime else "unset (0)"}


def read_archive(path: Path) -> ArchiveManifest:
    """Build a manifest for a ``.whl``/``.zip`` or ``.tar``/``.tar.gz``/``.tgz`` file."""
    lowered = path.name.lower()
    if lowered.endswith((".whl", ".zip")):
        return _read_zip(path)
    if lowered.endswith((".tar.gz", ".tgz", ".tar")):
        return _read_tar(path)
    raise ArchiveError(f"Unsupported archive type: {path.name}")


def _read_zip(path: Path) -> ArchiveManifest:
    manifest = ArchiveManifest()
    seen: set[str] = set()
    kept_total = 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        _check_limits(len(infos), sum(i.file_size for i in infos), path)
        for info in infos:
            _check_name(info.filename, path)
            if info.filename in seen:
                manifest.duplicates.append(info.filename)
                continue
            seen.add(info.filename)
            mode = (info.external_attr >> 16) & 0o7777 if info.create_system == 3 else None
            mtime = "%04d-%02d-%02d %02d:%02d:%02d" % info.date_time
            if info.is_dir():
                digest, size, data = EMPTY_SHA256, 0, None
            else:
                budget_left = SMALL_FILES_BUDGET - kept_total
                with archive.open(info) as handle:
                    digest, size, data = hash_stream(
                        handle, min(SMALL_FILE_LIMIT, max(budget_left, 0))
                    )
            if data is not None:
                manifest.small_files[info.filename] = data
                kept_total += len(data)
            manifest.members.append(
                ArchiveMember(info.filename, size, digest, info.is_dir(), mtime, mode or None)
            )
    return manifest


def _read_tar(path: Path) -> ArchiveManifest:
    manifest = ArchiveManifest(container_metadata=_gzip_header_metadata(path))
    seen: set[str] = set()
    total = count = kept_total = 0
    with tarfile.open(path, "r:*") as archive:
        for member in archive:
            count += 1
            total += max(member.size, 0)
            _check_limits(count, total, path)
            _check_name(member.name, path)
            if member.name in seen:
                manifest.duplicates.append(member.name)
                continue
            seen.add(member.name)
            data: bytes | None = None
            if member.isfile():
                handle = archive.extractfile(member)
                if handle is None:
                    raise ArchiveError(f"{path.name}: cannot read member {member.name!r}")
                budget_left = SMALL_FILES_BUDGET - kept_total
                digest, size, data = hash_stream(
                    handle, min(SMALL_FILE_LIMIT, max(budget_left, 0))
                )
            elif member.isdir():
                digest, size = EMPTY_SHA256, 0
            else:  # links, devices, fifos: compare by type and target, never follow
                digest = sha256_bytes(f"{member.type!r}:{member.linkname}".encode())
                size = 0
            if data is not None:
                manifest.small_files[member.name] = data
                kept_total += len(data)
            owner = f"{member.uname or member.uid}:{member.gname or member.gid}"
            manifest.members.append(
                ArchiveMember(
                    member.name, size, digest, member.isdir(), _format_time(member.mtime),
                    member.mode & 0o7777, owner,
                )  # fmt: skip
            )
    return manifest
