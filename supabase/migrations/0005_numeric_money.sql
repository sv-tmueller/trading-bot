-- Store price/money columns as exact decimals (numeric) instead of binary float
-- (double precision) for audit/dashboard/P&L fidelity (issue #242). Additive:
-- ALTER ... USING casts existing rows in place (no data loss). qty stays integer
-- (whole shares). No trade decision changes — the regime comparison is computed
-- in TypeScript before storage; these columns are forensic/dashboard only.

alter table regime_state
  alter column spy_close            type numeric(14,4) using spy_close::numeric(14,4),
  alter column spy_sma200           type numeric(14,4) using spy_sma200::numeric(14,4),
  alter column position_drawdown_pct type numeric(10,6) using position_drawdown_pct::numeric(10,6);

alter table trades
  alter column fill_price type numeric(14,4) using fill_price::numeric(14,4);
