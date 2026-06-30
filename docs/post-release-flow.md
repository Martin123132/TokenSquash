# Post-Release Flow

Use this flow after tagging or publishing a TokenSquash release. It keeps the
changelog, release notes, asset hashes, verification guide, and GitHub release
page aligned.

## 1. Confirm Release Evidence

Check the tag and CI run:

```powershell
$tag = "vX.Y.Z"
$run = "1234567890"
gh release view $tag --repo Martin123132/TokenSquash --json tagName,isDraft,isPrerelease,publishedAt,assets,url
gh run view $run --repo Martin123132/TokenSquash --json status,conclusion,jobs
```

Use the actual published tag and run id. The release should have:

- a non-draft GitHub Release
- successful `unittest (3.10)`, `unittest (3.13)`, and `exact-tokenizer` jobs
- public wheel and source distribution assets
- `release-attestation.json`
- `artifact-manifest.json`
- `scorecard-pack.json`
- `scorecard.json`
- `verify-release-candidate.json`

## 2. Refresh Asset Verification

Stage public assets from the verified local release-candidate pack:

```powershell
python -m tokensquash release-assets private-turns\release-candidate --tag $tag --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md --ci-run $run --json
python -m tokensquash verify-release-assets private-turns\release-assets\release-assets.json --json
```

Review:

- `private-turns\release-assets\release-assets.json`
- `private-turns\release-assets\release-assets.md`
- `verify-release-assets` output/status
- the generated section in `docs\release-verification.md`

Only upload after reviewing the staged report and generated verification
section:

```powershell
python -m tokensquash release-assets private-turns\release-candidate --tag $tag --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md --ci-run $run --upload
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

For a new release, keep the tracked notes in a matching versioned file such as
`docs/release-notes-vX.Y.Z.md`.

## 4. Update Changelog

After release:

- move completed `Unreleased` items into the released version section
- add the release date
- create a fresh `Unreleased` section for ongoing work
- keep public claims tied to evidence, not hopes

If the release is only a public-polish documentation update, say that plainly
instead of implying codec behavior changed.

## 5. Verify Published Assets

Download the release assets into ignored storage, compare hashes, and
smoke-test the published wheel:

```powershell
$tag = "vX.Y.Z"
python -m tokensquash verify-github-release $tag --repo Martin123132/TokenSquash --json
```

The command uses `docs/release-verification.md` by default, writes its report
under ignored `private-turns\github-release-verify`, verifies downloaded asset
hashes and JSON schemas, then installs the downloaded wheel into a temporary
venv for `about --json` and `demo --counter chars --json`.

## 6. Publish Or Update GitHub Release Notes

Once the tracked release notes are final, update the GitHub Release body:

```powershell
$tag = "vX.Y.Z"
gh release edit $tag --repo Martin123132/TokenSquash --notes-file docs\release-notes-vX.Y.Z.md
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
