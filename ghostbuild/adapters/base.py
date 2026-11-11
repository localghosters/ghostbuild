"""The interface an ecosystem adapter implements.

The engine only talks to this interface. To add an ecosystem (Node.js, Cargo,
Go, ...), subclass ``BuildAdapter`` and register it in ``adapters/__init__.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ghostbuild.config import Config
from ghostbuild.models import ProjectInfo


class BuildAdapter(ABC):
    """Knows how to recognise, inspect and build one kind of project."""

    #: Short identifier used in reports and configuration, e.g. ``"python"``.
    id: str
    #: Human-readable language name.
    language: str

    @abstractmethod
    def detect(self, project_dir: Path) -> bool:
        """Return True if this adapter can handle the project. Must not run project code."""

    @abstractmethod
    def inspect(self, project_dir: Path) -> ProjectInfo:
        """Read project metadata from files. Must not run project code."""

    @abstractmethod
    def available_tools(self) -> dict[str, str | None]:
        """Map tool name to a version/path, or ``None`` if it is not available."""

    @abstractmethod
    def missing_prerequisites(self, config: Config) -> list[str]:
        """Return human-readable problems that would stop a local build."""

    @abstractmethod
    def build_command(self, source_dir: Path, output_dir: Path, config: Config) -> list[str]:
        """Return the argument list (never a shell string) for a local build."""

    @abstractmethod
    def has_custom_build_command(self, config: Config) -> bool:
        """Return True if the user overrode the default build command."""

    @abstractmethod
    def container_image(self, config: Config) -> str:
        """Return the container image used for an independent rebuild."""

    @abstractmethod
    def container_script(self, config: Config) -> str:
        """Return the ``sh`` script run inside the container.

        The container mounts the prepared source read-only at ``/src`` and a
        writable output directory at ``/out``. The script must write artifacts
        to ``/out`` and print one ``GHOSTBUILD_ENV <json>`` line describing the
        container environment.
        """

    def describe_build_tool(self) -> str | None:
        """Return the local build tool and version, if known."""
        return None

    def collect_warnings(self, project: ProjectInfo) -> list[str]:
        """Return reproducibility risks visible from project metadata."""
        return []
