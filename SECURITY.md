# Security Policy

TokenSquash handles prompts, replies, redacted corpora, local model requests,
and package release evidence. Security reports are welcome, especially when
they protect private corpora or release integrity.

## Supported Versions

TokenSquash is pre-1.0. Security fixes are developed on `main` and documented
in `CHANGELOG.md`. Until stable releases exist, only the latest `main` branch
and the latest tagged release candidate, if any, are supported.

## Reporting A Vulnerability

Preferred private channel:

- Use GitHub private vulnerability reporting for this repository if the
  "Report a vulnerability" button is available under the repository Security
  tab.

Fallback when private reporting is unavailable:

- Open a public GitHub issue titled `Security contact request`.
- Do not include exploit details, raw prompts, raw replies, credentials,
  private corpus rows, or sensitive logs in the public issue.
- Ask for a private coordination channel and include only a short affected-area
  summary, such as `redaction`, `private-turns storage`, `release artifacts`,
  `CLI path handling`, or `sidecar network call`.

Please include privately, when a safe channel is available:

- affected command or workflow
- version, commit, or release-candidate evidence pack
- operating system and Python version
- minimal reproduction using synthetic data
- impact and whether private data, local files, credentials, or release
  artifacts can be exposed or modified

## Response Targets

These are targets, not guarantees:

- acknowledge within 7 days
- triage and request reproduction details within 14 days
- publish or document a fix plan within 30 days for confirmed issues

If a report is not a vulnerability, it may be moved to a normal issue or closed
with an explanation.

## In Scope

- raw or redacted corpus privacy leaks
- redaction failures that expose private prompts, replies, file paths, secrets,
  or local identifiers
- unsafe filesystem behavior in CLI commands
- release-candidate artifact tampering or verifier bypasses
- package metadata or packaged data integrity failures
- unexpected network calls from deterministic commands
- sidecar calls that ignore configured endpoints, timeouts, or local-only
  expectations

## Out Of Scope

- model output quality issues without a security or privacy impact
- reports that require real private data instead of synthetic reproduction
- denial-of-service reports that rely on extreme local input sizes without a
  practical impact
- vulnerabilities only in third-party dependencies unless TokenSquash exposes
  or worsens the impact
- social engineering or physical access scenarios

## Private Data Rules

Do not send raw private corpora in security reports. Use synthetic data or
redacted snippets. If a real prompt or reply is required to understand impact,
describe the shape of the data first and wait for a private coordination
channel.

Security fixes must preserve the `.gitignore` protections for `private-turns/`,
`private-prompts/`, and `private-aliases/`.
