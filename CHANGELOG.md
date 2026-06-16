# Changelog

All notable TokenSquash changes are tracked here.

The format is based on Keep a Changelog, with plain-language sections aimed at
people evaluating whether TokenSquash is ready to use or release. This project
does not yet publish signed distribution artifacts; release-candidate evidence
is produced locally and in GitHub Actions.

## [Unreleased]

### Added

- `turns scorecard` now summarizes real-turn corpus health, token savings,
  alias opportunities, privacy findings, adaptive benchmark behavior, and
  optional sidecar review evidence in a single report.
- `turns scorecard-pack` now writes reusable scorecard evidence directories
  with `scorecard.json`, `scorecard.md`, and optional history artifacts.
- `release-candidate` now includes bundled sample scorecard-pack evidence in
  its report, artifact manifest, verifier summary, and local attestation.
- `release-assets` now stages `scorecard-pack.json` and `scorecard.json` so
  public release evidence exposes codec health alongside build evidence.
- `verify-release-assets` now verifies staged or downloaded release assets
  against `release-assets.json`, including hashes and JSON schemas.
- GitHub Actions now stages and verifies release assets inside the
  exact-tokenizer release-candidate job and uploads that evidence.
- `turns compare-scorecards` now compares saved scorecard JSON files for
  release-review deltas across corpus size, savings, privacy findings, alias
  impact, and sidecar pass/watch/fail counts.
- `turns scorecard-history` now summarizes saved scorecards over time, including
  timeline rows, adjacent pass/watch/fail comparisons, net deltas, and warnings.
- Sidecar review reports now include pass/watch/fail decisions so experimental
  local-AI semantic compression can be judged on meaning risk, not token savings
  alone.
- `docs/v0.2.0-plan.md` now describes the next development track for real corpus
  scorecards, corpus growth milestones, sidecar meaning evidence, and release-tag
  comparison.
- Quickstart, real-turn, and first-real-corpus docs now show where the new
  scorecard fits between capture, validation, evaluation, and release evidence.

## [0.1.1] - 2026-06-14

### Added

- `release-assets --update-verification-doc` now refreshes the generated
  release asset hash section in `docs/release-verification.md` from the staged
  asset report.
- `docs/first-real-corpus.md` now gives a short 10-turn local capture,
  redaction, report, suggestions, and certification workflow.
- `docs/sidecar-meaning-rubric.md` now defines pass/watch/fail review guidance
  for experimental sidecar round-trip meaning preservation.
- `docs/post-release-flow.md` now documents the changelog, release notes,
  asset-hash, verification-doc, and GitHub Release update flow after publishing.
- v0.1.0 release notes now record the actual tag, release URL, release commit,
  CI run ids, verifier status, and release attestation evidence hash.
- v0.1.1 release notes now describe the public-polish scope, compatibility
  boundary, release evidence contract, and known limits for the patch release.
- `README.md` now acts as a concise public front door, with command-heavy
  workflows moved into focused docs for quickstart, real turns, evidence packs,
  release candidates, sidecar Ollama use, and commercial licensing.
- `ROADMAP.md` and `docs/v0.1.1-plan.md` now describe the public product
  direction, experimental boundaries, evidence bar, and next patch-release
  scope.
- `release-assets` stages verified public release assets from a
  release-candidate pack, writes a release asset report, and can optionally run
  `gh release upload`.
- Release asset verification docs now explain how to inspect published wheel,
  source distribution, attestation, artifact manifest, and verifier assets for
  `v0.1.0`.

## [0.1.0] - 2026-06-12

### Added

- Deterministic compact prompt protocol `ts1` and compact reply protocol `tr1`.
- Human-readable decoders for compact prompts and replies.
- Public sample turn corpus and first-run demo workflow.
- Benchmarking for prompts, replies, paired turns, aliases, and exact-tokenizer
  counters when `tiktoken` is installed.
- Private real-turn capture/import workflow with raw ignored storage and
  regenerated redacted corpora.
- Turn evaluation, certification, comparison, history, release-check, and
  release-verification report packs.
- Product manifest, release metadata report, workspace initialization, doctor,
  readiness verifier, and release-candidate verifier.
- Experimental local-AI sidecar translation, decode, round-trip, evaluation,
  sweep, review, gate, certification, and comparison workflows.
- GitHub Actions now runs unit tests across Python 3.10 and 3.13.
- GitHub Actions now verifies dependency-free and exact-tokenizer benchmark
  baselines.
- GitHub Actions now builds and checks both the package wheel and source
  distribution.
- The exact-tokenizer CI job now runs the release-candidate gate and uploads
  the saved release-candidate evidence pack.
- The release-candidate gate now builds a source distribution, verifies
  `PKG-INFO` metadata, checks packaged sample corpus data, and includes the
  sdist hash in local release attestations.
- A release checklist documents the manual steps required before tagging or
  sharing a release.
- Contributor, security, and pull-request policy docs now describe setup,
  quality gates, private-data rules, vulnerability reporting, and release
  impact checks.
- TokenSquash now declares PolyForm Noncommercial License 1.0.0 terms, required
  notices, and commercial licensing contact details for TWO HANDS NETWORK LTD.
- v0.1.0 release notes now summarize scope, evidence, private-data
  boundaries, license terms, and the release-prep command block.
- GitHub issue forms now guide public-safe bug reports, feature requests,
  commercial licensing enquiries, and private-data/security contact requests.
- Strict doctor and the product manifest now verify source-checkout governance
  docs as part of product-readiness evidence.

### Changed

- Release-candidate package checks now prove both installability from the wheel
  and source-package metadata integrity.
- Release-candidate package checks now verify that public and commercial
  licensing files are included in both wheel and source-distribution artifacts.
- CI explicitly installs the build backend so package checks do not depend on
  whichever tools happen to be preinstalled on a runner image.

### Fixed

- Source-distribution build evidence now uses a portable dist path and records
  stderr/stdout excerpts only when the build command fails.

### Notes

- TokenSquash remains benchmark-first and experimental. Token savings alone are
  not treated as success; meaning preservation and release evidence must also
  be inspected.
