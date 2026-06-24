"""Humbled Radar Paper Trading."""
import time, json, argparse
from datetime import datetime, date
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict
from utils.futures_data import load_daily, load_intraday, prior_settlement
from strategies.futures_setups import setup_a_golden_reversal, setup_b_gap_vwap, setup_c_vwap_breakout
from indicators.futures_indicators import pivot_points
from risk.futures_sizing import size_contracts, CONTRACT_SPECS

@dataclass
class PaperTrade:
    trade_id: str
    instrument: str
    setup: str
    direction: str
    entry_price: float
    stop_loss: float
    target1: float
    target2: Optional[float]
    contracts: int
    entry_time: str
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0

    def to_dict(self):
        return asdict(self)

class PaperTradeManager:
    def __init__(self, equity: float = 100_000, log_dir: Optional[str] = None):
        self.equity = equity
        self.log_dir = Path(log_dir) if log_dir else Path('.') / 'logs' / 'paper_trades'
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.active_trades = {}
        self.closed_trades = []
        self.daily_pnl = 0.0
        self.trade_count = 0

    def create_trade(self, instrument, setup, direction, entry_price, stop_loss, target1, target2, contracts):
        self.trade_count += 1
        trade_id = f'{date.today().isoformat()}_{self.trade_count}_{instrument}'
        trade = PaperTrade(trade_id, instrument, setup, direction, entry_price, stop_loss, target1, target2, contracts, datetime.now().isoformat())
        self.active_trades[trade_id] = trade
        self._log_trade_event('ENTRY', trade)
        return trade

    def get_summary(self):
        return {
            'date': date.today().isoformat(),
            'active_trades': len(self.active_trades),
            'closed_trades': len(self.closed_trades),
            'total_pnl': self.daily_pnl,
        }

    def _log_trade_event(self, event_type, trade):
        log_file = self.log_dir / f'trades_{date.today().isoformat()}.json'
        entry = {'timestamp': datetime.now().isoformat(), 'event': event_type, 'trade': trade.to_dict()}
        trades = []
        if log_file.exists():
            with open(log_file, 'r') as f:
                trades = json.load(f)
        trades.append(entry)
        with open(log_file, 'w') as f:
            json.dump(trades, f, indent=2)

def run_paper_trading(instruments=['ES', 'NQ'], equity=100_000, scan_interval=300, max_duration=16*3600, log_dir=None):
    manager = PaperTradeManager(equity, log_dir)
    print('Starting Humbled Radar Paper Trading')
    print(f'Instruments: {", ".join(instruments)}')
    print('=' * 50)
