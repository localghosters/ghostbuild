"""Self-contained HTML report (inline CSS, no scripts, no external resources)."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from ghostbuild.reports import short_hash, verdict_label

REPORT_FILENAME = "report.html"
_MAX_LOG_CHARS = 200_000

_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1c2330;--muted:#5d6879;--line:#dde2ea;--ok:#12805c;
--bad:#c0392b;--warn:#a86a00;--code:#eef1f5}
@media(prefers-color-scheme:dark){:root{--bg:#10141b;--card:#181e28;--fg:#e6eaf0;--muted:#98a2b3;
--line:#2b3445;--ok:#3ecf9a;--bad:#ff7b6b;--warn:#f0b24a;--code:#10141b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px 64px}
h1{margin:0;font-size:22px}h2{font-size:17px;margin:0 0 12px}
.tag{color:var(--muted);margin:2px 0 20px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin:16px 0}
.verdict{font-size:24px;font-weight:700}.reproducible{color:var(--ok)}
.non-reproducible{color:var(--bad)}.inconclusive{color:var(--warn)}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px 8px;
border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}
td.k{color:var(--muted);white-space:nowrap;width:1%}
code,pre{font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
code{background:var(--code);padding:1px 4px;border-radius:4px;word-break:break-all}
pre{background:var(--code);padding:10px;border-radius:8px;overflow:auto;max-height:420px;margin:6px 0}
details{margin:8px 0}summary{cursor:pointer;font-weight:600}
.badge{font-weight:700}.match{color:var(--ok)}.different,.missing,.additional{color:var(--bad)}
.note{color:var(--muted)}ul{margin:6px 0;padding-left:22px}
@media(max-width:600px){th,td{padding:5px 4px;font-size:13px}}
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _kv_table(rows: list[tuple[str, Any]]) -> str:
    body = "".join(f"<tr><td class='k'>{_e(k)}</td><td>{_e(v)}</td></tr>" for k, v in rows if v)
    return f"<table>{body}</table>"


def _list(items: list[str], css: str = "") -> str:
    if not items:
        return ""
    cls = f" class='{css}'" if css else ""
    return f"<ul{cls}>" + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>"


def _project_section(project: dict[str, Any] | None) -> str:
    if not project:
        return ""
    rows = [
        ("Name", project["name"]), ("Version", project["version"]),
        ("Language", project["language"]), ("Build system", project["build_system"]),
        ("Build backend", project["build_backend"]),
        ("Config files", ", ".join(project["config_files"])),
        ("Build requirements", ", ".join(project["build_requires"])),
        ("Declared dependencies", ", ".join(project["dependencies"])),
        ("Requires Python", project["requires_python"]),
        ("Lock files", ", ".join(project["lock_files"])),
    ]  # fmt: skip
    return f"<section><h2>Project</h2>{_kv_table(rows)}{_list(project['notes'], 'note')}</section>"


def _environment_section(data: dict[str, Any]) -> str:
    builds = [b for b in (data.get("original_build"), data.get("rebuilt_build")) if b]
    if not builds and not data.get("isolation"):
        return ""
    parts = ["<section><h2>Build environment</h2>"]
    isolation = data.get("isolation")
    if isolation:
        parts.append(f"<p><strong>Isolation: {_e(isolation['mode'])}.</strong> "
                     f"{_e(isolation['description'])}</p>")  # fmt: skip
    if builds:
        fields = [
            ("Runtime", "runtime"), ("Image", "image"), ("Image ID", "image_id"),
            ("Python", "python_version"), ("Implementation", "python_implementation"),
            ("OS", "os"), ("Architecture", "architecture"), ("Build tool", "build_tool"),
            ("Locale", "locale"), ("Timezone", "timezone"),
        ]  # fmt: skip
        header = "".join(f"<th>{_e(b['label']).title()}</th>" for b in builds)
        rows = ""
        for title, key in fields:
            values = [b["environment"].get(key) for b in builds]
            if any(values):
                cells = "".join(f"<td>{_e(v or '-')}</td>" for v in values)
                rows += f"<tr><td class='k'>{title}</td>{cells}</tr>"
        names = "".join(
            f"<td>{_e(', '.join(b['environment']['env_var_names']) or '-')}</td>" for b in builds
        )
        rows += f"<tr><td class='k'>Variables passed (names only)</td>{names}</tr>"
        parts.append(f"<table><tr><th></th>{header}</tr>{rows}</table>")
    if data.get("environment_differences"):
        parts.append("<p>Environment differences (facts, not causes):</p>")
        parts.append(_list(data["environment_differences"]))
    parts.append("</section>")
    return "".join(parts)


def _artifact_table(data: dict[str, Any]) -> str:
    rows = ""
    for art in data["comparison"]["artifacts"]:
        o, r = art["original"], art["rebuilt"]
        sizes = " / ".join(str(x["size"]) if x else "-" for x in (o, r))
        rows += (
            f"<tr><td>{_e(art['name'])}<br><span class='note'>{_e(art['kind'])}</span></td>"
            f"<td><code>{_e(short_hash(o and o['sha256']))}</code></td>"
            f"<td><code>{_e(short_hash(r and r['sha256']))}</code></td>"
            f"<td>{_e(sizes)}</td>"
            f"<td class='badge {_e(art['status'])}'>{_e(art['status'].upper())}</td></tr>"
        )
    if not rows:
        return "<p class='note'>No artifacts were found.</p>"
    return ("<table><tr><th>Artifact</th><th>Original SHA-256</th><th>Rebuilt SHA-256</th>"
            f"<th>Size (orig / rebuilt)</th><th>Status</th></tr>{rows}</table>")  # fmt: skip


def _difference_details(art: dict[str, Any]) -> str:
    if art["status"] != "different":
        return ""
    o, r = art["original"], art["rebuilt"]
    parts = [f"<details open><summary>{_e(art['name'])}</summary>",
             f"<p>Original SHA-256: <code>{_e(o['sha256'])}</code> ({_e(o['size'])} bytes)<br>"
             f"Rebuilt SHA-256: <code>{_e(r['sha256'])}</code> ({_e(r['size'])} bytes)</p>"]  # fmt: skip
    if art["members_compared"]:
        parts.append(
            f"<p>{art['members_identical']} of {art['members_compared']} shared archive members "
            "are identical in content and metadata.</p>"
        )
    if art["member_order_differs"]:
        parts.append("<p>Archive member order differs.</p>")
    if art["file_differences"]:
        rows = "".join(
            f"<tr><td><code>{_e(d['path'])}</code></td><td>{_e(d['change'])}</td>"
            f"<td>{_e(d['detail'])}"
            + (f"<pre>{_e(chr(10).join(d['diff_excerpt']))}</pre>" if d["diff_excerpt"] else "")
            + "</td></tr>"
            for d in art["file_differences"]
        )
        parts.append(f"<table><tr><th>Member</th><th>Change</th><th>Detail</th></tr>{rows}</table>")
    if art["metadata_differences"]:
        rows = "".join(
            f"<tr><td>{_e(m['source'])}</td><td>{_e(m['field'])}</td>"
            f"<td>{_e(m['original'])}</td><td>{_e(m['rebuilt'])}</td></tr>"
            for m in art["metadata_differences"]
        )
        parts.append("<table><tr><th>Source</th><th>Field</th><th>Original</th><th>Rebuilt</th></tr>"
                     f"{rows}</table>")  # fmt: skip
    parts.append(_list(art["notes"], "note"))
    if art["hypotheses"]:
        parts.append("<p><strong>Possible explanations (hypotheses, not confirmed):</strong></p>")
        parts.append(_list(art["hypotheses"]))
    parts.append("</details>")
    return "".join(parts)


def _logs_section(data: dict[str, Any]) -> str:
    parts = []
    for build in (data.get("original_build"), data.get("rebuilt_build")):
        if not build:
            continue
        status = "succeeded" if build["succeeded"] else f"FAILED: {build['failure_reason']}"
        body = [f"<p class='note'>Command: <code>{_e(' '.join(build['command'][:6]))}"
                f"{' …' if len(build['command']) > 6 else ''}</code> · {_e(build['duration_seconds'])} s"
                f" · exit {_e(build['returncode'])}</p>"]  # fmt: skip
        for stream in ("stdout", "stderr"):
            text = build[stream]
            if text.strip():
                if len(text) > _MAX_LOG_CHARS:
                    text = text[:_MAX_LOG_CHARS] + "\n... (truncated in HTML report; see result.json)"
                body.append(f"<details><summary>{stream}</summary><pre>{_e(text)}</pre></details>")
        parts.append(f"<details><summary>{_e(build['label'].title())} build, {_e(status)}</summary>"
                     f"{''.join(body)}</details>")  # fmt: skip
    return f"<section><h2>Build logs</h2>{''.join(parts)}</section>" if parts else ""


def render_html(data: dict[str, Any]) -> str:
    """Render a result dictionary as a self-contained HTML document."""
    label = verdict_label(data)
    details = "".join(_difference_details(a) for a in data["comparison"]["artifacts"])
    summary = data["comparison"]["summary"]
    execution = [
        ("Command", f"ghostbuild {data['command']}"), ("GhostBuild version", data["tool_version"]),
        ("Started", data["started_at"]), ("Finished", data["finished_at"]),
        ("Duration", f"{data['duration_seconds']} s"), ("Comparison policy", data["policy"]),
        ("Result schema", data["schema_version"]),
    ]  # fmt: skip
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>GhostBuild report: {_e(label)}</title><style>{_CSS}</style></head><body><main>"
        "<h1>GhostBuild report</h1><p class='tag'>Build it twice. Know what changed.</p>"
        f"<section><div class='verdict {_e(data['verdict'])}'>{_e(label)}</div>"
        f"{_list(data['verdict_reasons'])}"
        "<p class='note'>Reproducibility results depend on the environments and comparison policy "
        "used. This report describes these builds only.</p></section>"
        f"{_project_section(data.get('project'))}{_environment_section(data)}"
        "<section><h2>Artifact comparison</h2>"
        f"<p class='note'>{summary['matching']} matching · {summary['different']} different · "
        f"{summary['missing']} missing from rebuild · {summary['additional']} additional in "
        f"rebuild (policy: {_e(data['policy'])}, exact SHA-256)</p>"
        f"{_artifact_table(data)}</section>"
        + (f"<section><h2>Differences</h2>{details}</section>" if details else "")
        + (f"<section><h2>Warnings</h2>{_list(data['warnings'])}</section>" if data["warnings"] else "")
        + _logs_section(data)
        + f"<section><h2>Execution metadata</h2>{_kv_table(execution)}</section>"
        "</main></body></html>\n"
    )


def write_html(data: dict[str, Any], directory: Path) -> Path:
    """Write ``report.html`` into ``directory`` and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / REPORT_FILENAME
    path.write_text(render_html(data), encoding="utf-8")
    return path
