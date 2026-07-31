# Padder Scalp (PDS-01) Backtest — Micro Futures
5-minute bars, ~60-day yfinance window. Base params: {'atr_len': 14, 'manip_pct': 0.2, 'session_start': '09:30', 'session_end': '11:30', 'zone_pct': 0.2, 'min_run': 3, 'wick_pct': 0.5, 'tower_pct': 0.4, 'arm_bars': 5, 'risk_pct': 0.01, 'stop_mode': 'signal_wick', 'stop_buf_ticks': 2, 'min_rr': 2.0, 'enforce_rr': True, 'flat_at_end': True, 'initial_capital': 10000.0, 'commission_per_contract': 1.24}

## MES=F — Micro E-mini S&P 500
Overrides: {'arm_bars': 4}
- Trades: 7
- Win rate: 42.9%
- Avg R: 0.66
- Total R: 4.62
- Total PnL: $427.31
- Profit factor: 2.04
- Return: 4.27%
- Max drawdown: -4.09%

## MNQ=F — Micro E-mini Nasdaq 100
Overrides: {'arm_bars': 3}
- Trades: 8
- Win rate: 75.0%
- Avg R: 0.68
- Total R: 5.46
- Total PnL: $538.90
- Profit factor: 3.56
- Return: 5.39%
- Max drawdown: -1.72%
