| Figure | Development (to 2021) | Holdout (2022+) |
|---|---|---|
| CAGR (pre-tax, after costs) | 5.1% | -0.5% |
| CAGR after German tax | 3.9% | -1.1% |
| Max drawdown, and its dates | 17.0% (2015-04-24 to 2016-01-11) | 18.7% (2022-04-18 to 2023-11-16) |
| Calmar (return / max drawdown) | 0.30 | -0.02 |
| Sharpe; target and realised annualised volatility | Sharpe 0.80; target 10.0%, realised 6.4% | Sharpe -0.03; target 10.0%, realised 7.2% |
| Worst calendar year; 2008 and 2020 (development), 2022 (holdout) | worst 2015 -10.4%; 2008 5.2%; 2020 3.6% | worst 2022 -12.4%; 2022 -12.4% |
| Round trips per year, average holding days, max share of time in one ETF | 85.7 round trips/yr; 37.2 avg holding days; 74.5% max share in one ETF | 108.4 round trips/yr; 25.6 avg holding days; 69.7% max share in one ETF |
| Cost drag per year, incl. short-borrow cost; result at double cost | cost drag 1.6%/yr (borrow 0.0%/yr); double cost: CAGR 3.5%, max DD 19.5%, Calmar 0.18 | cost drag 2.8%/yr (borrow 0.0%/yr); double cost: CAGR -3.1%, max DD 22.3%, Calmar -0.14 |
| vs vol-targeted SPY benchmark (Calmar, CAGR, max DD) | benchmark Calmar 0.33, CAGR 7.3%, max DD 22.3%; median after-tax year Calmar 0.79 vs 0.96 (n_w=14) | benchmark Calmar 0.58, CAGR 7.8%, max DD 13.6%; median after-tax year Calmar 0.32 vs 1.17 (n_w=4) |
| DSR (with programme trial count), PBO, bootstrap CI on uplift | DSR 0.8843 over N=19 trials; PBO 0.2037; uplift CI [-1.1400, 1.0993]; dsr 0.8843 < threshold 0.95; bootstrap ci_low -1.140015 <= 0 | n/a |
| Same rule at 1.5x gross exposure, incl. financing (information only) | CAGR 6.6%, max DD 20.9%, Calmar 0.32 | CAGR -2.4%, max DD 24.4%, Calmar -0.10 |

**Verdict: FAIL**

- drawdown: pass (development 0.1698; holdout 0.1872; cap 0.2000)
- beats_benchmark: fail (median window Calmar candidate 0.7883 (n_w=14) vs benchmark 0.9585 (n_w=14))
- luck: fail (DSR 0.8843 over N=19 trials; PBO 0.2037; uplift CI [-1.1400, 1.0993]; dsr 0.8843 < threshold 0.95; bootstrap ci_low -1.140015 <= 0)
- holdout: fail (holdout CAGR -0.0046 (need > 0); max drawdown 0.1872)
- activity: pass (round trips per year 85.7436 (min 20); max time share in one ETF 0.7454 (max 0.9000))
