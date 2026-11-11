from __future__ import annotations

from pathlib import Path

import pytest

from ghostbuild.config import (
    CONFIG_FILENAME,
    EXAMPLE_CONFIG,
    Config,
    load_config,
    load_toml,
    parse_config,
)
from ghostbuild.errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / CONFIG_FILENAME
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_when_no_file(tmp_path):
    config = load_config(None, tmp_path)
    assert config.source is None
    assert config.comparison.policy == "exact"
    assert config.artifacts.patterns == ["*.whl", "*.tar.gz"]
    assert config.build.timeout_seconds == 900


def test_project_config_file_is_discovered_and_applied(tmp_path):
    write(tmp_path, '[build]\ntimeout_seconds = 30\n[artifacts]\npatterns = ["*.whl"]\n')
    config = load_config(None, tmp_path)
    assert config.build.timeout_seconds == 30
    assert config.artifacts.patterns == ["*.whl"]
    assert config.source == tmp_path / CONFIG_FILENAME


def test_explicit_missing_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.toml")


def test_example_config_parses_to_defaults_and_matches_shipped_file():
    config = parse_config(load_toml(REPO_ROOT / "examples" / "ghostbuild.example.toml"))
    assert (REPO_ROOT / "examples" / "ghostbuild.example.toml").read_text() == EXAMPLE_CONFIG
    default = Config()
    for section in ("build", "artifacts", "comparison", "workspace", "report", "python"):
        assert getattr(config, section) == getattr(default, section)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[nonsense]\nx = 1\n", "Unknown section"),
        ("[build]\ntimeuot_seconds = 5\n", "Unknown setting 'timeuot_seconds'"),
        ('[build]\ntimeout_seconds = "soon"\n', "must be an integer"),
        ("[build]\ntimeout_seconds = true\n", "must be an integer"),
        ("[build]\ntimeout_seconds = 0\n", "between 1 and 86400"),
        ('[build]\nenv_passthrough = ["BAD-NAME"]\n', "invalid variable name"),
        ("[artifacts]\npatterns = []\n", "must not be empty"),
        ('[artifacts]\npatterns = ["../*.whl"]\n', "must not contain"),
        ('[artifacts]\npatterns = ["/etc/*"]\n', "must be relative"),
        ('[comparison]\npolicy = "normalized"\n', "not supported"),
        ('[report]\nformat = "pdf"\n', "must be one of"),
        ('[python]\nbuild_command = ["python", ""]\n', "empty strings"),
        ("build = 3\n", "must be a table"),
    ],
)
def test_invalid_configuration_is_rejected_clearly(text, message):
    import tomllib

    with pytest.raises(ConfigError, match=message):
        parse_config(tomllib.loads(text))


def test_malformed_toml(tmp_path):
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(write(tmp_path, "[build\n"))


def test_empty_string_means_unset_for_optional_settings(tmp_path):
    config = load_config(write(tmp_path, '[workspace]\ntemp_dir = ""\n[python]\ndocker_image = ""\n'))
    assert config.workspace.temp_dir is None and config.python.docker_image is None
