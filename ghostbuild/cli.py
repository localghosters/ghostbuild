"""Command-line interface (Typer + Rich)."""

from __future__ import annotations

import shlex
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.text import Text

from ghostbuild import __version__
from ghostbuild.config import (
    CONFIG_FILENAME,
    EXAMPLE_CONFIG,
    REPORT_FORMATS,
    load_config,
)
from ghostbuild.detection import detect_project
from ghostbuild.engine.isolation import (
    ISOLATION_CHOICES,
    DockerStatus,
    detect_docker,
    resolve_isolation,
)
from ghostbuild.engine.verifier import compare_directories, verify_project
from ghostbuild.errors import GhostBuildError, LocalFallbackNotApproved, PathError
from ghostbuild.models import VerificationResult, to_plain
from ghostbuild.reports import json_report
from ghostbuild.reports.html_report import write_html
from ghostbuild.reports.terminal import render_banner, render_result, render_scan
from ghostbuild.utils.filesystem import validate_directory

# Exit codes: 2 is reserved for usage errors (Typer/Click).
EXIT_REPRODUCIBLE = 0
EXIT_NON_REPRODUCIBLE = 1
EXIT_INCONCLUSIVE = 3
EXIT_ERROR = 4
EXIT_DECLINED = 5
_VERDICT_EXIT = {
    "reproducible": EXIT_REPRODUCIBLE,
    "non-reproducible": EXIT_NON_REPRODUCIBLE,
    "inconclusive": EXIT_INCONCLUSIVE,
}

app = typer.Typer(
    name="ghostbuild",
    help="Build it twice. Know what changed. Reproducible build verification.",
    add_completion=False,
    no_args_is_help=False,
)

NoColorOption = Annotated[bool, typer.Option("--no-color", help="Disable coloured output.")]
VerboseOption = Annotated[bool, typer.Option("--verbose", help="Show full details and build logs.")]
ConfigOption = Annotated[
    Optional[Path],
    typer.Option("--config", "-c", help="Path to a ghostbuild.toml (default: <project>/ghostbuild.toml)."),
]


def _consoles(no_color: bool) -> tuple[Console, Console]:
    """Return (stdout console, stderr console). Progress and errors go to stderr."""
    return Console(no_color=no_color), Console(stderr=True, no_color=no_color)


@contextmanager
def _handle_errors(err: Console) -> Iterator[None]:
    """Turn expected GhostBuild errors into a clean message and exit code 4."""
    try:
        yield
    except GhostBuildError as exc:
        err.print(Text(f"Error: {exc}", style="bold red"))
        raise typer.Exit(EXIT_ERROR) from exc


def _check_format(value: str | None) -> str | None:
    if value is not None and value not in REPORT_FORMATS:
        raise typer.BadParameter(f"must be one of: {', '.join(REPORT_FORMATS)}", param_hint="--format")
    return value


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ghostbuild {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", "-V", callback=_version_callback, is_eager=True,
                     help="Show the version and exit."),
    ] = False,
) -> None:  # fmt: skip
    """Build it twice. Know what changed."""
    if ctx.invoked_subcommand is None:
        render_banner(Console())


@app.command()
def version() -> None:
    """Show the installed GhostBuild version."""
    typer.echo(f"ghostbuild {__version__}")


@app.command()
def init(
    path: Annotated[Path, typer.Argument(help="Where to write the example configuration.")] = Path(
        CONFIG_FILENAME
    ),
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
) -> None:
    """Write an example ghostbuild.toml containing all defaults."""
    out, err = _consoles(False)
    if path.exists() and not force:
        err.print(Text(f"Error: {path} already exists. Use --force to overwrite it.", style="bold red"))
        raise typer.Exit(EXIT_ERROR)
    path.write_text(EXAMPLE_CONFIG, encoding="utf-8")
    out.print(Text(f"Wrote {path}"))


@app.command()
def scan(
    project_dir: Annotated[Path, typer.Argument(help="Project directory to inspect.")] = Path("."),
    config_path: ConfigOption = None,
    no_color: NoColorOption = False,
) -> None:
    """Inspect a project: name, build system, requirements and available tools.

    Reads project files only. No build is run.
    """
    out, err = _consoles(no_color)
    with _handle_errors(err):
        load_config(config_path, validate_directory(project_dir, "project directory"))
        adapter, project = detect_project(project_dir)
        docker = detect_docker()
        render_scan(out, to_plain(project), adapter.available_tools(), to_plain(docker))


def _interactive() -> bool:
    return sys.stdin.isatty()


def _choose_isolation(requested: str, docker: DockerStatus, err: Console) -> str:
    """Resolve the isolation mode, asking before any local fallback."""
    try:
        return resolve_isolation(requested, docker, local_approved=False)
    except LocalFallbackNotApproved as exc:
        if not _interactive():
            raise
        err.print(Text(f"Docker is unavailable: {docker.reason}.", style="bold yellow"))
        err.print(
            "A local rebuild uses the same interpreter and tools as the original build, so it "
            "is NOT equivalent to an independent clean-container build. It can only show "
            "repeatability on this machine."
        )
        if not typer.confirm("Use the weaker local rebuild instead?", default=False):
            raise typer.Exit(EXIT_DECLINED) from exc
        return resolve_isolation(requested, docker, local_approved=True)


def _present_plan(err: Console, project_dir: Path, command: list[str], mode: str, image: str | None) -> None:
    err.print(Text("\nBuild plan", style="bold"))
    err.print(Text(f"  Project: {project_dir}"))
    err.print(Text(f"  Original build: runs on this host in a temporary copy: {shlex.join(command)}"))
    if mode == "docker":
        err.print(Text(f"  Independent rebuild: runs inside a Docker container ({image}), source mounted read-only"))
    else:
        err.print(Text("  Independent rebuild: runs on this host in a second temporary copy (LOCAL, weaker isolation)",
                       style="yellow"))  # fmt: skip
    err.print(Text("  Your project directory is only read, never modified.", style="dim"))
    err.print(Text("  WARNING: building runs code from this project (build backend, setup.py, hooks).",
                   style="bold yellow"))  # fmt: skip


@app.command()
def verify(
    project_dir: Annotated[Path, typer.Argument(help="Project directory to verify.")] = Path("."),
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Directory for reports.")] = None,
    fmt: Annotated[
        Optional[str],
        typer.Option("--format", "-f", help="Output format: terminal, json or html."),
    ] = None,
    keep_artifacts: Annotated[
        bool, typer.Option("--keep-artifacts", help="Keep both builds' artifacts in the output directory.")
    ] = False,
    isolation: Annotated[
        str,
        typer.Option(help="Rebuild isolation: auto (Docker if available), docker, or local."),
    ] = "auto",
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Approve running the project's build without prompting.")
    ] = False,
    timeout: Annotated[Optional[int], typer.Option(help="Per-build timeout in seconds.", min=1)] = None,
    config_path: ConfigOption = None,
    verbose: VerboseOption = False,
    no_color: NoColorOption = False,
) -> None:
    """Build the project twice and compare the artifacts.

    This executes the project's build scripts. GhostBuild asks for consent first
    (or use --yes) and never silently weakens isolation.
    """
    out, err = _consoles(no_color)
    if isolation not in ISOLATION_CHOICES:
        raise typer.BadParameter(f"must be one of: {', '.join(ISOLATION_CHOICES)}", param_hint="--isolation")
    _check_format(fmt)
    result: VerificationResult
    with _handle_errors(err):
        root = validate_directory(project_dir, "project directory")
        config = load_config(config_path, root)
        fmt = fmt or config.report.format
        output_dir = (output or Path(config.report.output_dir)).resolve()
        _check_output_dir(output_dir, keep_artifacts)
        adapter, project = detect_project(root)
        err.print(Text(f"GhostBuild v{__version__}", style="bold"))
        err.print(Text(f"Detected: {project.language}   Build system: {project.build_system}"))

        mode = _choose_isolation(isolation, detect_docker(), err)
        image = adapter.container_image(config) if mode == "docker" else None
        command = adapter.build_command(Path("<source>"), Path("<output>"), config)
        _present_plan(err, root, command, mode, image)
        if not yes:
            if not _interactive():
                raise GhostBuildError(
                    "Refusing to run build commands without consent in a non-interactive session. "
                    "Re-run with --yes to approve."
                )
            if not typer.confirm("Run these build commands now?", default=False):
                err.print("Aborted. No build commands were run.")
                raise typer.Exit(EXIT_DECLINED)

        err.print()
        with err.status("Starting...") as status:
            def on_stage(index: int, total: int, label: str) -> None:
                err.print(Text(f"[{index}/{total}] {label}", style="bold cyan"))
                status.update(f"{label}...")

            result = verify_project(
                root, adapter, project, config,
                mode=mode,
                timeout=timeout or config.build.timeout_seconds,
                keep_artifacts_dir=(output_dir / "artifacts") if keep_artifacts else None,
                skip_paths=[output_dir],
                on_stage=on_stage,
            )  # fmt: skip
        _emit(result, output_dir, fmt, out, err, verbose)
    raise typer.Exit(_VERDICT_EXIT[result.verdict.value])


def _check_output_dir(output_dir: Path, keep_artifacts: bool) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise PathError(f"The output path exists and is not a directory: {output_dir}")
    kept = output_dir / "artifacts"
    if keep_artifacts and kept.exists() and any(kept.iterdir()):
        raise PathError(
            f"{kept} already contains files. GhostBuild will not overwrite or delete them; "
            "choose another --output directory or remove it yourself."
        )


def _emit(
    result: VerificationResult, output_dir: Path, fmt: str, out: Console, err: Console, verbose: bool
) -> None:
    """Write result.json (always) and print/write the requested format."""
    saved = json_report.write_json(result, output_dir)
    data = result.to_dict()
    if fmt == "json":
        typer.echo(json_report.to_json(data), nl=False)
    else:
        render_result(out, data, verbose)
    if fmt == "html":
        err.print(Text(f"HTML report saved to: {write_html(data, output_dir)}"))
    err.print(Text(f"Report saved to: {saved.parent}/"))


@app.command()
def compare(
    dir_a: Annotated[Path, typer.Argument(help="First (original) artifact directory.")],
    dir_b: Annotated[Path, typer.Argument(help="Second (rebuilt) artifact directory.")],
    pattern: Annotated[
        Optional[list[str]], typer.Option("--pattern", "-p", help="Artifact glob (repeatable).")
    ] = None,
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Write reports to this directory.")] = None,
    fmt: Annotated[Optional[str], typer.Option("--format", "-f", help="terminal, json or html.")] = None,
    config_path: ConfigOption = None,
    verbose: VerboseOption = False,
    no_color: NoColorOption = False,
) -> None:
    """Compare two existing artifact directories. No builds are run."""
    out, err = _consoles(no_color)
    _check_format(fmt)
    with _handle_errors(err):
        first = validate_directory(dir_a, "first directory")
        second = validate_directory(dir_b, "second directory")
        config = load_config(config_path, None)
        fmt = fmt or "terminal"
        if fmt == "html" and output is None:
            raise PathError("--format html needs --output to choose where to write the report.")
        result = compare_directories(first, second, config, pattern or None)
        if output is not None:
            _emit(result, output.resolve(), fmt, out, err, verbose)
        else:
            data = result.to_dict()
            if fmt == "json":
                typer.echo(json_report.to_json(data), nl=False)
            else:
                render_result(out, data, verbose)
    raise typer.Exit(_VERDICT_EXIT[result.verdict.value])


@app.command()
def report(
    path: Annotated[Path, typer.Argument(help="A result.json file or a directory containing one.")] = Path(
        "ghostbuild-results"
    ),
    fmt: Annotated[str, typer.Option("--format", "-f", help="terminal, json or html.")] = "terminal",
    output: Annotated[
        Optional[Path], typer.Option("--output", "-o", help="Directory to write an HTML report to.")
    ] = None,
    verbose: VerboseOption = False,
    no_color: NoColorOption = False,
) -> None:
    """Display or regenerate a report from a stored result.json."""
    out, err = _consoles(no_color)
    _check_format(fmt)
    with _handle_errors(err):
        data = json_report.load_result(path)
        if fmt == "json":
            typer.echo(json_report.to_json(data), nl=False)
        elif fmt == "html":
            target = output or (path if path.is_dir() else path.parent)
            err.print(Text(f"HTML report saved to: {write_html(data, target.resolve())}"))
        else:
            render_result(out, data, verbose)
