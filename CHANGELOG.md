# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

First release. A small, working foundation.

### Added
- `ghostbuild scan`, `verify`, `compare`, `report`, `init` and `version` commands.
- Python adapter: detects `pyproject.toml` and legacy `setup.py` projects using
  setuptools, Hatch, Poetry, PDM or Flit build backends. Builds wheels and sdists with `python -m build`.
- Independent rebuild in Docker, or on the same host when the user explicitly approves it.
  A same-host match is labelled as such in every report.
- Exact SHA-256 artifact comparison, with wheel and sdist member-level diagnostics,
  metadata differences and clearly labelled hypotheses.
- Terminal, JSON (schema version 1) and self-contained HTML reports.
- Optional `ghostbuild.toml` configuration.
- Safety checks: explicit consent before any build, no silent isolation downgrade,
  no `shell=True`, subprocess timeouts, secret redaction, safe archive reading.

### Not included
- Ecosystems other than Python (Node.js, Cargo, Go and Java are planned, not implemented).
- Normalised or metadata-aware comparison policies. Only `exact` exists.
