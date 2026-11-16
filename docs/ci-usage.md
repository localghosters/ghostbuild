# Using GhostBuild in CI

`ghostbuild verify` can run non-interactively. Pass `--yes` to give consent in advance
(you are agreeing that the project's build code runs), and pick the isolation mode
explicitly so the job never depends on what happens to be installed.

```bash
ghostbuild verify . --yes --isolation docker --format json --output ghostbuild-results
```

Use `--isolation docker` in CI. If Docker is missing the command fails instead of
falling back to a same-host rebuild.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Reproducible |
| 1 | Non-reproducible |
| 2 | Usage error (bad option or value) |
| 3 | Inconclusive |
| 4 | Error (for example invalid path or missing prerequisite) |
| 5 | Declined (consent not given) |

A job that must only pass on a reproducible result can rely on a non-zero exit code.
Treat 3 as "not verified", not as a pass.

## GitHub Actions example

```yaml
jobs:
  reproducibility:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ghostbuild
      - run: ghostbuild verify . --yes --isolation docker --output ghostbuild-results --format html
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: ghostbuild-results
          path: ghostbuild-results/
```

## Job summary

`--format markdown` prints a Markdown report to standard output, so it can be appended to
the GitHub job summary. The report is written to `report.md` as well. It includes the
verdict, an artifact table, differing files and hypotheses, but not build logs.

```bash
ghostbuild verify . --yes --isolation docker --format markdown >> "$GITHUB_STEP_SUMMARY"
```

`result.json` is always written by `verify` and follows [the documented schema](json-schema.md).
