"""JSON and HTML reports (neither needs Rich or Typer)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbuild.config import Config
from ghostbuild.engine.verifier import compare_directories
from ghostbuild.errors import ReportError
from ghostbuild.reports import json_report, short_hash, verdict_label
from ghostbuild.reports.html_report import REPORT_FILENAME, render_html, write_html

from conftest import WHEEL_FILES, identical_artifacts, make_targz, make_zip


@pytest.fixture
def matching(tmp_path: Path):
    a, b = tmp_path / "m-a", tmp_path / "m-b"
    a.mkdir(), b.mkdir()
    identical_artifacts(1, a), identical_artifacts(2, b)
    return compare_directories(a, b, Config())


@pytest.fixture
def differing(tmp_path: Path):
    a, b = tmp_path / "d-a", tmp_path / "d-b"
    a.mkdir(), b.mkdir()
    make_zip(a / "pkg-1.0-py3-none-any.whl", WHEEL_FILES, (2020, 1, 1, 0, 0, 0))
    make_zip(b / "pkg-1.0-py3-none-any.whl", WHEEL_FILES, (2021, 6, 1, 0, 0, 0))
    make_targz(a / "pkg-1.0.tar.gz", {"pkg-1.0/PKG-INFO": "Name: pkg\n"})
    return compare_directories(a, b, Config())


def test_verdict_values(matching, differing):
    assert matching.verdict.value == "reproducible"
    assert differing.verdict.value == "non-reproducible"


def test_json_roundtrip(differing, tmp_path):
    path = json_report.write_json(differing, tmp_path / "out")
    assert path.name == "result.json"
    loaded = json_report.load_result(path.parent)  # directory form
    assert loaded == json_report.load_result(path)  # file form
    assert loaded["verdict"] == "non-reproducible"
    assert loaded["schema_version"] == "1"


def test_json_is_valid_and_has_full_hashes(differing):
    data = json.loads(json_report.to_json(differing))
    different = [a for a in data["comparison"]["artifacts"] if a["status"] == "different"]
    assert different
    for art in different:
        assert len(art["original"]["sha256"]) == 64 and len(art["rebuilt"]["sha256"]) == 64
        assert art["original"]["sha256"] != art["rebuilt"]["sha256"]


def test_missing_artifact_is_reported(differing):
    statuses = {a["status"] for a in differing.to_dict()["comparison"]["artifacts"]}
    assert {"different", "missing"} <= statuses


def test_load_result_rejects_bad_input(tmp_path):
    with pytest.raises(ReportError):
        json_report.load_result(tmp_path)  # no result.json
    bad = tmp_path / "result.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ReportError):
        json_report.load_result(bad)
    bad.write_text('{"unrelated": true}', encoding="utf-8")
    with pytest.raises(ReportError):
        json_report.load_result(bad)


def test_load_result_rejects_unknown_schema(matching, tmp_path):
    data = matching.to_dict()
    data["schema_version"] = "999"
    path = tmp_path / "result.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ReportError, match="schema"):
        json_report.load_result(path)


def test_html_is_self_contained(differing):
    page = render_html(differing.to_dict())
    assert page.startswith("<!doctype html>")
    assert "NON-REPRODUCIBLE" in page
    for forbidden in ("<script", "http://", "https://", "<link", "src="):
        assert forbidden not in page


def test_html_escapes_untrusted_text(matching):
    data = matching.to_dict()
    data["warnings"] = ["<script>alert(1)</script>"]
    page = render_html(data)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_write_html(matching, tmp_path):
    path = write_html(matching.to_dict(), tmp_path / "out")
    assert path.name == REPORT_FILENAME and path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_same_host_reproducible_is_qualified():
    data = {"verdict": "reproducible", "isolation": {"independent_environment": False}}
    assert "same-host" in verdict_label(data)
    data["isolation"]["independent_environment"] = True
    assert verdict_label(data) == "REPRODUCIBLE"


def test_inconclusive_label_is_never_reproducible():
    assert verdict_label({"verdict": "inconclusive"}) == "INCONCLUSIVE"


def test_short_hash():
    assert short_hash(None) == "-"
    assert short_hash("a" * 64, 8) == "aaaaaaaa…"


def test_terminal_report_renders(differing):
    pytest.importorskip("rich")
    from rich.console import Console

    from ghostbuild.reports.terminal import render_result

    console = Console(record=True, width=120, no_color=True)
    render_result(console, differing.to_dict(), verbose=True)
    text = console.export_text()
    assert "RESULT: NON-REPRODUCIBLE" in text
    assert "pkg-1.0-py3-none-any.whl" in text
