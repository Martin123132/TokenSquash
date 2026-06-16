# TokenSquash Release Checklist

Use this checklist before tagging, publishing, or sharing a TokenSquash release
candidate. It assumes the release is being prepared from `main`.

## 1. Confirm Scope

- Read `CHANGELOG.md` and move any completed items from `Unreleased` into the
  target version section.
- Review `docs/release-notes-v0.1.1.md` and confirm the release evidence
  contract matches the final release process.
- Confirm `pyproject.toml` contains the intended package version.
- Confirm the README still describes the current command surface accurately.
- Confirm the project-owner-approved `LICENSE` and `COMMERCIAL-LICENSE.md`
  files match the intended non-commercial and commercial-use terms before any
  external release or package publication.
- Keep the deterministic codec as the source of truth; sidecar model workflows
  must remain explicitly experimental.

## 2. Prepare Local Environment

```powershell
python -m pip install -e ".[tokenizer]"
python -m tokensquash release-info --require-clean --json
```

The `release-info` command must report:

- `status`: `pass`
- `require_clean`: `true`
- `summary.dirty`: `false`
- a concrete Git commit

## 2a. Release-Prep Command Block

Use this command block for a clean local release-prep pass:

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
python -m tokensquash release-assets private-turns\release-candidate --tag v0.1.1 --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md --json
python -m tokensquash verify-release-assets private-turns\release-assets\release-assets.json --json
```

## 3. Run Product Gates

```powershell
python -m unittest discover -s tests
python -m tokensquash doctor --strict --strict-out-dir private-turns\doctor-release
python -m tokensquash baselines verify --include-exact-tokenizer --json
python -m tokensquash readiness --out-dir private-turns\readiness-release --json
python -m tokensquash verify-readiness private-turns\readiness-release --require-readiness-pass --json
```

All commands above must pass before building release-candidate evidence.

## 4. Build Release-Candidate Evidence

```powershell
python -m tokensquash release-candidate --require-clean --out-dir private-turns\release-candidate --json
python -m tokensquash verify-release-candidate private-turns\release-candidate --require-release-candidate-pass --json
python -m tokensquash release-assets private-turns\release-candidate --tag v0.1.1 --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md --json
python -m tokensquash verify-release-assets private-turns\release-assets\release-assets.json --json
```

Inspect the saved pack before continuing:

- `private-turns\release-candidate\release-candidate.json`
- `private-turns\release-candidate\artifact-manifest.json`
- `private-turns\release-candidate\release-attestation.json`
- `private-turns\release-candidate\wheel-build.txt`
- `private-turns\release-candidate\wheel-smoke.txt`
- `private-turns\release-candidate\sdist-build.txt`
- `private-turns\release-assets\release-assets.json`
- `private-turns\release-assets\release-assets.md`

Required release-candidate evidence:

- release-candidate status is `pass`
- verifier status is `pass`
- exact-tokenizer baselines are `pass`
- wheel build is `pass`
- wheel smoke test is `pass`
- source distribution build is `pass`
- wheel and source distribution include `LICENSE` and `COMMERCIAL-LICENSE.md`
- artifact-manifest integrity is `pass`
- release attestation contains wheel, sdist, artifact-manifest, scorecard-pack,
  and scorecard SHA-256 hashes
- `docs/release-verification.md` can be updated with the public release asset
  names, hashes, CI run, and license-file evidence
- staged release assets include the wheel, source distribution,
  `release-attestation.json`, `artifact-manifest.json`, `scorecard-pack.json`,
  `scorecard.json`, and `verify-release-candidate.json`
- `docs/release-verification.md` has been refreshed from the
  `release-assets.json` report and reviewed before upload
- `verify-release-assets` passes against the staged release assets

## 5. Verify GitHub Actions

After pushing the release-prep commit, confirm the `tests` workflow passes on
GitHub.

The workflow must show:

- `unittest (3.10)`: success
- `unittest (3.13)`: success
- `exact-tokenizer`: success
- uploaded artifact: `release-candidate-evidence` with release-candidate,
  release-assets, `verify-release-candidate.json`, and
  `verify-release-assets.json` evidence

Download or inspect the `release-candidate-evidence` artifact if the release is
being reviewed outside the local machine.

Confirm the GitHub Actions run, evidence artifact, and release-attestation
hashes are available before tagging. The exact final evidence belongs in the
generated release-candidate pack and published release notes because it is
produced after the release commit exists.

## 6. Tag Or Publish

Only tag or publish after local and GitHub release evidence both pass.

Suggested local tag command:

```powershell
& 'D:\Apps\Git\cmd\git.exe' tag -a v0.1.1 -m "TokenSquash v0.1.1"
& 'D:\Apps\Git\cmd\git.exe' push origin v0.1.1
```

Do not publish to PyPI until a dedicated publishing workflow, credentials, and
artifact provenance policy have been added and reviewed.

## 7. Post-Release

Follow [post-release-flow.md](post-release-flow.md) for the detailed
post-release update and verification sequence.

- Add a new `Unreleased` section to `CHANGELOG.md`.
- Record the released tag, GitHub Actions run, and release-candidate evidence
  location in the published release notes.
- Upload public release assets for the wheel, source distribution,
  `release-attestation.json`, `artifact-manifest.json`, `scorecard-pack.json`,
  `scorecard.json`, and `verify-release-candidate.json`.
- Prefer `python -m tokensquash release-assets private-turns\release-candidate
  --tag <tag> --update-verification-doc docs\release-verification.md --upload`
  for the upload after reviewing the staged `release-assets.json` report and
  generated verification doc section.
- Update `docs/release-verification.md` with the final published asset hashes.
- Keep private corpora under ignored `private-turns/` storage; do not attach
  raw private turns to public releases.
