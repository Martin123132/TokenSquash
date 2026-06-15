# Release Candidate Workflow

Use this workflow before tagging, publishing, or sharing a TokenSquash release
candidate.

## Preconditions

```powershell
python -m pip install -e ".[tokenizer]"
python -m unittest discover -s tests
python -m tokensquash doctor --strict --strict-out-dir private-turns\doctor-release
python -m tokensquash baselines verify --include-exact-tokenizer --json
python -m tokensquash readiness --out-dir private-turns\readiness-release --json
python -m tokensquash verify-readiness private-turns\readiness-release --require-readiness-pass --json
python -m tokensquash release-info --require-clean --json
```

The release-info report should show:

- `status`: `pass`
- `summary.dirty`: `false`
- a concrete Git commit
- the intended package version

## Build The Candidate

```powershell
python -m tokensquash release-candidate --require-clean --out-dir private-turns\release-candidate --json
python -m tokensquash verify-release-candidate private-turns\release-candidate --require-release-candidate-pass --json
```

The candidate gate verifies:

- readiness evidence
- bundled sample scorecard-pack evidence
- dependency-free and exact-tokenizer benchmark baselines
- wheel build
- source distribution build
- package metadata
- installed wheel smoke test
- packaged public demo data
- `LICENSE` and `COMMERCIAL-LICENSE.md` in the wheel and source distribution
- artifact-manifest integrity
- release attestation status

The scorecard pack is written under `private-turns\release-candidate\scorecard-pack`
with a root `scorecard-pack.json` summary. The bundled public corpus may report
`watch` because it is intentionally small seed data; the release gate records
that status while verifying that the evidence files are present and hashed.

## Stage Public Release Assets

```powershell
python -m tokensquash release-assets private-turns\release-candidate --tag v0.1.1 --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md --json
```

Review:

- `private-turns\release-assets\release-assets.json`
- `private-turns\release-assets\release-assets.md`
- the generated section in `docs\release-verification.md`

The staged public assets should include:

- wheel
- source distribution
- `release-attestation.json`
- `artifact-manifest.json`
- `verify-release-candidate.json`

## Upload After Review

Only upload after local and GitHub evidence both pass:

```powershell
python -m tokensquash release-assets private-turns\release-candidate --tag v0.1.1 --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md --upload
```

`--upload` runs the generated `gh release upload` command. Keep it explicit and
review-first.

## GitHub Actions

After pushing a release-prep commit, confirm the `tests` workflow passes:

- `unittest (3.10)`: success
- `unittest (3.13)`: success
- `exact-tokenizer`: success
- uploaded artifact: `release-candidate-evidence`

## Related Docs

- [release-checklist.md](release-checklist.md)
- [release-verification.md](release-verification.md)
- [post-release-flow.md](post-release-flow.md)
- [release-notes-v0.1.1.md](release-notes-v0.1.1.md)
