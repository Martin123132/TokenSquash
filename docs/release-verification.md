# Release Verification

This guide explains how to inspect TokenSquash release assets and evidence.
Release assets are attached to GitHub Releases so reviewers do not need access
to local `private-turns/` storage or expired CI artifacts.

Future releases should stage their public assets from a verified
release-candidate pack before upload:

```powershell
$tag = "vX.Y.Z"
python -m tokensquash release-assets private-turns\release-candidate --tag $tag --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md
```

Review `private-turns\release-assets\release-assets.json` and the generated
section below before re-running the same command with `--upload`. Use the
intended next release tag; do not overwrite the tracked hash section for an
already-published tag unless you are correcting that exact release evidence
before upload.

<!-- tokensquash-release-assets:start -->
## v0.2.1 Assets

The `v0.2.1` GitHub Release includes:

- `tokensquash-0.2.1-py3-none-any.whl`
- `tokensquash-0.2.1.tar.gz`
- `release-attestation.json`
- `artifact-manifest.json`
- `scorecard-pack.json`
- `scorecard.json`
- `verify-release-candidate.json`

Release URL: [v0.2.1](https://github.com/Martin123132/TokenSquash/releases/tag/v0.2.1)

Expected SHA-256 values from the release asset report:

| Asset | SHA-256 |
|---|---|
| `tokensquash-0.2.1-py3-none-any.whl` | `d5c47f6e3db24cc15aeb8fb78598e6182e1afd69c003fd2028a018075f900d2c` |
| `tokensquash-0.2.1.tar.gz` | `5c534accabe7c91b9d982819eb73af5c2f60b6c3dda61c32c4bb52c8a1c84ad8` |
| `release-attestation.json` | `97dc4785433e51051279e924ed1c63377eeb73472650929f0db9cc1d66e6ff57` |
| `artifact-manifest.json` | `bcd064d9c1f5f6731fd677a0e0c56faf974870b471790833de60cdb06e34436c` |
| `scorecard-pack.json` | `a99281a69f40bab5d376ff51c855af1301d3e98adeeaee96d15defe9c336f489` |
| `scorecard.json` | `d9e74f5ddc1e2e9b19957afb74a870a77858af9b891152734077828e62f0b6c8` |
| `verify-release-candidate.json` | `e6c52337d501df08150c3fadfa1cf212b0b2da61fcaeec291f7ff389a63b88a3` |

Release evidence:

- tag: `v0.2.1`
- release commit: `369cba782695c943d5a3cd24263b0466b909d172`
- release-candidate verifier status: `pass`
- release-candidate status: `pass`
- release attestation status: `pass`
- release attestation evidence hash: `6a53d41eac832af6a90aa47f70b61458056034edd47721affbf903bd91a7e977`
- scorecard pack status: `watch`
- scorecard status: `watch`
- scorecard turns: `5`
- GitHub Actions run: `27763458140`
- packaged license evidence: inspect `verify-release-candidate.json` for `LICENSE` and `COMMERCIAL-LICENSE.md` checks on the wheel and source distribution
- scorecard evidence: inspect `scorecard-pack.json` and `scorecard.json` for public-corpus codec health, saved percent, and milestone status
<!-- tokensquash-release-assets:end -->

## Download Assets

```powershell
gh release download v0.2.1 --repo Martin123132/TokenSquash --dir private-turns\download-v0.2.1
python -m tokensquash verify-release-assets private-turns\release-assets\release-assets.json --asset-dir private-turns\download-v0.2.1 --json
```

`private-turns/` is ignored local storage, so downloaded release evidence should
not be committed back to the repository.

Final public check on 2026-06-18:

- downloaded the published `v0.2.1` GitHub Release assets into
  `private-turns\download-v0.2.1-public`
- ran `python -m tokensquash verify-release-assets private-turns\release-assets-v0.2.1-upload\release-assets.json --asset-dir private-turns\download-v0.2.1-public --json`
- result: `pass`, with 7 assets verified, 0 failed checks, and 0 warnings
- installed the downloaded wheel in
  `private-turns\verify-v0.2.1-public-venv`
- ran `python -m tokensquash about --json` and
  `python -m tokensquash demo --counter chars --json` from that installed wheel

## Check Hashes

```powershell
Get-FileHash private-turns\download-v0.2.1\tokensquash-0.2.1-py3-none-any.whl -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.1\tokensquash-0.2.1.tar.gz -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.1\release-attestation.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.1\artifact-manifest.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.1\scorecard-pack.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.1\scorecard.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.1\verify-release-candidate.json -Algorithm SHA256
```

Each hash should match the expected value above and the `digest` shown by:

```powershell
gh release view v0.2.1 --repo Martin123132/TokenSquash --json assets
```

## Inspect Evidence

Open `verify-release-candidate.json` and confirm:

- `status` is `pass`
- `summary.release_candidate_status` is `pass`
- `summary.release_attestation_status` is `pass`
- `summary.release_info_commit` is
  `369cba782695c943d5a3cd24263b0466b909d172`
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
python -m venv private-turns\verify-v0.2.1-venv
private-turns\verify-v0.2.1-venv\Scripts\python.exe -m pip install --no-deps private-turns\download-v0.2.1\tokensquash-0.2.1-py3-none-any.whl
private-turns\verify-v0.2.1-venv\Scripts\python.exe -m tokensquash about --json
private-turns\verify-v0.2.1-venv\Scripts\python.exe -m tokensquash demo --counter chars --json
```

The `about` command should report `tokensquash.product.manifest.v1` with
status `pass`. The `demo` command should report `tokensquash.demo.v1` with
status `pass`.
