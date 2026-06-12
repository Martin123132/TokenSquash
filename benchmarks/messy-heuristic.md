# TokenSquash Benchmark

- Status: `pass`
- Counter: `heuristic`
- Adaptive: `True`
- Source: `examples\messy-coding-prompts.jsonl`
- Target savings: `0.5%`
- Prompts: `72`
- Original tokens: `1954`
- Raw wire tokens: `1778`
- Squashed tokens: `1752`
- Raw wire saved: `176 (9.0072%)`
- Saved tokens: `202`
- Saved percent: `10.3378%`
- Raw wire wins/losses/ties: `57/8/7`
- Adaptive wins/losses/ties: `57/0/15`
- Pass-through rows: `15`

## Rows

| # | Mode | Original | Wire | Squashed | Saved |
|---:|---|---:|---:|---:|---:|
| 1 | passthrough | 3 | 4 | 3 | 0 (0.0%) |
| 2 | passthrough | 3 | 18 | 3 | 0 (0.0%) |
| 3 | passthrough | 3 | 3 | 3 | 0 (0.0%) |
| 4 | compact | 37 | 28 | 28 | 9 (24.3243%) |
| 5 | compact | 33 | 21 | 21 | 12 (36.3636%) |
| 6 | compact | 37 | 32 | 32 | 5 (13.5135%) |
| 7 | compact | 38 | 32 | 32 | 6 (15.7895%) |
| 8 | compact | 28 | 26 | 26 | 2 (7.1429%) |
| 9 | compact | 38 | 35 | 35 | 3 (7.8947%) |
| 10 | passthrough | 21 | 21 | 21 | 0 (0.0%) |
| 11 | compact | 36 | 26 | 26 | 10 (27.7778%) |
| 12 | compact | 36 | 32 | 32 | 4 (11.1111%) |
| 13 | compact | 36 | 33 | 33 | 3 (8.3333%) |
| 14 | compact | 32 | 23 | 23 | 9 (28.125%) |
| 15 | compact | 17 | 16 | 16 | 1 (5.8824%) |
| 16 | compact | 34 | 29 | 29 | 5 (14.7059%) |
| 17 | compact | 26 | 25 | 25 | 1 (3.8462%) |
| 18 | passthrough | 26 | 28 | 26 | 0 (0.0%) |
| 19 | compact | 33 | 28 | 28 | 5 (15.1515%) |
| 20 | compact | 27 | 17 | 17 | 10 (37.037%) |
| 21 | compact | 25 | 23 | 23 | 2 (8.0%) |
| 22 | compact | 34 | 28 | 28 | 6 (17.6471%) |
| 23 | compact | 30 | 24 | 24 | 6 (20.0%) |
| 24 | compact | 37 | 34 | 34 | 3 (8.1081%) |
| 25 | compact | 28 | 25 | 25 | 3 (10.7143%) |
| 26 | compact | 33 | 29 | 29 | 4 (12.1212%) |
| 27 | compact | 30 | 26 | 26 | 4 (13.3333%) |
| 28 | compact | 35 | 32 | 32 | 3 (8.5714%) |
| 29 | compact | 27 | 24 | 24 | 3 (11.1111%) |
| 30 | compact | 32 | 30 | 30 | 2 (6.25%) |
| 31 | compact | 26 | 22 | 22 | 4 (15.3846%) |
| 32 | passthrough | 23 | 23 | 23 | 0 (0.0%) |
| 33 | compact | 27 | 25 | 25 | 2 (7.4074%) |
| 34 | compact | 27 | 25 | 25 | 2 (7.4074%) |
| 35 | compact | 24 | 23 | 23 | 1 (4.1667%) |
| 36 | compact | 25 | 22 | 22 | 3 (12.0%) |
| 37 | passthrough | 28 | 31 | 28 | 0 (0.0%) |
| 38 | compact | 33 | 31 | 31 | 2 (6.0606%) |
| 39 | compact | 17 | 16 | 16 | 1 (5.8824%) |
| 40 | compact | 28 | 26 | 26 | 2 (7.1429%) |
| 41 | compact | 29 | 25 | 25 | 4 (13.7931%) |
| 42 | passthrough | 25 | 25 | 25 | 0 (0.0%) |
| 43 | compact | 31 | 29 | 29 | 2 (6.4516%) |
| 44 | compact | 29 | 26 | 26 | 3 (10.3448%) |
| 45 | compact | 24 | 21 | 21 | 3 (12.5%) |
| 46 | compact | 27 | 25 | 25 | 2 (7.4074%) |
| 47 | compact | 32 | 27 | 27 | 5 (15.625%) |
| 48 | compact | 23 | 21 | 21 | 2 (8.6957%) |
| 49 | compact | 28 | 25 | 25 | 3 (10.7143%) |
| 50 | compact | 27 | 26 | 26 | 1 (3.7037%) |
| 51 | compact | 27 | 24 | 24 | 3 (11.1111%) |
| 52 | passthrough | 21 | 22 | 21 | 0 (0.0%) |
| 53 | compact | 29 | 25 | 25 | 4 (13.7931%) |
| 54 | compact | 28 | 26 | 26 | 2 (7.1429%) |
| 55 | passthrough | 24 | 26 | 24 | 0 (0.0%) |
| 56 | passthrough | 28 | 29 | 28 | 0 (0.0%) |
| 57 | compact | 25 | 24 | 24 | 1 (4.0%) |
| 58 | compact | 24 | 21 | 21 | 3 (12.5%) |
| 59 | compact | 25 | 21 | 21 | 4 (16.0%) |
| 60 | compact | 26 | 25 | 25 | 1 (3.8462%) |
| 61 | compact | 26 | 25 | 25 | 1 (3.8462%) |
| 62 | compact | 33 | 30 | 30 | 3 (9.0909%) |
| 63 | compact | 25 | 22 | 22 | 3 (12.0%) |
| 64 | compact | 28 | 27 | 27 | 1 (3.5714%) |
| 65 | compact | 33 | 31 | 31 | 2 (6.0606%) |
| 66 | compact | 23 | 21 | 21 | 2 (8.6957%) |
| 67 | compact | 26 | 25 | 25 | 1 (3.8462%) |
| 68 | passthrough | 25 | 25 | 25 | 0 (0.0%) |
| 69 | passthrough | 18 | 18 | 18 | 0 (0.0%) |
| 70 | compact | 20 | 12 | 12 | 8 (40.0%) |
| 71 | passthrough | 26 | 27 | 26 | 0 (0.0%) |
| 72 | passthrough | 26 | 26 | 26 | 0 (0.0%) |
