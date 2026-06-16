# Release Verification

This guide explains how to inspect TokenSquash release assets and evidence.
Release assets are attached to GitHub Releases so reviewers do not need access
to local `private-turns/` storage or expired CI artifacts.

Future releases should stage their public assets from a verified
release-candidate pack before upload:

```powershell
$tag = "v0.1.1"
python -m tokensquash release-assets private-turns\release-candidate --tag $tag --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md
```

Review `private-turns\release-assets\release-assets.json` and the generated
section below before re-running the same command with `--upload`.

<!-- tokensquash-release-assets:start -->
## v0.1.1 Assets

The `v0.1.1` GitHub Release includes:

- `tokensquash-0.1.1-py3-none-any.whl`
- `tokensquash-0.1.1.tar.gz`
- `release-attestation.json`
- `artifact-manifest.json`
- `verify-release-candidate.json`

Release URL: [v0.1.1](https://github.com/Martin123132/TokenSquash/releases/tag/v0.1.1)

Expected SHA-256 values from the release asset report:

| Asset | SHA-256 |
|---|---|
| `tokensquash-0.1.1-py3-none-any.whl` | `bcf1757485b64c7e2466e5618b888738e6c3dbe3900802aec66ed733892c7f35` |
| `tokensquash-0.1.1.tar.gz` | `18064cb697dc4883dee38aad981cca274a82f448f2196a58a19ecb73be928fa9` |
| `release-attestation.json` | `f29a6315d8001a3f73e9e6187f99706a5ec0106ec97d918828228cc0106748fb` |
| `artifact-manifest.json` | `2b552ca9535c2e4c9580ca579a9ce89a31c50defec9a310bae5a858bfed98590` |
| `verify-release-candidate.json` | `3adfbb8a73853026d98d85e3f4ba9ff71f0ac61fadc0d035a9e6899df6e8e930` |

Release evidence:

- tag: `v0.1.1`
- release commit: `8fd573b46b962f5bddec27bcb86cf62c67c137c6`
- release-candidate verifier status: `pass`
- release-candidate status: `pass`
- release attestation status: `pass`
- release attestation evidence hash: `3a1ad89dc640ee8e383ddeadf51eb55168a26c694228a1d671c12ae412a766a4`
- GitHub Actions run: `27515208443`
- packaged license evidence: inspect `verify-release-candidate.json` for `LICENSE` and `COMMERCIAL-LICENSE.md` checks on the wheel and source distribution
<!-- tokensquash-release-assets:end -->

## Download Assets

```powershell
gh release download v0.1.1 --repo Martin123132/TokenSquash --dir private-turns\download-v0.1.1
python -m tokensquash release-assets verify private-turns\release-assets\release-assets.json --asset-dir private-turns\download-v0.1.1 --json
```

`private-turns/` is ignored local storage, so downloaded release evidence should
not be committed back to the repository.

## Check Hashes

```powershell
Get-FileHash private-turns\download-v0.1.1\tokensquash-0.1.1-py3-none-any.whl -Algorithm SHA256
Get-FileHash private-turns\download-v0.1.1\tokensquash-0.1.1.tar.gz -Algorithm SHA256
Get-FileHash private-turns\download-v0.1.1\release-attestation.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.1.1\artifact-manifest.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.1.1\verify-release-candidate.json -Algorithm SHA256
```

Each hash should match the expected value above and the `digest` shown by:

```powershell
gh release view v0.1.1 --repo Martin123132/TokenSquash --json assets
```

## Inspect Evidence

Open `verify-release-candidate.json` and confirm:

- `status` is `pass`
- `summary.release_candidate_status` is `pass`
- `summary.release_attestation_status` is `pass`
- `summary.release_info_commit` is
  `8fd573b46b962f5bddec27bcb86cf62c67c137c6`
- the `wheel` check has `license_files.LICENSE` and
  `license_files.COMMERCIAL-LICENSE.md` set to `true`
- the `sdist` check has `license_files.LICENSE` and
  `license_files.COMMERCIAL-LICENSE.md` set to `true`

Open `release-attestation.json` and confirm:

- `status` is `pass`
- `materials.wheel.sha256` matches the wheel hash
- `materials.sdist.sha256` matches the source-distribution hash
- `materials.artifact_manifest.sha256` matches the artifact-manifest hash
- for releases that include scorecard assets,
  `materials.scorecard_pack.sha256` matches `scorecard-pack.json` and
  `materials.scorecard.sha256` matches `scorecard.json`

Open `scorecard-pack.json` and `scorecard.json` when present and confirm:

- `schema_version` is `tokensquash.turns.scorecard.pack.v1` for the pack
- `schema_version` is `tokensquash.turns.scorecard.v1` for the scorecard
- `status` is `pass` or `watch`
- the scorecard summary reports the public corpus turn count and saved percent

## Install Smoke Check

Install the wheel in a temporary environment and run the public demo:

```powershell
python -m venv private-turns\verify-v0.1.1-venv
private-turns\verify-v0.1.1-venv\Scripts\python.exe -m pip install --no-deps private-turns\download-v0.1.1\tokensquash-0.1.1-py3-none-any.whl
private-turns\verify-v0.1.1-venv\Scripts\python.exe -m tokensquash about --json
private-turns\verify-v0.1.1-venv\Scripts\python.exe -m tokensquash demo --counter chars --json
```

The `about` command should report `tokensquash.product.manifest.v1` with
status `pass`. The `demo` command should report `tokensquash.demo.v1` with
status `pass`.
