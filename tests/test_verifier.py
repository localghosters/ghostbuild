"""Workflow tests. External commands are replaced by ``FakeRunner``; no real build runs."""

from __future__ import annotations

import json

import pytest

from conftest import SETUPTOOLS_PYPROJECT, FakeRunner, differing_artifacts, identical_artifacts
from ghostbuild.adapters.python import PythonAdapter
from ghostbuild.config import Config
from ghostbuild.detection import detect_project
from ghostbuild.engine.verifier import compare_directories, verify_project
from ghostbuild.errors import IsolationError, PrerequisiteError
from ghostbuild.models import Verdict
from ghostbuild.reports.json_report import to_json


@pytest.fixture
def setup(tmp_path, make_project, monkeypatch):
    """A project plus a config using a custom (fake) local build command."""
    project_dir = make_project(SETUPTOOLS_PYPROJECT)
    (project_dir / "demo.py").write_text("x = 1\n")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    config = Config()
    config.workspace.temp_dir = str(scratch)
    config.python.build_command = ["{python}", "-m", "fakebuild", "{outdir}"]
    adapter, info = detect_project(project_dir)

    def run(runner, mode="local", **kwargs):
        monkeypatch.setattr("ghostbuild.engine.verifier.run_command", runner)
        return verify_project(project_dir, adapter, info, config, mode=mode, timeout=5, **kwargs)

    return project_dir, scratch, config, run


def test_identical_builds_are_reproducible_but_flagged_as_same_host(setup):
    _, scratch, _, run = setup
    runner = FakeRunner(identical_artifacts)
    result = run(runner)
    assert result.verdict is Verdict.REPRODUCIBLE
    assert result.comparison.summary.matching == 2
    assert result.isolation.mode == "local" and not result.isolation.independent_environment
    assert any("does not demonstrate reproducibility across independent" in r for r in result.verdict_reasons)
    assert any("same host" in w for w in result.warnings)
    assert runner.build_count == 2
    assert list(scratch.iterdir()) == []  # temporary workspace cleaned up


def test_differing_builds_are_non_reproducible_with_diagnostics(setup):
    result = setup[3](FakeRunner(differing_artifacts))
    assert result.verdict is Verdict.NON_REPRODUCIBLE
    wheel = next(a for a in result.comparison.artifacts if a.name.endswith(".whl"))
    assert wheel.original.sha256 != wheel.rebuilt.sha256
    assert any("timestamp" in h for h in wheel.hypotheses)


def test_failed_original_build_is_inconclusive_and_skips_rebuild(setup):
    runner = FakeRunner(identical_artifacts, build_returncodes=(2, 0))
    result = setup[3](runner)
    assert result.verdict is Verdict.INCONCLUSIVE
    assert runner.build_count == 1 and result.rebuilt_build is None
    assert result.original_build.failure_reason.endswith("status 2")
    assert any("skipped" in w for w in result.warnings)


def test_failed_rebuild_is_inconclusive(setup):
    result = setup[3](FakeRunner(identical_artifacts, build_returncodes=(0, 1)))
    assert result.verdict is Verdict.INCONCLUSIVE and not result.rebuilt_build.succeeded


def test_timeout_is_inconclusive_and_recorded(setup):
    result = setup[3](FakeRunner(identical_artifacts, timed_out_builds=(2,)))
    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.rebuilt_build.timed_out and "Timed out" in result.rebuilt_build.failure_reason


def test_two_successful_builds_without_artifacts_are_inconclusive(setup):
    result = setup[3](FakeRunner(None))
    assert result.verdict is Verdict.INCONCLUSIVE
    assert any("No artifacts" in r for r in result.verdict_reasons)


def test_source_project_is_not_modified(setup):
    project_dir, _, _, run = setup
    before = {p: p.read_bytes() for p in project_dir.rglob("*") if p.is_file()}
    run(FakeRunner(identical_artifacts))
    assert {p: p.read_bytes() for p in project_dir.rglob("*") if p.is_file()} == before


def test_builds_run_in_copies_with_sanitised_environment(setup, monkeypatch):
    project_dir, _, _, run = setup
    monkeypatch.setenv("MY_API_TOKEN", "supersecretvalue123")
    monkeypatch.setenv("PYTHONPATH", "/should/not/leak")
    runner = FakeRunner(identical_artifacts, stdout="token is supersecretvalue123\n")
    result = run(runner)
    for call in runner.calls:
        assert "MY_API_TOKEN" not in call["env"] and "PYTHONPATH" not in call["env"]
        assert call["cwd"] != project_dir and not str(call["cwd"]).startswith(str(project_dir))
    assert runner.calls[0]["cwd"] != runner.calls[1]["cwd"]
    dumped = to_json(result)
    assert "supersecretvalue123" not in dumped
    assert "[REDACTED]" in result.original_build.stdout
    assert "MY_API_TOKEN" not in json.dumps(result.to_dict()["original_build"]["environment"])


def test_passthrough_variables_are_listed_by_name_only(setup, monkeypatch):
    _, _, config, run = setup
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    config.build.env_passthrough = ["SOURCE_DATE_EPOCH"]
    runner = FakeRunner(identical_artifacts)
    result = run(runner)
    assert runner.calls[0]["env"]["SOURCE_DATE_EPOCH"] == "1700000000"
    assert "SOURCE_DATE_EPOCH" in result.original_build.environment.env_var_names
    assert "1700000000" not in to_json(result)


def test_secret_looking_passthrough_adds_a_warning(setup, monkeypatch):
    _, _, config, run = setup
    monkeypatch.setenv("DEPLOY_TOKEN", "abcdef123456")
    config.build.env_passthrough = ["DEPLOY_TOKEN"]
    result = run(FakeRunner(identical_artifacts))
    assert any("DEPLOY_TOKEN" in w for w in result.warnings)
    assert "abcdef123456" not in to_json(result)


def test_docker_mode_rebuilds_in_container_and_records_its_environment(setup, monkeypatch):
    _, _, config, run = setup
    config.python.build_command = []
    config.python.docker_image = "python:3.12-slim"
    # The original build uses the default `python -m build` command; pretend `build` is installed.
    monkeypatch.setattr(PythonAdapter, "missing_prerequisites", lambda self, cfg: [])
    runner = FakeRunner(identical_artifacts)
    result = run(runner, mode="docker")
    docker_calls = [c["command"] for c in runner.calls if c["command"][0] == "docker"]
    assert docker_calls[0][:3] == ["docker", "image", "inspect"]
    run_call = next(c for c in docker_calls if c[1] == "run")
    assert "python:3.12-slim" in run_call and run_call[-3] == "sh"
    assert result.isolation.mode == "docker" and result.isolation.independent_environment
    rebuilt_env = result.rebuilt_build.environment
    assert (rebuilt_env.runtime, rebuilt_env.image, rebuilt_env.python_version) == ("docker", "python:3.12-slim", "3.12.1")
    assert rebuilt_env.image_id == "sha256:fakeimageid"
    assert any("Python version" in d for d in result.environment_differences)
    assert result.verdict is Verdict.REPRODUCIBLE
    assert not any("same host" in w for w in result.warnings)


def test_docker_image_unavailable_is_inconclusive_not_a_silent_fallback(setup, monkeypatch):
    _, _, config, run = setup
    config.python.build_command = []
    monkeypatch.setattr(PythonAdapter, "missing_prerequisites", lambda self, cfg: [])
    runner = FakeRunner(identical_artifacts, docker_fails=True)
    result = run(runner, mode="docker")
    assert result.verdict is Verdict.INCONCLUSIVE
    assert "Could not obtain Docker image" in result.rebuilt_build.failure_reason
    assert result.rebuilt_build.isolation == "docker"
    assert not any(c["command"][:2] == ["docker", "run"] for c in runner.calls)


def test_custom_build_command_is_refused_with_docker(setup):
    with pytest.raises(IsolationError, match="custom build_command"):
        setup[3](FakeRunner(identical_artifacts), mode="docker")


def test_missing_build_frontend_is_a_clear_error(setup, monkeypatch):
    _, _, config, run = setup
    config.python.build_command = []
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    with pytest.raises(PrerequisiteError, match="pip install build"):
        run(FakeRunner(identical_artifacts))


def test_keep_artifacts_copies_both_builds(setup, tmp_path):
    out = tmp_path / "kept"
    result = setup[3](FakeRunner(differing_artifacts), keep_artifacts_dir=out)
    names = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert names == {f"{side}/{a.name}" for side in ("original", "rebuilt") for a in result.comparison.artifacts}


def test_stage_callback_reports_four_stages(setup):
    stages = []
    setup[3](FakeRunner(identical_artifacts), on_stage=lambda i, n, label: stages.append((i, n, label)))
    assert [(i, n) for i, n, _ in stages] == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_result_dict_has_documented_top_level_keys(setup):
    data = setup[3](FakeRunner(identical_artifacts)).to_dict()
    assert list(data)[0] == "schema_version" and data["schema_version"] == "1"
    assert {"schema_version", "command", "tool_version", "verdict", "verdict_reasons", "policy", "started_at", "finished_at",
            "duration_seconds", "comparison", "isolation", "project", "original_build", "rebuilt_build",
            "environment_differences", "warnings"} == set(data)  # fmt: skip
    assert data["verdict"] == "reproducible"
    assert "path" not in data["original_build"]["artifacts"][0]  # temp paths are never serialised


def test_compare_directories_matches_and_differs(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    identical_artifacts(1, a), identical_artifacts(2, b)
    result = compare_directories(a, b, Config())
    assert result.verdict is Verdict.REPRODUCIBLE and result.command == "compare"
    assert any("did not run these builds" in w for w in result.warnings)
    differing_artifacts(7, b)
    assert compare_directories(a, b, Config()).verdict is Verdict.NON_REPRODUCIBLE


def test_compare_directories_with_nothing_to_compare_is_inconclusive(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    assert compare_directories(a, b, Config()).verdict is Verdict.INCONCLUSIVE
