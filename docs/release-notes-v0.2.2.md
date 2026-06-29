# TokenSquash v0.2.2 Release Notes

Status: release candidate on 2026-06-29.

Release evidence will be finalized after the public GitHub Release is staged,
uploaded, downloaded, and verified.

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

The GitHub Release should include:

- `tokensquash-0.2.2-py3-none-any.whl`
- `tokensquash-0.2.2.tar.gz`
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
Commercial licensing enquiries should go through COO Glyn Evans at
`glyn@twohandsnetwork.co.uk`.
