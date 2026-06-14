# TokenSquash v0.1.1 Release Notes

Status: released on 2026-06-14 as a public-polish and release-evidence patch.

Release evidence:

- tag: `v0.1.1`
- release URL: <https://github.com/Martin123132/TokenSquash/releases/tag/v0.1.1>
- release commit: `8fd573b46b962f5bddec27bcb86cf62c67c137c6`
- main CI run: `27515165418`
- tag CI run: `27515208443`
- release-candidate verifier status: `pass`
- release attestation evidence hash:
  `3a1ad89dc640ee8e383ddeadf51eb55168a26c694228a1d671c12ae412a766a4`
- published asset hashes are recorded in
  [release-verification.md](release-verification.md)

Published asset SHA-256 values:

| Asset | SHA-256 |
|---|---|
| `tokensquash-0.1.1-py3-none-any.whl` | `bcf1757485b64c7e2466e5618b888738e6c3dbe3900802aec66ed733892c7f35` |
| `tokensquash-0.1.1.tar.gz` | `18064cb697dc4883dee38aad981cca274a82f448f2196a58a19ecb73be928fa9` |
| `release-attestation.json` | `f29a6315d8001a3f73e9e6187f99706a5ec0106ec97d918828228cc0106748fb` |
| `artifact-manifest.json` | `2b552ca9535c2e4c9580ca579a9ce89a31c50defec9a310bae5a858bfed98590` |
| `verify-release-candidate.json` | `3adfbb8a73853026d98d85e3f4ba9ff71f0ac61fadc0d035a9e6899df6e8e930` |

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

For `v0.1.1`, the release owner confirmed:

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
