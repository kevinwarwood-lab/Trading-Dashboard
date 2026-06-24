"""Generate and POST structured JSON briefs for the Paperclip CAS dashboard."""
import requests
from typing import Optional


def generate_brief(
    signals: list,
    bias: str,
    instrument: str,
    account_equity: float,
    date_str: str,
) -> dict:
    """Build a structured brief dict ready for the CAS dashboard."""
    from risk.futures_sizing import size_contracts, CONTRACT_SPECS

    signal_list = []
    for sig in signals:
        spec = CONTRACT_SPECS.get(sig.instrument, CONTRACT_SPECS["ES"])
        contracts = size_contracts(account_equity, sig.entry, sig.stop, sig.instrument)
        risk_pts = abs(sig.entry - sig.stop)
        dollar_risk = contracts * risk_pts * spec["point_value"]
        signal_list.append({
            "setup": sig.setup,
            "direction": sig.direction,
            "entry": sig.entry,
            "stop": sig.stop,
            "target1": sig.target1,
            "target2": sig.target2,
            "rr": round(sig.rr, 2),
            "contracts": contracts,
            "dollar_risk": round(dollar_risk, 2),
        })

    return {
        "agent": "humbled_radar",
        "version": "1.0",
        "instrument": instrument,
        "date": date_str,
        "bias": bias,
        "account_equity": account_equity,
        "signals": signal_list,
        "risk_summary": {
            "max_risk_per_trade": "1%",
            "daily_halt_pct": "3%",
            "min_rr": 2.0,
        },
        "confluence_levels": {},
        "status": "ready_for_review",
    }


def post_brief(brief_dict: dict, url: str = "http://localhost:3100/CAS/dashboard") -> Optional[requests.Response]:
    """POST brief to CAS dashboard; silent fail on any error."""
    try:
        resp = requests.post(url, json=brief_dict, timeout=5)
        return resp
    except Exception:
        return None
