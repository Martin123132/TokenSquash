# TokenSquash v0.1.1 Release Notes

Status: release-prep in progress on 2026-06-14. The final tag, release commit,
GitHub Actions run, release attestation evidence hash, and published asset
hashes are recorded after the clean release commit is tagged and the release
assets are uploaded.

## Summary

TokenSquash v0.1.1 is a public-polish and release-evidence patch. It does not
change codec behavior: v0.1.1 does not change the deterministic `ts1` prompt protocol or `tr1` reply protocol.
The main change is presentation and repeatability: the README is now a concise
public front door, and the heavier workflows live in focused docs that are
checked by strict doctor.

## Included

- concise public README with a two-minute demo, safe-claims guidance, and
  workflow map
- focused docs for quickstart, real-turn workflow, evidence packs,
  release-candidate workflow, sidecar Ollama use, and commercial licensing
- first-real-corpus guide for collecting and reviewing 10 local turns
- sidecar meaning-preservation rubric for pass/watch/fail review
- post-release flow for keeping changelog, release notes, GitHub Release text,
  asset hashes, and verification docs aligned
- `release-assets --update-verification-doc` for regenerating the
  release-verification asset table from staged release asset reports
- governed product manifest and strict doctor references for the new docs
- finalized v0.1.0 release notes with actual release evidence

## Compatibility

No wire-format compatibility changes are included in v0.1.1:

- `ts1` remains the deterministic prompt codec.
- `tr1` remains the deterministic reply codec.
- The local-AI sidecar remains experimental and non-canonical.
- PyPI publishing is still not configured.

## Evidence Contract

Before publishing `v0.1.1`, the release owner must confirm:

- local `python -m unittest discover -s tests` status is `pass`
- local `python -m tokensquash doctor --strict` status is `pass`
- local readiness and verify-readiness status is `pass`
- local `release-info --require-clean` status is `pass`
- local `release-candidate --require-clean` status is `pass`
- local `verify-release-candidate --require-release-candidate-pass` status is
  `pass`
- GitHub Actions `tests` workflow status is `success`
- GitHub Actions jobs `unittest (3.10)`, `unittest (3.13)`, and
  `exact-tokenizer` are `success`
- wheel, source distribution, artifact manifest, release attestation, and
  release-candidate verifier assets are uploaded to the GitHub Release
- `docs/release-verification.md` records the final published asset hashes

## Known Limits

- TokenSquash is pre-1.0 and the protocol surface may still change.
- Sidecar workflows are model-dependent and experimental.
- Token savings are not success unless decoded meaning and warning/failure
  evidence support the result.
- Release evidence is local/GitHub based; signed distribution artifacts and
  PyPI publication are not configured yet.
- Commercial use requires a separate written license from TWO HANDS NETWORK
  LTD.

## License

TokenSquash remains source-available for personal and non-commercial use under
the PolyForm Noncommercial License 1.0.0.

Commercial use requires a separate written license from TWO HANDS NETWORK LTD.
