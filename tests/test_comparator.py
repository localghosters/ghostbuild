from __future__ import annotations

import pytest

from conftest import WHEEL_FILES, artifact, make_targz, make_zip
from ghostbuild.engine.comparator import compare_artifact_sets, determine_verdict
from ghostbuild.errors import ConfigError
from ghostbuild.models import ArtifactInfo, ArtifactStatus, BuildRecord, EnvironmentInfo, Verdict


def one(tmp_path, name, left, right, **kwargs):
    """Compare a single pair of wheels built from ``left`` / ``right`` file maps."""
    (tmp_path / "a").mkdir(parents=True, exist_ok=True)
    (tmp_path / "b").mkdir(parents=True, exist_ok=True)
    date_a = kwargs.pop("date_a", (2020, 1, 1, 0, 0, 0))
    date_b = kwargs.pop("date_b", (2020, 1, 1, 0, 0, 0))
    a = artifact(make_zip(tmp_path / "a" / name, left, date_a))
    b = artifact(make_zip(tmp_path / "b" / name, right, date_b))
    return compare_artifact_sets([a], [b], **kwargs)


def test_matching_artifacts_are_not_deeply_inspected(tmp_path):
    result = one(tmp_path, "p.whl", WHEEL_FILES, WHEEL_FILES)
    art = result.artifacts[0]
    assert art.status is ArtifactStatus.MATCH
    assert art.file_differences == [] and art.hypotheses == []
    assert (result.summary.matching, result.summary.different) == (1, 0)


def test_missing_and_additional_artifacts(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = [artifact(make_zip(tmp_path / "a" / "only-orig.whl", {"x": "1"})),
         artifact(make_zip(tmp_path / "a" / "both.whl", {"x": "1"}))]  # fmt: skip
    b = [artifact(make_zip(tmp_path / "b" / "both.whl", {"x": "1"})),
         artifact(make_zip(tmp_path / "b" / "only-new.whl", {"x": "2"}))]  # fmt: skip
    result = compare_artifact_sets(a, b)
    statuses = {c.name: c.status for c in result.artifacts}
    assert statuses == {"both.whl": ArtifactStatus.MATCH, "only-new.whl": ArtifactStatus.ADDITIONAL,
                        "only-orig.whl": ArtifactStatus.MISSING}  # fmt: skip
    assert (result.summary.missing, result.summary.additional, result.summary.total) == (1, 1, 3)


def test_content_difference_is_attributed_to_the_member_with_a_diff(tmp_path):
    changed = {**WHEEL_FILES, "pkg/__init__.py": "VALUE = 2\n"}
    art = one(tmp_path, "p.whl", WHEEL_FILES, changed).artifacts[0]
    assert art.status is ArtifactStatus.DIFFERENT
    assert [d.path for d in art.file_differences] == ["pkg/__init__.py"]
    diff = art.file_differences[0]
    assert diff.change == "content" and diff.original_sha256 != diff.rebuilt_sha256
    assert "-VALUE = 1" in diff.diff_excerpt and "+VALUE = 2" in diff.diff_excerpt
    assert art.original.sha256 != art.rebuilt.sha256
    assert art.members_compared == 4 and art.members_identical == 3


def test_timestamp_only_difference_is_reported_as_different_not_matching(tmp_path):
    result = one(tmp_path, "p.whl", WHEEL_FILES, WHEEL_FILES, date_b=(2021, 5, 5, 5, 5, 4))
    art = result.artifacts[0]
    assert art.status is ArtifactStatus.DIFFERENT  # never a match: policy is exact
    assert {d.change for d in art.file_differences} == {"metadata"}
    assert all(d.metadata_changes == ["timestamp"] for d in art.file_differences)
    assert any("timestamps differ" in h for h in art.hypotheses)
    assert result.summary.matching == 0


def test_wheel_metadata_differences_and_generator_hypothesis(tmp_path):
    changed = dict(WHEEL_FILES)
    changed["pkg-1.0.dist-info/WHEEL"] = WHEEL_FILES["pkg-1.0.dist-info/WHEEL"].replace("70.0", "75.1")
    changed["pkg-1.0.dist-info/METADATA"] = WHEEL_FILES["pkg-1.0.dist-info/METADATA"].replace(">=2", ">=3")
    art = one(tmp_path, "p.whl", WHEEL_FILES, changed).artifacts[0]
    found = {(m.source, m.field): (m.original, m.rebuilt) for m in art.metadata_differences}
    assert found[("WHEEL", "Generator")] == ("setuptools (70.0)", "setuptools (75.1)")
    assert found[("METADATA", "Requires-Dist")] == ("requests>=2", "requests>=3")
    assert any("Generator" in h for h in art.hypotheses)
    assert any("dependency" in h.lower() for h in art.hypotheses)


def test_one_sided_members_and_order_differences(tmp_path):
    reordered = dict(reversed(list(WHEEL_FILES.items())))
    art = one(tmp_path, "p.whl", WHEEL_FILES, reordered).artifacts[0]
    assert art.status is ArtifactStatus.DIFFERENT and art.member_order_differs
    assert any("order" in h for h in art.hypotheses)

    extra = {**WHEEL_FILES, "pkg/generated.py": "x = 1\n"}
    art = one(tmp_path / "x", "p.whl", WHEEL_FILES, extra).artifacts[0]
    assert [(d.path, d.change) for d in art.file_differences] == [("pkg/generated.py", "only-in-rebuilt")]


def test_hypotheses_are_hedged_and_never_certain(tmp_path):
    changed = {**WHEEL_FILES, "pkg/__init__.py": "VALUE = 2\n"}
    art = one(tmp_path, "p.whl", WHEEL_FILES, changed,
              environment_differences=["Python version: 3.12 vs 3.13"]).artifacts[0]  # fmt: skip
    assert art.hypotheses
    for text in art.hypotheses:
        assert not any(w in text.lower() for w in ("caused by", "the cause is", "proves"))
    assert any("different environments" in h and "not confirmed" in h for h in art.hypotheses)


def test_sdist_gzip_header_and_member_timestamps(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    files = {"p-1.0/PKG-INFO": "Name: p\nVersion: 1.0\n", "p-1.0/p.py": "x = 1\n"}
    a = artifact(make_targz(tmp_path / "a" / "p-1.0.tar.gz", files, gzip_mtime=1_700_000_000))
    b = artifact(make_targz(tmp_path / "b" / "p-1.0.tar.gz", files, gzip_mtime=1_700_000_500))
    art = compare_artifact_sets([a], [b]).artifacts[0]
    assert art.status is ArtifactStatus.DIFFERENT
    assert art.file_differences == []  # members are identical
    assert [m.field for m in art.metadata_differences] == ["gzip header mtime"]
    assert any("gzip header" in h for h in art.hypotheses)

    c = artifact(make_targz(tmp_path / "b" / "p-1.0.tar.gz", files, gzip_mtime=1_700_000_000, mtime=1_600_000_099))
    art = compare_artifact_sets([a], [c]).artifacts[0]
    assert {d.change for d in art.file_differences} == {"metadata"}


def test_pkg_info_differences_in_sdist(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = artifact(make_targz(tmp_path / "a" / "p.tar.gz", {"p-1.0/PKG-INFO": "Name: p\nVersion: 1.0\n"}))
    b = artifact(make_targz(tmp_path / "b" / "p.tar.gz", {"p-1.0/PKG-INFO": "Name: p\nVersion: 1.1\n"}))
    art = compare_artifact_sets([a], [b]).artifacts[0]
    assert [(m.source, m.field, m.original, m.rebuilt) for m in art.metadata_differences] == [
        ("PKG-INFO", "Version", "1.0", "1.1")
    ]


def test_corrupt_archive_records_a_note_and_still_reports_difference(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "p.whl").write_bytes(b"not a zip at all")
    (tmp_path / "b" / "p.whl").write_bytes(b"different junk")
    a, b = artifact(tmp_path / "a" / "p.whl"), artifact(tmp_path / "b" / "p.whl")
    art = compare_artifact_sets([a], [b]).artifacts[0]
    assert art.status is ArtifactStatus.DIFFERENT
    assert any("Deep inspection failed" in n for n in art.notes)
    assert art.file_differences == []


def test_hash_only_mode_skips_inspection(tmp_path):
    changed = {**WHEEL_FILES, "pkg/__init__.py": "VALUE = 2\n"}
    art = one(tmp_path, "p.whl", WHEEL_FILES, changed, inspect=False).artifacts[0]
    assert art.status is ArtifactStatus.DIFFERENT and art.file_differences == []


def test_unknown_policy_is_rejected():
    with pytest.raises(ConfigError):
        compare_artifact_sets([], [], policy="normalized")


# ------------------------------------------------------------------ verdicts


def build(succeeded=True, reason=None, label="original"):
    return BuildRecord(label, "local", ["x"], "t", 1.0, 0 if succeeded else 1, False, succeeded,
                       reason, "", "", EnvironmentInfo("host"))  # fmt: skip


def art(name, sha):
    return ArtifactInfo(name, "wheel", 1, sha)


def test_verdict_reproducible_requires_all_artifacts_to_match_exactly():
    result = compare_artifact_sets([art("a.whl", "1")], [art("a.whl", "1")])
    verdict, reasons = determine_verdict(result, build(), build(label="rebuilt"), builds_expected=True)
    assert verdict is Verdict.REPRODUCIBLE and "identical SHA-256" in reasons[0]


def test_verdict_non_reproducible_for_difference_missing_or_additional():
    for left, right in (
        ([art("a.whl", "1")], [art("a.whl", "2")]),
        ([art("a.whl", "1"), art("b.tar.gz", "2")], [art("a.whl", "1")]),
        ([art("a.whl", "1")], [art("a.whl", "1"), art("b.tar.gz", "2")]),
    ):
        verdict, _ = determine_verdict(compare_artifact_sets(left, right))
        assert verdict is Verdict.NON_REPRODUCIBLE


def test_successful_builds_alone_never_make_a_build_reproducible():
    verdict, reasons = determine_verdict(
        compare_artifact_sets([], []), build(), build(label="rebuilt"), builds_expected=True
    )
    assert verdict is Verdict.INCONCLUSIVE
    assert any("No artifacts" in r for r in reasons)


def test_verdict_inconclusive_when_a_build_failed_or_rebuild_missing():
    result = compare_artifact_sets([art("a.whl", "1")], [art("a.whl", "1")])
    verdict, reasons = determine_verdict(result, build(False, "exit 1"), None, builds_expected=True)
    assert verdict is Verdict.INCONCLUSIVE
    assert any("original build did not succeed" in r for r in reasons)
    assert any("rebuild was not performed" in r for r in reasons)
    verdict, _ = determine_verdict(result, build(), build(False, "timeout", "rebuilt"), builds_expected=True)
    assert verdict is Verdict.INCONCLUSIVE


def test_one_sided_empty_comparison_is_inconclusive():
    verdict, _ = determine_verdict(compare_artifact_sets([art("a.whl", "1")], []))
    assert verdict is Verdict.INCONCLUSIVE


def _zip_with_mode(path, files, mode):
    """Write a wheel-like zip whose members all carry the given Unix mode."""
    import zipfile

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.external_attr = mode << 16
            archive.writestr(info, content)
    return path


def test_metadata_only_difference_is_observed_but_not_an_exact_match(tmp_path):
    art = one(tmp_path, "p.whl", WHEEL_FILES, WHEEL_FILES, date_b=(2021, 5, 5, 5, 5, 4)).artifacts[0]
    assert art.status is ArtifactStatus.DIFFERENT
    observation = next(h for h in art.hypotheses if h.startswith("Observation"))
    assert "identical content" in observation and "timestamp" in observation
    assert "not an exact match" in observation


def test_content_difference_gets_no_metadata_only_observation(tmp_path):
    changed = {**WHEEL_FILES, "pkg/__init__.py": "VALUE = 2\n"}
    art = one(tmp_path, "p.whl", WHEEL_FILES, changed).artifacts[0]
    assert not any(h.startswith("Observation") for h in art.hypotheses)


def test_one_sided_member_gets_no_metadata_only_observation(tmp_path):
    extra = {**WHEEL_FILES, "pkg/generated.py": "X = 1\n"}
    art = one(tmp_path, "p.whl", WHEEL_FILES, extra).artifacts[0]
    assert not any(h.startswith("Observation") for h in art.hypotheses)


def test_permission_difference_produces_hedged_mode_hypothesis(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = artifact(_zip_with_mode(tmp_path / "a" / "p.whl", WHEEL_FILES, 0o644))
    b = artifact(_zip_with_mode(tmp_path / "b" / "p.whl", WHEEL_FILES, 0o755))
    art = compare_artifact_sets([a], [b]).artifacts[0]
    assert art.status is ArtifactStatus.DIFFERENT
    assert all("mode" in d.metadata_changes for d in art.file_differences)
    mode_hypothesis = next(h for h in art.hypotheses if "permissions" in h)
    assert "may" in mode_hypothesis
    assert not any(w in mode_hypothesis.lower() for w in ("caused by", "the cause is", "proves"))
