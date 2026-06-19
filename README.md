# TokenSquash

TokenSquash is a local-first codec and evidence harness for measuring whether
AI-agent task/reply traffic can be made shorter without losing meaning.

It is built around a simple pipeline:

```text
codec -> corpus -> benchmark -> gate -> certify -> release evidence -> commercial license
```

The point is not to claim magic compression. The point is to make prompt/reply
compression testable, auditable, and honest. If a compact form costs more than
the original, the benchmark should say so plainly.

## What It Is

| TokenSquash is | TokenSquash is not |
|---|---|
| A measurable prompt/reply codec | Magic binary compression |
| A local corpus evaluation workflow | A claim of universal token savings |
| A deterministic core with optional sidecar experiments | A model-dependent translation black box |
| A release evidence generator | A vague benchmark screenshot |

## Two-Minute Demo

Clone the repo, install it locally, and run the public deterministic demo:

```powershell
python -m pip install -e .
python -m tokensquash demo
```

The demo uses only the packaged public sample corpus. It does not require API
keys, a hosted service, or a local model. It reports status, turn count, token
savings, privacy findings, and the command paths needed to reproduce the result.

For the full product manifest:

```powershell
python -m tokensquash about --json
```

For local health and governance checks:

```powershell
python -m tokensquash doctor --strict
```

A typical public demo result should report `pass`, `5` sample turns, no privacy
findings, and a measured saved percent. The exact number depends on the counter;
with the `chars` counter the current packaged sample reports `20.6091%` saved.

## Small Example

Encode a normal coding-agent request:

```powershell
python -m tokensquash encode "Please fix the login bug, keep the diff small, run tests, and summarize the files changed."
```

Example compact form:

```text
ts1 f "login bug" c=sd v=t r=m,f
```

Decode it back:

```powershell
python -m tokensquash decode 'ts1 f "login bug" c=sd v=t r=m,f'
```

TokenSquash also has a matching compact reply format:

```powershell
python -m tokensquash reply encode --summary "fixed login bug" --file src/auth.py --verify "unit tests pass" --command "python -m unittest discover -s tests" --risk none
```

## Why It Matters

Companies and individual developers repeat the same agent workflow language
again and again: fix, test, summarize, keep the diff small, report files, note
risks, propose next steps. TokenSquash lets you measure which repeated language
can be compacted locally, without pretending every prompt should be encoded.

The deterministic `ts1` prompt codec and `tr1` reply codec are inspectable and
do not depend on a model behaving nicely. The optional local-AI sidecar can
propose compact semantic JSON through Ollama, but that output must be checked
with round-trip, review, gate, and certification evidence before it means
anything.

## Safe Claims

TokenSquash can support claims like:

- this corpus saved `x%` under this counter
- these rows passed through because compact form was not shorter
- these warnings or privacy findings blocked the gate
- this release candidate produced these hashes and evidence packs

TokenSquash should not be used to claim:

- universal token savings
- production-scale savings from synthetic data
- sidecar meaning preservation without review evidence
- safety for raw private prompts or replies committed to Git

Raw corpora, real prompts, replies, local model output, private aliases, and
release evidence stay in ignored local storage such as `private-turns/`,
`private-prompts/`, and `private-aliases/`.

The detailed evidence bar is in the [claims policy](docs/claims-policy.md).

## Main Workflows

Most readers only need these:

- [Quickstart](docs/quickstart.md): first commands and expected outputs.
- [Command map](docs/command-map.md): choose the right command for the job.
- [Real turn workflow](docs/real-turn-workflow.md): capture, redact, report,
  gate, certify, and compare private prompt/reply turns.
- [First real corpus guide](docs/first-real-corpus.md): a focused 10-turn
  local measurement pass.
- [Evidence packs](docs/evidence-packs.md): readiness, certification, quality
  budgets, release checks, and verification reports.
- [Claims policy](docs/claims-policy.md): what TokenSquash can say publicly and
  which evidence each claim needs, including `turns claim` and
  `turns claim-pack` output.
- [Release candidate workflow](docs/release-candidate.md): build and verify
  wheel/source-distribution evidence before publishing.

Deeper docs:

- [Release checklist](docs/release-checklist.md): manual release runbook.
- [Release verification](docs/release-verification.md): inspect published
  assets, hashes, attestations, and packaged license evidence.
- [Post-release flow](docs/post-release-flow.md): keep release notes,
  changelog, GitHub Release text, and verification hashes aligned.
- [Sidecar Ollama workflow](docs/sidecar-ollama.md): experimental local-AI
  semantic translation.
- [Sidecar meaning rubric](docs/sidecar-meaning-rubric.md): pass/watch/fail
  criteria for sidecar round trips.
- [Commercial license guide](docs/commercial-license.md): plain-language
  commercial-use boundaries and contact path.
- [Roadmap](ROADMAP.md): public product direction and evidence bar.
- [Changelog](CHANGELOG.md): user-facing change history.

Release notes and planning records:

- [v0.2.1 release notes](docs/release-notes-v0.2.1.md): claim-pack polish,
  release-evidence docs, required assets, and known limits.
- [v0.2.0 release notes](docs/release-notes-v0.2.0.md): scorecard evidence,
  release assets, CI evidence, and known limits.
- [v0.1.1 release notes](docs/release-notes-v0.1.1.md): public-polish patch
  scope and release evidence contract.
- [v0.1.1 plan](docs/v0.1.1-plan.md): next patch-release scope.
- [v0.2.0 plan](docs/v0.2.0-plan.md): real-corpus scorecard and evidence
  milestones.
- [v0.3.0 plan](docs/v0.3.0-plan.md): larger real-corpus trend evidence,
  sidecar meaning review, claim guardrails, and public release verification.

## Current Scope

- deterministic prompt wire format: `ts1`
- deterministic reply wire format: `tr1`
- prompt/reply encode, decode, benchmark, and compare commands
- private turn capture/import with regenerated redacted corpora
- turn scorecards, scorecard evidence packs, scorecard comparisons, scorecard
  history, reports, suggestions, gates, certifications, history, and release
  checks
- optional exact-tokenizer measurements through `tiktoken`
- experimental local-AI sidecar translate/decode/roundtrip/evaluate/review/gate
- product manifest, strict doctor, readiness, release-info, release-candidate,
  release-assets, release-asset verification, scorecard release evidence,
  artifact manifests, and release attestations
- PolyForm Noncommercial License 1.0.0 public terms plus commercial licensing
  contact for TWO HANDS NETWORK LTD

## Release Status

The first source-available release is published as
[TokenSquash v0.1.0](https://github.com/Martin123132/TokenSquash/releases/tag/v0.1.0).
The latest release is
[TokenSquash v0.2.1](https://github.com/Martin123132/TokenSquash/releases/tag/v0.2.1).
The previous release is
[TokenSquash v0.2.0](https://github.com/Martin123132/TokenSquash/releases/tag/v0.2.0).
The earlier public-polish release is
[TokenSquash v0.1.1](https://github.com/Martin123132/TokenSquash/releases/tag/v0.1.1).

Releases include a wheel, source distribution, artifact manifest,
release attestation, and release-candidate verifier output. The tracked
[v0.2.1 release notes](docs/release-notes-v0.2.1.md),
[v0.2.0 release notes](docs/release-notes-v0.2.0.md),
[v0.1.1 release notes](docs/release-notes-v0.1.1.md),
[v0.1.0 release notes](docs/release-notes-v0.1.0.md), and
[release verification guide](docs/release-verification.md) record the release
commit, CI runs, asset hashes, packaged license evidence, and release evidence.

PyPI publishing is not configured yet.

## License

TokenSquash is source-available for personal and non-commercial use under the
[PolyForm Noncommercial License 1.0.0](LICENSE).

Commercial use is not included in the public license. A separate written
commercial license from TWO HANDS NETWORK LTD is required before using
TokenSquash in a paid product, hosted service, managed service, enterprise
product, commercial developer tool, commercial AI system, commercial AI
coding/agent product, or commercial AI training/evaluation pipeline.

See [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md) and
[docs/commercial-license.md](docs/commercial-license.md). Commercial enquiries
should go through TWO HANDS NETWORK LTD, contact name Glyn Evans, at
glyn@twohandsnetwork.co.uk.

## Contributing And Security

Use [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, quality gates, privacy
rules, and pull-request expectations.

Use [SECURITY.md](SECURITY.md) for supported versions, responsible vulnerability
reporting, and private-data handling rules.

Use the GitHub issue templates under `.github/ISSUE_TEMPLATE/` for public-safe
bug reports, feature requests, commercial licensing enquiries, and
private-data/security contact requests. Do not put raw private prompts, replies,
corpora, credentials, secrets, or commercially sensitive material in public
issues.
