# TokenSquash v0.2.0 Release Notes

Status: released on 2026-06-17.

Release evidence:

- tag: `v0.2.0`
- release URL: <https://github.com/Martin123132/TokenSquash/releases/tag/v0.2.0>
- release commit: `6863ed522c32c329885f33e4b908a1b1487e6716`
- main CI run: `27654721390`
- tag CI run: `27654795021`
- release-candidate verifier status: `pass`
- release-assets verifier status: `pass`
- release attestation evidence hash:
  `4ebb167830e8697ee46d99f727635564dbdf3d68cfda33daadb399e33751e471`
- published asset hashes are recorded in
  [release-verification.md](release-verification.md)

Published asset SHA-256 values:

| Asset | SHA-256 |
|---|---|
| `tokensquash-0.2.0-py3-none-any.whl` | `a0598d0a3f58e8efc41cefd1f1f5990ee02322018432a1a0df94d124ddf98a56` |
| `tokensquash-0.2.0.tar.gz` | `774728555f4c7e7eeadd75864b9630b6f8c690ff99a7a781a02b0af1d127c9c6` |
| `release-attestation.json` | `ce8388cf04c26c5346eee348b1957d923f7468a48b97fe56edd577a963cf9349` |
| `artifact-manifest.json` | `671c1e7fcc94ed566ff1b78b68f2003a302d0e5a9e4d303a972da17f642b207d` |
| `scorecard-pack.json` | `f372148600caa179bd87aa74a390d5231ee59b0d3547e88838f7d57833248b55` |
| `scorecard.json` | `632ef13bbdd5fbb4d9168cf03756b14bf7373408a9dee67de80ad73038a304b6` |
| `verify-release-candidate.json` | `4127a09568c4a2e728e3fb9238c665c0d1d84de366b7b1ce8688755f0ad2a62f` |

## Summary

TokenSquash v0.2.0 turns the project from a compact-codec experiment into a
benchmark-first communication codec and release-evidence system for AI-agent
prompt/reply workflows.

The deterministic `ts1` prompt codec and `tr1` reply codec remain the source of
truth. The local-AI sidecar remains experimental. Token savings alone are not
success unless the corpus, redaction, scorecard, sidecar review, gate, and
release evidence support the result.

## Included

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

The GitHub Release includes:

- `tokensquash-0.2.0-py3-none-any.whl`
- `tokensquash-0.2.0.tar.gz`
- `release-attestation.json`
- `artifact-manifest.json`
- `scorecard-pack.json`
- `scorecard.json`
- `verify-release-candidate.json`

`docs/release-verification.md` was refreshed from the final
`release-assets.json` report and checked against the uploaded assets.

## Evidence Summary

The final release-evidence chain for v0.2.0 reported:

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
