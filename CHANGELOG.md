# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-11-16

### Added
- `--source-date-epoch` option and `[build] source_date_epoch` setting: sets
  `SOURCE_DATE_EPOCH` identically for both builds (local and Docker). Reports disclose
  when it was pinned and what a match then means.
- Docker commands can carry an explicit, validated set of environment variables; the
  host environment is still never forwarded.

### Fixed
- Tests that create symlinks are skipped on systems where symlinks are unavailable
  (for example Windows without privileges) instead of failing.

### Changed
- Documentation no longer carries pre-release wording.

## [0.2.0] - 2026-11-16

### Added
- Markdown report (`--format markdown`, `report.md`) for CI step summaries and pull
  request comments. Names, diffs and messages are escaped so archive contents cannot
  inject Markdown or HTML. Build logs are not included; use HTML or JSON for those.
- `SECURITY.md`, `.editorconfig`, Dependabot configuration, an FAQ, a CI usage guide
  and a roadmap.
- Comparison diagnostics: when every archive member has identical content and only
  metadata differs, the report now says so (and that it is still not an exact match).
- Hedged hypotheses for differing file permissions and file ownership in archives.

### Changed
- Removed hard-coded version numbers from user-facing messages and config comments.

## [0.1.0] - 2026-11-12

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
