# Changelog

All notable TokenSquash changes are tracked here.

The format is based on Keep a Changelog, with plain-language sections aimed at
people evaluating whether TokenSquash is ready to use or release. This project
does not yet publish signed distribution artifacts; release-candidate evidence
is produced locally and in GitHub Actions.

## [Unreleased]

### Added

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
- Release and contribution docs now call out that an owner-approved `LICENSE`
  file is still required before external release or package publication.

### Changed

- Release-candidate package checks now prove both installability from the wheel
  and source-package metadata integrity.
- CI explicitly installs the build backend so package checks do not depend on
  whichever tools happen to be preinstalled on a runner image.

### Fixed

- Source-distribution build evidence now uses a portable dist path and records
  stderr/stdout excerpts only when the build command fails.

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

### Notes

- TokenSquash remains benchmark-first and experimental. Token savings alone are
  not treated as success; meaning preservation and release evidence must also
  be inspected.
