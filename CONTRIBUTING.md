# Contributing To TokenSquash

Thanks for helping make TokenSquash more measurable, safer, and more useful.
This project is benchmark-first: a change is better when it preserves meaning,
has evidence, and keeps private data private.

## Project Principles

- Keep the deterministic codec as the source of truth.
- Treat the local-AI sidecar as experimental unless release evidence proves
  otherwise.
- Prefer measurable improvements over clever compression tricks.
- Never commit raw private prompts, replies, corpora, API keys, model outputs
  that expose private data, or local release evidence from `private-turns/`.
- Keep dependencies small. New runtime dependencies need a clear reason and
  should be optional when they support only experimental flows.
- Update docs and `CHANGELOG.md` when a user-facing command, schema, protocol,
  workflow, or quality gate changes.

## Local Setup

```powershell
python -m pip install -e .
python -m unittest discover -s tests
```

Install the tokenizer extra when working on exact-tokenizer benchmarks,
release-candidate evidence, or any command that uses `tiktoken`:

```powershell
python -m pip install -e ".[tokenizer]"
python -m tokensquash baselines verify --include-exact-tokenizer --json
```

## Useful Checks

For ordinary codec, CLI, docs, and workflow changes:

```powershell
python -m unittest discover -s tests
python -m tokensquash doctor --strict
python -m tokensquash readiness --out-dir private-turns\readiness --json
python -m tokensquash verify-readiness private-turns\readiness --require-readiness-pass --json
```

For release-facing changes:

```powershell
python -m pip install -e ".[tokenizer]"
python -m tokensquash release-candidate --require-clean --out-dir private-turns\release-candidate --json
python -m tokensquash verify-release-candidate private-turns\release-candidate --require-release-candidate-pass --json
```

Use [docs/release-checklist.md](docs/release-checklist.md) before tagging or
sharing a release candidate.

## License

TokenSquash is source-available for personal and non-commercial use under the
PolyForm Noncommercial License 1.0.0 in [LICENSE](LICENSE). Commercial use is
not included in the public license and requires a separate written license from
TWO HANDS NETWORK LTD.

Read [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md) before publishing,
redistributing, packaging, hosting, embedding, or using TokenSquash in a
commercial AI system, commercial developer tool, paid product, hosted service,
managed service, or commercial AI training/evaluation pipeline.

## Working With Corpora

- Public examples belong under `examples/` and must be synthetic or already
  safe to publish.
- Private captures belong under ignored `private-turns/` storage.
- Use `turns capture` or `turns import` so raw storage, redaction, and optional
  evaluation stay in sync.
- Redacted corpora still need review before they become public examples.
- If a test needs real-looking data, create a tiny synthetic fixture.

## Pull Request Checklist

- Explain the user-facing behavior or product-standard gap being improved.
- Include tests for new behavior, especially schemas, CLI output, and verifier
  failure paths.
- Run the relevant checks and paste the important results in the PR.
- Update `README.md`, `CHANGELOG.md`, and release docs when the command surface
  or release evidence changes.
- Keep generated private evidence out of the commit.
- Call out any added dependency, optional model requirement, or external tool.

## Sidecar Work

Sidecar changes must keep these boundaries clear:

- No local model is required for deterministic codec tests.
- Sidecar token savings are not success by themselves; round-trip meaning and
  warning/failure counts matter.
- Ollama or other local-model calls must stay optional and timeout-bound.
- The README and CLI help should continue to mark model-backed workflows as
  experimental.

## Release Work

Release work must preserve all of these checks:

- exact-tokenizer baselines
- wheel build
- wheel install smoke test
- source distribution build
- wheel and sdist metadata verification
- artifact manifest integrity
- release attestation hashes
- GitHub Actions `release-candidate-evidence` artifact

When a change affects any of those, update tests and docs in the same PR.
