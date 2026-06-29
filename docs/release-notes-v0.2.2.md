# TokenSquash v0.2.2 Release Notes

Status: released on 2026-06-29.

Release evidence:

- tag: `v0.2.2`
- release URL: <https://github.com/Martin123132/TokenSquash/releases/tag/v0.2.2>
- release commit: `68837ba1cfe388635d952ecea5920b51c2d31485`
- main GitHub Actions run: `28384672347`
- tag GitHub Actions run: `28384759819`
- release-candidate verifier status: `pass`
- release-assets verifier status: `pass`
- public download verifier status: `pass`
- release attestation evidence hash:
  `bc41dc33527617c71071402e0e5a6f33a2a88b32cc43a427a414c12c6d4fe87d`

Published asset hashes:

| Asset | SHA-256 |
|---|---|
| `tokensquash-0.2.2-py3-none-any.whl` | `338899b1f7e24cdd4951963e4af2e91a05b3850befd9880faf9eb18445f517f5` |
| `tokensquash-0.2.2.tar.gz` | `61913f01e1a3e1e03fe91c2bc8ddce268e16da825e9415cc4ce2f96f8cd921ff` |
| `release-attestation.json` | `7d3504a00ae3cd6d5c148ff5b443cb64f17044d3ab762eb5daedecb2be835c02` |
| `artifact-manifest.json` | `6c04cb7fd0cc89e53c4fa35db96be2edcfff926346c9ed66636cc59303e524bc` |
| `scorecard-pack.json` | `8b13c4ee7f59d79ddc93f75ea844a8978865f9ceda90400d6e7b0bc1b6806369` |
| `scorecard.json` | `2c5187543e124a6c5ad893d6d38e1bd37bec5266e6d5171cdefcf64fbd76fa3d` |
| `verify-release-candidate.json` | `38232d336aab897bc589e6bf5f1eeda30f0ce4e3d0af7da084702e640c3a4273` |

## Summary

TokenSquash v0.2.2 is a public-readiness patch release. It keeps the
deterministic `ts1` prompt codec and `tr1` reply codec unchanged while making
the first-use workflow easier to follow and the licensing/package evidence
clearer before wider public visibility.

The core product claim remains benchmark-first: token savings alone are not
success unless the corpus, redaction, gates, reports, and release evidence say
so.

## Included

- `guide`, `docs/command-map.md`, starter private templates, and
  `turns first-run` improve the first-run path for a new local user.
- `turns first-run` now refuses unchanged starter placeholder text, which helps
  prevent accidental starter-template captures.
- The README now has a short license-at-a-glance section for personal,
  non-commercial, and commercial-use boundaries.
- Commercial licensing contact details consistently route through TWO HANDS
  NETWORK LTD, COO Glyn Evans, at `glyn@twohandsnetwork.co.uk`.
- `NOTICE.md` is part of the product manifest, strict doctor checks, wheel and
  source-distribution license-file evidence, and release verification docs.
- The release evidence chain checks `LICENSE`, `NOTICE.md`, and
  `COMMERCIAL-LICENSE.md` in both wheel and source distribution artifacts.

## Release Bar

Prepare v0.2.2 from a clean checkout with the tokenizer extra installed:

```powershell
$tag = "v0.2.2"
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

The GitHub Release includes:

- `tokensquash-0.2.2-py3-none-any.whl`
- `tokensquash-0.2.2.tar.gz`
- `release-attestation.json`
- `artifact-manifest.json`
- `scorecard-pack.json`
- `scorecard.json`
- `verify-release-candidate.json`

`docs/release-verification.md` was refreshed from the final
`release-assets.json` report and checked against the uploaded assets.

## Evidence Summary

The final release-evidence chain for v0.2.2 reported:

- release-candidate status: `pass`
- verify-release-candidate status: `pass`
- release asset verifier status: `pass`
- public download verifier status: `pass`
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
Commercial licensing enquiries should go through COO Glyn Evans at
`glyn@twohandsnetwork.co.uk`.
