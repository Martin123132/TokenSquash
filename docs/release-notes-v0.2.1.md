# TokenSquash v0.2.1 Release Notes

Status: released on 2026-06-18.

Release evidence:

- tag: `v0.2.1`
- release URL: <https://github.com/Martin123132/TokenSquash/releases/tag/v0.2.1>
- release commit: `369cba782695c943d5a3cd24263b0466b909d172`
- main GitHub Actions run: `27763458140`
- tag GitHub Actions run: `27763608617`
- release-candidate verifier status: `pass`
- release-assets verifier status: `pass`
- public download verifier status: `pass`
- release attestation evidence hash:
  `6a53d41eac832af6a90aa47f70b61458056034edd47721affbf903bd91a7e977`

Published asset hashes:

| Asset | SHA-256 |
|---|---|
| `tokensquash-0.2.1-py3-none-any.whl` | `d5c47f6e3db24cc15aeb8fb78598e6182e1afd69c003fd2028a018075f900d2c` |
| `tokensquash-0.2.1.tar.gz` | `5c534accabe7c91b9d982819eb73af5c2f60b6c3dda61c32c4bb52c8a1c84ad8` |
| `release-attestation.json` | `97dc4785433e51051279e924ed1c63377eeb73472650929f0db9cc1d66e6ff57` |
| `artifact-manifest.json` | `bcd064d9c1f5f6731fd677a0e0c56faf974870b471790833de60cdb06e34436c` |
| `scorecard-pack.json` | `a99281a69f40bab5d376ff51c855af1301d3e98adeeaee96d15defe9c336f489` |
| `scorecard.json` | `d9e74f5ddc1e2e9b19957afb74a870a77858af9b891152734077828e62f0b6c8` |
| `verify-release-candidate.json` | `e6c52337d501df08150c3fadfa1cf212b0b2da61fcaeec291f7ff389a63b88a3` |

## Summary

TokenSquash v0.2.1 is a release-evidence and public-claims polish release. It
keeps the deterministic `ts1` prompt codec and `tr1` reply codec unchanged while
making supported public claims easier to review, package, and verify.

The main user-facing addition is a claim-pack workflow: saved deterministic or
sidecar evidence can now produce a public-safe bundle containing machine-readable
claim JSON, Markdown review text, copyable claim text, and known limits.

## Included

- `turns claim-pack` writes `claim.json`, `claim.md`, `claim.txt`, and
  `limits.md` from saved evidence.
- `turns certify` writes claim artifacts beside the certification pack so
  release reviewers can inspect supported public wording without an extra
  manual step.
- Product manifest, strict doctor, readiness command listings, claims policy,
  evidence-pack docs, and release docs now include the claim-pack workflow.
- README workflow links are grouped so the public front door starts with
  quickstart, real turns, evidence packs, claims, and release-candidate evidence
  before deeper release history.
- Release-prep docs now use an intended next tag variable and warn against
  reusing already-published tags when staging fresh assets from current `main`.

## Release Bar

Prepare v0.2.1 from a clean checkout with the tokenizer extra installed:

```powershell
$tag = "v0.2.1"
python -m pip install -e ".[tokenizer]"
python -m unittest discover -s tests
python -m tokensquash doctor --strict --strict-out-dir private-turns\doctor-release
python -m tokensquash baselines verify --include-exact-tokenizer --json
python -m tokensquash readiness --out-dir private-turns\readiness-release --json
python -m tokensquash verify-readiness private-turns\readiness-release --require-readiness-pass --json
python -m tokensquash release-info --require-clean --json
python -m tokensquash release-candidate --require-clean --out-dir private-turns\release-candidate --json
python -m tokensquash verify-release-candidate private-turns\release-candidate --require-release-candidate-pass --json
python -m tokensquash release-assets private-turns\release-candidate --tag $tag --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md --json
python -m tokensquash verify-release-assets private-turns\release-assets\release-assets.json --json
```

Before tagging, all of the following must be true:

- local tests pass
- strict doctor status is `pass`
- readiness and verify-readiness statuses are `pass`
- release-info status is `pass` with `summary.dirty` set to `false`
- release-candidate status is `pass`
- verify-release-candidate status is `pass`
- release-attestation status is `pass`
- artifact-manifest integrity status is `pass`
- staged release assets include the expected seven public assets
- verify-release-assets status is `pass`
- GitHub Actions `tests` workflow is successful on the release-prep commit

## Required Public Assets

The GitHub Release should include:

- `tokensquash-0.2.1-py3-none-any.whl`
- `tokensquash-0.2.1.tar.gz`
- `release-attestation.json`
- `artifact-manifest.json`
- `scorecard-pack.json`
- `scorecard.json`
- `verify-release-candidate.json`

`docs/release-verification.md` should be refreshed from the final
`release-assets.json` report and checked against the uploaded assets.

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
