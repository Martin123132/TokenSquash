# TokenSquash Reply Benchmark

- Status: `pass`
- Counter: `tiktoken:o200k_base`
- Adaptive: `True`
- Source: `examples\agent-replies.jsonl`
- Target savings: `0.5%`
- Replies: `10`
- Original tokens: `522`
- Raw wire tokens: `414`
- Squashed tokens: `411`
- Raw wire saved: `108 (20.6897%)`
- Saved tokens: `111`
- Saved percent: `21.2644%`
- Raw wire wins/losses/ties: `8/2/0`
- Adaptive wins/losses/ties: `8/0/2`
- Pass-through rows: `2`

## Rows

| # | Mode | Original | Wire | Squashed | Saved |
|---:|---|---:|---:|---:|---:|
| 1 | compact | 57 | 41 | 41 | 16 (28.0702%) |
| 2 | compact | 58 | 52 | 52 | 6 (10.3448%) |
| 3 | compact | 58 | 51 | 51 | 7 (12.069%) |
| 4 | compact | 55 | 36 | 36 | 19 (34.5455%) |
| 5 | compact | 62 | 44 | 44 | 18 (29.0323%) |
| 6 | passthrough | 40 | 41 | 40 | 0 (0.0%) |
| 7 | compact | 46 | 24 | 24 | 22 (47.8261%) |
| 8 | compact | 47 | 39 | 39 | 8 (17.0213%) |
| 9 | compact | 55 | 40 | 40 | 15 (27.2727%) |
| 10 | passthrough | 44 | 46 | 44 | 0 (0.0%) |
