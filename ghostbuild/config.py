"""Loading and validating ``ghostbuild.toml``."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ghostbuild.errors import ConfigError
from ghostbuild.utils.filesystem import is_safe_relative_path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

CONFIG_FILENAME = "ghostbuild.toml"
SUPPORTED_POLICIES = ("exact",)
REPORT_FORMATS = ("terminal", "json", "html")

EXAMPLE_CONFIG = """\
# GhostBuild configuration. Every setting is optional; the values below are the defaults.

[build]
# Maximum time for each build, in seconds.
timeout_seconds = 900
# Extra environment variable names to pass to builds. Builds otherwise run with a
# small allowlist (PATH, HOME, locale, proxy and CA settings). Values are never
# written to reports.
env_passthrough = []

[artifacts]
# Glob patterns, relative to each build's output directory.
patterns = ["*.whl", "*.tar.gz"]

[comparison]
# Only "exact" (SHA-256 of every artifact) is implemented in 0.1.0.
policy = "exact"

[workspace]
# Directory for temporary workspaces. Empty means the system temporary directory.
temp_dir = ""
# Copy version-control metadata (.git, .hg, .svn) into build workspaces.
# Needed by tools such as setuptools-scm; off by default.
include_vcs = false
# Extra file or directory name patterns to leave out of build workspaces
# (matched against names at any depth).
exclude = []

[report]
output_dir = "ghostbuild-results"
# "terminal", "json" or "html". result.json is always written.
format = "terminal"

[python]
# Override the build command. Placeholders: {python}, {source_dir}, {outdir}.
# Only usable with local isolation. Empty means: python -m build --sdist --wheel
build_command = []
# Docker image for the independent rebuild. Empty means python:<major>.<minor>-slim.
docker_image = ""
# Requirement installed inside the container to provide the build frontend.
build_requirement = "build"
"""


@dataclass
class BuildSettings:
    timeout_seconds: int = 900
    env_passthrough: list[str] = field(default_factory=list)


@dataclass
class ArtifactSettings:
    patterns: list[str] = field(default_factory=lambda: ["*.whl", "*.tar.gz"])


@dataclass
class ComparisonSettings:
    policy: str = "exact"


@dataclass
class WorkspaceSettings:
    temp_dir: str | None = None
    include_vcs: bool = False
    exclude: list[str] = field(default_factory=list)


@dataclass
class ReportSettings:
    output_dir: str = "ghostbuild-results"
    format: str = "terminal"


@dataclass
class PythonSettings:
    build_command: list[str] = field(default_factory=list)
    docker_image: str | None = None
    build_requirement: str = "build"


@dataclass
class Config:
    """Effective configuration (defaults plus any ``ghostbuild.toml`` overrides)."""

    build: BuildSettings = field(default_factory=BuildSettings)
    artifacts: ArtifactSettings = field(default_factory=ArtifactSettings)
    comparison: ComparisonSettings = field(default_factory=ComparisonSettings)
    workspace: WorkspaceSettings = field(default_factory=WorkspaceSettings)
    report: ReportSettings = field(default_factory=ReportSettings)
    python: PythonSettings = field(default_factory=PythonSettings)
    source: Path | None = None  # file the configuration was loaded from, if any


def load_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file, raising ``ConfigError`` with a readable message on failure."""
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


_KINDS = {
    "int": (_is_int, "an integer"),
    "bool": (lambda v: isinstance(v, bool), "true or false"),
    "str": (lambda v: isinstance(v, str), "a string"),
    "strlist": (
        lambda v: isinstance(v, list) and all(isinstance(i, str) for i in v),
        "a list of strings",
    ),
}

# section -> key -> kind
_SCHEMA: dict[str, dict[str, str]] = {
    "build": {"timeout_seconds": "int", "env_passthrough": "strlist"},
    "artifacts": {"patterns": "strlist"},
    "comparison": {"policy": "str"},
    "workspace": {"temp_dir": "str", "include_vcs": "bool", "exclude": "strlist"},
    "report": {"output_dir": "str", "format": "str"},
    "python": {"build_command": "strlist", "docker_image": "str", "build_requirement": "str"},
}  # fmt: skip

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_config(data: dict[str, Any], source: Path | None = None) -> Config:
    """Validate parsed TOML ``data`` and build a ``Config``."""
    where = f" in {source}" if source else ""
    config = Config(source=source)
    for section, table in data.items():
        if section not in _SCHEMA:
            raise ConfigError(
                f"Unknown section [{section}]{where}. Valid sections: {', '.join(_SCHEMA)}."
            )
        if not isinstance(table, dict):
            raise ConfigError(f"[{section}]{where} must be a table.")
        target = getattr(config, section)
        for key, value in table.items():
            if key not in _SCHEMA[section]:
                raise ConfigError(
                    f"Unknown setting '{key}' in [{section}]{where}. "
                    f"Valid settings: {', '.join(_SCHEMA[section])}."
                )
            check, description = _KINDS[_SCHEMA[section][key]]
            if not check(value):
                raise ConfigError(f"[{section}] {key}{where} must be {description}.")
            setattr(target, key, value)

    # An empty string means "unset" for optional string settings.
    if not config.workspace.temp_dir:
        config.workspace.temp_dir = None
    if not config.python.docker_image:
        config.python.docker_image = None
    _validate(config, where)
    return config


def _validate(config: Config, where: str) -> None:
    if not 1 <= config.build.timeout_seconds <= 86400:
        raise ConfigError(f"[build] timeout_seconds{where} must be between 1 and 86400.")
    for name in config.build.env_passthrough:
        if not _ENV_NAME.match(name):
            raise ConfigError(f"[build] env_passthrough{where}: invalid variable name {name!r}.")
    if not config.artifacts.patterns:
        raise ConfigError(f"[artifacts] patterns{where} must not be empty.")
    for pattern in config.artifacts.patterns:
        if not is_safe_relative_path(pattern):
            raise ConfigError(
                f"[artifacts] patterns{where}: {pattern!r} must be relative and must not contain '..'."
            )
    if config.comparison.policy not in SUPPORTED_POLICIES:
        raise ConfigError(
            f"[comparison] policy{where}: {config.comparison.policy!r} is not supported. "
            f"Supported: {', '.join(SUPPORTED_POLICIES)}."
        )
    if config.report.format not in REPORT_FORMATS:
        raise ConfigError(
            f"[report] format{where} must be one of: {', '.join(REPORT_FORMATS)}."
        )
    if not config.report.output_dir:
        raise ConfigError(f"[report] output_dir{where} must not be empty.")
    if any(not part for part in config.python.build_command):
        raise ConfigError(f"[python] build_command{where} must not contain empty strings.")


def load_config(explicit: Path | None = None, project_dir: Path | None = None) -> Config:
    """Load configuration.

    An explicit path must exist. Otherwise ``ghostbuild.toml`` in ``project_dir``
    is used if present; with neither, defaults apply.
    """
    if explicit is not None:
        if not explicit.is_file():
            raise ConfigError(f"Configuration file not found: {explicit}")
        return parse_config(load_toml(explicit), explicit)
    if project_dir is not None:
        candidate = project_dir / CONFIG_FILENAME
        if candidate.is_file():
            return parse_config(load_toml(candidate), candidate)
    return Config()
