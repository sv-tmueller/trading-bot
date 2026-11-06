| Figure | Development (to 2021) | Holdout (2022+) |
|---|---|---|
| CAGR (pre-tax, after costs) | 4.7% | 4.1% |
| CAGR after German tax | 3.7% | 3.0% |
| Max drawdown, and its dates | 19.0% (2015-03-20 to 2016-03-14) | 10.5% (2022-09-27 to 2023-10-27) |
| Calmar (return / max drawdown) | 0.25 | 0.39 |
| Sharpe; target and realised annualised volatility | Sharpe 0.70; target 10.0%, realised 6.9% | Sharpe 0.58; target 10.0%, realised 7.4% |
| Worst calendar year; 2008 and 2020 (development), 2022 (holdout) | worst 2015 -9.6%; 2008 4.1%; 2020 2.3% | worst 2022 -3.9%; 2022 -3.9% |
| Round trips per year, average holding days, max share of time in one ETF | 6.2 round trips/yr; 382.1 avg holding days; 72.0% max share in one ETF | 7.9 round trips/yr; 355.9 avg holding days; 69.5% max share in one ETF |
| Cost drag per year, incl. short-borrow cost; result at double cost | cost drag 0.2%/yr (borrow 0.0%/yr); double cost: CAGR 4.5%, max DD 19.3%, Calmar 0.23 | cost drag 0.3%/yr (borrow 0.0%/yr); double cost: CAGR 3.8%, max DD 10.8%, Calmar 0.35 |
| vs vol-targeted SPY benchmark (Calmar, CAGR, max DD) | benchmark Calmar 0.33, CAGR 7.3%, max DD 22.3%; median after-tax year Calmar 1.13 vs 0.96 (n_w=14) | benchmark Calmar 0.54, CAGR 7.3%, max DD 13.6%; median after-tax year Calmar 0.67 vs 1.17 (n_w=4) |
| DSR (with programme trial count), PBO, bootstrap CI on uplift | DSR 0.5574 over N=37 trials; PBO 0.7110; uplift CI [-0.8951, 0.8488]; dsr 0.5574 < threshold 0.95; pbo 0.7110 >= threshold 0.5; bootstrap ci_low -0.895085 <= 0 | n/a |
| Same rule at 1.5x gross exposure, incl. financing (information only) | CAGR 5.7%, max DD 21.6%, Calmar 0.26 | CAGR 4.0%, max DD 11.7%, Calmar 0.34 |

**Verdict: FAIL**

- drawdown: pass (development 0.1896; holdout 0.1054; cap 0.2000)
- beats_benchmark: pass (median window Calmar candidate 1.1289 (n_w=14) vs benchmark 0.9585 (n_w=14))
- luck: fail (DSR 0.5574 over N=37 trials; PBO 0.7110; uplift CI [-0.8951, 0.8488]; dsr 0.5574 < threshold 0.95; pbo 0.7110 >= threshold 0.5; bootstrap ci_low -0.895085 <= 0)
- holdout: pass (holdout CAGR 0.0411 (need > 0); max drawdown 0.1054)
- activity: fail (round trips per year 6.1686 (min 20); max time share in one ETF 0.7198 (max 0.9000))
