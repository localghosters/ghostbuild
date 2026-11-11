from __future__ import annotations

import pytest

from conftest import SETUPTOOLS_PYPROJECT
from ghostbuild.adapters import get_adapters
from ghostbuild.adapters.python import PythonAdapter
from ghostbuild.config import Config
from ghostbuild.detection import detect_project
from ghostbuild.errors import ConfigError, PathError, UnsupportedProjectError


def test_detects_setuptools_project(make_project):
    adapter, info = detect_project(make_project(SETUPTOOLS_PYPROJECT))
    assert isinstance(adapter, PythonAdapter)
    assert (info.name, info.version, info.language) == ("demo", "1.2.3", "Python")
    assert info.build_system == "setuptools"
    assert info.build_requires == ["setuptools>=77"]
    assert info.dependencies == ["requests>=2"]
    assert info.requires_python == ">=3.10"
    assert info.config_files == ["pyproject.toml"]


@pytest.mark.parametrize(
    ("backend", "requires", "expected"),
    [
        ("hatchling.build", "hatchling", "hatch"),
        ("poetry.core.masonry.api", "poetry-core", "poetry"),
        ("pdm.backend", "pdm-backend", "pdm"),
        ("flit_core.buildapi", "flit_core", "flit"),
        ("some_custom.backend", "some-custom", "some_custom.backend"),
    ],
)
def test_recognises_build_backends(make_project, backend, requires, expected):
    text = f'[build-system]\nrequires = ["{requires}"]\nbuild-backend = "{backend}"\n[project]\nname = "x"\nversion = "0.1"\n'
    _, info = detect_project(make_project(text))
    assert info.build_system == expected
    assert info.build_backend == backend


def test_poetry_metadata_and_lock_file(make_project):
    text = """\
[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"

[tool.poetry]
name = "poet"
version = "0.4.0"

[tool.poetry.dependencies]
python = "^3.10"
httpx = "^0.27"
"""
    root = make_project(text, **{"poetry.lock": ""})
    _, info = detect_project(root)
    assert (info.name, info.version) == ("poet", "0.4.0")
    assert info.dependencies == ["httpx ^0.27"]
    assert info.requires_python == "^3.10"
    assert info.lock_files == ["poetry.lock"]


def test_dynamic_version_is_reported_not_guessed(make_project):
    text = '[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n[project]\nname = "x"\ndynamic = ["version"]\n'
    _, info = detect_project(make_project(text))
    assert info.version == "dynamic"


def test_legacy_setup_py_is_detected_but_not_executed(make_project):
    marker = "executed.txt"
    root = make_project(None, **{"setup.py": f"open({marker!r}, 'w').write('x')\n"})
    adapter, info = detect_project(root)
    assert "setuptools" in info.build_system
    assert info.name is None
    assert not (root / marker).exists()
    assert any("setup.py" in note for note in info.notes)


def test_setup_cfg_metadata(make_project):
    root = make_project(None, **{"setup.cfg": "[metadata]\nname = cfgpkg\nversion = 2.0\n"})
    _, info = detect_project(root)
    assert (info.name, info.version) == ("cfgpkg", "2.0")


def test_pyproject_with_only_tool_config_is_not_a_project(make_project):
    with pytest.raises(UnsupportedProjectError):
        detect_project(make_project("[tool.black]\nline-length = 100\n"))


def test_empty_directory_is_unsupported(tmp_path):
    with pytest.raises(UnsupportedProjectError, match="Supported ecosystems"):
        detect_project(tmp_path)


def test_invalid_toml_gives_clear_error(make_project):
    with pytest.raises(ConfigError, match="not valid TOML"):
        detect_project(make_project("[build-system\n"))


def test_missing_and_non_directory_paths(tmp_path):
    with pytest.raises(PathError, match="does not exist"):
        detect_project(tmp_path / "nope")
    a_file = tmp_path / "file.txt"
    a_file.write_text("x")
    with pytest.raises(PathError, match="not a directory"):
        detect_project(a_file)


def test_adapter_registry_contains_python_only():
    assert [a.id for a in get_adapters()] == ["python"]


def test_unpinned_build_requirements_produce_warning(make_project):
    adapter, info = detect_project(make_project(SETUPTOOLS_PYPROJECT))
    assert any("not pinned" in w for w in adapter.collect_warnings(info))
    info.build_requires = ["setuptools==70.0.0"]
    assert adapter.collect_warnings(info) == []


def test_default_build_command_is_an_argument_list(tmp_path):
    command = PythonAdapter().build_command(tmp_path / "src", tmp_path / "out", Config())
    assert isinstance(command, list) and command[1:3] == ["-m", "build"]
    assert str(tmp_path / "out") in command


def test_container_script_keeps_literal_braces_and_fills_requirement():
    config = Config()
    config.python.build_requirement = "build==1.2.2"
    script = PythonAdapter().container_script(config)
    assert "build==1.2.2" in script and "{requirement}" not in script
    assert 'json.dumps({"python_version"' in script
    config.python.build_requirement = "bad'quote"
    with pytest.raises(ConfigError):
        PythonAdapter().container_script(config)
