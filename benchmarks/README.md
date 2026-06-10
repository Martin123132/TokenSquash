# Benchmark Snapshots

These benchmark artifacts are generated from
`examples/messy-coding-prompts.jsonl`, a synthetic starter corpus of 72
coding-agent prompts.

They are regression baselines, not proof of production-wide savings.

| Counter | Raw wire saved | Adaptive saved | Pass-through rows |
|---|---:|---:|---:|
| `heuristic` | `8.8536%` | `10.1331%` | `16` |
| `char4` | `17.4501%` | `17.8613%` | `3` |
| `tiktoken:cl100k_base` | `3.9416%` | `7.5182%` | `31` |
| `tiktoken:o200k_base` | `4.0639%` | `7.6197%` | `30` |

Regenerate locally:

```powershell
python -m tokensquash bench examples\messy-coding-prompts.jsonl --counter heuristic --out benchmarks\messy-heuristic.md
python -m tokensquash bench examples\messy-coding-prompts.jsonl --counter char4 --json --out benchmarks\messy-char4.json
python -m tokensquash bench examples\messy-coding-prompts.jsonl --counter tiktoken:cl100k_base --json --out benchmarks\messy-cl100k.json
python -m tokensquash bench examples\messy-coding-prompts.jsonl --counter tiktoken:o200k_base --json --out benchmarks\messy-o200k.json
```
