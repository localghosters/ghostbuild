"""Data models shared across GhostBuild.

``VerificationResult.to_dict()`` is the stable JSON structure documented in
``docs/json-schema.md``. Reports are rendered from that dictionary, so the
terminal, JSON and HTML outputs always agree.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

SCHEMA_VERSION = "1"


class Verdict(str, enum.Enum):
    """Overall outcome of a verification."""

    REPRODUCIBLE = "reproducible"
    NON_REPRODUCIBLE = "non-reproducible"
    INCONCLUSIVE = "inconclusive"


class ArtifactStatus(str, enum.Enum):
    """Outcome of comparing one artifact name across the two builds."""

    MATCH = "match"
    DIFFERENT = "different"
    MISSING = "missing"  # present in the original build only
    ADDITIONAL = "additional"  # present in the rebuild only


def to_plain(obj: Any) -> Any:
    """Convert dataclasses and enums into JSON-serialisable values.

    Fields marked ``metadata={"internal": True}`` are omitted.
    """
    if is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: to_plain(getattr(obj, f.name))
            for f in fields(obj)
            if not f.metadata.get("internal")
        }
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    return obj


@dataclass
class ProjectInfo:
    """What GhostBuild learned by inspecting a project (without building it)."""

    path: str
    name: str | None
    version: str | None
    language: str
    build_system: str
    build_backend: str | None
    adapter: str
    config_files: list[str] = field(default_factory=list)
    build_requires: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    requires_python: str | None = None
    lock_files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ArtifactInfo:
    """A build artifact on disk."""

    name: str
    kind: str  # "wheel", "sdist" or "file"
    size: int
    sha256: str
    # Location on disk; never serialised (temporary paths are meaningless later).
    path: str = field(default="", compare=False, repr=False, metadata={"internal": True})


@dataclass
class EnvironmentInfo:
    """Facts about the environment a build ran in. Variable *values* are never stored."""

    runtime: str  # "host" or "docker"
    python_version: str | None = None
    python_implementation: str | None = None
    os: str | None = None
    architecture: str | None = None
    build_tool: str | None = None
    locale: str | None = None
    timezone: str | None = None
    env_var_names: list[str] = field(default_factory=list)
    image: str | None = None
    image_id: str | None = None


@dataclass
class BuildRecord:
    """One build execution: command, outcome, logs, environment and artifacts."""

    label: str  # "original" or "rebuilt"
    isolation: str  # "local" or "docker"
    command: list[str]
    started_at: str
    duration_seconds: float
    returncode: int | None
    timed_out: bool
    succeeded: bool
    failure_reason: str | None
    stdout: str
    stderr: str
    environment: EnvironmentInfo
    artifacts: list[ArtifactInfo] = field(default_factory=list)


@dataclass
class FileDifference:
    """A difference between two archive members (or one member missing on a side)."""

    path: str
    change: str  # "content", "metadata", "only-in-original", "only-in-rebuilt"
    metadata_changes: list[str] = field(default_factory=list)  # e.g. "timestamp", "mode"
    original_size: int | None = None
    rebuilt_size: int | None = None
    original_sha256: str | None = None
    rebuilt_sha256: str | None = None
    detail: str = ""
    diff_excerpt: list[str] = field(default_factory=list)


@dataclass
class MetadataDifference:
    """A difference in a parsed metadata field (e.g. a wheel's ``Generator``)."""

    source: str
    field: str
    original: str
    rebuilt: str


@dataclass
class ArtifactComparison:
    """Comparison of one artifact name across the two builds."""

    name: str
    kind: str
    status: ArtifactStatus
    original: ArtifactInfo | None = None
    rebuilt: ArtifactInfo | None = None
    file_differences: list[FileDifference] = field(default_factory=list)
    metadata_differences: list[MetadataDifference] = field(default_factory=list)
    member_order_differs: bool = False
    members_compared: int = 0
    members_identical: int = 0
    hypotheses: list[str] = field(default_factory=list)  # unconfirmed explanations
    notes: list[str] = field(default_factory=list)  # facts, e.g. inspection failures


@dataclass
class ComparisonSummary:
    total: int = 0
    matching: int = 0
    different: int = 0
    missing: int = 0
    additional: int = 0


@dataclass
class ComparisonResult:
    policy: str
    artifacts: list[ArtifactComparison]
    summary: ComparisonSummary


@dataclass
class IsolationInfo:
    """How the rebuild was isolated, and what that does and does not prove."""

    mode: str  # "docker" or "local"
    independent_environment: bool
    description: str
    image: str | None = None


@dataclass
class VerificationResult:
    """Complete outcome of ``ghostbuild verify`` or ``ghostbuild compare``."""

    command: str  # "verify" or "compare"
    tool_version: str
    verdict: Verdict
    verdict_reasons: list[str]
    policy: str
    started_at: str
    finished_at: str
    duration_seconds: float
    comparison: ComparisonResult
    isolation: IsolationInfo | None = None
    project: ProjectInfo | None = None
    original_build: BuildRecord | None = None
    rebuilt_build: BuildRecord | None = None
    environment_differences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return the documented, JSON-serialisable result structure."""
        plain = to_plain(self)
        ordered = {"schema_version": plain.pop("schema_version")}
        ordered.update(plain)
        return ordered
