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
python -m tokensquash bench examples\coding-prompts.jsonl --json
```

The default counter is dependency-free and approximate. It is meant for quick
local comparisons. Exact model tokenizers are optional so the core experiment
stays lightweight.

For an exact tokenizer backend when `tiktoken` is installed:

```powershell
python -m pip install -e ".[tokenizer]"
python -m tokensquash bench examples\coding-prompts.jsonl --counter tiktoken:cl100k_base
```

Benchmarks use adaptive mode by default. If the compact wire format is longer
than the original prompt, TokenSquash counts that row as pass-through rather
than pretending every prompt should be encoded.

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
- No network calls, no API keys, no model dependency.

## Design Rule

TokenSquash should only claim savings that it can measure. If a compact form
costs more than the original, the benchmark should say so plainly.
