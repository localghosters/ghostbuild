# Contributing to GhostBuild

Thanks for helping. GhostBuild is small on purpose: it should be reliable where it
claims to work and honest about where it does not. Contributions that make it more
correct, clearer or safer are as welcome as new features.

Please read the [Code of Conduct](CODE_OF_CONDUCT.md) first.

## Development setup

```bash
git clone https://github.com/LocalGhosters/ghostbuild.git
cd ghostbuild
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

Python 3.10 or newer is required. Docker is optional: the test suite never needs it
and never runs a real project build.

## Ground rules

- **Tests never run real builds.** Use `FakeRunner` in `tests/conftest.py` to stand in
  for subprocesses and Docker, and build archive fixtures with `make_zip` / `make_targz`.
- **Never weaken a safety property** (consent before building, no silent isolation
  downgrade, no `shell=True`, safe archive handling, secret redaction). If a change
  touches these, add a test in `tests/test_safety.py`.
- **Never present a weaker result as a stronger one.** A same-host rebuild is not an
  independent one; a normalised match is not an exact match.
- **No fake functionality.** Do not add placeholder features. Planned work belongs in
  an issue or in `docs/supported-ecosystems.md`, labelled as planned.
- **Keep the JSON schema stable.** Changing result fields means bumping
  `SCHEMA_VERSION` and updating `docs/json-schema.md`.
- Use type hints and short docstrings. Keep modules focused.
- No telemetry and no network requests from GhostBuild itself.

## Where to start

Architecture is described in [docs/architecture.md](docs/architecture.md). Areas open
for contribution (none of these exist yet unless stated otherwise):

| Area | Notes |
| --- | --- |
| Ecosystem adapters | Node.js, Cargo, Go, Java. Implement `BuildAdapter` ([docs](docs/supported-ecosystems.md)). |
| Comparison | Additional archive formats; normalised policies that are always labelled as not exact. |
| Diagnostics | Better, evidence-based explanations of why artifacts differ. |
| Isolation | Other isolation providers (for example Podman). |
| Cross-platform | Windows and macOS testing and fixes. |
| Reports | Additional output formats. |
| Tests | Edge cases: unusual archives, odd project layouts, failing builds. |
| Docs | Corrections, examples, translations. |

Issues are labelled `good first issue`, `help wanted`, `enhancement`, `bug`,
`documentation` and `research`.

## Pull requests

1. Open or comment on an issue first for anything larger than a small fix.
2. Create a branch, make focused changes, add or update tests.
3. Run `pytest` and make sure it passes.
4. Update `CHANGELOG.md` and the docs when behaviour changes.
5. Fill in the pull request template.

## Reporting security problems

Because GhostBuild runs project build code, issues in isolation, archive handling or
secret redaction matter. Please report them privately using GitHub's private
vulnerability reporting rather than a public issue.
