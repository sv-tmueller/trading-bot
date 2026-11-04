| Figure | Development (to 2021) | Holdout (2022+) |
|---|---|---|
| CAGR (pre-tax, after costs) | 7.0% | 5.0% |
| CAGR after German tax | 5.8% | 3.3% |
| Max drawdown, and its dates | 16.3% (2008-03-14 to 2008-10-30) | 10.6% (2024-10-18 to 2025-04-08) |
| Calmar (return / max drawdown) | 0.43 | 0.47 |
| Sharpe; target and realised annualised volatility | Sharpe 0.76; target 10.0%, realised 9.6% | Sharpe 0.56; target 10.0%, realised 9.6% |
| Worst calendar year; 2008 and 2020 (development), 2022 (holdout) | worst 2015 -7.4%; 2008 0.0%; 2020 10.1% | worst 2022 -5.5%; 2022 -5.5% |
| Round trips per year, average holding days, max share of time in one ETF | 25.9 round trips/yr; 51.8 avg holding days; 58.5% max share in one ETF | 30.0 round trips/yr; 53.4 avg holding days; 64.7% max share in one ETF |
| Cost drag per year, incl. short-borrow cost; result at double cost | cost drag 0.8%/yr (borrow 0.0%/yr); double cost: CAGR 6.2%, max DD 16.8%, Calmar 0.37 | cost drag 0.8%/yr (borrow 0.0%/yr); double cost: CAGR 4.2%, max DD 11.1%, Calmar 0.38 |
| vs vol-targeted SPY benchmark (Calmar, CAGR, max DD) | benchmark Calmar 0.33, CAGR 7.3%, max DD 22.3%; median after-tax year Calmar 0.70 vs 0.96 (n_w=14) | benchmark Calmar 0.58, CAGR 7.8%, max DD 13.6%; median after-tax year Calmar 0.85 vs 1.17 (n_w=4) |
| DSR (with programme trial count), PBO, bootstrap CI on uplift | DSR 0.8496 over N=19 trials; PBO 0.0869; uplift CI [-1.0565, 0.1874]; dsr 0.8496 < threshold 0.95; bootstrap ci_low -1.056466 <= 0 | n/a |
| Same rule at 1.5x gross exposure, incl. financing (information only) | CAGR 8.0%, max DD 17.8%, Calmar 0.45 | CAGR 4.5%, max DD 13.6%, Calmar 0.33 |

**Verdict: FAIL**

- drawdown: pass (development 0.1626; holdout 0.1061; cap 0.2000)
- beats_benchmark: fail (median window Calmar candidate 0.6978 (n_w=14) vs benchmark 0.9585 (n_w=14))
- luck: fail (DSR 0.8496 over N=19 trials; PBO 0.0869; uplift CI [-1.0565, 0.1874]; dsr 0.8496 < threshold 0.95; bootstrap ci_low -1.056466 <= 0)
- holdout: pass (holdout CAGR 0.0503 (need > 0); max drawdown 0.1061)
- activity: pass (round trips per year 25.9081 (min 20); max time share in one ETF 0.5851 (max 0.9000))
