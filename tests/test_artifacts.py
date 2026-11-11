from __future__ import annotations

import pytest

from conftest import WHEEL_FILES, make_targz, make_zip
from ghostbuild.engine.artifacts import classify_artifact, copy_artifacts, discover_artifacts
from ghostbuild.errors import PathError
from ghostbuild.utils.hashing import sha256_bytes


def test_classification():
    assert classify_artifact("a-1.0-py3-none-any.whl") == "wheel"
    assert classify_artifact("a-1.0.tar.gz") == "sdist"
    assert classify_artifact("notes.txt") == "file"


def test_discovers_wheel_and_sdist_with_hashes_and_sizes(tmp_path):
    wheel = make_zip(tmp_path / "a-1.0-py3-none-any.whl", WHEEL_FILES)
    sdist = make_targz(tmp_path / "a-1.0.tar.gz", {"a-1.0/PKG-INFO": "x"})
    (tmp_path / "ignored.txt").write_text("nope")
    found = discover_artifacts(tmp_path, ["*.whl", "*.tar.gz"])
    assert [a.name for a in found] == ["a-1.0-py3-none-any.whl", "a-1.0.tar.gz"]
    assert [a.kind for a in found] == ["wheel", "sdist"]
    assert found[0].sha256 == sha256_bytes(wheel.read_bytes())
    assert found[1].size == sdist.stat().st_size


def test_custom_patterns_and_subdirectories(tmp_path):
    (tmp_path / "sub").mkdir()
    make_zip(tmp_path / "sub" / "x.whl", {"a": "b"})
    assert discover_artifacts(tmp_path, ["*.whl"]) == []
    assert [a.name for a in discover_artifacts(tmp_path, ["**/*.whl"])] == ["sub/x.whl"]


def test_symlinks_and_directories_are_ignored(tmp_path):
    real = make_zip(tmp_path / "real.whl", {"a": "b"})
    (tmp_path / "link.whl").symlink_to(real)
    (tmp_path / "dir.whl").mkdir()
    assert [a.name for a in discover_artifacts(tmp_path, ["*.whl"])] == ["real.whl"]


def test_empty_directory_yields_nothing(tmp_path):
    assert discover_artifacts(tmp_path, ["*.whl", "*.tar.gz"]) == []


@pytest.mark.parametrize("pattern", ["../*.whl", "/abs/*.whl"])
def test_unsafe_patterns_are_refused(tmp_path, pattern):
    with pytest.raises(PathError):
        discover_artifacts(tmp_path, [pattern])


def test_copy_artifacts_does_not_modify_originals(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_zip(src / "a.whl", {"a": "b"})
    artifacts = discover_artifacts(src, ["*.whl"])
    before = (src / "a.whl").read_bytes()
    copy_artifacts(artifacts, tmp_path / "kept")
    assert (tmp_path / "kept" / "a.whl").read_bytes() == before == (src / "a.whl").read_bytes()
