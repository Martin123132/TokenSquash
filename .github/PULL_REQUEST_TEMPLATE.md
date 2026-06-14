## Summary

- 

## Verification

- [ ] `python -m unittest discover -s tests`
- [ ] `python -m tokensquash doctor --strict`
- [ ] `python -m tokensquash readiness --out-dir private-turns\readiness --json`
- [ ] `python -m tokensquash verify-readiness private-turns\readiness --require-readiness-pass --json`

## Release Impact

- [ ] `README.md` updated when command behavior or workflows changed
- [ ] `CHANGELOG.md` updated for user-facing changes
- [ ] `docs/release-checklist.md` updated when release evidence changed
- [ ] `docs/release-notes-v0.1.0.md` and `docs/release-notes-v0.1.1.md` updated when release scope or release evidence changed
- [ ] `LICENSE` and `COMMERCIAL-LICENSE.md` reviewed when licensing or distribution terms changed
- [ ] issue templates reviewed when reporting, licensing, privacy, or security process changed
- [ ] release-candidate gate run when packaging, baselines, or release evidence changed

## Privacy And Security

- [ ] no raw private prompts, replies, corpora, secrets, or local evidence committed
- [ ] sidecar/model-backed behavior remains optional and explicitly experimental
- [ ] new paths, file writes, or network calls are documented and bounded
