"""Markdown report, suited to CI step summaries and pull request comments.

Everything that comes from a build or an archive (names, diff lines, messages) is treated
as untrusted text: it is escaped or placed in code spans/fences so it cannot inject
Markdown or HTML into the rendered page. Build logs are deliberately left out; use the
HTML or JSON report for those.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ghostbuild.reports import short_hash, verdict_label

REPORT_FILENAME = "report.md"
_MAX_FILES_PER_ARTIFACT = 25
_MAX_DIFF_LINES = 20
_SPECIAL = re.compile(r"([\\`*_\[\]<>#|~&])")


def _text(value: object) -> str:
    """Escape ``value`` for use as plain Markdown text on a single line."""
    return _SPECIAL.sub(r"\\\1", " ".join(str(value).split()))


def _code(value: object) -> str:
    """Return ``value`` as an inline code span that cannot be broken out of."""
    text = " ".join(str(value).split()).replace("|", "\\|")
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _fenced(lines: list[str]) -> list[str]:
    """Return a fenced code block whose fence is longer than any backtick run inside."""
    longest = max((len(run) for line in lines for run in re.findall(r"`+", line)), default=0)
    fence = "`" * max(3, longest + 1)
    return [fence, *lines, fence]


def render_markdown(data: dict[str, Any]) -> str:
    """Render a result dictionary (``VerificationResult.to_dict()``) as Markdown."""
    out: list[str] = [f"# GhostBuild: {_text(verdict_label(data))}", ""]
    out.append(f"GhostBuild {_text(data.get('tool_version', ''))}, policy {_code(data.get('policy', 'exact'))}.")
    out.append("")

    for reason in data.get("verdict_reasons", []):
        out.append(f"- {_text(reason)}")
    if data.get("verdict_reasons"):
        out.append("")

    isolation = data.get("isolation")
    if isolation:
        out.append(f"**Isolation:** {_text(isolation.get('description', isolation.get('mode', '')))}")
        out.append("")
    project = data.get("project")
    if project:
        label = _text(project.get("name") or "unknown")
        version = project.get("version")
        out.append(f"**Project:** {label}{' ' + _text(version) if version else ''}"
                   f" ({_text(project.get('build_system') or 'unknown build system')})")
        out.append("")

    comparison = data.get("comparison", {})
    summary = comparison.get("summary", {})
    out += ["## Artifacts", "",
            f"{summary.get('total', 0)} compared: {summary.get('matching', 0)} matching, "
            f"{summary.get('different', 0)} different, {summary.get('missing', 0)} missing, "
            f"{summary.get('additional', 0)} additional.", ""]
    artifacts = comparison.get("artifacts", [])
    if artifacts:
        out += ["| Artifact | Status | Original SHA-256 | Rebuilt SHA-256 |", "| --- | --- | --- | --- |"]
        for art in artifacts:
            original = short_hash((art.get("original") or {}).get("sha256"))
            rebuilt = short_hash((art.get("rebuilt") or {}).get("sha256"))
            out.append(f"| {_code(art['name'])} | {_text(art['status'])} | {_code(original)} | {_code(rebuilt)} |")
        out.append("")

    for art in artifacts:
        if art["status"] == "match":
            continue
        out += [f"### {_text(art['name'])}", ""]
        out += _artifact_details(art)

    warnings = data.get("warnings", [])
    if warnings:
        out += ["## Warnings", ""] + [f"- {_text(w)}" for w in warnings] + [""]
    out.append("*Reproducibility results depend on the environments and comparison policy used.*")
    return "\n".join(out) + "\n"


def _artifact_details(art: dict[str, Any]) -> list[str]:
    """Return the detail lines for one artifact that did not match."""
    out: list[str] = []
    diffs = art.get("file_differences", [])
    for diff in diffs[:_MAX_FILES_PER_ARTIFACT]:
        extra = f" ({', '.join(diff['metadata_changes'])})" if diff.get("metadata_changes") else ""
        out.append(f"- {_code(diff['path'])}: {_text(diff['change'] + extra)}")
        excerpt = diff.get("diff_excerpt") or []
        if excerpt:
            out += ["", *_fenced([str(line) for line in excerpt[:_MAX_DIFF_LINES]]), ""]
    if len(diffs) > _MAX_FILES_PER_ARTIFACT:
        out.append(f"- … and {len(diffs) - _MAX_FILES_PER_ARTIFACT} more (see result.json)")
    for meta in art.get("metadata_differences", []):
        out.append(f"- {_text(meta['source'])} {_code(meta['field'])}: "
                   f"{_code(meta['original'])} → {_code(meta['rebuilt'])}")
    for note in art.get("notes", []):
        out.append(f"- Note: {_text(note)}")
    if art.get("hypotheses"):
        out += ["", "Possible explanations (hypotheses, not confirmed):", ""]
        out += [f"- {_text(h)}" for h in art["hypotheses"]]
    out.append("")
    return out


def write_markdown(data: dict[str, Any], directory: Path) -> Path:
    """Write ``report.md`` into ``directory`` and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / REPORT_FILENAME
    path.write_text(render_markdown(data), encoding="utf-8")
    return path
