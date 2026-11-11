"""Artifact comparison.

Verdicts come only from exact SHA-256 comparison of whole artifacts. Everything
else here (member diffs, metadata diffs, hypotheses) is diagnostic and never
turns a mismatch into a match.
"""

from __future__ import annotations

import difflib
import email
import zlib
import tarfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

from ghostbuild.config import SUPPORTED_POLICIES
from ghostbuild.engine.archives import ArchiveManifest, ArchiveMember, read_archive
from ghostbuild.errors import ArchiveError, ConfigError
from ghostbuild.models import (
    ArtifactComparison,
    ArtifactInfo,
    ArtifactStatus,
    BuildRecord,
    ComparisonResult,
    ComparisonSummary,
    FileDifference,
    MetadataDifference,
    Verdict,
)

_DIFF_MAX_LINES = 20
_DIFF_MAX_LINE_LENGTH = 200
_INSPECTION_ERRORS = (ArchiveError, zipfile.BadZipFile, tarfile.TarError, OSError, EOFError,
                      zlib.error)  # fmt: skip


def compare_artifact_sets(
    original: Sequence[ArtifactInfo],
    rebuilt: Sequence[ArtifactInfo],
    *,
    policy: str = "exact",
    environment_differences: Sequence[str] = (),
    inspect: bool = True,
) -> ComparisonResult:
    """Compare two artifact sets by name using the given policy.

    ``inspect=False`` skips archive inspection (hash comparison only).
    """
    if policy not in SUPPORTED_POLICIES:
        raise ConfigError(f"Unsupported comparison policy: {policy!r}")
    left = {a.name: a for a in original}
    right = {a.name: a for a in rebuilt}
    comparisons: list[ArtifactComparison] = []
    for name in sorted(left.keys() | right.keys()):
        a, b = left.get(name), right.get(name)
        if a is not None and b is not None:
            comparisons.append(_compare_pair(a, b, environment_differences, inspect))
        elif a is not None:
            comparisons.append(ArtifactComparison(name, a.kind, ArtifactStatus.MISSING, original=a))
        else:
            assert b is not None
            comparisons.append(ArtifactComparison(name, b.kind, ArtifactStatus.ADDITIONAL, rebuilt=b))
    return ComparisonResult(policy, comparisons, _summarise(comparisons))


def _summarise(comparisons: Sequence[ArtifactComparison]) -> ComparisonSummary:
    def count(status: ArtifactStatus) -> int:
        return sum(1 for c in comparisons if c.status is status)

    return ComparisonSummary(
        total=len(comparisons),
        matching=count(ArtifactStatus.MATCH),
        different=count(ArtifactStatus.DIFFERENT),
        missing=count(ArtifactStatus.MISSING),
        additional=count(ArtifactStatus.ADDITIONAL),
    )


def _compare_pair(
    a: ArtifactInfo, b: ArtifactInfo, environment_differences: Sequence[str], inspect: bool
) -> ArtifactComparison:
    if a.sha256 == b.sha256:
        return ArtifactComparison(a.name, a.kind, ArtifactStatus.MATCH, a, b)
    comparison = ArtifactComparison(a.name, a.kind, ArtifactStatus.DIFFERENT, a, b)
    if inspect:
        _inspect(comparison, a, b)
    comparison.hypotheses = _hypotheses(comparison, environment_differences)
    return comparison


# --------------------------------------------------------------------------- inspection


def _inspect(comparison: ArtifactComparison, a: ArtifactInfo, b: ArtifactInfo) -> None:
    if comparison.kind not in ("wheel", "sdist"):
        comparison.notes.append("Deep inspection is only available for wheel and sdist archives.")
        return
    if not a.path or not b.path:
        comparison.notes.append("Artifact files were not available for deep inspection.")
        return
    try:
        manifest_a = read_archive(Path(a.path))
        manifest_b = read_archive(Path(b.path))
    except _INSPECTION_ERRORS as exc:
        comparison.notes.append(
            f"Deep inspection failed ({type(exc).__name__}: {exc}). "
            "The artifacts still differ by SHA-256."
        )
        return
    for label, manifest in (("original", manifest_a), ("rebuilt", manifest_b)):
        if manifest.duplicates:
            comparison.notes.append(
                f"The {label} archive has duplicate member names (only the first was compared): "
                + ", ".join(manifest.duplicates[:5])
            )
    _diff_manifests(comparison, manifest_a, manifest_b)
    comparison.metadata_differences = _metadata_differences(manifest_a, manifest_b)
    if not comparison.file_differences and not comparison.metadata_differences:
        if not comparison.member_order_differs:
            comparison.notes.append(
                "Every member has identical content and metadata, yet the archives differ by "
                "SHA-256: the difference is in archive-level encoding (for example compression "
                "or headers)."
            )


def _diff_manifests(
    comparison: ArtifactComparison, a: ArchiveManifest, b: ArchiveManifest
) -> None:
    left = {m.name: m for m in a.members}
    right = {m.name: m for m in b.members}
    for name in sorted(left.keys() | right.keys()):
        in_a, in_b = left.get(name), right.get(name)
        if in_b is None:
            assert in_a is not None
            comparison.file_differences.append(
                FileDifference(name, "only-in-original", original_size=in_a.size,
                               original_sha256=in_a.sha256, detail="missing from the rebuild")
            )  # fmt: skip
        elif in_a is None:
            comparison.file_differences.append(
                FileDifference(name, "only-in-rebuilt", rebuilt_size=in_b.size,
                               rebuilt_sha256=in_b.sha256, detail="not present in the original")
            )  # fmt: skip
        else:
            comparison.members_compared += 1
            difference = _compare_members(in_a, in_b, a, b)
            if difference is None:
                comparison.members_identical += 1
            else:
                comparison.file_differences.append(difference)
    common_a = [m.name for m in a.members if m.name in right]
    common_b = [m.name for m in b.members if m.name in left]
    comparison.member_order_differs = common_a != common_b


def _compare_members(
    a: ArchiveMember, b: ArchiveMember, ma: ArchiveManifest, mb: ArchiveManifest
) -> FileDifference | None:
    changes = []
    if a.mtime != b.mtime:
        changes.append("timestamp")
    if a.mode != b.mode:
        changes.append("mode")
    if a.owner != b.owner:
        changes.append("owner")
    content_differs = not a.is_dir and a.sha256 != b.sha256
    if not content_differs and not changes:
        return None
    meta_text = "; ".join(_describe_change(c, a, b) for c in changes)
    if content_differs:
        detail = f"content differs ({a.size} -> {b.size} bytes)"
        if meta_text:
            detail += f"; also {meta_text}"
        return FileDifference(
            a.name, "content", changes, a.size, b.size, a.sha256, b.sha256, detail,
            _diff_excerpt(ma.small_files.get(a.name), mb.small_files.get(b.name)),
        )  # fmt: skip
    return FileDifference(a.name, "metadata", changes, a.size, b.size, a.sha256, b.sha256, meta_text)


def _describe_change(change: str, a: ArchiveMember, b: ArchiveMember) -> str:
    if change == "timestamp":
        return f"timestamp {a.mtime} -> {b.mtime}"
    if change == "mode":
        return f"mode {_octal(a.mode)} -> {_octal(b.mode)}"
    return f"owner {a.owner} -> {b.owner}"


def _octal(mode: int | None) -> str:
    return "unknown" if mode is None else f"{mode:o}"


def _diff_excerpt(a: bytes | None, b: bytes | None) -> list[str]:
    """Return a short unified diff for small UTF-8 text files, else an empty list."""
    if a is None or b is None:
        return []
    try:
        text_a, text_b = a.decode("utf-8"), b.decode("utf-8")
    except UnicodeDecodeError:
        return []
    lines = list(
        difflib.unified_diff(
            text_a.splitlines(), text_b.splitlines(), "original", "rebuilt", n=1, lineterm=""
        )
    )
    excerpt = [line[:_DIFF_MAX_LINE_LENGTH] for line in lines[:_DIFF_MAX_LINES]]
    if len(lines) > _DIFF_MAX_LINES:
        excerpt.append(f"... ({len(lines) - _DIFF_MAX_LINES} more diff lines)")
    return excerpt


def _parse_headers(data: bytes) -> dict[str, list[str]]:
    """Parse RFC 822-style headers (wheel WHEEL/METADATA, sdist PKG-INFO), ignoring any body."""
    message = email.message_from_bytes(data)
    headers: dict[str, list[str]] = {}
    for key, value in message.items():
        headers.setdefault(key, []).append(str(value))
    return headers


def _metadata_files(manifest: ArchiveManifest) -> dict[str, bytes]:
    """Select parseable metadata files, keyed by a display name like ``WHEEL``."""
    selected: dict[str, bytes] = {}
    for name, data in manifest.small_files.items():
        parts = name.split("/")
        leaf = parts[-1]
        in_dist_info = len(parts) == 2 and parts[0].endswith(".dist-info")
        if in_dist_info and leaf in ("WHEEL", "METADATA"):
            selected[leaf] = data
        elif len(parts) == 2 and leaf == "PKG-INFO":
            selected[leaf] = data
    return selected


def _metadata_differences(a: ArchiveManifest, b: ArchiveManifest) -> list[MetadataDifference]:
    differences = [
        MetadataDifference("archive", key, a.container_metadata.get(key, "(absent)"),
                           b.container_metadata.get(key, "(absent)"))
        for key in sorted(a.container_metadata.keys() | b.container_metadata.keys())
        if a.container_metadata.get(key) != b.container_metadata.get(key)
    ]  # fmt: skip
    files_a, files_b = _metadata_files(a), _metadata_files(b)
    for source in sorted(files_a.keys() & files_b.keys()):
        headers_a, headers_b = _parse_headers(files_a[source]), _parse_headers(files_b[source])
        for key in sorted(headers_a.keys() | headers_b.keys()):
            value_a = "; ".join(headers_a.get(key, ["(absent)"]))
            value_b = "; ".join(headers_b.get(key, ["(absent)"]))
            if value_a != value_b:
                differences.append(MetadataDifference(source, key, value_a, value_b))
    return differences


# --------------------------------------------------------------------------- hypotheses

_GENERATED_METADATA = ("WHEEL", "METADATA", "PKG-INFO", "entry_points.txt", "top_level.txt",
                       "SOURCES.txt", "requires.txt")  # fmt: skip
_NATIVE_SUFFIXES = (".so", ".pyd", ".dylib", ".dll")


def _hypotheses(comparison: ArtifactComparison, environment_differences: Sequence[str]) -> list[str]:
    """Derive possible explanations from the evidence. They are never certain."""
    diffs = comparison.file_differences
    content = [d for d in diffs if d.change == "content"]
    one_sided = [d for d in diffs if d.change.startswith("only-in")]
    hypotheses: list[str] = []

    if any("timestamp" in d.metadata_changes for d in diffs):
        hypotheses.append(
            "Archive entry timestamps differ. The build may be embedding the build time or file "
            "modification times; tools that honour SOURCE_DATE_EPOCH can often be made to "
            "use a fixed value."
        )
    if any(m.source == "archive" and "gzip" in m.field for m in comparison.metadata_differences):
        hypotheses.append(
            "The gzip header timestamp differs. It may be written from the current time at "
            "build time rather than from a fixed value."
        )
    if comparison.member_order_differs:
        hypotheses.append(
            "Archive members are in a different order. The build tool may be adding files in "
            "filesystem order without sorting them."
        )
    if any(m.field.lower() == "generator" for m in comparison.metadata_differences):
        hypotheses.append(
            "The wheel 'Generator' field differs, which suggests the builds used different "
            "versions of the build tool or backend."
        )
    if any(m.field in ("Version", "Requires-Dist", "Requires-Python")
           for m in comparison.metadata_differences):  # fmt: skip
        hypotheses.append(
            "Package version or dependency metadata differs. Dependency resolution or "
            "version computation may differ between the two builds."
        )
    if any(d.path.endswith(".pyc") for d in content):
        hypotheses.append(
            "Compiled bytecode (.pyc) differs. It can embed source timestamps and depends on "
            "the Python version."
        )
    if any(d.path.lower().endswith(_NATIVE_SUFFIXES) for d in content):
        hypotheses.append(
            "Compiled extension modules differ, which may point to different compilers, "
            "compiler flags or build paths."
        )
    generated = [
        d for d in content
        if d.path.split("/")[-1] in _GENERATED_METADATA and not d.path.endswith(".pyc")
    ]  # fmt: skip
    if generated:
        hypotheses.append(
            "Generated packaging metadata differs (" + ", ".join(d.path for d in generated[:4])
            + "). It may be produced from build-time state such as tool versions or timestamps."
        )
    other_content = [
        d for d in content
        if d not in generated
        and not d.path.endswith((".pyc", *_NATIVE_SUFFIXES))
        and d.path.split("/")[-1] != "RECORD"
    ]  # fmt: skip
    if other_content:
        hypotheses.append(
            "Contents of non-metadata files differ. This may indicate build-time code "
            "generation, environment-dependent output, or builds that started from different "
            "inputs."
        )
    if one_sided:
        hypotheses.append(
            "Some archive members exist in only one build. A generated or environment-dependent "
            "file may be produced differently between builds."
        )
    if environment_differences:
        hypotheses.append(
            "The two builds ran in different environments ("
            + "; ".join(environment_differences[:4])
            + "). Environment differences may contribute, but this is not confirmed."
        )
    if not hypotheses:
        hypotheses.append(
            "No explanation could be derived from the inspected evidence. Compare the artifacts "
            "with a dedicated tool such as diffoscope for more detail."
        )
    return hypotheses


# --------------------------------------------------------------------------- verdict


def _failure_text(label: str, record: BuildRecord) -> str:
    return f"The {label} build did not succeed: {record.failure_reason or 'unknown failure'}."


def determine_verdict(
    comparison: ComparisonResult,
    original: BuildRecord | None = None,
    rebuilt: BuildRecord | None = None,
    *,
    builds_expected: bool = False,
) -> tuple[Verdict, list[str]]:
    """Decide the overall verdict and the reasons behind it.

    ``builds_expected`` is True for ``verify`` (both builds should exist) and
    False for ``compare`` (artifacts only).
    """
    reasons: list[str] = []
    if original is not None and not original.succeeded:
        reasons.append(_failure_text("original", original))
    if rebuilt is not None and not rebuilt.succeeded:
        reasons.append(_failure_text("rebuilt", rebuilt))
    if builds_expected and rebuilt is None:
        reasons.append("The rebuild was not performed.")

    s = comparison.summary
    in_original = s.matching + s.different + s.missing
    in_rebuilt = s.matching + s.different + s.additional
    if in_original == 0:
        reasons.append("No artifacts were found for the original build.")
    if in_rebuilt == 0:
        reasons.append("No artifacts were found for the rebuild.")
    if reasons:
        return Verdict.INCONCLUSIVE, reasons

    if s.different == 0 and s.missing == 0 and s.additional == 0:
        return Verdict.REPRODUCIBLE, [
            f"All {s.matching} artifact(s) have identical SHA-256 digests (policy: "
            f"{comparison.policy})."
        ]
    if s.different:
        reasons.append(f"{s.different} artifact(s) differ by SHA-256.")
    if s.missing:
        reasons.append(f"{s.missing} artifact(s) from the original build are missing in the rebuild.")
    if s.additional:
        reasons.append(f"{s.additional} artifact(s) appear only in the rebuild.")
    return Verdict.NON_REPRODUCIBLE, reasons
