# TokenSquash Benchmark

- Status: `pass`
- Counter: `tiktoken:cl100k_base`
- Adaptive: `True`
- Source: `examples\messy-coding-prompts.jsonl`
- Target savings: `0.5%`
- Prompts: `72`
- Original tokens: `1370`
- Raw wire tokens: `1316`
- Squashed tokens: `1267`
- Raw wire saved: `54 (3.9416%)`
- Saved tokens: `103`
- Saved percent: `7.5182%`
- Raw wire wins/losses/ties: `41/18/13`
- Adaptive wins/losses/ties: `41/0/31`
- Pass-through rows: `31`

## Rows

| # | Mode | Original | Wire | Squashed | Saved |
|---:|---|---:|---:|---:|---:|
| 1 | passthrough | 2 | 4 | 2 | 0 (0.0%) |
| 2 | passthrough | 2 | 16 | 2 | 0 (0.0%) |
| 3 | passthrough | 2 | 4 | 2 | 0 (0.0%) |
| 4 | compact | 24 | 20 | 20 | 4 (16.6667%) |
| 5 | compact | 25 | 16 | 16 | 9 (36.0%) |
| 6 | compact | 28 | 26 | 26 | 2 (7.1429%) |
| 7 | compact | 26 | 23 | 23 | 3 (11.5385%) |
| 8 | passthrough | 20 | 20 | 20 | 0 (0.0%) |
| 9 | passthrough | 26 | 27 | 26 | 0 (0.0%) |
| 10 | passthrough | 17 | 18 | 17 | 0 (0.0%) |
| 11 | compact | 25 | 20 | 20 | 5 (20.0%) |
| 12 | compact | 24 | 22 | 22 | 2 (8.3333%) |
| 13 | compact | 24 | 23 | 23 | 1 (4.1667%) |
| 14 | compact | 22 | 18 | 18 | 4 (18.1818%) |
| 15 | passthrough | 15 | 15 | 15 | 0 (0.0%) |
| 16 | compact | 23 | 20 | 20 | 3 (13.0435%) |
| 17 | compact | 18 | 17 | 17 | 1 (5.5556%) |
| 18 | passthrough | 19 | 24 | 19 | 0 (0.0%) |
| 19 | compact | 20 | 18 | 18 | 2 (10.0%) |
| 20 | compact | 25 | 18 | 18 | 7 (28.0%) |
| 21 | compact | 18 | 16 | 16 | 2 (11.1111%) |
| 22 | compact | 26 | 21 | 21 | 5 (19.2308%) |
| 23 | compact | 24 | 18 | 18 | 6 (25.0%) |
| 24 | compact | 23 | 22 | 22 | 1 (4.3478%) |
| 25 | compact | 22 | 20 | 20 | 2 (9.0909%) |
| 26 | compact | 25 | 23 | 23 | 2 (8.0%) |
| 27 | compact | 19 | 18 | 18 | 1 (5.2632%) |
| 28 | passthrough | 24 | 25 | 24 | 0 (0.0%) |
| 29 | compact | 19 | 18 | 18 | 1 (5.2632%) |
| 30 | compact | 25 | 24 | 24 | 1 (4.0%) |
| 31 | compact | 18 | 15 | 15 | 3 (16.6667%) |
| 32 | passthrough | 16 | 18 | 16 | 0 (0.0%) |
| 33 | compact | 21 | 20 | 20 | 1 (4.7619%) |
| 34 | passthrough | 19 | 19 | 19 | 0 (0.0%) |
| 35 | passthrough | 18 | 19 | 18 | 0 (0.0%) |
| 36 | compact | 18 | 16 | 16 | 2 (11.1111%) |
| 37 | passthrough | 18 | 23 | 18 | 0 (0.0%) |
| 38 | compact | 21 | 19 | 19 | 2 (9.5238%) |
| 39 | passthrough | 13 | 13 | 13 | 0 (0.0%) |
| 40 | compact | 18 | 17 | 17 | 1 (5.5556%) |
| 41 | compact | 19 | 16 | 16 | 3 (15.7895%) |
| 42 | passthrough | 16 | 16 | 16 | 0 (0.0%) |
| 43 | compact | 22 | 21 | 21 | 1 (4.5455%) |
| 44 | compact | 18 | 15 | 15 | 3 (16.6667%) |
| 45 | passthrough | 18 | 18 | 18 | 0 (0.0%) |
| 46 | compact | 18 | 17 | 17 | 1 (5.5556%) |
| 47 | compact | 21 | 19 | 19 | 2 (9.5238%) |
| 48 | passthrough | 15 | 15 | 15 | 0 (0.0%) |
| 49 | compact | 22 | 20 | 20 | 2 (9.0909%) |
| 50 | passthrough | 16 | 16 | 16 | 0 (0.0%) |
| 51 | compact | 17 | 16 | 16 | 1 (5.8824%) |
| 52 | passthrough | 14 | 17 | 14 | 0 (0.0%) |
| 53 | compact | 20 | 17 | 17 | 3 (15.0%) |
| 54 | compact | 23 | 22 | 22 | 1 (4.3478%) |
| 55 | passthrough | 18 | 20 | 18 | 0 (0.0%) |
| 56 | passthrough | 21 | 24 | 21 | 0 (0.0%) |
| 57 | passthrough | 16 | 16 | 16 | 0 (0.0%) |
| 58 | compact | 18 | 16 | 16 | 2 (11.1111%) |
| 59 | compact | 16 | 14 | 14 | 2 (12.5%) |
| 60 | passthrough | 18 | 18 | 18 | 0 (0.0%) |
| 61 | passthrough | 18 | 18 | 18 | 0 (0.0%) |
| 62 | compact | 19 | 17 | 17 | 2 (10.5263%) |
| 63 | compact | 16 | 15 | 15 | 1 (6.25%) |
| 64 | passthrough | 22 | 22 | 22 | 0 (0.0%) |
| 65 | passthrough | 22 | 22 | 22 | 0 (0.0%) |
| 66 | compact | 15 | 14 | 14 | 1 (6.6667%) |
| 67 | passthrough | 19 | 21 | 19 | 0 (0.0%) |
| 68 | passthrough | 16 | 17 | 16 | 0 (0.0%) |
| 69 | passthrough | 12 | 13 | 12 | 0 (0.0%) |
| 70 | compact | 17 | 12 | 12 | 5 (29.4118%) |
| 71 | passthrough | 16 | 18 | 16 | 0 (0.0%) |
| 72 | passthrough | 20 | 21 | 20 | 0 (0.0%) |
