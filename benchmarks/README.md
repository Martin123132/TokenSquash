# Benchmark Snapshots

The prompt benchmark artifacts are generated from
`examples/messy-coding-prompts.jsonl`, a synthetic starter corpus of 72
coding-agent prompts. The reply benchmark artifacts are generated from
`examples/agent-replies.jsonl`, a synthetic starter corpus of 10 agent replies.

They are regression baselines, not proof of production-wide savings.

| Counter | Raw wire saved | Adaptive saved | Pass-through rows |
|---|---:|---:|---:|
| `heuristic` | `9.0072%` | `10.3378%` | `15` |
| `char4` | `17.8026%` | `18.2139%` | `3` |
| `tiktoken:cl100k_base` | `4.2336%` | `7.5912%` | `30` |
| `tiktoken:o200k_base` | `4.3541%` | `7.6923%` | `29` |

## Reply Baselines

| Counter | Raw wire saved | Adaptive saved | Pass-through rows |
|---|---:|---:|---:|
| `tiktoken:cl100k_base` | `24.6628%` | `24.6628%` | `1` |
| `tiktoken:o200k_base` | `24.5211%` | `24.7126%` | `1` |

Regenerate locally:

```powershell
python -m tokensquash bench examples\messy-coding-prompts.jsonl --counter heuristic --out benchmarks\messy-heuristic.md
python -m tokensquash bench examples\messy-coding-prompts.jsonl --counter char4 --json --out benchmarks\messy-char4.json
python -m tokensquash bench examples\messy-coding-prompts.jsonl --counter tiktoken:cl100k_base --json --out benchmarks\messy-cl100k.json
python -m tokensquash bench examples\messy-coding-prompts.jsonl --counter tiktoken:o200k_base --json --out benchmarks\messy-o200k.json
python -m tokensquash reply bench examples\agent-replies.jsonl --counter tiktoken:cl100k_base --json --out benchmarks\replies-cl100k.json
python -m tokensquash reply bench examples\agent-replies.jsonl --counter tiktoken:o200k_base --json --out benchmarks\replies-o200k.json
```

Verify committed baselines against freshly regenerated outputs:

```powershell
python -m tokensquash baselines verify
python -m tokensquash baselines verify --include-exact-tokenizer
```
