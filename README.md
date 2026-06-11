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

## Compact Replies

`tr1` is the matching compact format for agent replies. It keeps routine result
messages structured so the sidecar can turn them back into normal human text.

```powershell
python -m tokensquash reply encode --summary "added compact reply codec" --file tokensquash/reply.py --file tokensquash/cli.py --verify "unit tests pass" --command "python -m unittest discover -s tests" --risk none
```

Output:

```text
tr1 "added compact reply codec" f=tokensquash/reply.py,tokensquash/cli.py v=t c=pyunit r=0
```

Decode it back:

```powershell
python -m tokensquash reply decode 'tr1 "added compact reply codec" f=tokensquash/reply.py v=t c=pyunit r=0'
```

Benchmark structured reply records:

```powershell
python -m tokensquash reply bench examples\agent-replies.jsonl
python -m tokensquash reply bench examples\agent-replies.jsonl --counter tiktoken:cl100k_base
```

Reply JSONL rows can include structured fields plus the original human reply
text used as the benchmark baseline:

```json
{"status":"done","summary":"added compact reply codec","files":["tokensquash/reply.py"],"verification":["unit tests pass"],"text":"Done. I added the compact reply codec and verified it with unit tests."}
```

Reply wire omits the default `done` status. Common field values use compact
codes, for example `v=t` decodes to `unit tests pass`, `c=pyunit` decodes to
`python -m unittest discover -s tests`, and `r=0` decodes to `none`.

## Benchmark

```powershell
python -m tokensquash bench examples\coding-prompts.jsonl
python -m tokensquash bench examples\messy-coding-prompts.jsonl
python -m tokensquash bench examples\coding-prompts.jsonl --json
python -m tokensquash bench examples\messy-coding-prompts.jsonl --json --out benchmarks\messy-heuristic.json
```

The default counter is dependency-free and approximate. It is meant for quick
local comparisons. Exact model tokenizers are optional so the core experiment
stays lightweight.

For an exact tokenizer backend when `tiktoken` is installed:

```powershell
python -m pip install -e ".[tokenizer]"
python -m tokensquash bench examples\messy-coding-prompts.jsonl --counter tiktoken:cl100k_base
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

Append one turn without hand-editing JSON:

```powershell
python -m tokensquash turns add --prompt "fix the login bug, keep the diff small, run tests" --reply "Done. I fixed the login bug in src/auth.py and verified it with python -m unittest discover -s tests. Risks: none." --changed-file src/auth.py --verify "unit tests pass" --command "python -m unittest discover -s tests" --risk none
```

By default, `turns add` writes to `private-turns\real.jsonl`.
For longer turns, put the text in files and use `--prompt-file` and
`--reply-file`.

```powershell
python -m tokensquash turns validate private-turns\real.jsonl
python -m tokensquash turns stats private-turns\real.jsonl
python -m tokensquash turns redact private-turns\real.jsonl --out private-turns\real.redacted-turns.jsonl
python -m tokensquash turns split private-turns\real.redacted-turns.jsonl --prompts-out prompts\real.prompts.jsonl --replies-out prompts\real.replies.jsonl
python -m tokensquash turns measure private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --target 0
python -m tokensquash turns diagnose private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base
python -m tokensquash turns bench private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --json --out benchmarks\real-turns-cl100k.json
```

`turns measure` validates the corpus, summarizes it, and reports combined
savings plus prompt-side and reply-side savings. `turns diagnose` shows the
largest wins, raw wire losses, and adaptive pass-through rows so the next codec
change has a target. `turns bench` returns the full benchmark payload for saving
as JSON.
For a first measurement run, add `--target 0` if you want the command to exit
successfully even when the corpus does not beat the default `0.5%` target.
When a raw reply has no structured fields, TokenSquash guesses a starter `tr1`
record from obvious files, commands, verification phrases, risks, and next-step
phrases. That heuristic is for measurement, not a claim of perfect translation.

## Install For Local Development

```powershell
python -m pip install -e .
python -m unittest discover -s tests
```

## Current Scope

- Compact coding-agent intent format: `ts1`.
- Compact coding-agent reply format: `tr1`.
- Common reply field-code shortcuts for repeated verification, command, and risk values.
- Deterministic human-request encoder for common coding workflows.
- Decoders back into readable task and result text.
- Local benchmark reports for original versus compact/adaptive prompts and replies.
- Local paired-turn workflow for validating, redacting, splitting, and benchmarking private prompt/reply exports.
- Optional exact-tokenizer benchmarks through `tiktoken`.
- No network calls, no API keys, no model dependency.

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
