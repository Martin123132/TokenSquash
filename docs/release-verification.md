# Release Verification

This guide explains how to inspect TokenSquash release assets and evidence.
Release assets are attached to GitHub Releases so reviewers do not need access
to local `private-turns/` storage or expired CI artifacts.

Future releases should stage their public assets from a verified
release-candidate pack before upload:

```powershell
python -m tokensquash release-assets private-turns\release-candidate --tag v0.1.0 --out-dir private-turns\release-assets
```

Review `private-turns\release-assets\release-assets.json` before re-running the
same command with `--upload`.

## v0.1.0 Assets

The `v0.1.0` GitHub Release includes:

- `tokensquash-0.1.0-py3-none-any.whl`
- `tokensquash-0.1.0.tar.gz`
- `release-attestation.json`
- `artifact-manifest.json`
- `verify-release-candidate.json`

Expected SHA-256 values from the tag CI run:

| Asset | SHA-256 |
|---|---|
| `tokensquash-0.1.0-py3-none-any.whl` | `5e2118072de2c1e7a879238126afce252825c07c58b2b24c2d1376826e9b2e91` |
| `tokensquash-0.1.0.tar.gz` | `fa991f10f999f3d121f4778cf842a73aad61cea4de6a549731283d6010776adb` |
| `artifact-manifest.json` | `f8a1539e3cca153afea5bbb8018f0b8eb0e9418f933e06939bbf78add84aa179` |

Release evidence:

- tag: `v0.1.0`
- release commit: `9583c296f4ada082c88b7bc8149b678ed1529a16`
- tag CI run: `27437873313`
- tag CI verifier status: `pass`
- tag CI evidence hash:
  `d5dd3482b253bbb38ecf805d1097d301700a2eab80daf149a6f2774354c043d8`
- packaged license files: `LICENSE` and `COMMERCIAL-LICENSE.md` are present in
  both the wheel and source distribution

## Download Assets

```powershell
gh release download v0.1.0 --repo Martin123132/TokenSquash --dir private-turns\download-v0.1.0
```

`private-turns/` is ignored local storage, so downloaded release evidence should
not be committed back to the repository.

## Check Hashes

```powershell
Get-FileHash private-turns\download-v0.1.0\tokensquash-0.1.0-py3-none-any.whl -Algorithm SHA256
Get-FileHash private-turns\download-v0.1.0\tokensquash-0.1.0.tar.gz -Algorithm SHA256
Get-FileHash private-turns\download-v0.1.0\artifact-manifest.json -Algorithm SHA256
```

Each hash should match the expected value above and the `digest` shown by:

```powershell
gh release view v0.1.0 --repo Martin123132/TokenSquash --json assets
```

## Inspect Evidence

Open `verify-release-candidate.json` and confirm:

- `status` is `pass`
- `summary.release_candidate_status` is `pass`
- `summary.release_attestation_status` is `pass`
- `summary.release_info_commit` is
  `9583c296f4ada082c88b7bc8149b678ed1529a16`
- the `wheel` check has `license_files.LICENSE` and
  `license_files.COMMERCIAL-LICENSE.md` set to `true`
- the `sdist` check has `license_files.LICENSE` and
  `license_files.COMMERCIAL-LICENSE.md` set to `true`

Open `release-attestation.json` and confirm:

- `status` is `pass`
- `materials.wheel.sha256` matches the wheel hash
- `materials.sdist.sha256` matches the source-distribution hash
- `materials.artifact_manifest.sha256` matches the artifact-manifest hash

## Install Smoke Check

Install the wheel in a temporary environment and run the public demo:

```powershell
python -m venv private-turns\verify-v0.1.0-venv
private-turns\verify-v0.1.0-venv\Scripts\python.exe -m pip install --no-deps private-turns\download-v0.1.0\tokensquash-0.1.0-py3-none-any.whl
private-turns\verify-v0.1.0-venv\Scripts\python.exe -m tokensquash about --json
private-turns\verify-v0.1.0-venv\Scripts\python.exe -m tokensquash demo --counter chars --json
```

The `about` command should report `tokensquash.product.manifest.v1` with
status `pass`. The `demo` command should report `tokensquash.demo.v1` with
status `pass`.
