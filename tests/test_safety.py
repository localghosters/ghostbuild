"""Safety checks: archives, subprocesses, secrets, workspaces and isolation decisions."""

from __future__ import annotations

import io
import os
import sys
import tarfile
import time
import zipfile
from pathlib import Path

import pytest

from conftest import make_targz, make_zip
from ghostbuild.config import Config
from ghostbuild.engine.archives import read_archive
from ghostbuild.engine.executor import docker_run_command, run_command
from ghostbuild.engine.isolation import (
    DockerStatus,
    describe_isolation,
    detect_docker,
    resolve_isolation,
)
from ghostbuild.engine.workspace import (
    WORKSPACE_MARKER,
    Workspace,
    copy_source,
    remove_workspace,
)
from ghostbuild.errors import (
    IsolationError,
    LocalFallbackNotApproved,
    UnsafeArchiveError,
    UnsafeDeletionError,
)
from ghostbuild.utils.environment import build_env, is_secret_name, redact_secrets
from ghostbuild.utils.filesystem import is_safe_relative_path

# ------------------------------------------------------------------ path / archive safety


@pytest.mark.parametrize(
    "name",
    ["../evil", "a/../../evil", "/etc/passwd", "C:\\Windows\\x", "c:/x", "..\\evil", "a\\..\\..\\b", "", "a\x00b"],
)
def test_unsafe_member_names_are_rejected(name):
    assert not is_safe_relative_path(name)


@pytest.mark.parametrize("name", ["a.py", "pkg/sub/mod.py", "./x", "pkg-1.0.dist-info/RECORD", "a..b/c"])
def test_ordinary_member_names_are_accepted(name):
    assert is_safe_relative_path(name)


def test_zip_with_path_traversal_is_refused_and_nothing_is_written(tmp_path):
    evil = tmp_path / "evil.whl"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("../../escaped.txt", "pwned")
    before = sorted(p.name for p in tmp_path.rglob("*"))
    with pytest.raises(UnsafeArchiveError, match="unsafe member path"):
        read_archive(evil)
    assert sorted(p.name for p in tmp_path.rglob("*")) == before
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_tar_with_absolute_path_is_refused(tmp_path):
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as archive:
        info = tarfile.TarInfo("/tmp/absolute.txt")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(UnsafeArchiveError):
        read_archive(evil)


def test_tar_symlinks_are_recorded_never_followed(tmp_path):
    path = tmp_path / "links.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("pkg/link")
        info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
        archive.addfile(info)
    manifest = read_archive(path)
    assert [m.name for m in manifest.members] == ["pkg/link"]
    assert manifest.members[0].size == 0
    assert manifest.small_files == {}


def test_member_count_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("ghostbuild.engine.archives.MAX_MEMBERS", 2)
    path = make_zip(tmp_path / "many.whl", {"a": "1", "b": "2", "c": "3"})
    with pytest.raises(Exception, match="more than 2 members"):
        read_archive(path)


def test_total_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("ghostbuild.engine.archives.MAX_TOTAL_BYTES", 10)
    path = make_targz(tmp_path / "big.tar.gz", {"a": "x" * 50})
    with pytest.raises(Exception, match="would expand"):
        read_archive(path)


def test_duplicate_members_are_flagged(tmp_path):
    path = tmp_path / "dup.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.py", "1")
        archive.writestr("a.py", "2")
    assert read_archive(path).duplicates == ["a.py"]


def test_reading_an_archive_does_not_modify_it(tmp_path):
    path = make_zip(tmp_path / "x.whl", {"a": "b"})
    before = path.read_bytes()
    read_archive(path)
    assert path.read_bytes() == before


# ------------------------------------------------------------------ subprocess handling


def test_run_command_rejects_shell_strings():
    with pytest.raises(TypeError):
        run_command("echo hi", cwd=None, env={}, timeout=5)


def test_run_command_never_uses_a_shell(tmp_path):
    # Shell metacharacters are passed to the program literally, not interpreted.
    code = "import sys; print(sys.argv[1])"
    result = run_command([sys.executable, "-c", code, "a; echo injected"], cwd=tmp_path, env=os.environ, timeout=30)
    assert result.succeeded and result.stdout.strip() == "a; echo injected"


def test_timeout_kills_the_process_and_is_reported():
    began = time.monotonic()
    result = run_command(
        [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(60)"],
        cwd=None, env=os.environ, timeout=1,
    )  # fmt: skip
    assert time.monotonic() - began < 20
    assert result.timed_out and not result.succeeded
    assert result.returncode is None and "Timed out" in (result.error or "")
    assert "started" in result.stdout


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
def test_timeout_also_kills_child_processes(tmp_path):
    marker = tmp_path / "child-survived"
    code = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', \"import time; time.sleep(3); open({str(marker)!r}, 'w').close()\"])\n"
        "time.sleep(60)\n"
    )
    result = run_command([sys.executable, "-c", code], cwd=None, env=os.environ, timeout=1)
    assert result.timed_out
    time.sleep(4)
    assert not marker.exists()


def test_missing_executable_is_reported_not_raised():
    result = run_command(["definitely-not-a-real-program-xyz"], cwd=None, env=os.environ, timeout=5)
    assert not result.succeeded and result.returncode is None
    assert "Could not start" in (result.error or "")


def test_failing_command_captures_stdout_and_stderr():
    code = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"
    result = run_command([sys.executable, "-c", code], cwd=None, env=os.environ, timeout=30)
    assert (result.returncode, result.stdout.strip(), result.stderr.strip()) == (3, "out", "err")
    assert not result.succeeded


# ------------------------------------------------------------------ secrets


@pytest.mark.parametrize("name", ["GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "DB_PASSWORD", "API_KEY", "PYPI_API_TOKEN", "KEY", "MY_KEY_ID"])
def test_secret_looking_names(name):
    assert is_secret_name(name)


@pytest.mark.parametrize("name", ["PATH", "HOME", "LANG", "KEYBOARD_LAYOUT", "MONKEY"])
def test_ordinary_names_are_not_secret(name):
    assert not is_secret_name(name)


def test_build_env_is_an_allowlist_and_drops_secrets():
    host = {"PATH": "/bin", "HOME": "/h", "GITHUB_TOKEN": "ghp_secretsecret", "PYTHONPATH": "/x", "CUSTOM": "1"}
    env = build_env(["CUSTOM"], host)
    assert env == {"PATH": "/bin", "HOME": "/h", "CUSTOM": "1"}


def test_build_env_rejects_invalid_passthrough_names():
    from ghostbuild.errors import ConfigError

    with pytest.raises(ConfigError):
        build_env(["NOT VALID"], {})


def test_redaction_removes_secret_values_and_url_credentials():
    environ = {"MY_TOKEN": "s3cr3t-value-123", "PATH": "/usr/bin", "SHORT_SECRET": "ab"}
    text = "token=s3cr3t-value-123 index https://user:hunter2@pypi.example/simple path /usr/bin ab"
    cleaned = redact_secrets(text, environ)
    assert "s3cr3t-value-123" not in cleaned and "hunter2" not in cleaned
    assert "/usr/bin" in cleaned and "pypi.example" in cleaned


# ------------------------------------------------------------------ workspace and deletion


def test_workspace_is_created_and_removed(tmp_path):
    with Workspace(tmp_path) as workspace:
        root = workspace.root
        assert root.parent == tmp_path.resolve() and (root / WORKSPACE_MARKER).is_file()
        dirs = workspace.new_build_dirs("original")
        assert dirs.output.is_dir() and not dirs.source.exists()
    assert not root.exists()
    assert list(tmp_path.iterdir()) == []


def test_workspace_is_removed_even_when_the_body_fails(tmp_path):
    with pytest.raises(RuntimeError):
        with Workspace(tmp_path) as workspace:
            root = workspace.root
            raise RuntimeError("boom")
    assert not root.exists()


def test_refuses_to_delete_directories_it_did_not_create(tmp_path):
    precious = tmp_path / "ghostbuild-precious"
    precious.mkdir()
    (precious / "data.txt").write_text("keep me")
    with pytest.raises(UnsafeDeletionError):
        remove_workspace(precious)  # right prefix, no marker
    other = tmp_path / "documents"
    other.mkdir()
    (other / WORKSPACE_MARKER).write_text("")
    with pytest.raises(UnsafeDeletionError):
        remove_workspace(other)  # marker, wrong prefix
    link = tmp_path / "ghostbuild-link"
    link.symlink_to(precious)
    with pytest.raises(UnsafeDeletionError):
        remove_workspace(link)
    assert (precious / "data.txt").read_text() == "keep me"


def test_copy_source_excludes_generated_output_and_never_touches_the_original(tmp_path):
    project = tmp_path / "proj"
    (project / "src" / "pkg" / "build").mkdir(parents=True)  # a package named "build" must be kept
    (project / "src" / "pkg" / "build" / "x.py").write_text("keep")
    (project / "src" / "pkg" / "__pycache__").mkdir()
    (project / "dist").mkdir()
    (project / "dist" / "old.whl").write_text("stale")
    (project / "build").mkdir()
    (project / ".git").mkdir()
    (project / "results").mkdir()
    (project / "pkg.egg-info").mkdir()
    (project / "pyproject.toml").write_text("x")
    snapshot = sorted(p.relative_to(project).as_posix() for p in project.rglob("*"))
    copy_source(project, tmp_path / "copy", skip_paths=[project / "results"])
    copied = sorted(p.relative_to(tmp_path / "copy").as_posix() for p in (tmp_path / "copy").rglob("*"))
    assert "pyproject.toml" in copied and "src/pkg/build/x.py" in copied
    assert not any(c.startswith(("dist", "build", ".git", "results", "pkg.egg-info")) for c in copied)
    assert not any("__pycache__" in c for c in copied)
    assert sorted(p.relative_to(project).as_posix() for p in project.rglob("*")) == snapshot


def test_copy_source_can_include_vcs_and_does_not_follow_symlinks(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".git").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (project / "link").symlink_to(outside)
    copy_source(project, tmp_path / "copy", include_vcs=True)
    assert (tmp_path / "copy" / ".git").is_dir()
    assert (tmp_path / "copy" / "link").is_symlink()


# ------------------------------------------------------------------ isolation decisions


UP = DockerStatus(True, "27.0")
DOWN = DockerStatus(False, reason="the Docker daemon is not reachable (boom)")


def test_auto_prefers_docker_when_available():
    assert resolve_isolation("auto", UP, local_approved=False) == "docker"


def test_auto_never_silently_falls_back_to_local():
    with pytest.raises(LocalFallbackNotApproved, match="--isolation local"):
        resolve_isolation("auto", DOWN, local_approved=False)


def test_local_fallback_requires_explicit_approval():
    assert resolve_isolation("auto", DOWN, local_approved=True) == "local"
    assert resolve_isolation("local", DOWN, local_approved=False) == "local"


def test_explicit_docker_never_falls_back_even_if_approved():
    with pytest.raises(IsolationError, match="will not fall back"):
        resolve_isolation("docker", DOWN, local_approved=True)
    assert resolve_isolation("docker", UP, local_approved=False) == "docker"


def test_unknown_mode_is_rejected():
    with pytest.raises(IsolationError, match="Unknown isolation"):
        resolve_isolation("sandbox", UP, local_approved=False)


def test_local_description_says_it_is_not_independent():
    info = describe_isolation("local", None)
    assert not info.independent_environment and "NOT an independent" in info.description
    docker = describe_isolation("docker", "python:3.12-slim")
    assert docker.independent_environment and docker.image == "python:3.12-slim"


def test_detect_docker_when_not_installed(monkeypatch):
    monkeypatch.setattr("ghostbuild.engine.isolation.shutil.which", lambda name: None)
    status = detect_docker()
    assert not status.available and "not found" in status.reason


def test_detect_docker_when_daemon_is_down_and_up(monkeypatch):
    from conftest import FakeRunner
    from ghostbuild.engine.executor import CommandResult

    monkeypatch.setattr("ghostbuild.engine.isolation.shutil.which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(
        "ghostbuild.engine.isolation.run_command",
        lambda *a, **k: CommandResult(["docker"], 1, "", "Cannot connect to the Docker daemon\n", "t", 0.0),
    )
    status = detect_docker()
    assert not status.available and "Cannot connect" in status.reason
    monkeypatch.setattr(
        "ghostbuild.engine.isolation.run_command",
        lambda *a, **k: CommandResult(["docker"], 0, "27.1.0\n", "", "t", 0.0),
    )
    assert detect_docker() == DockerStatus(True, version="27.1.0")


def test_docker_command_is_an_argument_list_with_readonly_source(tmp_path):
    command = docker_run_command(
        image="python:3.12-slim", source_dir=tmp_path / "src", output_dir=tmp_path / "out",
        script="echo hi", user="1000:1000",
    )  # fmt: skip
    assert isinstance(command, list) and command[:3] == ["docker", "run", "--rm"]
    assert any(a.endswith("target=/src,readonly") for a in command)
    assert "--cap-drop" in command and "no-new-privileges" in command
    assert command[-3:] == ["sh", "-c", "echo hi"]  # the shell runs inside the container only


def test_docker_command_rejects_commas_in_mount_paths(tmp_path):
    with pytest.raises(IsolationError):
        docker_run_command(image="i", source_dir=tmp_path / "a,b", output_dir=tmp_path, script="x", user=None)


def test_temp_dir_setting_must_exist(tmp_path):
    from ghostbuild.errors import PathError

    with pytest.raises(PathError):
        Workspace(tmp_path / "missing")
    assert Config().workspace.temp_dir is None
