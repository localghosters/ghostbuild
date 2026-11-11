# Configuration

GhostBuild works without configuration. To customise it, place a `ghostbuild.toml` in
the project root or pass `--config PATH`. Generate a file containing every default with:

```bash
ghostbuild init            # writes ./ghostbuild.toml
ghostbuild init path.toml --force
```

An annotated copy is also in [`examples/ghostbuild.example.toml`](../examples/ghostbuild.example.toml).
Unknown keys and invalid values are reported as errors rather than ignored.

| Section | Key | Default | Meaning |
| --- | --- | --- | --- |
| `[build]` | `timeout_seconds` | `900` | Per-build timeout. |
| `[build]` | `env_passthrough` | `[]` | Extra environment variable names passed to builds. Values are never reported. Secret-looking names trigger a warning. |
| `[artifacts]` | `patterns` | `["*.whl", "*.tar.gz"]` | Glob patterns for artifacts in each build's output directory. |
| `[comparison]` | `policy` | `"exact"` | Only `exact` is implemented. |
| `[workspace]` | `temp_dir` | `""` | Where temporary workspaces go; empty uses the system temp directory. |
| `[workspace]` | `include_vcs` | `false` | Copy `.git`, `.hg`, `.svn` into workspaces (needed by tools like setuptools-scm). |
| `[workspace]` | `exclude` | `[]` | Extra name patterns left out of workspaces. |
| `[report]` | `output_dir` | `"ghostbuild-results"` | Where reports are written. |
| `[report]` | `format` | `"terminal"` | `terminal`, `json` or `html`. `result.json` is always written by `verify`. |
| `[python]` | `build_command` | `[]` | Override the build command (local isolation only). Placeholders: `{python}`, `{source_dir}`, `{outdir}`. |
| `[python]` | `docker_image` | `""` | Image for the Docker rebuild; empty means `python:<major>.<minor>-slim`. |
| `[python]` | `build_requirement` | `"build"` | Requirement installed in the container to provide the build frontend. |

Command-line options (`--output`, `--format`, `--timeout`) override the file.
