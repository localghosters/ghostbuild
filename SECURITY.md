# Security Policy

## Supported versions

Only the latest released version of GhostBuild receives security fixes.

## What matters here

GhostBuild runs project build code on request, so these areas are security-sensitive:

- Isolation: running a build on the host without the user's consent, or silently
  falling back from Docker to a local build.
- Archive handling: path traversal or resource exhaustion when reading artifacts.
- Secret handling: environment variable values appearing in logs or reports.
- Subprocess execution: any use of a shell or unsanitised command construction.

Note that building a malicious project locally executes that project's code by design.
That alone is not a vulnerability; the consent prompt and documentation say so.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting
("Security" tab, then "Report a vulnerability") on this repository.

Include the GhostBuild version, your OS and Python version, and steps to reproduce.
We will acknowledge the report as soon as we can and keep you updated on the fix.
