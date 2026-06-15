# Real Turn Workflow

Use this workflow to measure real AI-agent prompt/reply turns locally. Raw
turns stay in ignored private storage. Redacted turns are measured, gated, and
certified.

## Storage Rule

Keep real data under ignored folders:

- `private-turns/`
- `private-prompts/`
- `private-aliases/`
- `turns/`
- `prompts/`
- `aliases/`

Do not commit raw private prompts, replies, local model output, credentials, or
commercially sensitive repository details.

## Initialize Local Storage

```powershell
python -m tokensquash init
```

This prepares local private folders and `.gitignore` rules.

## Capture One Turn

```powershell
python -m tokensquash turns capture --prompt "fix the login bug, keep the diff small, run tests" --reply "Done. I fixed the login bug in src/auth.py and verified it with python -m unittest discover -s tests. Risks: none." --changed-file src/auth.py --verify "unit tests pass" --command "python -m unittest discover -s tests" --risk none --evaluate --counter tiktoken:cl100k_base
```

Defaults:

- raw output: `private-turns\real.jsonl`
- redacted output: `private-turns\real.redacted-turns.jsonl`
- evaluation output with `--evaluate`: `private-turns\eval-real`

For longer turns:

```powershell
python -m tokensquash turns capture --prompt-file private-turns\capture\turn-001.prompt.txt --reply-file private-turns\capture\turn-001.reply.txt --evaluate --counter tiktoken:cl100k_base
```

For an existing export:

```powershell
python -m tokensquash turns import exports\turns.jsonl --evaluate --counter tiktoken:cl100k_base
```

## Validate And Summarize

```powershell
python -m tokensquash turns validate private-turns\real.jsonl
python -m tokensquash turns validate private-turns\real.redacted-turns.jsonl
python -m tokensquash turns stats private-turns\real.redacted-turns.jsonl
python -m tokensquash turns scorecard private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --json --out private-turns\scorecards\current.json
```

Redaction is a safety net, not a privacy guarantee. Review redacted corpora
before sharing them.

## Report And Diagnose

```powershell
python -m tokensquash turns report private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --json > private-turns\real-report.json
python -m tokensquash turns suggestions private-turns\real-report.json
python -m tokensquash turns diagnose private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base
python -m tokensquash turns mine private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base
```

Review:

- corpus growth milestone: `seed`, `smoke`, `early_pattern`, or
  `benchmark_ready`
- top saved turns
- raw-wire losses
- adaptive pass-through rows
- privacy findings
- repeated commands, paths, risks, and verification phrases
- sidecar pass/watch/fail counts when review evidence is present

## Gate And Certify

```powershell
python -m tokensquash turns gate private-turns\eval-real\evaluation.json --min-saved-pct 0.5 --max-privacy-findings 0 --json
python -m tokensquash turns certify private-turns\real.redacted-turns.jsonl --counter tiktoken:cl100k_base --out-dir private-turns\certification --json
```

Compare saved certification packs after a codec or documentation change:

```powershell
python -m tokensquash turns compare-scorecards private-turns\scorecards\v0.1.1.json private-turns\scorecards\current.json
python -m tokensquash turns scorecard-history private-turns\scorecards\v0.1.1.json private-turns\scorecards\current.json private-turns\scorecards\latest.json
python -m tokensquash turns compare-certifications private-turns\cert-before\certification.json private-turns\cert-after\certification.json
python -m tokensquash turns certification-history private-turns\cert-before private-turns\cert-after private-turns\cert-latest
```

## Release-Impact Check

```powershell
python -m tokensquash turns release-check private-turns\real.redacted-turns.jsonl --budget examples\quality-budget.json --history private-turns\certification --counter tiktoken:cl100k_base --out-dir private-turns\release-check --json
python -m tokensquash turns verify-release private-turns\release-check --require-release-pass --json
```

Use [first-real-corpus.md](first-real-corpus.md) for a shorter 10-turn first
measurement pass.
