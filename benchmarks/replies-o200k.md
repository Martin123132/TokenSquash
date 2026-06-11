# TokenSquash Reply Benchmark

- Status: `pass`
- Counter: `tiktoken:o200k_base`
- Adaptive: `True`
- Source: `examples\agent-replies.jsonl`
- Target savings: `0.5%`
- Replies: `10`
- Original tokens: `522`
- Raw wire tokens: `394`
- Squashed tokens: `393`
- Raw wire saved: `128 (24.5211%)`
- Saved tokens: `129`
- Saved percent: `24.7126%`
- Raw wire wins/losses/ties: `9/1/0`
- Adaptive wins/losses/ties: `9/0/1`
- Pass-through rows: `1`

## Rows

| # | Mode | Original | Wire | Squashed | Saved |
|---:|---|---:|---:|---:|---:|
| 1 | compact | 57 | 37 | 37 | 20 (35.0877%) |
| 2 | compact | 58 | 48 | 48 | 10 (17.2414%) |
| 3 | compact | 58 | 49 | 49 | 9 (15.5172%) |
| 4 | compact | 55 | 36 | 36 | 19 (34.5455%) |
| 5 | compact | 62 | 40 | 40 | 22 (35.4839%) |
| 6 | passthrough | 40 | 41 | 40 | 0 (0.0%) |
| 7 | compact | 46 | 24 | 24 | 22 (47.8261%) |
| 8 | compact | 47 | 37 | 37 | 10 (21.2766%) |
| 9 | compact | 55 | 40 | 40 | 15 (27.2727%) |
| 10 | compact | 44 | 42 | 42 | 2 (4.5455%) |
