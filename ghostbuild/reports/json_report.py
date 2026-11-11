"""JSON reports. The structure is documented in ``docs/json-schema.md``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ghostbuild.errors import ReportError
from ghostbuild.models import SCHEMA_VERSION, VerificationResult

RESULT_FILENAME = "result.json"
_REQUIRED_KEYS = ("schema_version", "command", "verdict", "verdict_reasons", "comparison")


def to_json(result: VerificationResult | dict[str, Any]) -> str:
    """Serialise a result to indented JSON."""
    data = result.to_dict() if isinstance(result, VerificationResult) else result
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write_json(result: VerificationResult, directory: Path) -> Path:
    """Write ``result.json`` into ``directory`` and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / RESULT_FILENAME
    path.write_text(to_json(result), encoding="utf-8")
    return path


def load_result(path: Path) -> dict[str, Any]:
    """Load a stored result from a ``result.json`` file or a directory containing one."""
    file_path = path / RESULT_FILENAME if path.is_dir() else path
    if not file_path.is_file():
        raise ReportError(f"No {RESULT_FILENAME} found at {path}.")
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"Cannot read {file_path}: {exc}") from exc
    if not isinstance(data, dict) or any(key not in data for key in _REQUIRED_KEYS):
        raise ReportError(f"{file_path} is not a GhostBuild result (missing required fields).")
    if data["schema_version"] != SCHEMA_VERSION:
        raise ReportError(
            f"{file_path} uses result schema {data['schema_version']!r}; this version of "
            f"GhostBuild understands schema {SCHEMA_VERSION!r}."
        )
    return data
