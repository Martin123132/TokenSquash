# TokenSquash

TokenSquash is an experiment in saving small percentages of AI-agent tokens by
turning common human task wording into a compact, model-readable protocol.

The goal is not magic binary compression. The goal is a sidecar codec:

```text
human request -> compact intent -> agent work -> compact reply -> human reply
```

Even a small average saving matters when the same workflow is repeated at large
scale. TokenSquash is built benchmark-first so we can prove whether a codec is
helping before making it clever.

## Example

```powershell
python -m tokensquash encode "Please fix the login bug, keep the diff small, run tests, and summarize the files changed."
```

Output:

```text
ts1 f "login bug" c=sd v=t r=m,f
```

Decode it back:

```powershell
python -m tokensquash decode 'ts1 f "login bug" c=sd v=t r=m,f'
```

Show the machine-readable product manifest:

```powershell
python -m tokensquash about --json
```

Show the package, Git, and runtime fingerprint for the current checkout:

```powershell
python -m tokensquash release-info --json
```

Prepare local private folders and `.gitignore` rules for real corpora:

```powershell
python -m tokensquash init
```

## Quick Demo

Run the public paired-turn demo with no private data and no local model:

```powershell
python -m tokensquash demo
```

Check the local install and workspace health:

```powershell
python -m tokensquash doctor
```

Run the stricter product-readiness check when you want the deterministic demo,
package metadata, sample corpus, and certification workflow verified together:

```powershell
python -m tokensquash doctor --strict
```

Run the full local readiness checklist and write a reusable evidence pack:

```powershell
python -m tokensquash readiness --out-dir private-turns\readiness
python -m tokensquash verify-readiness private-turns\readiness --require-readiness-pass
```

Before tagging or sharing a release candidate, install the tokenizer extra and
run the full pre-release gate:

```powershell
python -m pip install -e ".[tokenizer]"
python -m tokensquash release-candidate --out-dir private-turns\release-candidate
python -m tokensquash verify-release-candidate private-turns\release-candidate --require-release-candidate-pass
```

Add `--check-ollama` when you want the doctor to query a local Ollama server
for the experimental sidecar path.

Write a reusable demo report pack:

```powershell
python -m tokensquash demo --counter chars --out-dir private-turns\demo-output --json
```

The default demo uses a packaged copy of the public sample corpus, with the same
rows available for inspection at `examples\sample-turns.jsonl`. It runs the
same deterministic turn-evaluation workflow used for private corpora.

## Compact Replies

`tr1` is the matching compact format for agent replies. It keeps routine result
messages structured so the sidecar can turn them back into normal human text.

```powershell
python -m tokensquash reply encode --summary "added compact reply codec" --file tokensquash/reply.py --file tokensquash/cli.py --verify "unit tests pass" --command "python -m unittest discover -s tests" --risk none
```

Output:

```text
tr1 "added compact reply codec" f=@t/reply.py,@t/cli.py v=t c=pyunit r=0
```

Decode it back:

```powershell
python -m tokensquash reply decode 'tr1 "added compact reply codec" f=tokensquash/reply.py v=t c=pyunit r=0'
```

Benchmark structured reply records:

```powershell
python -m tokensquash reply bench examples\agent-replies.jsonl
python -m tokensquash reply bench examples\agent-replies.jsonl --counter tiktoken:cl100k_base
python -m tokensquash reply mine examples\agent-replies.jsonl --counter tiktoken:cl100k_base
python -m tokensquash reply aliases examples\agent-replies.jsonl --counter tiktoken:cl100k_base --out aliases\session.json
python -m tokensquash reply bench examples\agent-replies.jsonl --aliases aliases\session.json
```

Reply JSONL rows can include structured fields plus the original human reply
text used as the benchmark baseline:

```json
{"status":"done","summary":"added compact reply codec","files":["tokensquash/reply.py"],"verification":["unit tests pass"],"text":"Done. I added the compact reply codec and verified it with unit tests."}
```

Reply wire omits the default `done` status. Common field values use compact
codes, for example `v=t` decodes to `unit tests pass`, `c=pyunit` decodes to
`python -m unittest discover -s tests`, and `r=0` decodes to `none`.
Common file prefixes are aliased inside `f=`, including `@t/` for
`tokensquash/`, `@x/` for `tests/`, `@e/` for `examples/`, `@b/` for
`benchmarks/`, `@g/` for `.github/workflows/`, and `@s/` for `src/`.
`reply mine` scans a reply corpus for repeated commands, verification phrases,
risks, next steps, warnings, and path patterns that may deserve the next compact
code.

Session alias tables let the sidecar learn project-specific file prefixes and
repeated reply field values without changing the `ts1` or `tr1` specs for
everyone. Prompt `p=` paths and reply `f=` paths use the same path aliases. A
table is shared out-of-band by the translator and the agent, then passed with
`--aliases`:

```json
{"schema_version":"tokensquash.aliases.v1","path_prefixes":{"packages/mobile/src/":"@0/"},"field_values":{"commands":{"npm test":"c0"}}}
```

Learned aliases can reveal private repository paths, commands, and workflow
details. Keep real alias tables under `aliases/` or `private-aliases/`; both are
ignored by Git.

```powershell
python -m tokensquash encode "Review packages/mobile/src/screens/login.tsx and summarize files" --aliases aliases\session.json
python -m tokensquash bench prompts\real.redacted.jsonl --aliases aliases\session.json
```

## Benchmark

```powershell
python -m tokensquash bench examples\coding-prompts.jsonl
python -m tokensquash bench examples\messy-coding-prompts.jsonl
python -m tokensquash bench examples\coding-prompts.jsonl --json
python -m tokensquash bench examples\messy-coding-prompts.jsonl --json --out benchmarks\messy-heuristic.json
python -m tokensquash baselines verify
```

The default counter is dependency-free and approximate. It is meant for quick
local comparisons. Exact model tokenizers are optional so the core experiment
stays lightweight.

For an exact tokenizer backend when `tiktoken` is installed:

```powershell
python -m pip install -e ".[tokenizer]"
python -m tokensquash bench examples\messy-coding-prompts.jsonl --counter tiktoken:cl100k_base
python -m tokensquash baselines verify --include-exact-tokenizer
```

Benchmarks use adaptive mode by default. If the compact wire format is longer
than the original prompt, TokenSquash counts that row as pass-through rather
than pretending every prompt should be encoded.

Reports include both raw wire savings and adaptive savings:

- Raw wire savings show whether `ts1` is shorter before any safety policy.
- Adaptive savings show what happens when the sidecar refuses encodings that
  would cost more tokens than the original text.

The current corpora are synthetic starter corpora. They are useful for regression
testing, but they are not proof of production-wide savings.

## Real Prompt Workflow

Use corpus commands before benchmarking real prompts:

```powershell
python -m tokensquash corpus validate prompts\real.jsonl
python -m tokensquash corpus stats prompts\real.jsonl
python -m tokensquash corpus redact prompts\real.jsonl --out prompts\real.redacted.jsonl
python -m tokensquash bench prompts\real.redacted.jsonl --counter tiktoken:cl100k_base --json --out benchmarks\real-cl100k.json
python -m tokensquash compare benchmarks\messy-cl100k.json benchmarks\real-cl100k.json
```

The `prompts/` and `private-prompts/` folders are ignored by Git so local real
corpora do not get committed by accident.

`corpus validate` flags malformed JSONL rows and common privacy risks such as
email addresses, token-looking values, secret assignments, phone numbers, and
user home paths. Redaction is a safety net, not a privacy guarantee; review the
redacted file before sharing it.

JSONL rows can use either `text` or `prompt`:

```json
{"id":"example-001","text":"fix the login bug, keep the diff small, run tests"}
```

## Real Turn Workflow

For paired prompt/reply exports, use a local JSONL turn corpus:

```json
{"id":"turn-001","prompt":"fix the login bug, keep the diff small, run tests","reply":"Done. I fixed the login bug in src/auth.py and verified it with `python -m unittest discover -s tests`. Risks: none."}
```

Keep real files under `turns/` or `private-turns/`; both are ignored by Git.

Capture one real turn without hand-editing JSON. This appends the raw turn to
`private-turns\real.jsonl`, regenerates
`private-turns\real.redacted-turns.jsonl`, and can optionally write a fresh
evaluation pack:

```powershell
python -m tokensquash turns capture --prompt "fix the login bug, keep the diff small, run tests" --reply "Done. I fixed the login bug in src/auth.py and verified it with python -m unittest discover -s tests. Risks: none." --changed-file src/auth.py --verify "unit tests pass" --command "python -m unittest discover -s tests" --risk none --evaluate --counter tiktoken:cl100k_base
```

For longer turns, put the text in files and use `--prompt-file` and
`--reply-file`. `turns add` remains available as the low-level append-only
command when you do not want redaction or evaluation side effects.

You can also paste a complete turn through stdin. Separate the prompt from the
reply with a line containing `---reply---`:

```powershell
@"
fix the login bug, keep the diff small, run tests
---reply---
Done. I fixed the login bug in src/auth.py and verified it with python -m unittest discover -s tests.
"@ | python -m tokensquash turns capture --stdin --evaluate --counter tiktoken:cl100k_base
```

Import an existing JSON or JSONL export in bulk with the same private raw plus
redacted workflow. This appends each imported turn to `private-turns\real.jsonl`,
regenerates `private-turns\real.redacted-turns.jsonl`, and can run evaluation
against the redacted corpus:

```powershell
python -m tokensquash turns import exports\turns.jsonl --evaluate --counter tiktoken:cl100k_base
```

After you build a redacted corpus, run a compact feedback report to review gains
and regressions:

```powershell
python -m tokensquash turns report private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --json > private-turns\real-report.json
```

Compare two saved reports after a codec change:

```powershell
python -m tokensquash turns compare-reports private-turns\report-before.json private-turns\report-after.json
```

Gate a saved report or evaluation when you want a CI-style pass/fail signal:

```powershell
python -m tokensquash turns gate private-turns\eval-real\evaluation.json --min-saved-pct 0.5 --max-privacy-findings 0 --json
```

Certify a redacted corpus when you want one folder containing evaluation,
gate, suggestions, and a top-level certification summary:

```powershell
python -m tokensquash turns certify private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --out-dir private-turns\certification --json
```

Compare two saved certification packs after a release or codec change:

```powershell
python -m tokensquash turns compare-certifications private-turns\cert-before\certification.json private-turns\cert-after\certification.json
```

Summarize a chronological run of saved certification packs:

```powershell
python -m tokensquash turns certification-history private-turns\cert-before private-turns\cert-after private-turns\cert-latest
```

Run the release gate before publishing a codec change:

```powershell
python -m tokensquash turns release-check private-turns\real.redacted-turns.jsonl --budget examples\quality-budget.json --history private-turns\cert-before --out-dir private-turns\release-check --counter tiktoken:cl100k_base --json
```

Verify that a saved release evidence pack is complete and internally readable:

```powershell
python -m tokensquash turns verify-release private-turns\release-check --json
python -m tokensquash turns verify-release private-turns\release-check --require-release-pass --json
```

Turn a saved report into a prioritized codec-improvement checklist:

```powershell
python -m tokensquash turns suggestions private-turns\real-report.json
```

`turns report` defaults to `private-turns\real.redacted-turns.jsonl`, so you can
just run:

```powershell
python -m tokensquash turns report --counter tiktoken:cl100k_base
```

Use this loop:

1. Capture turns with `turns capture`.
2. Run `turns report`.
3. Review top wins, top raw-wire losses, and repeated candidates.
4. Run `turns suggestions` for a short prioritized improvement list.
5. Save a before/after report around codec changes.
6. Run `turns compare-reports` to check whether saved percent improved.
7. Run `turns gate` on the saved report/evaluation before treating it as passing.
8. Run `turns certify` when you need a durable evidence pack.
9. Run `turns compare-certifications` across saved certification packs.
10. Run `turns certification-history` across chronological certification packs to spot regressions.
11. Run `turns release-check` before publishing a codec or measurement change.
12. Run `turns verify-release` on the saved release-check pack before sharing it.
13. Keep iterating with more capture turns.

```powershell
python -m tokensquash turns validate private-turns\real.jsonl
python -m tokensquash turns stats private-turns\real.jsonl
python -m tokensquash turns redact private-turns\real.jsonl --out private-turns\real.redacted-turns.jsonl
python -m tokensquash turns split private-turns\real.redacted-turns.jsonl --prompts-out prompts\real.prompts.jsonl --replies-out prompts\real.replies.jsonl
python -m tokensquash turns evaluate private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --out-dir private-turns\eval-real
python -m tokensquash turns gate private-turns\eval-real\evaluation.json --min-saved-pct 0.5 --max-privacy-findings 0
python -m tokensquash turns certify private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --out-dir private-turns\certification
python -m tokensquash turns compare-certifications private-turns\cert-before\certification.json private-turns\cert-after\certification.json
python -m tokensquash turns certification-history private-turns\cert-before private-turns\cert-after private-turns\cert-latest
python -m tokensquash turns release-check private-turns\real.redacted-turns.jsonl --budget examples\quality-budget.json --history private-turns\cert-before --counter tiktoken:cl100k_base --out-dir private-turns\release-check
python -m tokensquash turns verify-release private-turns\release-check --require-release-pass
python -m tokensquash turns measure private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --target 0
python -m tokensquash turns diagnose private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base
python -m tokensquash turns mine private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base
python -m tokensquash turns aliases private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --out aliases\session.json
python -m tokensquash turns alias-impact private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --target 0
python -m tokensquash turns bench private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --json --out benchmarks\real-turns-cl100k.json
python -m tokensquash turns bench private-turns\real.redacted-turns.jsonl --aliases aliases\session.json --counter tiktoken:cl100k_base
```

`turns capture` is the safest way to build a real local corpus incrementally:
it stores the raw turn privately, rebuilds the redacted corpus, and runs
`turns evaluate` when `--evaluate` is set. `turns import` does the same
raw/redacted/evaluate workflow for a prepared JSON or JSONL turn corpus.
`turns evaluate` runs the measurement workflow in one pass and can write a local
report pack with validation, stats, measure, diagnose, mine, aliases,
alias-impact, and benchmark JSON files.
`turns gate` turns a saved `turns report` JSON or `turns evaluate` output into
a thresholded pass/fail result for saved percent, privacy findings,
pass-through rows, and raw-wire-loss turns.
`turns certify` runs the deterministic evaluation once, derives the compact
report, applies the gate, writes suggestions, and stores the full evidence pack
under one output directory.
`turns compare-certifications` compares saved certification packs across token
savings, gate failures, privacy findings, pass-throughs, raw-wire losses, and
suggestion counts.
`turns certification-history` accepts certification JSON files or certification
output directories in chronological order, then reports net movement, adjacent
regressions, best/worst saved percent, and warnings when the latest pack has
fallen below the best observed result.
`turns release-check` writes a release evidence pack that runs `turns certify`,
strict `doctor`, and optional certification history in one command. A supplied
history regression fails the release check; no history is allowed but reported
as a warning so first-run projects can still get a usable pack. The pack also
writes `quality-budget.json` and `quality-budget-validation.json` so the exact
effective release policy is preserved with the release evidence.
`turns verify-release` audits a saved release-check directory or
`release-check.json` file, verifies the required top-level and nested JSON
schemas plus markdown artifacts, and reports whether the evidence pack is
complete enough to trust.
It can verify a complete pack whose release gate failed; check
`summary.release_status` to distinguish evidence integrity from release
approval.
Use `--require-release-pass` in CI when verification should also fail unless
the saved release-check status is `pass`.
Python automation can use the same release verifier through the package root:

```python
import tokensquash

report = tokensquash.verify_turn_release_pack(
    "private-turns/release-check",
    require_release_pass=True,
)
assert report["status"] in {"pass", "warn"}
```

Pass `--budget` with a `tokensquash.quality_budget.v1` JSON file to keep release
thresholds in source control. The example in `examples\quality-budget.json`
sets saved-percent, privacy, pass-through, raw-wire-loss, history, and doctor
warning budgets; explicit CLI threshold flags override the budget for one run.
Run `budget init --out quality-budget.json` to create a starter project budget.
Run `budget validate examples\quality-budget.json` to check the schema, unknown
keys, and effective defaulted release-check policy before using the file in CI.
`turns measure` validates the corpus, summarizes it, and reports combined
savings plus prompt-side and reply-side savings. `turns diagnose` shows the
largest wins, raw wire losses, and adaptive pass-through rows so the next codec
change has a target. `turns mine` reports repeated reply field values plus
prompt/reply path patterns with estimated token impact. `turns aliases` learns a
session dictionary from prompt paths plus reply-side files, commands, risks,
next steps, and warnings.
`turns alias-impact` learns aliases and compares turn benchmarks with and
without them, including alias setup tokens and break-even corpus count. `turns
bench` returns the full benchmark payload for saving as JSON.
For a first measurement run, add `--target 0` if you want the command to exit
successfully even when the corpus does not beat the default `0.5%` target.
When a raw reply has no structured fields, TokenSquash guesses a starter `tr1`
record from obvious files, commands, verification phrases, risks, and next-step
phrases. That heuristic is for measurement, not a claim of perfect translation.

## Experimental Local AI Sidecar

TokenSquash can also experiment with a local model such as Ollama as an optional
semantic translator. This does not replace the deterministic codec. The local
model proposes compact semantic JSON, and TokenSquash measures whether that
semantic form is actually shorter than the original text.

Preview the exact Ollama request without calling a model:

```powershell
python -m tokensquash sidecar translate prompt "fix the login bug, keep the diff small, run tests" --model llama3.2:3b --dry-run
```

Call a local Ollama server and measure the returned semantic JSON:

```powershell
python -m tokensquash sidecar translate reply "Done. I fixed login in src/auth.py and tests pass." --model llama3.2:3b --counter chars --json
```

Decode a semantic payload back into readable English (for inspection and debugging):

```powershell
python -m tokensquash sidecar decode reply '{"s":"d","m":"fixed login","f":["src/auth.py"]}'
```

Run a full round-trip check: translate then decode so you can inspect meaning loss:

```powershell
python -m tokensquash sidecar roundtrip reply "Done. I fixed login in src/auth.py and tests pass." --model llama3.2:3b --counter chars --json
```

Evaluate a redacted turn corpus in batch. Use `--limit` for a small first run,
then increase it once the local model behavior looks sensible:

```powershell
python -m tokensquash sidecar evaluate private-turns\real.redacted-turns.jsonl --mode both --limit 10 --model llama3.2:3b --counter chars --out-dir private-turns\sidecar-eval --json
```

Run a named experiment when you want TokenSquash to create the folder and write
the evidence pack for you:

```powershell
python -m tokensquash sidecar experiment private-turns\real.redacted-turns.jsonl --name llama3-baseline --mode both --limit 20 --model llama3.2:3b --counter chars
```

This creates a timestamped folder under
`private-turns\sidecar-experiments\` containing `evaluation.json`,
`rows.jsonl`, `summary.md`, and `run.json`.

Run a sweep when you want the same corpus checked across multiple counters,
models, or input corpora. Each run gets its own evidence pack, and the sweep
writes top-level comparisons against the first run when the source, mode, and
counter are like-for-like. Mixed-counter or mixed-corpus comparisons are listed
as skipped so token deltas do not look more meaningful than they are:

```powershell
python -m tokensquash sidecar sweep private-turns\real.redacted-turns.jsonl --name real-corpus-sweep --mode both --limit 20 --model llama3.2:3b --model another-local-model --counter chars
```

Review a saved sidecar evaluation when you need a human inspection checklist for
meaning risk. The command writes `review.json` and `review.md` next to the input
evaluation by default:

```powershell
python -m tokensquash sidecar review private-turns\sidecar-sweeps\real-corpus-sweep\runs\001-realredacted-turns-llama323b-chars\evaluation.json
```

Turn a review report into prioritized tuning suggestions:

```powershell
python -m tokensquash sidecar suggestions private-turns\sidecar-sweeps\real-corpus-sweep\runs\001-realredacted-turns-llama323b-chars\review.json
```

Gate a saved evaluation or review when you want a CI-style pass/fail check:

```powershell
python -m tokensquash sidecar gate private-turns\sidecar-sweeps\real-corpus-sweep\runs\001-realredacted-turns-llama323b-chars\review.json --min-saved-pct 0.5 --max-review-count 0 --json
```

Certify a saved evaluation or review when you want a single folder containing
the review, gate, suggestions, and top-level certification result:

```powershell
python -m tokensquash sidecar certify private-turns\sidecar-sweeps\real-corpus-sweep\runs\001-realredacted-turns-llama323b-chars\evaluation.json --out-dir private-turns\sidecar-certification --json
```

Compare two saved sidecar evaluation reports after changing the semantic prompt,
schema, or local model:

```powershell
python -m tokensquash sidecar compare-evaluations private-turns\sidecar-before\evaluation.json private-turns\sidecar-after\evaluation.json
```

The sidecar command asks the local model for strict compact JSON only. The
measured wire uses short keys to avoid spending tokens on field names, and it
omits a kind field because the command already carries prompt/reply mode. Prompt
mode uses `o`, `q`, `p`, `c`, `v`, and `r` for operation, task gist, paths,
constraints, verification, and return wants. Reply mode uses `s`, `m`, `f`,
`v`, `c`, `r`, and `n` for status, result gist, files, verification, commands,
risks, and next steps. Older payloads that include `k` still decode, and reports
normalize all fields back into readable names for inspection. During live
translation, path/file fields and reply next steps are kept only when they are
anchored in the original text, and obvious reply-side command/test evidence is
recovered from the original reply when the model omits it. This helps catch
local-model invention without changing the deterministic codec. The decoder also
warns when a model copies schema placeholders such as `<=5 words`,
`constraint1`, or `returns:` into the semantic payload, because that can make
token savings look better while meaning quality gets worse. Prompt-mode
translations should keep safety and quality guardrails in `c` rather than
dropping them from a very short `q`.

This is intentionally experimental. A local model can add latency and may
misread intent, so sidecar output should be treated as a proposal, not source of
truth. TokenSquash's deterministic codec remains the canonical format for reply
and prompt exchanges. For this reason, evaluate sidecar usefulness by running
round-trip checks and comparing both token savings and whether the decoded text
still preserves meaning. `sidecar evaluate` writes a batch report with total
savings, warning/failure counts, and best/worst examples when `--out-dir` is
set. `sidecar experiment` wraps that evaluation in a named run folder so real
experiments are easy to repeat and compare. `sidecar sweep` runs a small matrix
of experiments and writes a top-level summary plus comparison files. `sidecar
review` turns a saved evaluation into a row-by-row checklist for suspicious
savings, warnings, missing fields, and generic decoded results. `sidecar
suggestions` groups those review flags into prioritized tuning work. `sidecar
gate` turns a saved evaluation or review into a pass/fail threshold report for
repeatable checks. `sidecar certify` writes all three quality artifacts plus a
top-level certification report so an experiment can be archived or checked in
one step. `sidecar compare-evaluations` reports before/after token deltas
alongside warning and failure deltas, so increased savings do not hide worse
meaning-risk signals.

## Install For Local Development

```powershell
python -m pip install -e .
python -m unittest discover -s tests
```

## Production Readiness Checklist

Before treating a TokenSquash change as product-ready, run the deterministic
checks that do not depend on API keys or a local model:

```powershell
python -m tokensquash readiness --out-dir private-turns\readiness
python -m tokensquash verify-readiness private-turns\readiness --require-readiness-pass
```

That command writes `readiness.json`, `readiness.md`, and the nested doctor,
demo, certification, release-check, and release-verification artifacts. The
verification command audits the saved files and schemas after the pack is
written.

The stricter release-candidate gate also verifies exact-tokenizer benchmark
baselines and builds the package wheel:

```powershell
python -m pip install -e ".[tokenizer]"
python -m tokensquash release-candidate --out-dir private-turns\release-candidate
python -m tokensquash verify-release-candidate private-turns\release-candidate --require-release-candidate-pass
```

Use `--skip-exact-tokenizer` only for local smoke checks where the tokenizer
extra is intentionally not installed. Use the expanded form below when CI or
debugging needs each command separated:

```powershell
python -m unittest discover -s tests
python -m tokensquash about --json
python -m tokensquash release-info --json
python -m tokensquash init --dry-run
python -m tokensquash baselines verify
python -m tokensquash baselines verify --include-exact-tokenizer
python -m tokensquash budget init --out private-turns\quality-budget.json --dry-run --json
python -m tokensquash budget validate examples\quality-budget.json
python -m tokensquash doctor --strict
python -m tokensquash demo --counter chars --out-dir private-turns\demo-output
python -m tokensquash turns certify examples\sample-turns.jsonl --counter chars --out-dir private-turns\certification
python -m tokensquash turns release-check examples\sample-turns.jsonl --counter chars --budget examples\quality-budget.json --history private-turns\certification --out-dir private-turns\release-check
python -m tokensquash turns verify-release private-turns\release-check --require-release-pass
python -m pip wheel . --no-deps -w private-turns\wheel
```

`doctor --strict` writes its certification evidence to
`private-turns\doctor-strict` by default. Use `--strict-out-dir` when CI or a
release process needs the evidence somewhere else.

## Current Scope

- Compact coding-agent intent format: `ts1`.
- Compact coding-agent reply format: `tr1`.
- Common reply field-code shortcuts for repeated verification, command, and risk values.
- Built-in reply file-prefix aliases for common project paths.
- Configurable session alias tables for project-specific prompt/reply path prefixes and repeated reply field values.
- Deterministic human-request encoder for common coding workflows.
- Decoders back into readable task and result text.
- Local benchmark reports for original versus compact/adaptive prompts and replies.
- Committed benchmark baseline verifier for detecting stale public benchmark snapshots.
- Local paired-turn workflow for validating, redacting, splitting, and benchmarking private prompt/reply exports.
- Safe one-command turn capture with raw private storage and regenerated redacted corpora.
- Bulk turn import into private raw storage with regenerated redacted corpora.
- Alias-impact reports for learned session dictionaries.
- Public paired-turn sample corpus and first-run deterministic demo command.
- Machine-readable product manifest for version, commands, schemas, protocols, quality budgets, and readiness checks.
- Release metadata report for package version, Git commit, dirty state, Python runtime, and platform details.
- Idempotent workspace initialization for private corpora, aliases, and ignore rules.
- Local doctor command for install, demo, private-storage, tokenizer, strict readiness, and optional Ollama checks.
- One-command product readiness evidence pack and verifier for tests, strict doctor, demo, certification, release-check, and release verification.
- One-command release-candidate gate and verifier for readiness verification, benchmark baseline freshness, exact-tokenizer baselines, and wheel packaging evidence.
- One-command turn evaluation, certification, comparison, history, release-check, and release-verification report packs for real-corpus measurement.
- Experimental local-AI sidecar round-trip, corpus evaluation, experiment/sweep packs, review reports, tuning suggestions, and evaluation comparison.
- Pattern mining for repeated reply values and path patterns.
- Optional exact-tokenizer benchmarks through `tiktoken`.
- No API keys or model dependency for the deterministic core codec; the optional
  sidecar can call a local Ollama server.

## Future Work

- Collect larger real-world prompt corpora with privacy filtering.
- Compare multiple model tokenizers, not just one encoding.
- Collect larger real-world reply corpora with privacy filtering.
- Improve raw-reply field extraction for paired turn benchmarks.
- Integrate RepoMori pack and snapshot references into compact intents.
- Measure task success as well as token savings.

## Design Rule

TokenSquash should only claim savings that it can measure. If a compact form
costs more than the original, the benchmark should say so plainly.
