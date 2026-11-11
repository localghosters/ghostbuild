# Architecture

GhostBuild is a small pipeline. Each stage lives in its own module and passes plain
data (dataclasses in `ghostbuild/models.py`) to the next.

```
cli.py ──► detection.py ──► adapters/ (inspect, build command)
   │
   └────► engine/verifier.py
              ├─ engine/workspace.py   temporary copies of the source (never the original)
              ├─ engine/isolation.py   Docker detection and the isolation decision
              ├─ engine/executor.py    subprocess runner: no shell, timeout, captured output
              ├─ engine/artifacts.py   artifact discovery by glob, SHA-256
              ├─ engine/archives.py    safe reading of wheel / sdist members
              └─ engine/comparator.py  exact comparison, diagnostics, verdict
                         │
                         ▼
              VerificationResult ──► reports/ (terminal, json_report, html_report)
```

## Verification workflow

1. **Inspect.** `detection.detect_project` asks each registered adapter whether it
   recognises the directory. Inspection only reads files and never runs project code.
2. **Consent.** The CLI shows a plan (what runs where) and requires approval.
3. **Original build.** The source is copied to a temporary workspace and built there
   with the adapter's command. The original project directory is only read.
4. **Independent rebuild.** A second fresh copy is built either in Docker
   (source mounted read-only, capabilities dropped) or, only with explicit approval,
   on the same host. Nothing from the first build is reused.
5. **Compare.** Artifacts are matched by file name. The verdict is based only on
   exact SHA-256 equality. Everything else (member diffs, metadata, hypotheses) is
   diagnostic.
6. **Report.** `result.json` is always written; HTML and terminal output are rendered
   from the same dictionary.

## Verdict rules

- `reproducible`: at least one artifact was compared and every artifact matches exactly.
- `non-reproducible`: at least one artifact differs, is missing, or was added.
- `inconclusive`: a build failed or timed out, no artifacts were found, or the comparison
  could not be completed.

A same-host rebuild that matches is still reported as reproducible only with a
"same-host check only" qualifier, because it shares the interpreter and tools with
the original build.

## Extension point: build adapters

An adapter implements `ghostbuild.adapters.base.BuildAdapter`:

| Method | Purpose |
| --- | --- |
| `detect` | Is this directory a project this adapter handles? Must not run project code. |
| `inspect` | Return `ProjectInfo` from files only. |
| `available_tools` | Report build tools on the host. |
| `missing_prerequisites` | Problems that would block a local build. |
| `build_command` | Argument list (never a shell string) for a local build. |
| `container_image`, `container_script` | How to build inside Docker. |
| `collect_warnings` | Reproducibility risks visible from metadata. |

Register a new adapter in `ghostbuild/adapters/__init__.py`. The engine does not
need to change. Artifact discovery uses the configured glob patterns and
`engine/archives.py` currently understands zip (wheel) and tar.gz (sdist) archives.

## Safety design

- `executor.run_command` takes an argument list, never uses a shell, enforces a timeout
  and kills timed-out processes.
- Builds run with an allowlisted environment (`utils/environment.py`). Values of
  variables whose names look secret are redacted from all logs and reports, and
  only variable *names* are recorded.
- `engine/archives.py` never extracts archives to disk; members are streamed and hashed
  with member-count and size limits, and unsafe names (absolute paths, `..`, duplicates)
  are rejected or flagged.
- Temporary workspaces are created with `tempfile` and only GhostBuild's own
  directories are removed. User files are never deleted.
- `--keep-artifacts` refuses to write into a non-empty destination.

## Contribution points

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the list of open areas.
