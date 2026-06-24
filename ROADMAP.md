# TokenSquash Roadmap

TokenSquash is a benchmark-first experiment in compact AI-agent communication.
The project should grow only in directions that make token savings easier to
measure, safer to inspect, or more useful in real workflows.

## Product Principles

- Measure before claiming. Token savings, pass-throughs, raw-wire losses,
  privacy findings, and meaning-risk signals must be visible in reports.
- Keep the deterministic codec as the source of truth. Local-AI sidecar output
  is experimental until round-trip meaning evidence is strong enough.
- Prefer small, reviewable protocols over opaque compression. The compact form
  should remain inspectable by humans and machines.
- Keep private corpora private. Raw real turns belong in ignored local storage,
  and public evidence must use redacted or synthetic data.
- Treat releases as evidence packs, not just tags. A release should carry
  package hashes, verifier output, licensing files, and enough context for a
  reviewer to reproduce the claim.

## Stable Surface

These areas are intended to remain compatible across normal patch releases:

- `ts1` deterministic prompt intent wire format
- `tr1` deterministic reply wire format
- human-readable decode commands for `ts1` and `tr1`
- prompt, reply, and paired-turn benchmark reports
- real-turn capture/import with private raw storage and regenerated redacted
  corpora
- turn evaluation, certification, release-check, and verification evidence packs
- product manifest, doctor, readiness, release-candidate, and release-assets
  workflows
- PolyForm Noncommercial public license, required notice, and separate written
  commercial licensing path

## Experimental Surface

These areas can change more quickly while the evidence improves:

- local-AI sidecar semantic JSON shape
- sidecar prompt templates and model instructions
- sidecar decode templates
- sidecar review, suggestion, and meaning-risk heuristics
- learned alias selection policies
- real-corpus quality budgets and recommended thresholds

Experimental reports must keep saying when token savings alone are not enough.

## v0.1.x Goals

The first patch series should make the existing product easier to evaluate
without expanding the idea beyond recognition.

- Make release verification more automatic, including generated asset hash
  tables for published release docs.
- Improve sidecar meaning-preservation evidence so local-AI compression can be
  judged by round-trip quality, not just shorter JSON.
- Add a guided first-real-corpus workflow for collecting the first 10 to 50
  private turns safely.
- Strengthen regression reports around raw-wire losses and pass-through rows.
- Keep README examples short while moving deeper runbooks into docs.

## v0.2 Goals

The next minor release should focus on real evidence:

- collect and certify larger private redacted turn corpora
- compare deterministic codec performance across multiple tokenizers
- compare sidecar model/counter sweeps with saved before/after evidence
- add stronger corpus sampling and anonymized summary reports
- document what would count as enough evidence for external adoption

## Later Possibilities

These are interesting but should wait until the measurement story is stronger:

- RepoMori pack/snapshot references inside compact intents
- optional editor or chat-side helper for easier capture
- richer semantic loss detection for sidecar round trips
- signed release attestations
- hosted documentation or generated report viewer
- integration examples for non-commercial local use

## Not Goals Yet

- replacing normal English with an unreadable binary format
- claiming universal token savings from synthetic corpora
- making local-AI sidecar output canonical
- adding cloud AI dependencies to the deterministic core
- publishing commercial-use rights through the public license

## Evidence Bar

A feature is not considered product-ready just because it saves tokens on one
example. At minimum, it should have:

- a documented command path
- JSON and markdown output where appropriate
- unit tests or a saved evidence pack
- privacy behavior for real data
- release/readiness coverage when it affects public workflows
- clear wording about whether it is stable or experimental
