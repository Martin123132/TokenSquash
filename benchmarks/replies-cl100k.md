# TokenSquash Reply Benchmark

- Status: `pass`
- Counter: `tiktoken:cl100k_base`
- Adaptive: `True`
- Source: `examples\agent-replies.jsonl`
- Target savings: `0.5%`
- Replies: `10`
- Original tokens: `519`
- Raw wire tokens: `411`
- Squashed tokens: `410`
- Raw wire saved: `108 (20.8092%)`
- Saved tokens: `109`
- Saved percent: `21.0019%`
- Raw wire wins/losses/ties: `8/1/1`
- Adaptive wins/losses/ties: `8/0/2`
- Pass-through rows: `2`

## Rows

| # | Mode | Original | Wire | Squashed | Saved |
|---:|---|---:|---:|---:|---:|
| 1 | compact | 57 | 40 | 40 | 17 (29.8246%) |
| 2 | compact | 56 | 52 | 52 | 4 (7.1429%) |
| 3 | compact | 58 | 50 | 50 | 8 (13.7931%) |
| 4 | compact | 55 | 36 | 36 | 19 (34.5455%) |
| 5 | compact | 63 | 44 | 44 | 19 (30.1587%) |
| 6 | passthrough | 40 | 40 | 40 | 0 (0.0%) |
| 7 | compact | 46 | 24 | 24 | 22 (47.8261%) |
| 8 | compact | 45 | 40 | 40 | 5 (11.1111%) |
| 9 | compact | 55 | 40 | 40 | 15 (27.2727%) |
| 10 | passthrough | 44 | 45 | 44 | 0 (0.0%) |
