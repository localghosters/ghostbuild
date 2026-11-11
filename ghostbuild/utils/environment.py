"""Environment inspection, sanitisation and secret redaction.

GhostBuild never records environment variable *values*. Builds run with an
allowlisted environment, and captured logs are scrubbed of values that look
like secrets.
"""

from __future__ import annotations

import os
import platform
import re
import time
from collections.abc import Iterable, Mapping

from ghostbuild.errors import ConfigError
from ghostbuild.models import EnvironmentInfo

# Variables passed to builds by default. Everything else is dropped.
DEFAULT_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH", "HOME", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TZ",
    "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "COMSPEC", "PATHEXT",
    # Needed so build dependencies can be fetched behind a proxy or custom CA.
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
)  # fmt: skip

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_NAME = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE|SESSION|PRIVATE|"
    r"API[_-]?KEY|ACCESS[_-]?KEY|(^|[_-])KEY($|[_-]))",
    re.IGNORECASE,
)
_URL_CREDENTIALS = re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+@")
REDACTED = "[REDACTED]"
_MIN_SECRET_LENGTH = 6


def is_secret_name(name: str) -> bool:
    """Return True if an environment variable name looks like it holds a secret."""
    return bool(_SECRET_NAME.search(name))


def build_env(
    passthrough: Iterable[str] = (), environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Return the sanitised environment for a build subprocess."""
    source = os.environ if environ is None else environ
    names = list(DEFAULT_ENV_ALLOWLIST)
    for name in passthrough:
        if not _ENV_NAME.match(name):
            raise ConfigError(f"Invalid environment variable name in env_passthrough: {name!r}")
        names.append(name)
    return {name: source[name] for name in names if name in source}


def redact_secrets(text: str, environ: Mapping[str, str] | None = None) -> str:
    """Remove secret-looking environment values and URL credentials from ``text``."""
    source = os.environ if environ is None else environ
    for name, value in source.items():
        if is_secret_name(name) and len(value) >= _MIN_SECRET_LENGTH:
            text = text.replace(value, REDACTED)
    return _URL_CREDENTIALS.sub(f"{REDACTED}@", text)


def capture_host_environment(build_tool: str | None, env: Mapping[str, str]) -> EnvironmentInfo:
    """Describe the machine GhostBuild is running on (names of variables only)."""
    return EnvironmentInfo(
        runtime="host",
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        os=platform.platform(),
        architecture=platform.machine(),
        build_tool=build_tool,
        locale=env.get("LC_ALL") or env.get("LANG"),
        timezone=env.get("TZ") or "/".join(time.tzname),
        env_var_names=sorted(env),
    )
