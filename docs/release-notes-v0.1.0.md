# TokenSquash v0.1.0 Release Notes

Status: ready for the first source-available TokenSquash release once the
release checklist passes from a clean commit. The final tag, commit, artifact
hashes, and GitHub Actions run are generated after this tracked file is
committed and are recorded in the release-candidate evidence pack and published
release notes.

## Summary

TokenSquash is a benchmark-first experiment in saving small percentages of
AI-agent tokens by translating routine coding-agent prompts and replies into
compact, model-readable protocols.

The goal of v0.1.0 is not to claim universal compression. It is to provide a
measurable local toolkit for testing whether compact prompt/reply protocols,
path aliases, repeated-field aliases, and experimental local-AI sidecar
translation can preserve meaning while reducing token use.

## Included

- deterministic compact prompt protocol `ts1`
- deterministic compact reply protocol `tr1`
- human-readable decode paths for prompts and replies
- public sample paired-turn corpus and first-run demo workflow
- private real-turn capture/import workflows under ignored `private-turns/`
  storage
- redaction, validation, statistics, splitting, measuring, diagnostics,
  benchmarking, alias learning, certification, release-check, and verification
  workflows for paired turns
- local product-readiness, doctor, release-info, release-candidate, and
  release-verification evidence packs
- wheel and source-distribution build checks, package metadata checks, package
  smoke tests, artifact manifests, and release attestations
- experimental local-AI sidecar translate, decode, round-trip, evaluation,
  review, sweep, gate, certify, and comparison workflows
- non-commercial public license terms and commercial licensing contact details
  for TWO HANDS NETWORK LTD

## Experimental Boundaries

The deterministic codec is the source of truth. The local-AI sidecar is
experimental and should be judged by round-trip meaning, warning/failure counts,
and corpus-level evidence, not token savings alone.

No local model, API key, or hosted service is required for deterministic codec
tests. Sidecar model calls are optional, local-first, and timeout-bound.

## Private Data

Real prompts, replies, private corpora, local release evidence, raw model
outputs that expose private data, API keys, credentials, and secrets must stay
out of Git. TokenSquash uses ignored local storage such as `private-turns/`,
`private-prompts/`, and `private-aliases/` for private experiments and release
evidence.

Redacted corpora still need review before they become public examples.

## License

TokenSquash is source-available for personal and non-commercial use under the
PolyForm Noncommercial License 1.0.0. Commercial use is not included in the
public license and requires a separate written license from TWO HANDS NETWORK
LTD.

Commercial use includes paid products, hosted services, managed services,
enterprise products, commercial developer tools, commercial AI systems,
commercial AI coding/agent products, and commercial AI training/evaluation
pipelines.

See `LICENSE` and `COMMERCIAL-LICENSE.md` for the full public license, required
notices, commercial-use examples, request details, and contact channel.

## Release-Prep Command Block

Run this from a clean checkout before tagging:

```powershell
python -m pip install -e ".[tokenizer]"
python -m unittest discover -s tests
python -m tokensquash doctor --strict --strict-out-dir private-turns\doctor-release
python -m tokensquash baselines verify --include-exact-tokenizer --json
python -m tokensquash readiness --out-dir private-turns\readiness-release --json
python -m tokensquash verify-readiness private-turns\readiness-release --require-readiness-pass --json
python -m tokensquash release-info --require-clean --json
python -m tokensquash release-candidate --require-clean --out-dir private-turns\release-candidate --json
python -m tokensquash verify-release-candidate private-turns\release-candidate --require-release-candidate-pass --json
```

After pushing the final release-prep commit, confirm GitHub Actions passes:

```powershell
gh run list --repo Martin123132/TokenSquash --limit 5
gh run view <run-id> --repo Martin123132/TokenSquash --json status,conclusion,jobs
gh run download <run-id> --repo Martin123132/TokenSquash --name release-candidate-evidence --dir private-turns\ci-release-candidate-evidence
```

## Release Evidence Contract

Before tagging `v0.1.0`, the release owner must confirm:

- local `release-info --require-clean` status is `pass`
- local `release-candidate --require-clean` status is `pass`
- local `verify-release-candidate --require-release-candidate-pass` status is
  `pass`
- GitHub Actions `tests` workflow status is `success`
- GitHub Actions jobs `unittest (3.10)`, `unittest (3.13)`, and
  `exact-tokenizer` are `success`
- GitHub artifact `release-candidate-evidence` exists
- wheel, source distribution, and artifact manifest SHA-256 hashes are present
  in `release-attestation.json`
- `LICENSE` and `COMMERCIAL-LICENSE.md` are packaged in both the wheel and
  source distribution

## Known Limits

- TokenSquash is pre-1.0 and the protocol surface may still change.
- The sidecar is experimental and model-dependent.
- Token savings are not success unless decoded meaning still matches the
  original task or reply.
- PyPI publishing is not configured yet.
- Commercial use requires a separate written license from TWO HANDS NETWORK
  LTD.
