# TokenSquash v0.2.0 Release Notes

Status: draft. v0.2.0 has not been tagged or published yet.

These notes describe the intended release bar for the next minor release. The
final tag, release URL, release commit, CI run, evidence hash, and asset hashes
must be regenerated from the release commit before publication.

## Summary

TokenSquash v0.2.0 is intended to turn the project from a compact-codec
experiment into a benchmark-first communication codec and release-evidence
system for AI-agent prompt/reply workflows.

The deterministic `ts1` prompt codec and `tr1` reply codec remain the source of
truth. The local-AI sidecar remains experimental. Token savings alone are not
success unless the corpus, redaction, scorecard, sidecar review, gate, and
release evidence support the result.

## Expected Scope

- real-turn scorecards for corpus size, savings, privacy findings, adaptive
  pass-through rows, raw wire loss rows, alias impact, and sidecar review
  status
- scorecard evidence packs with `scorecard-pack.json`, `scorecard.json`, and
  Markdown review artifacts
- scorecard comparison and history reports for release-review deltas
- pass/watch/fail sidecar review decisions so model-dependent semantic
  compression is judged by meaning risk, not shortness alone
- release-candidate evidence that includes bundled public sample scorecard
  evidence and hashes it into the artifact manifest and release attestation
- public release asset staging for wheel, source distribution, attestation,
  artifact manifest, scorecard pack, scorecard, and verifier output
- `verify-release-assets` for checking staged or downloaded public assets
  against `tokensquash.release_assets.v1` and
  `tokensquash.release_assets.verify.v1`
- GitHub Actions release evidence that builds, stages, verifies, and uploads
  release-candidate and release-asset evidence from the exact-tokenizer job

## Release Bar

The release owner should prepare v0.2.0 from a clean checkout with the
tokenizer extra installed:

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
python -m tokensquash release-assets private-turns\release-candidate --tag v0.2.0 --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md --json
python -m tokensquash verify-release-assets private-turns\release-assets\release-assets.json --json
```

Before tagging, all of the following must be true:

- local tests pass
- strict doctor status is `pass`
- readiness and verify-readiness statuses are `pass`
- release-info status is `pass` with `summary.dirty` set to `false`
- release-candidate status is `pass`
- verify-release-candidate status is `pass`
- `verify-release-candidate --require-release-candidate-pass` status is `pass`
- release-attestation status is `pass`
- artifact-manifest integrity status is `pass`
- bundled public scorecard-pack evidence is present and hashed
- staged release assets include the expected seven public assets
- verify-release-assets status is `pass`
- GitHub Actions `tests` workflow is successful on the release-prep commit
- the exact-tokenizer job uploads `release-candidate-evidence` with both
  release-candidate and release-assets evidence

The bundled public sample scorecard may report `watch` because the public corpus
is intentionally small seed data. That is acceptable only when the release gate
records the scorecard status honestly and verifies the scorecard evidence files.

## Required Public Assets

The GitHub Release should include:

- `tokensquash-0.2.0-py3-none-any.whl`
- `tokensquash-0.2.0.tar.gz`
- `release-attestation.json`
- `artifact-manifest.json`
- `scorecard-pack.json`
- `scorecard.json`
- `verify-release-candidate.json`

`docs/release-verification.md` must be refreshed from the final
`release-assets.json` report before publication and reviewed against the
uploaded assets.

## Draft Evidence Fields

Fill these from the final release-prep run:

- tag: `v0.2.0`
- release URL: `TODO`
- release commit: `TODO`
- main CI run: `TODO`
- tag CI run: `TODO`
- release-candidate verifier status: `TODO`
- release-assets verifier status: `TODO`
- release attestation evidence hash: `TODO`
- wheel SHA-256: `TODO`
- source distribution SHA-256: `TODO`
- `scorecard-pack.json` SHA-256: `TODO`
- `scorecard.json` SHA-256: `TODO`

## Recent Development Checkpoint

The release-evidence chain has already been exercised locally during v0.2.0
development. This checkpoint is not final release evidence and must be
regenerated after the release commit exists:

- release-candidate status: `pass`
- verify-release-candidate status: `pass`
- release asset verifier status: `pass`
- staged public assets: `7`
- release-candidate verifier checks: `39`
- release asset verifier checks: `14`
- public sample scorecard status: `watch`
- public sample turn count: `5`
- public sample saved percent: `20.6091`

## Known Limits

- TokenSquash is pre-1.0 and the protocol surface may still change.
- The sidecar is experimental, local-model-dependent, and non-canonical.
- Token savings are not success unless meaning and release evidence survive
  review.
- Private raw corpora must stay in ignored local storage such as
  `private-turns/`.
- PyPI publishing and signed distribution artifacts are not configured yet.
- Commercial use requires a separate written license from TWO HANDS NETWORK
  LTD.

## License

TokenSquash remains source-available for personal and non-commercial use under
the PolyForm Noncommercial License 1.0.0.

Commercial use requires a separate written license from TWO HANDS NETWORK LTD.
