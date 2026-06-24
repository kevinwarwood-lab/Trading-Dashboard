import math
from dataclasses import dataclass, field
from typing import Optional

CONTRACT_SPECS = {
    "ES":  {"point_value": 50,  "tick": 0.25, "tick_value": 12.50},
    "NQ":  {"point_value": 20,  "tick": 0.25, "tick_value":  5.00},
    "MES": {"point_value":  5,  "tick": 0.25, "tick_value":  1.25},
    "MNQ": {"point_value":  2,  "tick": 0.25, "tick_value":  0.50},
}

_MICRO_MAP = {"ES": "MES", "NQ": "MNQ"}


def size_contracts(
    account_equity: float,
    entry: float,
    stop: float,
    instrument: str,
    risk_pct: float = 0.01,
    use_micro: bool = False,
) -> int:
    key = _MICRO_MAP.get(instrument, instrument) if use_micro else instrument
    spec = CONTRACT_SPECS[key]
    dollar_risk = account_equity * risk_pct
    risk_pts = abs(entry - stop)
    if risk_pts == 0:
        return 0
    contracts = math.floor(dollar_risk / (risk_pts * spec["point_value"]))
    return max(contracts, 0)


def stop_with_buffer(structural_low: float, instrument: str, buffer_ticks: int = 2) -> float:
    tick = CONTRACT_SPECS[instrument]["tick"]
    raw = structural_low - buffer_ticks * tick
    return round(round(raw / tick) * tick, 10)


def scale_out_plan(
    contracts: int,
    entry: float,
    target1: float,
    target2: Optional[float] = None,
) -> list:
    if contracts <= 0:
        return []
    if target2 is None or contracts == 1:
        return [{"contracts": contracts, "target": target1, "action": "close_all"}]
    half = max(1, contracts // 2)
    remainder = contracts - half
    plan = [{"contracts": half, "target": target1, "action": "partial_close"}]
    if remainder > 0:
        plan.append({"contracts": remainder, "target": target2, "action": "close_all"})
    return plan


@dataclass
class TradeSetup:
    symbol: str
    instrument: str
    direction: str
    entry: float
    stop: float
    target1: float
    target2: Optional[float] = None

    @property
    def risk_pts(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward_pts(self) -> float:
        return abs(self.target1 - self.entry)

    @property
    def rr_ratio(self) -> float:
        return self.reward_pts / self.risk_pts if self.risk_pts > 0 else 0.0

    def is_valid(self, min_rr: float = 2.0) -> bool:
        return self.risk_pts > 0 and self.rr_ratio >= min_rr
