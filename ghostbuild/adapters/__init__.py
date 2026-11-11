"""Registry of ecosystem adapters.

To add an ecosystem, implement ``BuildAdapter`` and append an instance here.
"""

from __future__ import annotations

from ghostbuild.adapters.base import BuildAdapter
from ghostbuild.adapters.python import PythonAdapter

ADAPTERS: tuple[BuildAdapter, ...] = (PythonAdapter(),)


def get_adapters() -> tuple[BuildAdapter, ...]:
    """Return all registered adapters, in detection order."""
    return ADAPTERS


__all__ = ["ADAPTERS", "BuildAdapter", "PythonAdapter", "get_adapters"]
