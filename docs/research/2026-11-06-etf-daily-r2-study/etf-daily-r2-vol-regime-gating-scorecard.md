| Figure | Development (to 2021) | Holdout (2022+) |
|---|---|---|
| CAGR (pre-tax, after costs) | 5.3% | 4.4% |
| CAGR after German tax | 4.4% | 3.3% |
| Max drawdown, and its dates | 8.3% (2008-05-19 to 2009-06-22) | 10.7% (2022-01-03 to 2022-09-27) |
| Calmar (return / max drawdown) | 0.64 | 0.41 |
| Sharpe; target and realised annualised volatility | Sharpe 1.21; target 10.0%, realised 4.3% | Sharpe 0.74; target 10.0%, realised 6.0% |
| Worst calendar year; 2008 and 2020 (development), 2022 (holdout) | worst 2008 -4.6%; 2008 -4.6%; 2020 6.3% | worst 2022 -7.9%; 2022 -7.9% |
| Round trips per year, average holding days, max share of time in one ETF | 14.4 round trips/yr; 267.5 avg holding days; 85.3% max share in one ETF | 20.2 round trips/yr; 225.0 avg holding days; 89.5% max share in one ETF |
| Cost drag per year, incl. short-borrow cost; result at double cost | cost drag 0.1%/yr (borrow 0.0%/yr); double cost: CAGR 5.2%, max DD 8.5%, Calmar 0.61 | cost drag 0.3%/yr (borrow 0.0%/yr); double cost: CAGR 4.2%, max DD 11.0%, Calmar 0.38 |
| vs vol-targeted SPY benchmark (Calmar, CAGR, max DD) | benchmark Calmar 0.33, CAGR 7.3%, max DD 22.3%; median after-tax year Calmar 2.18 vs 0.96 (n_w=14) | benchmark Calmar 0.54, CAGR 7.3%, max DD 13.6%; median after-tax year Calmar 1.57 vs 1.17 (n_w=4) |
| DSR (with programme trial count), PBO, bootstrap CI on uplift | DSR 0.9806 over N=37 trials; PBO 0.2204; uplift CI [-0.7994, 1.8997]; bootstrap ci_low -0.799434 <= 0 | n/a |
| Same rule at 1.5x gross exposure, incl. financing (information only) | CAGR 7.1%, max DD 12.3%, Calmar 0.57 | CAGR 3.7%, max DD 13.7%, Calmar 0.27 |

**Verdict: FAIL**

- drawdown: pass (development 0.0830; holdout 0.1072; cap 0.2000)
- beats_benchmark: pass (median window Calmar candidate 2.1835 (n_w=14) vs benchmark 0.9585 (n_w=14))
- luck: fail (DSR 0.9806 over N=37 trials; PBO 0.2204; uplift CI [-0.7994, 1.8997]; bootstrap ci_low -0.799434 <= 0)
- holdout: pass (holdout CAGR 0.0441 (need > 0); max drawdown 0.1072)
- activity: fail (round trips per year 14.3934 (min 20); max time share in one ETF 0.8534 (max 0.9000))
