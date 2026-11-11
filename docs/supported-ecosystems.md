# Supported ecosystems

## Implemented

### Python (adapter id: `python`)

Detected from `pyproject.toml` (or a legacy `setup.py`). The build backend is read from
`[build-system]` and reported as:

| Backend | Reported as |
| --- | --- |
| `setuptools.build_meta` | setuptools |
| `hatchling.build` | hatch |
| `poetry.core.masonry.api` | poetry |
| `pdm.backend`, `pdm.pep517.api` | pdm |
| `flit_core.buildapi` | flit |

Builds are run with `python -m build --sdist --wheel`, so any PEP 517 backend works in
principle, but only the backends above are specifically recognised. Output artifacts
are wheels (`*.whl`) and source distributions (`*.tar.gz`).

Limits: no lock-file based environment recreation. The adapter warns when build
requirements are not pinned. The Docker rebuild installs the build frontend and build
requirements from the network inside the container.

## Planned, not implemented

Nothing below exists in 0.1.0. They are listed so contributors know the intended direction.

- Node.js
- Rust / Cargo
- Go
- Java

## Adding an adapter

Subclass `BuildAdapter` ([architecture](architecture.md)), register it, add fixture-based
tests that do not run real builds, and document it here.
