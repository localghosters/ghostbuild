"""The verification workflow: original build, independent rebuild, comparison."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

from ghostbuild import __version__
from ghostbuild.adapters.base import BuildAdapter
from ghostbuild.config import Config
from ghostbuild.engine.artifacts import copy_artifacts, discover_artifacts
from ghostbuild.engine.comparator import compare_artifact_sets, determine_verdict
from ghostbuild.engine.executor import CommandResult, docker_run_command, run_command
from ghostbuild.engine.isolation import describe_isolation
from ghostbuild.engine.workspace import BuildDirs, Workspace, copy_source
from ghostbuild.errors import IsolationError, PrerequisiteError
from ghostbuild.models import (
    BuildRecord,
    EnvironmentInfo,
    IsolationInfo,
    ProjectInfo,
    Verdict,
    VerificationResult,
)
from ghostbuild.utils.environment import (
    build_env,
    capture_host_environment,
    is_secret_name,
    redact_secrets,
)

TOTAL_STAGES = 4
StageCallback = Callable[[int, int, str], None]
_ENV_MARKER = "GHOSTBUILD_ENV "
_LOCAL_REBUILD_WARNING = (
    "The rebuild ran on the same host as the original build. A match does not show that the "
    "project builds identically in an independent environment."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _failure_reason(result: CommandResult) -> str | None:
    if result.succeeded:
        return None
    if result.error:
        return result.error
    return f"the build command exited with status {result.returncode}"


def _record(
    label: str,
    isolation: str,
    result: CommandResult,
    environment: EnvironmentInfo,
    patterns: Sequence[str],
    artifact_root: Path,
) -> BuildRecord:
    """Turn a command result into a record, with secrets redacted from all text."""
    artifacts = discover_artifacts(artifact_root, patterns) if result.succeeded else []
    return BuildRecord(
        label=label,
        isolation=isolation,
        command=[redact_secrets(part) for part in result.command],
        started_at=result.started_at,
        duration_seconds=round(result.duration_seconds, 3),
        returncode=result.returncode,
        timed_out=result.timed_out,
        succeeded=result.succeeded,
        failure_reason=redact_secrets(_failure_reason(result) or "") or None,
        stdout=redact_secrets(result.stdout),
        stderr=redact_secrets(result.stderr),
        environment=environment,
        artifacts=artifacts,
    )


def _build_locally(
    label: str,
    adapter: BuildAdapter,
    dirs: BuildDirs,
    config: Config,
    env: Mapping[str, str],
    timeout: float,
) -> BuildRecord:
    command = adapter.build_command(dirs.source, dirs.output, config)
    result = run_command(command, cwd=dirs.source, env=env, timeout=timeout)
    environment = capture_host_environment(adapter.describe_build_tool(), env)
    return _record(label, "local", result, environment, config.artifacts.patterns, dirs.output)


def _ensure_image(image: str, timeout: float) -> str | None:
    """Make sure the image exists locally, pulling it if needed. Returns an error or None."""
    inspect = run_command(["docker", "image", "inspect", image], cwd=None, env=os.environ, timeout=60)
    if inspect.succeeded:
        return None
    pull = run_command(["docker", "pull", image], cwd=None, env=os.environ, timeout=timeout)
    if pull.succeeded:
        return None
    detail = pull.error or (pull.stderr.strip().splitlines() or ["unknown error"])[-1]
    return f"Could not obtain Docker image {image!r}: {detail}"


def _image_id(image: str) -> str | None:
    result = run_command(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        cwd=None, env=os.environ, timeout=60,
    )  # fmt: skip
    return result.stdout.strip() or None if result.succeeded else None


def _container_environment(stdout: str, image: str, warnings: list[str]) -> EnvironmentInfo:
    """Read the environment report the container script prints."""
    info = EnvironmentInfo(runtime="docker", image=image, image_id=_image_id(image))
    for line in stdout.splitlines():
        if not line.startswith(_ENV_MARKER):
            continue
        try:
            reported = json.loads(line[len(_ENV_MARKER):])
        except json.JSONDecodeError as exc:
            warnings.append(f"Could not parse the container environment report: {exc}")
            break
        for key in ("python_version", "python_implementation", "os", "architecture",
                    "build_tool", "locale", "timezone"):  # fmt: skip
            if isinstance(reported.get(key), str):
                setattr(info, key, reported[key])
        return info
    warnings.append("The container did not report its environment; details are incomplete.")
    return info


def _build_in_docker(
    adapter: BuildAdapter,
    dirs: BuildDirs,
    config: Config,
    image: str,
    timeout: float,
    pull_error: str | None,
    warnings: list[str],
) -> BuildRecord:
    user = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else None
    command = docker_run_command(
        image=image,
        source_dir=dirs.source,
        output_dir=dirs.output,
        script=adapter.container_script(config),
        user=user,
    )
    if pull_error:
        result = CommandResult(command, None, "", "", _now(), 0.0, error=pull_error)
    else:
        result = run_command(command, cwd=None, env=os.environ, timeout=timeout)
    environment = _container_environment(result.stdout, image, warnings)
    return _record("rebuilt", "docker", result, environment, config.artifacts.patterns, dirs.output)


def environment_differences(a: EnvironmentInfo, b: EnvironmentInfo) -> list[str]:
    """List facts that differ between two environments (not causes)."""
    labels = (
        ("python_version", "Python version"), ("python_implementation", "Python implementation"),
        ("os", "operating system"), ("architecture", "architecture"),
        ("build_tool", "build tool"), ("locale", "locale"), ("timezone", "timezone"),
    )  # fmt: skip
    return [
        f"{label}: {getattr(a, attr) or 'unknown'} vs {getattr(b, attr) or 'unknown'}"
        for attr, label in labels
        if getattr(a, attr) != getattr(b, attr)
    ]


def verify_project(
    project_dir: Path,
    adapter: BuildAdapter,
    project: ProjectInfo,
    config: Config,
    *,
    mode: str,
    timeout: float,
    keep_artifacts_dir: Path | None = None,
    skip_paths: Sequence[Path] = (),
    on_stage: StageCallback | None = None,
) -> VerificationResult:
    """Build ``project_dir`` twice and compare the artifacts.

    ``mode`` is the already-resolved isolation mode (``"docker"`` or ``"local"``);
    the caller is responsible for user consent. The source project is only read.
    """
    stage = on_stage or (lambda index, total, label: None)
    started_at, began = _now(), time.monotonic()

    if mode == "docker" and adapter.has_custom_build_command(config):
        raise IsolationError(
            "A custom build_command is only supported with local isolation in 0.1.0; "
            "remove it or use --isolation local."
        )
    problems = adapter.missing_prerequisites(config)
    if problems:
        raise PrerequisiteError(" ".join(problems))

    warnings = list(adapter.collect_warnings(project))
    warnings += [
        f"Environment variable {name} looks secret but is passed to the build; "
        "its value is not stored in reports."
        for name in config.build.env_passthrough
        if is_secret_name(name)
    ]
    image = adapter.container_image(config) if mode == "docker" else None
    isolation: IsolationInfo = describe_isolation(mode, image)
    if mode == "local":
        warnings.append(_LOCAL_REBUILD_WARNING)

    env = build_env(config.build.env_passthrough)
    copy_options = {
        "include_vcs": config.workspace.include_vcs,
        "extra_excludes": config.workspace.exclude,
        "skip_paths": skip_paths,
    }
    rebuilt: BuildRecord | None = None

    with Workspace(config.workspace.temp_dir) as workspace:
        stage(1, TOTAL_STAGES, "Capturing original build")
        original_dirs = workspace.new_build_dirs("original")
        copy_source(project_dir, original_dirs.source, **copy_options)
        original = _build_locally("original", adapter, original_dirs, config, env, timeout)

        stage(2, TOTAL_STAGES, "Preparing clean environment")
        rebuild_dirs = workspace.new_build_dirs("rebuilt")
        copy_source(project_dir, rebuild_dirs.source, **copy_options)
        pull_error = _ensure_image(image, timeout) if image and original.succeeded else None

        stage(3, TOTAL_STAGES, "Performing independent rebuild")
        if not original.succeeded:
            warnings.append("The rebuild was skipped because the original build did not succeed.")
        elif mode == "docker":
            assert image is not None
            rebuilt = _build_in_docker(
                adapter, rebuild_dirs, config, image, timeout, pull_error, warnings
            )
        else:
            rebuilt = _build_locally("rebuilt", adapter, rebuild_dirs, config, env, timeout)

        stage(4, TOTAL_STAGES, "Comparing artifacts")
        env_diffs = environment_differences(original.environment, rebuilt.environment) if rebuilt else []
        comparison = compare_artifact_sets(
            original.artifacts,
            rebuilt.artifacts if rebuilt else [],
            policy=config.comparison.policy,
            environment_differences=env_diffs,
        )
        if keep_artifacts_dir is not None:
            copy_artifacts(original.artifacts, keep_artifacts_dir / "original")
            if rebuilt:
                copy_artifacts(rebuilt.artifacts, keep_artifacts_dir / "rebuilt")

    verdict, reasons = determine_verdict(comparison, original, rebuilt, builds_expected=True)
    if verdict is Verdict.REPRODUCIBLE and not isolation.independent_environment:
        reasons.append(
            "Both builds ran on this host, so this does not demonstrate reproducibility across "
            "independent environments."
        )
    return VerificationResult(
        command="verify",
        tool_version=__version__,
        verdict=verdict,
        verdict_reasons=reasons,
        policy=config.comparison.policy,
        started_at=started_at,
        finished_at=_now(),
        duration_seconds=round(time.monotonic() - began, 3),
        comparison=comparison,
        isolation=isolation,
        project=project,
        original_build=original,
        rebuilt_build=rebuilt,
        environment_differences=env_diffs,
        warnings=warnings,
    )


def compare_directories(
    dir_a: Path, dir_b: Path, config: Config, patterns: Sequence[str] | None = None
) -> VerificationResult:
    """Compare artifacts that already exist on disk. No builds are run."""
    started_at, began = _now(), time.monotonic()
    patterns = patterns or config.artifacts.patterns
    first = discover_artifacts(dir_a, patterns)
    second = discover_artifacts(dir_b, patterns)
    comparison = compare_artifact_sets(first, second, policy=config.comparison.policy)
    verdict, reasons = determine_verdict(comparison)
    return VerificationResult(
        command="compare",
        tool_version=__version__,
        verdict=verdict,
        verdict_reasons=reasons,
        policy=config.comparison.policy,
        started_at=started_at,
        finished_at=_now(),
        duration_seconds=round(time.monotonic() - began, 3),
        comparison=comparison,
        warnings=[
            "GhostBuild did not run these builds. It cannot tell how, where or with which "
            "tools the artifacts were produced; the result only says whether the files match."
        ],
    )
