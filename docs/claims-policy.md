# Claims Policy

TokenSquash is benchmark-first. A token-saving claim is only useful when it is
measured, scoped, reproducible, and honest about failures.

This policy covers public README text, release notes, benchmark summaries,
commercial evaluation notes, and sidecar experiment writeups. It is product
evidence guidance, not a replacement for the license terms in
[../LICENSE](../LICENSE) or [../COMMERCIAL-LICENSE.md](../COMMERCIAL-LICENSE.md).
The public license is the PolyForm Noncommercial License 1.0.0.

## Short Rule

Name the evidence. Name the limit.

A valid claim should tell a reader what corpus was measured, which counter was
used, which TokenSquash version or commit produced the result, what warnings or
privacy findings appeared, and where the saved report or release artifact lives.

Token savings alone are not success.

## Supported Claims

TokenSquash can support scoped claims such as:

- this corpus saved `x%` under this counter
- this release candidate produced these wheel, sdist, and artifact hashes
- these rows passed through because compact output was not shorter
- this gate passed or failed under these thresholds
- this sidecar experiment is shorter but still has these review findings

Prefer plain wording:

```text
On the redacted 42-turn local corpus, TokenSquash v0.2.0 saved 1.3% with the
tiktoken:cl100k_base counter. The certification passed with 0 privacy findings
and 3 passthrough rows. See private-turns/certification/certification.json.
```

## Unsupported Claims

Do not claim:

- universal token savings
- guaranteed savings for all prompts, replies, models, teams, or products
- production-scale savings from synthetic examples alone
- meaning preservation from sidecar output without review evidence
- safety for raw private prompts or replies committed to Git
- commercial permission from the public source-available license

Avoid wording like:

```text
TokenSquash reduces AI costs by 10% for agent traffic.
```

That can become true only for a named corpus, counter, workflow, and evidence
pack. Without that context, it is an overclaim.

## Evidence Requirements

Every public savings claim should include:

- corpus identity, size, and whether it is public, redacted, or private
- counter name, such as `chars`, `heuristic`, or `tiktoken:cl100k_base`
- TokenSquash version, release tag, or commit
- command used to generate the report
- report schema and status
- original tokens, compact tokens, saved tokens, and saved percent
- pass-through, win, loss, warning, and privacy-finding counts when available
- quality gate or certification status for release-facing claims
- known limits, especially if the corpus is small, synthetic, or not reviewed

When a compact form costs more than the original, the report should say so. Do
not hide losses behind averages.

## Deterministic Codec Claims

The deterministic `ts1` and `tr1` codecs remain the source of truth.

Claims about the deterministic codec should be tied to reports from commands
such as:

```powershell
python -m tokensquash turns evaluate private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --out-dir private-turns\eval-real
python -m tokensquash turns certify private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --out-dir private-turns\certification
python -m tokensquash turns release-check private-turns\real.redacted-turns.jsonl --budget examples\quality-budget.json --history private-turns\certification --out-dir private-turns\release-check
python -m tokensquash turns claim private-turns\certification\certification.json --corpus-label "redacted local turn corpus"
python -m tokensquash turns claim private-turns\certification\certification.json --claim-only --fail-on-unsupported
python -m tokensquash turns claim private-turns\certification\certification.json --limits-only
```

For public examples, use public or redacted corpora. Keep raw prompts, replies,
aliases, local model output, and customer material in ignored private storage.

Use `--claim-only` when you need a copyable paragraph, `--limits-only` during
release review, and `--fail-on-unsupported` when CI should fail unless the claim
is supported by passed deterministic evidence.

## Sidecar Claims

The local-AI sidecar is experimental. Treat sidecar semantic JSON as a proposal,
not as a canonical protocol.

A sidecar claim needs more than token savings. It should cite:

- `sidecar evaluate` output
- decoded text or representative round trips
- `sidecar review` findings
- `sidecar gate` thresholds and status
- `sidecar certify` evidence for durable claims

Generate cautious wording from saved sidecar evidence with:

```powershell
python -m tokensquash turns claim private-turns\sidecar-certification\certification.json --corpus-label "redacted local sidecar run"
python -m tokensquash turns claim private-turns\sidecar-certification\certification.json --limits-only
```

Use [sidecar-meaning-rubric.md](sidecar-meaning-rubric.md) to classify pass,
watch, and fail rows. If decoded meaning has not been reviewed, call the result
an experiment, not a successful compression method.

## Release Claims

Release claims should point to release evidence, not just a tag.

For a public release, cite:

- release tag and commit
- CI run ids and status
- wheel and sdist hashes
- artifact manifest hash
- release attestation hash
- release-candidate verifier output
- public release-asset verification status

See [release-verification.md](release-verification.md) for the current release
asset evidence format.

## Commercial Claims

The public license is for personal and non-commercial use. Commercial use
requires a separate written license from TWO HANDS NETWORK LTD.

A benchmark result does not grant commercial rights. Commercial evaluation notes
should follow this policy and the [commercial license guide](commercial-license.md):
state who measured the result, what corpus was used, whether AI training or
product integration is involved, and which evidence pack supports the claim.

No commercial license is granted unless agreed in writing by TWO HANDS NETWORK
LTD.
