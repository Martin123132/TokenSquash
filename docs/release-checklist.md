# TokenSquash Release Checklist

Use this checklist before tagging, publishing, or sharing a TokenSquash release
candidate. It assumes the release is being prepared from `main`.

## 1. Confirm Scope

- Read `CHANGELOG.md` and move any completed items from `Unreleased` into the
  target version section.
- Confirm `pyproject.toml` contains the intended package version.
- Confirm the README still describes the current command surface accurately.
- Confirm a project-owner-approved `LICENSE` file exists before any external
  release or package publication.
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
```

Inspect the saved pack before continuing:

- `private-turns\release-candidate\release-candidate.json`
- `private-turns\release-candidate\artifact-manifest.json`
- `private-turns\release-candidate\release-attestation.json`
- `private-turns\release-candidate\wheel-build.txt`
- `private-turns\release-candidate\wheel-smoke.txt`
- `private-turns\release-candidate\sdist-build.txt`

Required release-candidate evidence:

- release-candidate status is `pass`
- verifier status is `pass`
- exact-tokenizer baselines are `pass`
- wheel build is `pass`
- wheel smoke test is `pass`
- source distribution build is `pass`
- artifact-manifest integrity is `pass`
- release attestation contains wheel, sdist, and artifact-manifest SHA-256
  hashes

## 5. Verify GitHub Actions

After pushing the release-prep commit, confirm the `tests` workflow passes on
GitHub.

The workflow must show:

- `unittest (3.10)`: success
- `unittest (3.13)`: success
- `exact-tokenizer`: success
- uploaded artifact: `release-candidate-evidence`

Download or inspect the `release-candidate-evidence` artifact if the release is
being reviewed outside the local machine.

## 6. Tag Or Publish

Only tag or publish after local and GitHub release evidence both pass.

Suggested local tag command:

```powershell
& 'D:\Apps\Git\cmd\git.exe' tag -a v0.1.0 -m "TokenSquash v0.1.0"
& 'D:\Apps\Git\cmd\git.exe' push origin v0.1.0
```

Do not publish to PyPI until a dedicated publishing workflow, credentials, and
artifact provenance policy have been added and reviewed.

## 7. Post-Release

- Add a new `Unreleased` section to `CHANGELOG.md`.
- Record the released tag, GitHub Actions run, and release-candidate evidence
  location in the release notes.
- Keep private corpora under ignored `private-turns/` storage; do not attach
  raw private turns to public releases.
