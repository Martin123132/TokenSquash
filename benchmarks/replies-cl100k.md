# TokenSquash Reply Benchmark

- Status: `pass`
- Counter: `tiktoken:cl100k_base`
- Adaptive: `True`
- Source: `examples\agent-replies.jsonl`
- Target savings: `0.5%`
- Replies: `10`
- Original tokens: `519`
- Raw wire tokens: `650`
- Squashed tokens: `484`
- Raw wire saved: `-131 (-25.2408%)`
- Saved tokens: `35`
- Saved percent: `6.7437%`
- Raw wire wins/losses/ties: `3/7/0`
- Adaptive wins/losses/ties: `3/0/7`
- Pass-through rows: `7`

## Rows

| # | Mode | Original | Wire | Squashed | Saved |
|---:|---|---:|---:|---:|---:|
| 1 | passthrough | 57 | 66 | 57 | 0 (0.0%) |
| 2 | passthrough | 56 | 82 | 56 | 0 (0.0%) |
| 3 | passthrough | 58 | 65 | 58 | 0 (0.0%) |
| 4 | compact | 55 | 40 | 40 | 15 (27.2727%) |
| 5 | passthrough | 63 | 98 | 63 | 0 (0.0%) |
| 6 | passthrough | 40 | 91 | 40 | 0 (0.0%) |
| 7 | compact | 46 | 39 | 39 | 7 (15.2174%) |
| 8 | passthrough | 45 | 54 | 45 | 0 (0.0%) |
| 9 | compact | 55 | 42 | 42 | 13 (23.6364%) |
| 10 | passthrough | 44 | 73 | 44 | 0 (0.0%) |
