"""Rich terminal output."""

from __future__ import annotations

from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ghostbuild import __version__
from ghostbuild.reports import short_hash, verdict_label

LOGO = r"""
  ____ _               _   ____        _ _     _
 / ___| |__   ___  ___| |_| __ )_   _(_) | __| |
| |  _| '_ \ / _ \/ __| __|  _ \| | | | | |/ _` |
| |_| | | | | (_) \__ \ |_| |_) | |_| | | | (_| |
 \____|_| |_|\___/|___/\__|____/ \__,_|_|_|\__,_|
"""

_VERDICT_STYLE = {"reproducible": "bold green", "non-reproducible": "bold red",
                  "inconclusive": "bold yellow"}  # fmt: skip
_STATUS_STYLE = {"match": "green", "different": "red", "missing": "red", "additional": "red"}
_MAX_FILE_DIFFS = 15
_LOG_TAIL_LINES = 25


def render_banner(console: Console) -> None:
    """Print the logo, version, description, commands and examples."""
    console.print(Text(LOGO, style="bold cyan"), end="")
    console.print(Text(f"GhostBuild v{__version__}", style="bold"))
    console.print("Build it twice. Know what changed.")
    console.print("Independently rebuilds a project and compares the artifacts.\n")
    commands = Table(box=None, show_header=False, padding=(0, 2))
    for name, help_text in (
        ("scan", "Inspect a project (does not run builds)"),
        ("verify", "Build twice and compare the artifacts"),
        ("compare", "Compare two existing artifact directories"),
        ("report", "Show or regenerate a report from stored results"),
        ("init", "Write an example ghostbuild.toml"),
        ("version", "Show the installed version"),
    ):
        commands.add_row(Text(f"ghostbuild {name}", style="cyan"), help_text)
    console.print(Text("Commands", style="bold"))
    console.print(commands)
    console.print(Text("\nExamples", style="bold"))
    for example in ("ghostbuild scan ./my-project", "ghostbuild verify ./my-project",
                    "ghostbuild compare ./build-one ./build-two",
                    "ghostbuild report ./ghostbuild-results/"):  # fmt: skip
        console.print(Text(f"  $ {example}", style="dim"))


def render_scan(console: Console, project: dict[str, Any], tools: dict[str, str | None],
                docker: dict[str, Any]) -> None:  # fmt: skip
    """Print what ``ghostbuild scan`` found."""
    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column(style="bold")
    table.add_column()
    rows = [
        ("Project", project["name"] or "unknown"), ("Version", project["version"] or "unknown"),
        ("Language", project["language"]), ("Build system", project["build_system"]),
        ("Build backend", project["build_backend"] or "-"),
        ("Requires Python", project["requires_python"] or "-"),
        ("Config files", ", ".join(project["config_files"]) or "-"),
        ("Build requirements", ", ".join(project["build_requires"]) or "-"),
        ("Lock files", ", ".join(project["lock_files"]) or "none"),
    ]  # fmt: skip
    for key, value in rows:
        table.add_row(key, Text(str(value)))
    console.print(table)
    tool_table = Table(title="Available tools", box=box.SIMPLE)
    tool_table.add_column("Tool", style="bold")
    tool_table.add_column("Status")
    for name, detail in tools.items():
        tool_table.add_row(name, Text(detail, style="green") if detail else Text("not found", style="dim"))
    docker_text = (
        Text(f"available (server {docker['version'] or 'unknown'})", style="green")
        if docker["available"] else Text(f"unavailable: {docker['reason']}", style="yellow")
    )
    tool_table.add_row("docker", docker_text)
    console.print(tool_table)
    for note in project["notes"]:
        console.print(Text(f"Note: {note}", style="dim"))
    console.print(Text("No build was run. `ghostbuild verify` runs the build after asking for consent.",
                       style="dim"))  # fmt: skip


def _artifact_table(data: dict[str, Any]) -> Table:
    table = Table(box=box.SIMPLE_HEAVY)
    for column in ("Artifact", "Original", "Rebuilt", "Size", "Status"):
        table.add_column(column)
    for art in data["comparison"]["artifacts"]:
        o, r = art["original"], art["rebuilt"]
        table.add_row(
            Text(art["name"]),
            Text(f"SHA256: {short_hash(o and o['sha256'])}" if o else "-"),
            Text(f"SHA256: {short_hash(r and r['sha256'])}" if r else "-"),
            Text(" / ".join(str(x["size"]) if x else "-" for x in (o, r))),
            Text(art["status"].upper(), style=_STATUS_STYLE.get(art["status"], "")),
        )
    return table


def _render_differences(console: Console, art: dict[str, Any], verbose: bool) -> None:
    o, r = art["original"], art["rebuilt"]
    console.print(Text(f"\n{art['name']}", style="bold red"))
    console.print(Text(f"  original sha256: {o['sha256']} ({o['size']} bytes)"))
    console.print(Text(f"  rebuilt  sha256: {r['sha256']} ({r['size']} bytes)"))
    if art["members_compared"]:
        console.print(Text(f"  {art['members_identical']}/{art['members_compared']} shared members "
                           "identical in content and metadata"))  # fmt: skip
    if art["member_order_differs"]:
        console.print(Text("  member order differs"))
    limit = None if verbose else _MAX_FILE_DIFFS
    if art["file_differences"]:
        console.print(Text("  Internal differences:", style="bold"))
    for diff in art["file_differences"][:limit]:
        console.print(Text(f"  - {diff['path']}: {diff['detail']}"))
        if verbose:
            for line in diff["diff_excerpt"]:
                console.print(Text(f"      {line}", style="dim"))
    hidden = len(art["file_differences"]) - _MAX_FILE_DIFFS
    if not verbose and hidden > 0:
        console.print(Text(f"  ... and {hidden} more (use --verbose or see result.json)", style="dim"))
    if art["metadata_differences"]:
        console.print(Text("  Metadata differences:", style="bold"))
        for meta in art["metadata_differences"]:
            console.print(Text(f"  - {meta['source']} / {meta['field']}: "
                               f"{meta['original']} -> {meta['rebuilt']}"))  # fmt: skip
    for note in art["notes"]:
        console.print(Text(f"  Note: {note}", style="dim"))
    if art["hypotheses"]:
        console.print(Text("  Possible explanations (hypotheses, not confirmed):", style="bold yellow"))
        for hypothesis in art["hypotheses"]:
            console.print(Text(f"  ? {hypothesis}"))


def _render_logs(console: Console, data: dict[str, Any], verbose: bool) -> None:
    for build in (data.get("original_build"), data.get("rebuilt_build")):
        if not build or (build["succeeded"] and not verbose):
            continue
        console.print(Text(f"\n{build['label'].title()} build log"
                           f" ({'ok' if build['succeeded'] else build['failure_reason']})",
                           style="bold"))  # fmt: skip
        for stream in ("stdout", "stderr"):
            lines = build[stream].splitlines()
            if not lines:
                continue
            shown = lines if verbose else lines[-_LOG_TAIL_LINES:]
            console.print(Text(f"--- {stream}" + ("" if verbose or len(lines) <= len(shown)
                                                 else f" (last {len(shown)} lines)"), style="dim"))  # fmt: skip
            for line in shown:
                console.print(Text(line, style="dim"))


def render_result(console: Console, data: dict[str, Any], verbose: bool = False) -> None:
    """Print a verification result."""
    style = _VERDICT_STYLE.get(data["verdict"], "bold")
    console.print()
    console.print(Panel(Text(f"RESULT: {verdict_label(data)}", style=style), box=box.HEAVY,
                        expand=False))  # fmt: skip
    for reason in data["verdict_reasons"]:
        console.print(Text(f"  • {reason}"))
    isolation = data.get("isolation")
    if isolation:
        console.print(Text(f"\nIsolation: {isolation['mode']}", style="bold"))
        console.print(Text(f"  {isolation['description']}"))
    console.print()
    console.print(_artifact_table(data))
    for art in data["comparison"]["artifacts"]:
        if art["status"] == "different":
            _render_differences(console, art, verbose)
    if data.get("environment_differences"):
        console.print(Text("\nEnvironment differences (facts, not causes):", style="bold"))
        for item in data["environment_differences"]:
            console.print(Text(f"  - {item}"))
    if data["warnings"]:
        console.print(Text("\nWarnings:", style="bold yellow"))
        for warning in data["warnings"]:
            console.print(Text(f"  ! {warning}"))
    _render_logs(console, data, verbose)
    console.print(Text(f"\nCompleted in {data['duration_seconds']} s · policy: {data['policy']} · "
                       "results depend on the environments and policy used.", style="dim"))  # fmt: skip
