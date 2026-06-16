# Release Verification

This guide explains how to inspect TokenSquash release assets and evidence.
Release assets are attached to GitHub Releases so reviewers do not need access
to local `private-turns/` storage or expired CI artifacts.

Future releases should stage their public assets from a verified
release-candidate pack before upload:

```powershell
$tag = "v0.2.0"
python -m tokensquash release-assets private-turns\release-candidate --tag $tag --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md
```

Review `private-turns\release-assets\release-assets.json` and the generated
section below before re-running the same command with `--upload`.

<!-- tokensquash-release-assets:start -->
## v0.2.0 Assets

The `v0.2.0` GitHub Release includes:

- `tokensquash-0.2.0-py3-none-any.whl`
- `tokensquash-0.2.0.tar.gz`
- `release-attestation.json`
- `artifact-manifest.json`
- `scorecard-pack.json`
- `scorecard.json`
- `verify-release-candidate.json`

Release URL: [v0.2.0](https://github.com/Martin123132/TokenSquash/releases/tag/v0.2.0)

Expected SHA-256 values from the release asset report:

| Asset | SHA-256 |
|---|---|
| `tokensquash-0.2.0-py3-none-any.whl` | `a0598d0a3f58e8efc41cefd1f1f5990ee02322018432a1a0df94d124ddf98a56` |
| `tokensquash-0.2.0.tar.gz` | `774728555f4c7e7eeadd75864b9630b6f8c690ff99a7a781a02b0af1d127c9c6` |
| `release-attestation.json` | `ce8388cf04c26c5346eee348b1957d923f7468a48b97fe56edd577a963cf9349` |
| `artifact-manifest.json` | `671c1e7fcc94ed566ff1b78b68f2003a302d0e5a9e4d303a972da17f642b207d` |
| `scorecard-pack.json` | `f372148600caa179bd87aa74a390d5231ee59b0d3547e88838f7d57833248b55` |
| `scorecard.json` | `632ef13bbdd5fbb4d9168cf03756b14bf7373408a9dee67de80ad73038a304b6` |
| `verify-release-candidate.json` | `4127a09568c4a2e728e3fb9238c665c0d1d84de366b7b1ce8688755f0ad2a62f` |

Release evidence:

- tag: `v0.2.0`
- release commit: `6863ed522c32c329885f33e4b908a1b1487e6716`
- release-candidate verifier status: `pass`
- release-candidate status: `pass`
- release attestation status: `pass`
- release attestation evidence hash: `4ebb167830e8697ee46d99f727635564dbdf3d68cfda33daadb399e33751e471`
- scorecard pack status: `watch`
- scorecard status: `watch`
- scorecard turns: `5`
- GitHub Actions run: `27654795021`
- packaged license evidence: inspect `verify-release-candidate.json` for `LICENSE` and `COMMERCIAL-LICENSE.md` checks on the wheel and source distribution
- scorecard evidence: inspect `scorecard-pack.json` and `scorecard.json` for public-corpus codec health, saved percent, and milestone status
<!-- tokensquash-release-assets:end -->

## Download Assets

```powershell
gh release download v0.2.0 --repo Martin123132/TokenSquash --dir private-turns\download-v0.2.0
python -m tokensquash release-assets verify private-turns\release-assets\release-assets.json --asset-dir private-turns\download-v0.2.0 --json
```

`private-turns/` is ignored local storage, so downloaded release evidence should
not be committed back to the repository.

## Check Hashes

```powershell
Get-FileHash private-turns\download-v0.2.0\tokensquash-0.2.0-py3-none-any.whl -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.0\tokensquash-0.2.0.tar.gz -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.0\release-attestation.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.0\artifact-manifest.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.0\scorecard-pack.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.0\scorecard.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.0\verify-release-candidate.json -Algorithm SHA256
```

Each hash should match the expected value above and the `digest` shown by:

```powershell
gh release view v0.2.0 --repo Martin123132/TokenSquash --json assets
```

## Inspect Evidence

Open `verify-release-candidate.json` and confirm:

- `status` is `pass`
- `summary.release_candidate_status` is `pass`
- `summary.release_attestation_status` is `pass`
- `summary.release_info_commit` is
  `6863ed522c32c329885f33e4b908a1b1487e6716`
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
python -m venv private-turns\verify-v0.2.0-venv
private-turns\verify-v0.2.0-venv\Scripts\python.exe -m pip install --no-deps private-turns\download-v0.2.0\tokensquash-0.2.0-py3-none-any.whl
private-turns\verify-v0.2.0-venv\Scripts\python.exe -m tokensquash about --json
private-turns\verify-v0.2.0-venv\Scripts\python.exe -m tokensquash demo --counter chars --json
```

The `about` command should report `tokensquash.product.manifest.v1` with
status `pass`. The `demo` command should report `tokensquash.demo.v1` with
status `pass`.
