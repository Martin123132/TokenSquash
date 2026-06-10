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

## Install For Local Development

```powershell
python -m pip install -e .
python -m unittest discover -s tests
```

## Current Scope

- Compact coding-agent intent format: `ts1`.
- Deterministic human-request encoder for common coding workflows.
- Decoder back into readable task text.
- Local benchmark reports for original versus compact/adaptive prompts.
- Optional exact-tokenizer benchmarks through `tiktoken`.
- No network calls, no API keys, no model dependency.

## Future Work

- Collect larger real-world prompt corpora with privacy filtering.
- Compare multiple model tokenizers, not just one encoding.
- Add compact reply schemas for agent summaries and verification results.
- Integrate RepoMori pack and snapshot references into compact intents.
- Measure task success as well as token savings.

## Design Rule

TokenSquash should only claim savings that it can measure. If a compact form
costs more than the original, the benchmark should say so plainly.
