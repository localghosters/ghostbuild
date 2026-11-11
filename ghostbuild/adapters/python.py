"""Python build adapter: PEP 517 projects built with ``python -m build``."""

from __future__ import annotations

import configparser
import importlib.metadata
import importlib.util
import platform
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from ghostbuild.adapters.base import BuildAdapter
from ghostbuild.config import Config, load_toml
from ghostbuild.errors import ConfigError
from ghostbuild.models import ProjectInfo

# build-backend -> friendly build system name
_BACKENDS = {
    "setuptools.build_meta": "setuptools",
    "setuptools.build_meta:__legacy__": "setuptools",
    "hatchling.build": "hatch",
    "poetry.core.masonry.api": "poetry",
    "pdm.backend": "pdm",
    "pdm.pep517.api": "pdm",
    "flit_core.buildapi": "flit",
    "maturin": "maturin",
    "scikit_build_core.build": "scikit-build-core",
}
_LEGACY_BACKEND = "setuptools.build_meta:__legacy__"
_LEGACY_REQUIRES = ["setuptools>=40.8.0", "wheel"]
_CONFIG_FILES = (
    "pyproject.toml", "setup.py", "setup.cfg", "MANIFEST.in", "hatch.toml",
    "poetry.lock", "pdm.lock", "uv.lock", "Pipfile.lock", "tox.ini", "ghostbuild.toml",
)  # fmt: skip
_LOCK_FILES = ("poetry.lock", "pdm.lock", "uv.lock", "Pipfile.lock")
_TOOLS_ON_PATH = ("hatch", "poetry", "pdm", "uv")

_CONTAINER_SCRIPT = """\
set -eu
export HOME=/tmp/ghostbuild-home
mkdir -p "$HOME" /tmp/work
cp -a /src/. /tmp/work/
cd /tmp/work
python -m pip install --quiet --disable-pip-version-check --user '{requirement}'
python -c 'import importlib.metadata as m, json, os, platform, time; print("GHOSTBUILD_ENV " + json.dumps({"python_version": platform.python_version(), "python_implementation": platform.python_implementation(), "os": platform.platform(), "architecture": platform.machine(), "build_tool": "build " + m.version("build"), "locale": os.environ.get("LC_ALL") or os.environ.get("LANG"), "timezone": os.environ.get("TZ") or "/".join(time.tzname)}))'
python -m build --sdist --wheel --outdir /out .
"""  # noqa: E501


def _is_pinned(requirement: str) -> bool:
    """Return True if a PEP 508 requirement pins an exact version or URL."""
    return bool(re.search(r"(===?|@)", requirement))


class PythonAdapter(BuildAdapter):
    """Builds Python projects through the standard ``build`` frontend."""

    id = "python"
    language = "Python"

    def detect(self, project_dir: Path) -> bool:
        if (project_dir / "setup.py").is_file() or (project_dir / "setup.cfg").is_file():
            return True
        pyproject = project_dir / "pyproject.toml"
        if not pyproject.is_file():
            return False
        data = load_toml(pyproject)
        return any(k in data for k in ("build-system", "project")) or "poetry" in data.get(
            "tool", {}
        )

    def inspect(self, project_dir: Path) -> ProjectInfo:
        data: dict[str, Any] = {}
        pyproject = project_dir / "pyproject.toml"
        if pyproject.is_file():
            data = load_toml(pyproject)
        project = data.get("project", {})
        poetry = data.get("tool", {}).get("poetry", {})
        notes: list[str] = []

        name, version = self._name_and_version(project_dir, project, poetry, notes)

        build_system_table = data.get("build-system")
        if build_system_table is not None:
            backend = build_system_table.get("build-backend")
            requires = list(build_system_table.get("requires", []))
            if backend is None:
                backend = _LEGACY_BACKEND
                notes.append("[build-system] has no build-backend; pip would use setuptools.")
        else:
            backend, requires = _LEGACY_BACKEND, list(_LEGACY_REQUIRES)
            notes.append("No [build-system] table; the default setuptools backend would be used.")
            if poetry:
                notes.append(
                    "Found [tool.poetry] without [build-system]; add one (poetry-core) so the "
                    "project builds with Poetry's backend."
                )
        build_system = _BACKENDS.get(backend, backend)
        if build_system_table is None and not pyproject.is_file():
            build_system = "setuptools (legacy setup.py/setup.cfg)"

        dependencies = list(project.get("dependencies", []))
        if not dependencies and poetry:
            dependencies = [
                f"{dep} {spec if isinstance(spec, str) else ''}".strip()
                for dep, spec in poetry.get("dependencies", {}).items()
                if dep.lower() != "python"
            ]
        requires_python = project.get("requires-python")
        if requires_python is None and isinstance(poetry.get("dependencies", {}).get("python"), str):
            requires_python = poetry["dependencies"]["python"]

        config_files = [f for f in _CONFIG_FILES if (project_dir / f).is_file()]
        config_files += sorted(p.name for p in project_dir.glob("requirements*.txt") if p.is_file())

        return ProjectInfo(
            path=str(project_dir),
            name=name,
            version=version,
            language=self.language,
            build_system=build_system,
            build_backend=backend,
            adapter=self.id,
            config_files=config_files,
            build_requires=requires,
            dependencies=dependencies,
            requires_python=requires_python,
            lock_files=[f for f in _LOCK_FILES if (project_dir / f).is_file()],
            notes=notes,
        )

    @staticmethod
    def _name_and_version(
        project_dir: Path, project: dict[str, Any], poetry: dict[str, Any], notes: list[str]
    ) -> tuple[str | None, str | None]:
        name = project.get("name") or poetry.get("name")
        version = project.get("version") or poetry.get("version")
        if version is None and "version" in project.get("dynamic", []):
            version = "dynamic"
        setup_cfg = project_dir / "setup.cfg"
        if (name is None or version is None) and setup_cfg.is_file():
            parser = configparser.ConfigParser(interpolation=None)
            try:
                parser.read(setup_cfg, encoding="utf-8")
            except configparser.Error as exc:
                notes.append(f"setup.cfg could not be parsed: {exc}")
            else:
                name = name or parser.get("metadata", "name", fallback=None)
                cfg_version = parser.get("metadata", "version", fallback=None)
                if version is None and cfg_version:
                    version = "dynamic" if cfg_version.startswith(("attr:", "file:")) else cfg_version
        if name is None and (project_dir / "setup.py").is_file():
            notes.append("Name/version are defined in setup.py, which GhostBuild does not execute.")
        if version == "dynamic":
            notes.append("The version is computed at build time (dynamic).")
        return name, version

    def available_tools(self) -> dict[str, str | None]:
        tools: dict[str, str | None] = {"python": f"{platform.python_version()} ({sys.executable})"}
        for package in ("pip", "build", "setuptools", "wheel"):
            tools[package] = self._package_version(package)
        for executable in _TOOLS_ON_PATH:
            tools[executable] = shutil.which(executable)
        return tools

    @staticmethod
    def _package_version(package: str) -> str | None:
        try:
            return importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            return None

    def describe_build_tool(self) -> str | None:
        version = self._package_version("build")
        return f"build {version}" if version else None

    def missing_prerequisites(self, config: Config) -> list[str]:
        if config.python.build_command:
            return []
        if importlib.util.find_spec("build") is None:
            return [
                "The 'build' package is not installed for this Python interpreter "
                f"({sys.executable}). Install it with: python -m pip install build"
            ]
        return []

    def has_custom_build_command(self, config: Config) -> bool:
        return bool(config.python.build_command)

    def build_command(self, source_dir: Path, output_dir: Path, config: Config) -> list[str]:
        if config.python.build_command:
            replacements = {
                "{python}": sys.executable,
                "{source_dir}": str(source_dir),
                "{outdir}": str(output_dir),
            }
            command = []
            for part in config.python.build_command:
                for placeholder, value in replacements.items():
                    part = part.replace(placeholder, value)
                command.append(part)
            return command
        return [
            sys.executable, "-m", "build", "--sdist", "--wheel",
            "--outdir", str(output_dir), str(source_dir),
        ]  # fmt: skip

    def container_image(self, config: Config) -> str:
        if config.python.docker_image:
            return config.python.docker_image
        return f"python:{sys.version_info.major}.{sys.version_info.minor}-slim"

    def container_script(self, config: Config) -> str:
        requirement = config.python.build_requirement
        if "'" in requirement:
            raise ConfigError("[python] build_requirement must not contain a single quote.")
        # str.replace, not str.format: the script contains literal braces.
        return _CONTAINER_SCRIPT.replace("{requirement}", requirement)

    def collect_warnings(self, project: ProjectInfo) -> list[str]:
        warnings = []
        unpinned = [r for r in project.build_requires if not _is_pinned(r)]
        if unpinned:
            warnings.append(
                "Build requirements are not pinned to exact versions "
                f"({', '.join(unpinned)}). Builds in different environments may resolve "
                "different versions, which is a common cause of differing artifacts."
            )
        return warnings
