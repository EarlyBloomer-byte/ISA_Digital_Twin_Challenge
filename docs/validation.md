# Estimator validation (60 simulated days, 3 seeds, mean over seeds; simulation only)

| Case | CI MAE (points) | CI bias (points) | Truth within 2 SD | Mean NIS |
|---|---:|---:|---:|---:|
| matched | 0.50 | -0.19 | 64% | 1.13 |
| mismatched | 12.30 | +12.30 | 0% | 1.13 |

NIS near 1 means the filter's stated uncertainty matches its actual innovations; well above 1 means it is overconfident.
Mismatched truth: load exponent 3.2 (twin assumes 4), IRI(D) with beta 1.6 and span 6 (twin assumes 1.3 and 7).
