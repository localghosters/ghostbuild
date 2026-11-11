# GhostBuild

**Build it twice. Know what changed.**

GhostBuild is a local-first command-line tool that independently rebuilds a software
project and compares the resulting artifacts, so you can see whether your build is
reproducible and, if not, which files differ.

> **Status: 0.1.0, early.** Only Python projects are supported. Not yet published on PyPI.

## Why it exists

A build that succeeds is not necessarily a reproducible one. Timestamps, tool versions,
unpinned dependencies and file ordering can all change the bytes of a wheel or sdist
without changing its behaviour. If you can't rebuild an artifact and get the same bytes,
it is hard to confirm that what you published came from the source you reviewed.
GhostBuild automates the "build it again and compare" step and explains differences.

## How it works

1. Inspect the project (reads files only; nothing is executed) and pick an adapter.
2. Show you a plan and ask for consent, because builds run project code.
3. Build the project in a temporary copy (the original build).
4. Build a second, fresh copy in Docker (preferred) or, if you approve, on the same host.
5. Compare artifacts by exact SHA-256 and inspect wheel/sdist members for the cause of any difference.
6. Print a report and write `result.json` (and optionally `report.html`).

Verdicts:

- **reproducible**: every artifact matches exactly under the comparison policy.
- **non-reproducible**: at least one artifact differs, is missing, or is extra.
- **inconclusive**: a build failed or timed out, no artifacts were found, or the comparison could not be completed.

## Features

- Python projects: setuptools, Hatch, Poetry, PDM (and Flit) detected via `pyproject.toml`; legacy `setup.py` projects too.
- Wheel and sdist artifacts, compared by SHA-256.
- For differing archives: per-member differences, timestamp/mode metadata, wheel `WHEEL`/`METADATA` fields, and hypotheses clearly labelled as unconfirmed.
- Docker isolation, with a same-host fallback that needs explicit approval and is labelled in every report.
- Terminal, JSON and self-contained HTML reports.
- Optional `ghostbuild.toml`. No accounts, no API keys, no telemetry.

## Installation

Once published:

```bash
pip install ghostbuild
```

From a checkout today:

```bash
git clone https://github.com/LocalGhosters/ghostbuild.git
cd ghostbuild
pip install .
ghostbuild --version
```

Requires Python 3.10+. Docker is optional but recommended for independent rebuilds.

## Quick start

```bash
ghostbuild scan ./my-project          # inspect only, runs nothing
ghostbuild verify ./my-project        # asks before running the build
ghostbuild verify ./my-project --format html --output ./results
ghostbuild compare ./build-one ./build-two
ghostbuild report ./ghostbuild-results/
```

## Commands

| Command | Purpose |
| --- | --- |
| `ghostbuild` | Banner, version and examples. |
| `ghostbuild scan [DIR]` | Show name, version, build system, config files, build requirements, available tools. Never builds. |
| `ghostbuild verify [DIR]` | Full workflow. Options: `--output`, `--format terminal\|json\|html`, `--keep-artifacts`, `--isolation auto\|docker\|local`, `--yes`, `--timeout`, `--config`, `--verbose`, `--no-color`. |
| `ghostbuild compare A B` | Compare two existing artifact directories. Runs no builds. |
| `ghostbuild report [PATH]` | Display or regenerate a report from a stored `result.json`. |
| `ghostbuild init [PATH]` | Write an example `ghostbuild.toml`. |
| `ghostbuild version` | Print the version. |

Exit codes: `0` reproducible, `1` non-reproducible, `2` usage error, `3` inconclusive,
`4` error, `5` user declined.

## Example output

The shape of a report (values depend on your project):

```
RESULT: NON-REPRODUCIBLE

Artifact                      Original       Rebuilt        Status
pkg-1.0-py3-none-any.whl      9f2c41ab07e1…  3be8d0c5a912…  different

Internal differences:
  pkg-1.0.dist-info/RECORD   metadata (timestamp)
Hypotheses (unconfirmed):
  - Archive member timestamps differ; the build may embed the current time.
```

## Configuration

Everything is optional. See [docs/configuration.md](docs/configuration.md) and
[examples/ghostbuild.example.toml](examples/ghostbuild.example.toml). Generate a file with `ghostbuild init`.

## Supported ecosystems

| Ecosystem | Status |
| --- | --- |
| Python (wheel, sdist) | Implemented |
| Node.js, Cargo, Go, Java | Planned, **not implemented** |

Details: [docs/supported-ecosystems.md](docs/supported-ecosystems.md).

## Isolation and safety

Building runs arbitrary project code (build backends, `setup.py`, hooks). Only verify projects you trust.

- Nothing is built without consent (`--yes` or an interactive confirmation). `scan` and `compare` never build.
- The plan states what runs on the host and what runs in Docker.
- Docker mode mounts the source read-only, drops capabilities and sets `no-new-privileges`.
  The container downloads the build frontend and build requirements.
- If Docker is unavailable, `--isolation auto` stops and asks. A local rebuild uses the same
  interpreter and tools as the original build, so it only shows repeatability on this machine.
  A match is labelled "same-host check only". `--isolation docker` never falls back.
- Your project directory is only read. Builds run in temporary copies. GhostBuild deletes only its own temporary directories.
- No `shell=True`; every subprocess has a timeout; output is captured.
- Builds get an allowlisted environment. Reports record variable names only, and secret-looking values are redacted from logs.
- Archives are never extracted to disk; unsafe member names are rejected.

## Limitations

- Python only.
- Only the `exact` comparison policy exists. There is no normalised comparison.
- Hypotheses are hints from patterns, not proof of cause.
- The Docker rebuild installs build tools from the network, so differing package versions between builds are possible; unpinned build requirements are flagged as a warning.
- Python-version, OS and architecture differences are reported but not controlled.
- Tested on Linux. Windows and macOS are not verified.

**Disclaimer:** reproducibility results depend on the environments and comparison policy used.
A "reproducible" result means these two builds matched, not that every build everywhere will.

## Development

```bash
pip install -e ".[dev]"
pytest
python -m build
```

Tests never run real project builds; subprocesses and Docker are faked. See
[docs/architecture.md](docs/architecture.md).

## Contributing

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). Open areas include new ecosystem adapters, better
diagnostics, other isolation providers and more test scenarios.

## License

MIT. Copyright (c) 2026 LocalGhosters. See [LICENSE](LICENSE).
