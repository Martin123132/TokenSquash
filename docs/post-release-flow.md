# Post-Release Flow

Use this flow after tagging or publishing a TokenSquash release. It keeps the
changelog, release notes, asset hashes, verification guide, and GitHub release
page aligned.

## 1. Confirm Release Evidence

Check the tag and CI run:

```powershell
gh release view v0.1.0 --repo Martin123132/TokenSquash --json tagName,isDraft,isPrerelease,publishedAt,assets,url
gh run view 27437873313 --repo Martin123132/TokenSquash --json status,conclusion,jobs
```

For a new release, use the actual tag and run id. The release should have:

- a non-draft GitHub Release
- successful `unittest (3.10)`, `unittest (3.13)`, and `exact-tokenizer` jobs
- public wheel and source distribution assets
- `release-attestation.json`
- `artifact-manifest.json`
- `verify-release-candidate.json`

## 2. Refresh Asset Verification

Stage public assets from the verified local release-candidate pack:

```powershell
python -m tokensquash release-assets private-turns\release-candidate --tag v0.1.0 --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md --ci-run 27437873313 --json
```

Review:

- `private-turns\release-assets\release-assets.json`
- `private-turns\release-assets\release-assets.md`
- the generated section in `docs\release-verification.md`

Only upload after reviewing the staged report and generated verification
section:

```powershell
python -m tokensquash release-assets private-turns\release-candidate --tag v0.1.0 --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md --ci-run 27437873313 --upload
```

## 3. Update Release Notes

Update the release notes for the published tag so they no longer read like a
draft. Record:

- tag
- release URL
- release commit
- GitHub Actions run id
- release-candidate verifier status
- release attestation evidence hash
- link to `docs/release-verification.md`

For `v0.1.0`, the tracked notes are
`docs/release-notes-v0.1.0.md`. Future releases can use the same shape with a
new file or a versioned section.

## 4. Update Changelog

After release:

- move completed `Unreleased` items into the released version section
- add the release date
- create a fresh `Unreleased` section for ongoing work
- keep public claims tied to evidence, not hopes

If the release is only a public-polish documentation update, say that plainly
instead of implying codec behavior changed.

## 5. Verify Published Assets

Download the release assets into ignored storage and compare hashes:

```powershell
gh release download v0.1.0 --repo Martin123132/TokenSquash --dir private-turns\download-v0.1.0
Get-FileHash private-turns\download-v0.1.0\tokensquash-0.1.0-py3-none-any.whl -Algorithm SHA256
Get-FileHash private-turns\download-v0.1.0\tokensquash-0.1.0.tar.gz -Algorithm SHA256
Get-FileHash private-turns\download-v0.1.0\release-attestation.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.1.0\artifact-manifest.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.1.0\verify-release-candidate.json -Algorithm SHA256
```

Each hash should match `docs/release-verification.md`.

## 6. Publish Or Update GitHub Release Notes

Once the tracked release notes are final, update the GitHub Release body:

```powershell
gh release edit v0.1.0 --repo Martin123132/TokenSquash --notes-file docs\release-notes-v0.1.0.md
```

Use the release page for concise public context and the tracked docs for the
full audit trail.

## 7. Final Public-Safety Check

Before making the repository public, confirm:

- `git status --short` is clean
- `python -m unittest discover -s tests` passes
- `python -m tokensquash doctor --strict` passes
- `python -m tokensquash readiness --out-dir private-turns\readiness-public --json` passes
- `python -m tokensquash verify-readiness private-turns\readiness-public --require-readiness-pass --json` passes
- no raw private prompts, replies, corpora, local model output, credentials, or
  local release packs are tracked

The visibility switch should be treated as a release action. Do it only after
the owner has reviewed licensing, contact details, public docs, and tracked
files.

All downloaded release evidence and temporary verification environments should
stay under `private-turns/` or another ignored local path.
