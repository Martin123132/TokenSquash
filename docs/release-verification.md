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
## v0.2.2 Assets

The `v0.2.2` GitHub Release includes:

- `tokensquash-0.2.2-py3-none-any.whl`
- `tokensquash-0.2.2.tar.gz`
- `release-attestation.json`
- `artifact-manifest.json`
- `scorecard-pack.json`
- `scorecard.json`
- `verify-release-candidate.json`

Release URL: [v0.2.2](https://github.com/Martin123132/TokenSquash/releases/tag/v0.2.2)

Expected SHA-256 values from the release asset report:

| Asset | SHA-256 |
|---|---|
| `tokensquash-0.2.2-py3-none-any.whl` | `338899b1f7e24cdd4951963e4af2e91a05b3850befd9880faf9eb18445f517f5` |
| `tokensquash-0.2.2.tar.gz` | `61913f01e1a3e1e03fe91c2bc8ddce268e16da825e9415cc4ce2f96f8cd921ff` |
| `release-attestation.json` | `7d3504a00ae3cd6d5c148ff5b443cb64f17044d3ab762eb5daedecb2be835c02` |
| `artifact-manifest.json` | `6c04cb7fd0cc89e53c4fa35db96be2edcfff926346c9ed66636cc59303e524bc` |
| `scorecard-pack.json` | `8b13c4ee7f59d79ddc93f75ea844a8978865f9ceda90400d6e7b0bc1b6806369` |
| `scorecard.json` | `2c5187543e124a6c5ad893d6d38e1bd37bec5266e6d5171cdefcf64fbd76fa3d` |
| `verify-release-candidate.json` | `38232d336aab897bc589e6bf5f1eeda30f0ce4e3d0af7da084702e640c3a4273` |

Release evidence:

- tag: `v0.2.2`
- release commit: `68837ba1cfe388635d952ecea5920b51c2d31485`
- release-candidate verifier status: `pass`
- release-candidate status: `pass`
- release attestation status: `pass`
- release attestation evidence hash: `bc41dc33527617c71071402e0e5a6f33a2a88b32cc43a427a414c12c6d4fe87d`
- scorecard pack status: `watch`
- scorecard status: `watch`
- scorecard turns: `5`
- GitHub Actions run: `28384759819`
- packaged license evidence: inspect `verify-release-candidate.json` for `LICENSE`, `NOTICE.md`, and `COMMERCIAL-LICENSE.md` checks on the wheel and source distribution
- scorecard evidence: inspect `scorecard-pack.json` and `scorecard.json` for public-corpus codec health, saved percent, and milestone status
<!-- tokensquash-release-assets:end -->

## One-Command Public Verification

Use `verify-github-release` to repeat the public download, hash/schema
verification, and downloaded-wheel smoke check from tracked release evidence:

```powershell
python -m tokensquash verify-github-release v0.2.2 --repo Martin123132/TokenSquash --json
```

By default, the command reads this guide for the expected asset hashes, runs
`gh release view`, downloads the release assets under
`private-turns\github-release-verify\download`, verifies the downloaded files
with `verify-release-assets`, then installs the downloaded wheel in a temporary
venv and runs `about --json` plus `demo --counter chars --json`.

Use `--report private-turns\release-assets\release-assets.json` when you want
to verify against a saved machine-readable release-assets report instead of the
tracked Markdown hash table. Use `--skip-install-smoke` only when a reviewer
needs a hash/schema-only check.

## Download Assets

```powershell
gh release download v0.2.2 --repo Martin123132/TokenSquash --dir private-turns\download-v0.2.2
python -m tokensquash verify-release-assets private-turns\release-assets-v0.2.2-final\release-assets.json --asset-dir private-turns\download-v0.2.2 --json
```

`private-turns/` is ignored local storage, so downloaded release evidence should
not be committed back to the repository.

Final public check on 2026-06-29:

- downloaded the published `v0.2.2` GitHub Release assets into
  `private-turns\download-v0.2.2-public`
- ran `python -m tokensquash verify-release-assets private-turns\release-assets-v0.2.2\release-assets.json --asset-dir private-turns\download-v0.2.2-public --json`
- result: `pass`, with 7 assets verified, 0 failed checks, and 0 warnings
- installed the downloaded wheel in
  `private-turns\verify-v0.2.2-public-venv`
- ran `python -m tokensquash about --json` and
  `python -m tokensquash demo --counter chars --json` from that installed wheel

## Check Hashes

```powershell
Get-FileHash private-turns\download-v0.2.2\tokensquash-0.2.2-py3-none-any.whl -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.2\tokensquash-0.2.2.tar.gz -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.2\release-attestation.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.2\artifact-manifest.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.2\scorecard-pack.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.2\scorecard.json -Algorithm SHA256
Get-FileHash private-turns\download-v0.2.2\verify-release-candidate.json -Algorithm SHA256
```

Each hash should match the expected value above and the `digest` shown by:

```powershell
gh release view v0.2.2 --repo Martin123132/TokenSquash --json assets
```

## Inspect Evidence

Open `verify-release-candidate.json` and confirm:

- `status` is `pass`
- `summary.release_candidate_status` is `pass`
- `summary.release_attestation_status` is `pass`
- `summary.release_info_commit` is
  `68837ba1cfe388635d952ecea5920b51c2d31485`
- the `wheel` check has `license_files.LICENSE`,
  `license_files.NOTICE.md`, and `license_files.COMMERCIAL-LICENSE.md` set to
  `true`
- the `sdist` check has `license_files.LICENSE`,
  `license_files.NOTICE.md`, and `license_files.COMMERCIAL-LICENSE.md` set to
  `true`

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
python -m venv private-turns\verify-v0.2.2-venv
private-turns\verify-v0.2.2-venv\Scripts\python.exe -m pip install --no-deps private-turns\download-v0.2.2\tokensquash-0.2.2-py3-none-any.whl
private-turns\verify-v0.2.2-venv\Scripts\python.exe -m tokensquash about --json
private-turns\verify-v0.2.2-venv\Scripts\python.exe -m tokensquash demo --counter chars --json
```

The `about` command should report `tokensquash.product.manifest.v1` with
status `pass`. The `demo` command should report `tokensquash.demo.v1` with
status `pass`.
