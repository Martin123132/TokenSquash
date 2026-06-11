# TokenSquash Reply Benchmark

- Status: `pass`
- Counter: `tiktoken:cl100k_base`
- Adaptive: `True`
- Source: `examples\agent-replies.jsonl`
- Target savings: `0.5%`
- Replies: `10`
- Original tokens: `519`
- Raw wire tokens: `391`
- Squashed tokens: `391`
- Raw wire saved: `128 (24.6628%)`
- Saved tokens: `128`
- Saved percent: `24.6628%`
- Raw wire wins/losses/ties: `9/0/1`
- Adaptive wins/losses/ties: `9/0/1`
- Pass-through rows: `1`

## Rows

| # | Mode | Original | Wire | Squashed | Saved |
|---:|---|---:|---:|---:|---:|
| 1 | compact | 57 | 36 | 36 | 21 (36.8421%) |
| 2 | compact | 56 | 48 | 48 | 8 (14.2857%) |
| 3 | compact | 58 | 48 | 48 | 10 (17.2414%) |
| 4 | compact | 55 | 36 | 36 | 19 (34.5455%) |
| 5 | compact | 63 | 40 | 40 | 23 (36.5079%) |
| 6 | passthrough | 40 | 40 | 40 | 0 (0.0%) |
| 7 | compact | 46 | 24 | 24 | 22 (47.8261%) |
| 8 | compact | 45 | 38 | 38 | 7 (15.5556%) |
| 9 | compact | 55 | 40 | 40 | 15 (27.2727%) |
| 10 | compact | 44 | 41 | 41 | 3 (6.8182%) |
