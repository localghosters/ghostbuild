"""Report rendering. All renderers consume the dictionary from ``VerificationResult.to_dict()``."""

from __future__ import annotations

from typing import Any

_LABELS = {
    "reproducible": "REPRODUCIBLE",
    "non-reproducible": "NON-REPRODUCIBLE",
    "inconclusive": "INCONCLUSIVE",
}


def verdict_label(data: dict[str, Any]) -> str:
    """Return the headline verdict text.

    A reproducible verdict from a same-host rebuild is always qualified, so it
    cannot be mistaken for an independent-environment result.
    """
    label = _LABELS.get(data["verdict"], str(data["verdict"]).upper())
    isolation = data.get("isolation")
    if data["verdict"] == "reproducible" and isolation and not isolation["independent_environment"]:
        label += " (same-host check only)"
    return label


def short_hash(digest: str | None, length: int = 12) -> str:
    """Abbreviate a SHA-256 digest for tables; full digests stay in the JSON and detail views."""
    return "-" if not digest else f"{digest[:length]}…"
