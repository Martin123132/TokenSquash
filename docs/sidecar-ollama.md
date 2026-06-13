# Sidecar Ollama Workflow

The local-AI sidecar is experimental. It can ask a local Ollama model to
propose compact semantic JSON, then TokenSquash measures and reviews whether
the round trip preserved meaning.

The sidecar does not replace the deterministic `ts1` and `tr1` codecs.

## Preview A Request

Use `--dry-run` to inspect the exact Ollama request without calling a model:

```powershell
python -m tokensquash sidecar translate prompt "fix the login bug, keep the diff small, run tests" --model llama3.2:3b --dry-run
```

## Translate

```powershell
python -m tokensquash sidecar translate reply "Done. I fixed login in src/auth.py and tests pass." --model llama3.2:3b --counter chars --json
```

The measured semantic JSON uses compact keys:

- prompt mode: `o`, `q`, `p`, `c`, `v`, `r`
- reply mode: `s`, `m`, `f`, `v`, `c`, `r`, `n`

## Decode

```powershell
python -m tokensquash sidecar decode reply '{"s":"d","m":"fixed login","f":["src/auth.py"]}'
```

Decode is deterministic/template-based so the semantic payload can be inspected
without calling Ollama again.

## Round Trip

```powershell
python -m tokensquash sidecar roundtrip reply "Done. I fixed login in src/auth.py and tests pass." --model llama3.2:3b --counter chars --json
```

Roundtrip reports:

- original text
- semantic JSON
- decoded text
- original tokens
- semantic tokens
- saved tokens
- saved percent
- warnings

## Evaluate A Corpus

```powershell
python -m tokensquash sidecar evaluate private-turns\real.redacted-turns.jsonl --mode both --limit 10 --model llama3.2:3b --counter chars --out-dir private-turns\sidecar-eval --json
```

Use small limits until model behavior is clear.

## Review, Gate, Certify

```powershell
python -m tokensquash sidecar review private-turns\sidecar-eval\evaluation.json
python -m tokensquash sidecar suggestions private-turns\sidecar-eval\review.json
python -m tokensquash sidecar gate private-turns\sidecar-eval\review.json --min-saved-pct 0.5 --max-review-count 0 --json
python -m tokensquash sidecar certify private-turns\sidecar-eval\evaluation.json --out-dir private-turns\sidecar-certification --json
```

Use [sidecar-meaning-rubric.md](sidecar-meaning-rubric.md) to judge pass,
watch, and fail cases. Token savings alone are not success.

## Sweep Experiments

```powershell
python -m tokensquash sidecar experiment private-turns\real.redacted-turns.jsonl --name llama3-baseline --mode both --limit 20 --model llama3.2:3b --counter chars
python -m tokensquash sidecar sweep private-turns\real.redacted-turns.jsonl --name real-corpus-sweep --mode both --limit 20 --model llama3.2:3b --model another-local-model --counter chars
python -m tokensquash sidecar compare-evaluations private-turns\sidecar-before\evaluation.json private-turns\sidecar-after\evaluation.json
```

Sweeps compare like-for-like runs and skip comparisons where counter, corpus, or
mode differences would make deltas misleading.

## Safety Boundary

Sidecar output should be treated as a proposal. Watch for:

- missing fields
- invented files, commands, or success claims
- generic decoded text
- schema placeholders copied into output
- token savings caused by dropped meaning

Keep local model output under ignored `private-turns/` storage unless it has
been reviewed and intentionally shared.
