# TokenSquash Reply Benchmark

- Status: `pass`
- Counter: `tiktoken:o200k_base`
- Adaptive: `True`
- Source: `examples\agent-replies.jsonl`
- Target savings: `0.5%`
- Replies: `10`
- Original tokens: `522`
- Raw wire tokens: `655`
- Squashed tokens: `487`
- Raw wire saved: `-133 (-25.4789%)`
- Saved tokens: `35`
- Saved percent: `6.705%`
- Raw wire wins/losses/ties: `3/7/0`
- Adaptive wins/losses/ties: `3/0/7`
- Pass-through rows: `7`

## Rows

| # | Mode | Original | Wire | Squashed | Saved |
|---:|---|---:|---:|---:|---:|
| 1 | passthrough | 57 | 67 | 57 | 0 (0.0%) |
| 2 | passthrough | 58 | 83 | 58 | 0 (0.0%) |
| 3 | passthrough | 58 | 66 | 58 | 0 (0.0%) |
| 4 | compact | 55 | 40 | 40 | 15 (27.2727%) |
| 5 | passthrough | 62 | 97 | 62 | 0 (0.0%) |
| 6 | passthrough | 40 | 93 | 40 | 0 (0.0%) |
| 7 | compact | 46 | 39 | 39 | 7 (15.2174%) |
| 8 | passthrough | 47 | 54 | 47 | 0 (0.0%) |
| 9 | compact | 55 | 42 | 42 | 13 (23.6364%) |
| 10 | passthrough | 44 | 74 | 44 | 0 (0.0%) |
