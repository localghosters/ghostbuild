"""Subprocess execution with timeouts and output capture.

Commands are always argument lists; nothing here ever uses ``shell=True``.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ghostbuild.errors import IsolationError

MAX_OUTPUT_CHARS = 1_000_000
_KILL_GRACE_SECONDS = 10


@dataclass
class CommandResult:
    """Outcome of running a command."""

    command: list[str]
    returncode: int | None  # None if the process never started or was killed on timeout
    stdout: str
    stderr: str
    started_at: str
    duration_seconds: float
    timed_out: bool = False
    error: str | None = None  # set if the command could not start or timed out

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.error is None


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    omitted = len(text) - 2 * half
    return f"{text[:half]}\n... [{omitted} characters omitted] ...\n{text[-half:]}"


def _kill(process: subprocess.Popen[str]) -> None:
    """Kill the process and, on POSIX, its whole process group."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # already exited; nothing left to kill
    else:  # pragma: no cover - not exercised on POSIX CI
        process.kill()


def run_command(
    command: Sequence[str],
    *,
    cwd: Path | None,
    env: Mapping[str, str],
    timeout: float,
) -> CommandResult:
    """Run ``command`` without a shell, capturing stdout and stderr.

    On timeout the process group is killed and the result is marked ``timed_out``.
    A command that cannot be started yields a result with ``error`` set rather
    than raising, so callers can record the failure in the report.
    """
    if isinstance(command, (str, bytes)):
        raise TypeError("command must be a sequence of arguments, not a string")
    argv = [str(part) for part in command]
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    began = time.monotonic()
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        return CommandResult(
            argv, None, "", "", started_at, time.monotonic() - began,
            error=f"Could not start {argv[0]!r}: {exc}",
        )  # fmt: skip

    timed_out = False
    error: str | None = None
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        error = f"Timed out after {timeout:g} seconds and was killed."
        _kill(process)
        try:
            stdout, stderr = process.communicate(timeout=_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
            error += " Output could not be collected after the kill."
    return CommandResult(
        command=argv,
        returncode=None if timed_out else process.returncode,
        stdout=_truncate(stdout or ""),
        stderr=_truncate(stderr or ""),
        started_at=started_at,
        duration_seconds=time.monotonic() - began,
        timed_out=timed_out,
        error=error,
    )


def docker_run_command(
    *,
    image: str,
    source_dir: Path,
    output_dir: Path,
    script: str,
    user: str | None,
) -> list[str]:
    """Build the ``docker run`` argument list for an isolated rebuild.

    The source is mounted read-only, capabilities are dropped, and the script is
    passed to ``sh -c`` *inside the container* (the host never uses a shell).
    """
    for path in (source_dir, output_dir):
        if "," in str(path):
            raise IsolationError(f"Cannot mount a path containing a comma into Docker: {path}")
    command = [
        "docker", "run", "--rm",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
    ]  # fmt: skip
    if user:
        command += ["--user", user]
    command += [
        "--mount", f"type=bind,source={source_dir},target=/src,readonly",
        "--mount", f"type=bind,source={output_dir},target=/out",
        "--workdir", "/tmp",
        image,
        "sh", "-c", script,
    ]  # fmt: skip
    return command
