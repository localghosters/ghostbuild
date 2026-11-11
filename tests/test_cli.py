"""CLI behaviour. Skipped when Typer/Rich are not installed. No project build is ever run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.testing import CliRunner  # noqa: E402

from ghostbuild import __version__  # noqa: E402
from ghostbuild import cli  # noqa: E402

from conftest import SETUPTOOLS_PYPROJECT, differing_artifacts, identical_artifacts  # noqa: E402

runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(cli.app, list(args))


def test_version_flag_and_command():
    assert __version__ in invoke("--version").output
    assert __version__ in invoke("version").output


def test_banner_without_arguments():
    result = invoke()
    assert result.exit_code == 0 and "ghostbuild" in result.output.lower()


def test_help_lists_commands():
    output = invoke("--help").output
    for command in ("scan", "verify", "compare", "report", "init"):
        assert command in output


def test_scan_reads_project_without_building(make_project, monkeypatch):
    monkeypatch.setattr(cli, "detect_docker", lambda: cli.DockerStatus(False, reason="test"))
    root = make_project(SETUPTOOLS_PYPROJECT)
    result = invoke("scan", str(root), "--no-color")
    assert result.exit_code == 0, result.output
    assert "demo" in result.output and "setuptools" in result.output


def test_scan_invalid_path(tmp_path):
    result = invoke("scan", str(tmp_path / "missing"))
    assert result.exit_code == cli.EXIT_ERROR


def test_scan_not_a_project(tmp_path):
    result = invoke("scan", str(tmp_path))
    assert result.exit_code == cli.EXIT_ERROR


def test_verify_refuses_without_consent_when_non_interactive(make_project, monkeypatch):
    """Without --yes and without a TTY, no build command may run."""
    root = make_project(SETUPTOOLS_PYPROJECT)
    monkeypatch.setattr(cli, "detect_docker", lambda: cli.DockerStatus(True, version="x"))
    monkeypatch.setattr(cli, "verify_project", lambda *a, **k: pytest.fail("build must not start"))
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    result = invoke("verify", str(root))
    assert result.exit_code == cli.EXIT_ERROR


def test_verify_without_docker_does_not_fall_back_silently(make_project, monkeypatch):
    root = make_project(SETUPTOOLS_PYPROJECT)
    monkeypatch.setattr(cli, "detect_docker", lambda: cli.DockerStatus(False, reason="no docker"))
    monkeypatch.setattr(cli, "verify_project", lambda *a, **k: pytest.fail("build must not start"))
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    result = invoke("verify", str(root), "--yes")
    assert result.exit_code == cli.EXIT_ERROR


def test_verify_rejects_bad_options(make_project):
    root = make_project(SETUPTOOLS_PYPROJECT)
    assert invoke("verify", str(root), "--format", "pdf").exit_code == 2
    assert invoke("verify", str(root), "--isolation", "vm").exit_code == 2


def test_compare_matching_exits_zero(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    identical_artifacts(1, a), identical_artifacts(2, b)
    result = invoke("compare", str(a), str(b), "--no-color")
    assert result.exit_code == cli.EXIT_REPRODUCIBLE, result.output


def test_compare_differing_exits_one_and_writes_reports(tmp_path):
    a, b, out = tmp_path / "a", tmp_path / "b", tmp_path / "out"
    a.mkdir(), b.mkdir()
    differing_artifacts(1, a), differing_artifacts(2, b)
    result = invoke("compare", str(a), str(b), "--output", str(out), "--format", "html", "--no-color")
    assert result.exit_code == cli.EXIT_NON_REPRODUCIBLE
    assert (out / "result.json").is_file() and (out / "report.html").is_file()


def test_compare_json_output_is_parseable(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    identical_artifacts(1, a), identical_artifacts(2, b)
    result = runner.invoke(cli.app, ["compare", str(a), str(b), "--format", "json"])
    assert json.loads(result.stdout)["verdict"] == "reproducible"


def test_compare_empty_directories_is_not_reproducible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    assert invoke("compare", str(a), str(b)).exit_code != cli.EXIT_REPRODUCIBLE


def test_report_regenerates_from_result(tmp_path):
    a, b, out = tmp_path / "a", tmp_path / "b", tmp_path / "out"
    a.mkdir(), b.mkdir()
    differing_artifacts(1, a), differing_artifacts(2, b)
    invoke("compare", str(a), str(b), "--output", str(out))
    shown = invoke("report", str(out), "--no-color")
    assert shown.exit_code == 0 and "NON-REPRODUCIBLE" in shown.output
    assert invoke("report", str(out), "--format", "html").exit_code == 0
    assert (out / "report.html").is_file()


def test_report_missing_result(tmp_path):
    assert invoke("report", str(tmp_path)).exit_code == cli.EXIT_ERROR


def test_init_writes_config_and_refuses_overwrite(tmp_path):
    target = tmp_path / "ghostbuild.toml"
    assert invoke("init", str(target)).exit_code == 0 and target.is_file()
    assert invoke("init", str(target)).exit_code == cli.EXIT_ERROR
    assert invoke("init", str(target), "--force").exit_code == 0
