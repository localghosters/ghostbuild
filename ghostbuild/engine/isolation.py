"""Choosing how the rebuild is isolated.

Stronger isolation (Docker) is never silently replaced by weaker isolation
(a local rebuild). A local rebuild needs explicit approval.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from ghostbuild.engine.executor import run_command
from ghostbuild.errors import IsolationError, LocalFallbackNotApproved
from ghostbuild.models import IsolationInfo

ISOLATION_CHOICES = ("auto", "docker", "local")
_DOCKER_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class DockerStatus:
    """Whether a usable Docker daemon was found, and why not if unavailable."""

    available: bool
    version: str | None = None
    reason: str | None = None


def detect_docker() -> DockerStatus:
    """Check for a Docker CLI and a reachable daemon. Runs only ``docker version``."""
    if shutil.which("docker") is None:
        return DockerStatus(False, reason="the 'docker' executable was not found on PATH")
    result = run_command(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        cwd=None,
        env=os.environ,
        timeout=_DOCKER_TIMEOUT_SECONDS,
    )
    if result.succeeded:
        return DockerStatus(True, version=result.stdout.strip() or None)
    detail = result.error or (result.stderr.strip().splitlines() or ["unknown error"])[0]
    return DockerStatus(False, reason=f"the Docker daemon is not reachable ({detail})")


def resolve_isolation(requested: str, docker: DockerStatus, *, local_approved: bool) -> str:
    """Decide between ``"docker"`` and ``"local"`` for the rebuild.

    * ``docker``: Docker or an error. Never falls back.
    * ``local``: local; choosing it is the explicit approval.
    * ``auto``: Docker if available; otherwise ``LocalFallbackNotApproved`` unless
      ``local_approved`` is True.
    """
    if requested not in ISOLATION_CHOICES:
        raise IsolationError(
            f"Unknown isolation mode {requested!r}. Choose one of: {', '.join(ISOLATION_CHOICES)}."
        )
    if requested == "local":
        return "local"
    if docker.available:
        return "docker"
    if requested == "docker":
        raise IsolationError(
            f"Docker isolation was requested but {docker.reason}. GhostBuild will not fall back "
            "to a weaker local rebuild on its own; use --isolation local to approve one."
        )
    if local_approved:
        return "local"
    raise LocalFallbackNotApproved(
        f"Docker is unavailable: {docker.reason}. The only alternative is a local rebuild, "
        "which is weaker isolation and needs your explicit approval "
        "(re-run with --isolation local)."
    )


def describe_isolation(mode: str, image: str | None) -> IsolationInfo:
    """Describe what the chosen mode does and does not demonstrate."""
    if mode == "docker":
        return IsolationInfo(
            mode="docker",
            independent_environment=True,
            image=image,
            description=(
                "The original build ran on this host in a temporary copy of the source. The "
                f"rebuild ran in a fresh Docker container ({image}) from a second copy of the "
                "source. The two builds used different toolchains and filesystems, so a match is "
                "meaningful evidence of reproducibility across these two environments only."
            ),
        )
    return IsolationInfo(
        mode="local",
        independent_environment=False,
        description=(
            "Both builds ran on this host, in separate temporary copies of the source with a "
            "filtered environment. This is NOT an independent clean-container rebuild: the same "
            "interpreter, tools and installed packages were used. A match shows repeatability "
            "on this host, not reproducibility across environments."
        ),
    )
