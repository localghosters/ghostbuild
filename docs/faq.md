# FAQ

## Does a successful build mean the build is reproducible?

No. Two builds can both succeed and still produce different bytes. GhostBuild reports
**reproducible** only when the compared artifacts match exactly (SHA-256).

## What does "inconclusive" mean?

The comparison could not be completed reliably: a build failed or timed out, no
artifacts were found, or an artifact could not be read. It is not a pass.

## Why does a same-host match carry a qualifier?

A local rebuild uses the same interpreter, tools and machine as the original build, so a
match shows repeatability on this host only. Use Docker for an independent rebuild.
Even then, a match applies to those two builds, not to every environment.

## Does `scan` or `compare` run my build?

No. `scan` only reads files. `compare` only reads two existing artifact directories.
Only `verify` builds, and only after you consent.

## Does GhostBuild change my project?

No. The project directory is only read. Builds run in temporary copies.

## Can I ignore timestamps and still call it reproducible?

Not currently. Only the exact policy exists. If a normalised policy is added later, its
results will be reported separately and never presented as an exact match.

## Which projects are supported?

Python projects with a `pyproject.toml` or `setup.py`. See
[supported-ecosystems.md](supported-ecosystems.md).

## Does GhostBuild send any data anywhere?

No. There is no telemetry and no account. The Docker rebuild downloads build tools
inside the container, which is network access made by pip, not by GhostBuild.

## What does `--source-date-epoch` do, and does it make my build reproducible?

It sets `SOURCE_DATE_EPOCH` to the same value for both builds (also inside Docker). Many
build tools use it instead of the current time when writing timestamps. GhostBuild never
turns it on by itself, and any result obtained with it says so, because a match then shows
the project reproduces with timestamps pinned, not that it does without.

It only helps if the build tool honours it. In a test with the sample project and
setuptools 84.0.0, pinning it made the wheels match exactly, but the sdist still differed
(gzip header and member timestamps). The report listed those exact differences. Results
depend on the tool and its version.

## Why do my wheels differ?

Check the "Internal differences" and hypotheses in the report. Common causes are
timestamps in the archive, unpinned build requirements and differing tool versions.
These are hints, not confirmed causes.
