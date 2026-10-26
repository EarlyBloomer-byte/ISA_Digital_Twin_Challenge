# Simulated maintenance policy comparison (180 days, 2 seeds, mean over seeds)

| Policy | Mean CI | Segment-days CI<45 | Pothole-days | Spend (units) | CI range across seeds |
|---|---:|---:|---:|---:|---:|
| None | 54.3 | 704 | 1597 | 0 | 0.2 |
| Fixed rotation | 62.3 | 574 | 1038 | 72 | 0.6 |
| Oracle inspection, 30 d | 65.8 | 268 | 212 | 62 | 0.4 |
| Twin, 30 d | 66.1 | 280 | 246 | 66 | 1.4 |
| Twin, 7 d | 66.2 | 289 | 222 | 61 | 0.1 |

All policies except None get the same budget: 12 units per 30 days, accumulating (patch 1, resurface 12).
Environment (weather, demand, incidents) is identical across policies for a given seed.

**How to quote these results.** They are simulation outcomes under illustrative parameters. Oracle inspection
knows the true state of the road for free every 30 days, so it is an optimistic baseline; the twin's expected
advantage is faster response through continuous monitoring and no inspection cost, not better guessing.
Variability across seeds has not been characterised beyond the range column. Field evidence: none.
