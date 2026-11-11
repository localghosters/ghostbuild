"""Shared fixtures. Nothing here runs a real project build."""

from __future__ import annotations

import gzip
import io
import json
import sys
import tarfile
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from ghostbuild.engine.artifacts import discover_artifacts
from ghostbuild.engine.executor import CommandResult
from ghostbuild.models import ArtifactInfo

WHEEL_FILES: dict[str, str] = {
    "pkg/__init__.py": "VALUE = 1\n",
    "pkg-1.0.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: setuptools (70.0)\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    "pkg-1.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: pkg\nVersion: 1.0\nRequires-Dist: requests>=2\n\nLong description\n",
    "pkg-1.0.dist-info/RECORD": "pkg/__init__.py,,\n",
}  # fmt: skip


def make_zip(
    path: Path,
    files: Mapping[str, str | bytes],
    date_time: tuple[int, int, int, int, int, int] = (2020, 1, 1, 0, 0, 0),
) -> Path:
    """Write a zip (wheel-like) archive with fixed timestamps, in dict order."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, date_time=date_time)
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return path


def make_targz(
    path: Path,
    files: Mapping[str, str | bytes],
    mtime: int = 1_600_000_000,
    gzip_mtime: int = 0,
) -> Path:
    """Write a .tar.gz (sdist-like) archive with controlled member and gzip timestamps."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), mtime, 0o644
            archive.addfile(info, io.BytesIO(data))
    with gzip.GzipFile(path, "wb", mtime=gzip_mtime) as handle:
        handle.write(raw.getvalue())
    return path


def artifact(path: Path) -> ArtifactInfo:
    """Describe a single archive file as an ``ArtifactInfo``."""
    return discover_artifacts(path.parent, [path.name])[0]


@pytest.fixture
def make_project(tmp_path: Path) -> Callable[..., Path]:
    """Create a minimal project directory with the given pyproject.toml text."""

    def _make(pyproject: str | None, name: str = "proj", **files: str) -> Path:
        root = tmp_path / name
        root.mkdir()
        if pyproject is not None:
            (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
        for filename, content in files.items():
            (root / filename.replace("__", "/")).write_text(content, encoding="utf-8")
        return root

    return _make


SETUPTOOLS_PYPROJECT = """\
[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"

[project]
name = "demo"
version = "1.2.3"
dependencies = ["requests>=2"]
requires-python = ">=3.10"
"""


class FakeRunner:
    """Stand-in for ``run_command`` that never starts a process.

    ``write_artifacts(build_number, output_dir)`` creates the artifacts for each
    build (1 = original, 2 = rebuild). Docker sub-commands are answered with
    canned success output unless ``docker_fails`` is set.
    """

    def __init__(
        self,
        write_artifacts: Callable[[int, Path], None] | None = None,
        *,
        build_returncodes: tuple[int, ...] = (0, 0),
        timed_out_builds: tuple[int, ...] = (),
        stdout: str = "building\n",
        docker_fails: bool = False,
    ) -> None:
        self.write_artifacts = write_artifacts
        self.build_returncodes = build_returncodes
        self.timed_out_builds = timed_out_builds
        self.stdout = stdout
        self.docker_fails = docker_fails
        self.calls: list[dict[str, Any]] = []
        self.build_count = 0

    def __call__(
        self, command: Any, *, cwd: Path | None, env: Mapping[str, str], timeout: float
    ) -> CommandResult:
        argv = [str(part) for part in command]
        self.calls.append({"command": argv, "cwd": cwd, "env": dict(env), "timeout": timeout})
        if argv[0] == "docker" and argv[1] != "run":
            if self.docker_fails:
                return CommandResult(argv, 1, "", "no such image", "t", 0.0)
            return CommandResult(argv, 0, "sha256:fakeimageid\n", "", "t", 0.0)
        if argv[0] == "docker":
            mount = next(a for a in argv if a.endswith("target=/out"))
            output_dir = Path(mount.split("source=")[1].split(",")[0])
        else:
            output_dir = Path(argv[argv.index("--outdir") + 1]) if "--outdir" in argv else Path(argv[-1])
        self.build_count += 1
        number = self.build_count
        stdout = self.stdout
        if argv[0] == "docker":
            env_report = {"python_version": "3.12.1", "os": "Linux-container", "architecture": "x86_64",
                          "build_tool": "build 1.2.2", "python_implementation": "CPython"}  # fmt: skip
            stdout += "GHOSTBUILD_ENV " + json.dumps(env_report) + "\n"
        if number in self.timed_out_builds:
            return CommandResult(argv, None, stdout, "", "t", 1.0, True, "Timed out after 1 seconds and was killed.")
        returncode = self.build_returncodes[min(number, len(self.build_returncodes)) - 1]
        if returncode == 0 and self.write_artifacts:
            self.write_artifacts(number, output_dir)
        return CommandResult(argv, returncode, stdout, "", "2026-01-01T00:00:00+00:00", 1.0)


def identical_artifacts(number: int, output_dir: Path) -> None:
    make_zip(output_dir / "pkg-1.0-py3-none-any.whl", WHEEL_FILES)
    make_targz(output_dir / "pkg-1.0.tar.gz", {"pkg-1.0/PKG-INFO": "Name: pkg\n"})


def differing_artifacts(number: int, output_dir: Path) -> None:
    make_zip(output_dir / "pkg-1.0-py3-none-any.whl", WHEEL_FILES, (2020, 1, 1, 0, 0, number))
    make_targz(output_dir / "pkg-1.0.tar.gz", {"pkg-1.0/PKG-INFO": "Name: pkg\n"})


@pytest.fixture
def python_exe() -> str:
    return sys.executable
