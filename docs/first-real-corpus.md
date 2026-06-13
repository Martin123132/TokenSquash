# First Real Corpus Guide

Use this guide when you want the first useful local TokenSquash measurement
from real prompt/reply turns. The target is 10 ordinary coding-agent turns,
captured locally, redacted, measured, and reviewed without committing raw data.

## Privacy Boundary

Raw turns belong under ignored local storage:

- `private-turns/`
- `private-prompts/`
- `private-aliases/`

Do not commit raw private prompts, replies, local model output, credentials,
customer data, or commercially sensitive repository details. Redaction helps,
but it is not a guarantee. Review redacted files before sharing them.

## Capture 10 Turns

Start by preparing the ignored local folders:

```powershell
python -m tokensquash init
```

Capture one turn at a time. Use inline text for short examples:

```powershell
python -m tokensquash turns capture --prompt "fix the login bug, keep the diff small, run tests" --reply "Done. I fixed the login bug in src/auth.py and verified it with python -m unittest discover -s tests. Risks: none." --changed-file src/auth.py --verify "unit tests pass" --command "python -m unittest discover -s tests" --risk none --evaluate --counter tiktoken:cl100k_base
```

Use files for real turns that are long enough to be awkward on the command
line:

```powershell
python -m tokensquash turns capture --prompt-file private-turns\capture\turn-001.prompt.txt --reply-file private-turns\capture\turn-001.reply.txt --evaluate --counter tiktoken:cl100k_base
```

Repeat until `private-turns\real.jsonl` contains about 10 turns. Ten turns is
not proof of broad savings, but it is enough to reveal obvious wins, losses,
privacy findings, and repeated patterns.

## Review The Corpus

Validate both the raw private corpus and the regenerated redacted corpus:

```powershell
python -m tokensquash turns validate private-turns\real.jsonl
python -m tokensquash turns validate private-turns\real.redacted-turns.jsonl
python -m tokensquash turns stats private-turns\real.redacted-turns.jsonl
```

Build a compact report:

```powershell
python -m tokensquash turns report private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --json > private-turns\real-report.json
python -m tokensquash turns suggestions private-turns\real-report.json
```

Read the report before changing the codec. Focus on:

- top saved turns
- raw-wire losses
- adaptive pass-through rows
- privacy findings
- repeated paths, commands, risks, and verification phrases

## Certify A Baseline

When the first 10-turn corpus looks clean enough to compare against future
work, write a durable certification pack:

```powershell
python -m tokensquash turns certify private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --out-dir private-turns\certification --json
```

For release-impact work, run the turn release check against a source-controlled
quality budget:

```powershell
python -m tokensquash turns release-check private-turns\real.redacted-turns.jsonl --budget examples\quality-budget.json --history private-turns\certification --counter tiktoken:cl100k_base --out-dir private-turns\release-check --json
python -m tokensquash turns verify-release private-turns\release-check --require-release-pass --json
```

Use `--target 0` on early exploratory measurement commands when the goal is to
learn rather than pass a savings gate.

## Optional Sidecar Pass

Only evaluate the experimental local-AI sidecar after the deterministic
redacted corpus looks sane:

```powershell
python -m tokensquash sidecar evaluate private-turns\real.redacted-turns.jsonl --mode both --limit 10 --model llama3.2:3b --counter chars --out-dir private-turns\sidecar-eval --json
python -m tokensquash sidecar review private-turns\sidecar-eval\evaluation.json
python -m tokensquash sidecar suggestions private-turns\sidecar-eval\review.json
```

Sidecar token savings are not enough. Inspect the decoded meaning and warnings
with the [sidecar meaning rubric](sidecar-meaning-rubric.md) before treating a
sidecar experiment as useful.
