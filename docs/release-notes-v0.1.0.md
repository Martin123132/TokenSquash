# TokenSquash v0.1.0 Release Notes

Status: released on 2026-06-12 as the first source-available TokenSquash
release.

Release evidence:

- tag: `v0.1.0`
- release URL: <https://github.com/Martin123132/TokenSquash/releases/tag/v0.1.0>
- release commit: `9583c296f4ada082c88b7bc8149b678ed1529a16`
- main CI run: `27437797983`
- tag CI run: `27437873313`
- release-candidate verifier status: `pass`
- release attestation evidence hash:
  `d5dd3482b253bbb38ecf805d1097d301700a2eab80daf149a6f2774354c043d8`
- published asset hashes are recorded in
  [release-verification.md](release-verification.md)

Published asset SHA-256 values:

| Asset | SHA-256 |
|---|---|
| `tokensquash-0.1.0-py3-none-any.whl` | `5e2118072de2c1e7a879238126afce252825c07c58b2b24c2d1376826e9b2e91` |
| `tokensquash-0.1.0.tar.gz` | `fa991f10f999f3d121f4778cf842a73aad61cea4de6a549731283d6010776adb` |
| `release-attestation.json` | `1aa0b166a99bc8361f5bf8887355db7b96ffb89fe5330e52e123b6f40b71081b` |
| `artifact-manifest.json` | `f8a1539e3cca153afea5bbb8018f0b8eb0e9418f933e06939bbf78add84aa179` |
| `verify-release-candidate.json` | `f51a60bfae867590ac78b0103b7041eba3d8d9db886c72f34c09c10609f1490e` |

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

The v0.1.0 release was prepared from a clean checkout with this command block:

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

For `v0.1.0`, the release owner confirmed:

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
