# JSON result format

`result.json` is written by `ghostbuild verify` (and by `compare --output`). The
structure below is stable within a `schema_version`; fields are only added, renamed or
removed with a version bump. `ghostbuild report` refuses results with an unknown version.

Current `schema_version`: `"1"`.

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | string | Always the first key. |
| `command` | string | `"verify"` or `"compare"`. |
| `tool_version` | string | GhostBuild version. |
| `verdict` | string | `"reproducible"`, `"non-reproducible"` or `"inconclusive"`. |
| `verdict_reasons` | string[] | Human-readable reasons. |
| `policy` | string | Comparison policy; currently `"exact"`. |
| `started_at`, `finished_at` | string | ISO 8601 timestamps. |
| `duration_seconds` | number | |
| `isolation` | object or null | `mode` (`docker`/`local`), `independent_environment` (bool), `description`, `image`. Null for `compare`. |
| `project` | object or null | `name`, `version`, `language`, `build_system`, `build_backend`, `config_files`, `build_requires`, `dependencies`, ... Null for `compare`. |
| `original_build`, `rebuilt_build` | object or null | `command`, `started_at`, `duration_seconds`, `returncode`, `timed_out`, `succeeded`, `failure_reason`, `stdout`, `stderr`, `environment`, `artifacts`. |
| `environment_differences` | string[] | Facts about differing environments, not causes. |
| `warnings` | string[] | |
| `comparison.summary` | object | `total`, `matching`, `different`, `missing`, `additional`. |
| `comparison.artifacts[]` | object | See below. |

Artifact entry: `name`, `kind` (`wheel`/`sdist`/`file`), `status`
(`match`/`different`/`missing`/`additional`), `original` and `rebuilt`
(each `{name, kind, size, sha256}` or null), `file_differences[]`,
`metadata_differences[]`, `member_order_differs`, `members_compared`,
`members_identical`, `hypotheses` (unconfirmed explanations, never stated as fact) and `notes`.

Build environment records store variable **names** only. Values are never written, and
secret-looking values are redacted from logs. Temporary filesystem paths are not serialised.
