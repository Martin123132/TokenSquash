# Evidence Packs

TokenSquash evidence packs make results repeatable. They are local folders or
JSON reports that preserve inputs, thresholds, summaries, warnings, gates, and
verification status.

Use the [claims policy](claims-policy.md) before quoting savings publicly. The
claim should name the evidence pack, counter, corpus, limits, and warnings.

## Product Readiness

```powershell
python -m tokensquash readiness --out-dir private-turns\readiness --json
python -m tokensquash verify-readiness private-turns\readiness --require-readiness-pass --json
```

Readiness writes a product-level evidence pack with nested doctor, demo,
certification, release-check, and release-verification artifacts. The verifier
audits the saved files and schemas after the pack is written.

## Strict Doctor

```powershell
python -m tokensquash doctor --strict --strict-out-dir private-turns\doctor-strict --json
```

Strict doctor checks:

- packaged public demo corpus
- deterministic demo workflow
- private-storage ignore patterns
- workspace init dry run
- source governance documents
- product manifest
- turn certification workflow

## Turn Certification

```powershell
python -m tokensquash turns certify private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --out-dir private-turns\certification --json
python -m tokensquash turns claim private-turns\certification\certification.json --corpus-label "redacted local turn corpus"
python -m tokensquash turns claim private-turns\certification\certification.json --claim-only --fail-on-unsupported
python -m tokensquash turns claim private-turns\certification\certification.json --limits-only
python -m tokensquash turns claim-pack private-turns\certification --out-dir private-turns\claim-pack --fail-on-unsupported
```

Certification writes:

- `certification.json`
- `certification.md`
- `report.json`
- `gate.json`
- `suggestions.json`
- `claim.json`
- `claim.md`
- `claim.txt`
- `limits.md`
- nested deterministic evaluation artifacts

## Quality Budgets

```powershell
python -m tokensquash budget init --out private-turns\quality-budget.json --dry-run --json
python -m tokensquash budget validate examples\quality-budget.json
```

Quality budgets define thresholds for saved percent, privacy findings,
pass-through rows, raw-wire-loss rows, history regressions, and doctor warnings.
Use source-controlled budgets for release checks.

## Turn Release Evidence

```powershell
python -m tokensquash turns release-check private-turns\real.redacted-turns.jsonl --budget examples\quality-budget.json --history private-turns\certification --counter tiktoken:cl100k_base --out-dir private-turns\release-check --json
python -m tokensquash turns verify-release private-turns\release-check --require-release-pass --json
```

Turn release evidence combines certification, strict doctor, quality budget
validation, and optional certification history into a release-impact report.

## Release Candidate Evidence

```powershell
python -m tokensquash release-candidate --require-clean --out-dir private-turns\release-candidate --json
python -m tokensquash verify-release-candidate private-turns\release-candidate --require-release-candidate-pass --json
```

Release-candidate evidence includes bundled sample scorecard-pack artifacts,
wheel/source-distribution builds, metadata checks, package smoke tests, artifact
manifests, and release attestations. See
[release-candidate.md](release-candidate.md) for the full flow.

## Release Asset Evidence

```powershell
$tag = "vX.Y.Z"
python -m tokensquash release-assets private-turns\release-candidate --tag $tag --out-dir private-turns\release-assets --update-verification-doc docs\release-verification.md --json
python -m tokensquash verify-release-assets private-turns\release-assets\release-assets.json --json
python -m tokensquash verify-github-release $tag --repo Martin123132/TokenSquash --json
```

Release asset evidence stages public assets, including the release-candidate
scorecard JSON evidence, writes `release-assets.json` and `release-assets.md`,
can verify staged or downloaded assets, and can regenerate the hash section in
`docs\release-verification.md`. GitHub Release verification downloads the
published assets, verifies them against tracked release evidence, and runs an
installed-wheel `about`/`demo` smoke check. Use the intended next tag; upload
remains explicit through `--upload`.

## Sidecar Evidence

```powershell
python -m tokensquash sidecar evaluate private-turns\real.redacted-turns.jsonl --mode both --limit 10 --model llama3.2:3b --counter chars --out-dir private-turns\sidecar-eval --json
python -m tokensquash sidecar review private-turns\sidecar-eval\evaluation.json
python -m tokensquash sidecar certify private-turns\sidecar-eval\evaluation.json --out-dir private-turns\sidecar-certification --json
```

Sidecar evidence must be judged with warning counts, missing fields, decoded
meaning, gate results, and the [sidecar meaning rubric](sidecar-meaning-rubric.md).
Token savings alone are not success.

`turns claim` can read saved sidecar evidence too, but it labels the result as
experimental rather than a deterministic codec claim.
