"""
Python port of PADDER-SCALP-01.pine — bar-by-bar, mirrors the Pine logic
exactly (same variable names/roles) so results are directly comparable to
what the strategy would do on TradingView.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


def daily_atr(daily_df: pd.DataFrame, length: int) -> pd.Series:
    h, l, c = daily_df["high"], daily_df["low"], daily_df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def size_qty(equity: float, stop_dist: float, point_value: float, params: dict) -> int:
    """Whole-contract position size. 'fixed_dollar' risks a flat $ amount per
    trade (params['fixed_risk_usd']) regardless of account equity — matches
    what a manual trader actually does when the account is too small for
    stop_dist * point_value to fit a sane % of equity. 'pct_equity' (default)
    is the original equity * risk_pct sizing. Either way, returns an INTEGER
    contract count (floored) — 0 means the setup isn't affordable/skip it,
    not a fractional contract you can't actually place."""
    if stop_dist <= 0:
        return 0
    risk_dollars = params.get("fixed_risk_usd", 0.0) if params.get("risk_mode") == "fixed_dollar" \
        else equity * params["risk_pct"]
    return int(risk_dollars / (stop_dist * point_value))


def prev_day_lookup(daily_df: pd.DataFrame, atr: pd.Series):
    """Given a session date, return (prev_high, prev_low, prev_atr) as of the
    prior completed trading day — mirrors request.security(..., high[1])."""
    dates = daily_df.index.normalize()

    def _lookup(session_date: pd.Timestamp):
        if session_date.tzinfo is not None:
            session_date = session_date.tz_localize(None)
        idx = dates.searchsorted(session_date)
        prev_idx = idx - 1
        if prev_idx < 0:
            return np.nan, np.nan, np.nan
        return (daily_df["high"].iloc[prev_idx],
                daily_df["low"].iloc[prev_idx],
                atr.iloc[prev_idx])

    return _lookup


@dataclass
class Trade:
    symbol: str
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    qty: float
    exit_time: pd.Timestamp = None
    exit_price: float = None
    exit_reason: str = None
    r_multiple: float = None
    pnl: float = None
    leg: str = "full"          # "full" | "tp1" | "runner" — which exit leg this row is
    position_id: int = None    # groups tp1 + runner rows from the same entry


def prep_bars(m5: pd.DataFrame, params: dict):
    """Shared bar arrays + session/weekday columns used by every engine variant.
    `session_weekdays` (default Mon-Fri) lets a box span a window that isn't
    calendar-weekday-aligned — e.g. the Asian open (19:00 ET) trades Sun-Thu
    evenings, not Mon-Fri, since Friday evening ET the market is already
    closed for the weekend."""
    m5 = m5.copy()
    m5["time_of_day"] = m5.index.time
    m5["date"] = m5.index.normalize()
    allowed_wd = set(params.get("session_weekdays", (0, 1, 2, 3, 4)))
    m5["in_weekday"] = m5.index.weekday.isin(allowed_wd)
    sess_start = pd.to_datetime(params["session_start"]).time()
    sess_end = pd.to_datetime(params["session_end"]).time()
    o, h, l, c = m5["open"].values, m5["high"].values, m5["low"].values, m5["close"].values
    return m5, sess_start, sess_end, o, h, l, c


def precompute_signals(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray, params: dict):
    """Momentum runs + John Wick / Power Tower signal-candle flags. Pure
    function of OHLC + params so both the 1-TP and 2-TP engines share it."""
    n = len(o)

    # ---- continuous momentum runs (not reset by session, matches Pine) ----
    down_run = np.zeros(n, dtype=int)
    up_run = np.zeros(n, dtype=int)
    for i in range(n):
        if i == 0:
            continue
        down_run[i] = down_run[i - 1] + 1 if c[i] < o[i] else 0
        up_run[i] = up_run[i - 1] + 1 if c[i] > o[i] else 0

    # ---- signal candle patterns (John Wick / Power Tower) ----
    candle_rng = h - l
    body = np.abs(c - o)
    lo_wick = np.minimum(o, c) - l
    hi_wick = h - np.maximum(o, c)
    prev_rng = np.roll(candle_rng, 1)
    prev_rng[0] = np.nan
    prev_o = np.roll(o, 1)
    prev_c = np.roll(c, 1)
    prev_o[0] = prev_c[0] = np.nan

    wick_pct, tower_pct = params["wick_pct"], params["tower_pct"]
    jw_bull = (candle_rng > 0) & (lo_wick >= wick_pct * candle_rng)
    jw_bear = (candle_rng > 0) & (hi_wick >= wick_pct * candle_rng)
    pt_bull = (c > o) & (prev_c < prev_o) & (prev_rng > 0) & (body >= tower_pct * prev_rng) & (c >= prev_o)
    pt_bear = (c < o) & (prev_c > prev_o) & (prev_rng > 0) & (body >= tower_pct * prev_rng) & (c <= prev_o)

    return down_run, up_run, jw_bull, jw_bear, pt_bull, pt_bear


def run_backtest(symbol: str, m5: pd.DataFrame, daily: pd.DataFrame,
                  tick_size: float, point_value: float, params: dict) -> dict:
    atr = daily_atr(daily, params["atr_len"])
    lookup = prev_day_lookup(daily, atr)

    m5, sess_start, sess_end, o, h, l, c = prep_bars(m5, params)
    n = len(m5)
    down_run, up_run, jw_bull, jw_bear, pt_bull, pt_bear = precompute_signals(o, h, l, c, params)

    zone_pct = params["zone_pct"]
    min_run = params["min_run"]
    arm_bars = params["arm_bars"]
    manip_pct = params["manip_pct"]

    trades: list[Trade] = []
    equity = params["initial_capital"]
    equity_curve = []

    box_top = box_bot = np.nan
    cheater = False
    manip_done = manip_confirmed = False
    f15h = f15l = np.nan
    sess_t0 = None
    box_mid = np.nan

    arm_l = arm_s = 0
    sig_close_l = sig_low_l = np.nan
    sig_close_s = sig_high_s = np.nan

    open_trade: Trade | None = None

    diag = dict(sessions=0, cheater_sessions=0, manip_confirmed_sessions=0,
                bull_signals=0, bear_signals=0,
                confirmed=0, blocked_past_mid=0, blocked_rr=0, blocked_qty=0)

    for i in range(n):
        ts = m5.index[i]
        tod = m5["time_of_day"].iat[i]
        is_weekday = m5["in_weekday"].iat[i]
        in_sess = is_weekday and (sess_start <= tod < sess_end)
        prev_in_sess = False
        if i > 0:
            prev_tod = m5["time_of_day"].iat[i - 1]
            prev_wd = m5["in_weekday"].iat[i - 1]
            prev_in_sess = prev_wd and (sess_start <= prev_tod < sess_end) and m5["date"].iat[i - 1] == m5["date"].iat[i]
        new_sess = in_sess and not prev_in_sess

        # ---- manage an already-open trade EVERY bar (in-session or not) ----
        # A trade must never silently ride past the box close just because it
        # was opened on the session's last bar — flatten as soon as we're no
        # longer in the session, using this bar's open as the fill.
        if open_trade is not None:
            exit_price = exit_reason = None
            if in_sess:
                if open_trade.side == "long":
                    if l[i] <= open_trade.stop_price:
                        exit_price, exit_reason = open_trade.stop_price, "stop"
                    elif h[i] >= open_trade.target_price:
                        exit_price, exit_reason = open_trade.target_price, "target"
                else:
                    if h[i] >= open_trade.stop_price:
                        exit_price, exit_reason = open_trade.stop_price, "stop"
                    elif l[i] <= open_trade.target_price:
                        exit_price, exit_reason = open_trade.target_price, "target"
            elif params["flat_at_end"]:
                exit_price, exit_reason = o[i], "session_end"
            if exit_price is not None:
                open_trade.exit_time = ts
                open_trade.exit_price = exit_price
                open_trade.exit_reason = exit_reason
                risk = abs(open_trade.entry_price - open_trade.stop_price)
                direction = 1 if open_trade.side == "long" else -1
                raw_pnl = direction * (exit_price - open_trade.entry_price) * open_trade.qty * point_value
                comm = 2 * params["commission_per_contract"] * open_trade.qty
                open_trade.pnl = raw_pnl - comm
                open_trade.r_multiple = (direction * (exit_price - open_trade.entry_price) / risk) if risk > 0 else np.nan
                equity += open_trade.pnl
                trades.append(open_trade)
                open_trade = None

        if new_sess:
            pd_h, pd_l, pd_atr = lookup(m5["date"].iat[i])
            manip_thresh = manip_pct * pd_atr if not np.isnan(pd_atr) else np.nan
            cheater = (not np.isnan(pd_h)) and (o[i] > pd_h or o[i] < pd_l)
            box_top = h[i] if cheater else pd_h
            box_bot = l[i] if cheater else pd_l
            manip_done = False
            manip_confirmed = False
            f15h, f15l = h[i], l[i]
            sess_t0 = ts
            arm_l = arm_s = 0
            sig_close_l = sig_low_l = sig_close_s = sig_high_s = np.nan
            diag["sessions"] += 1
            if cheater:
                diag["cheater_sessions"] += 1

        if not in_sess or np.isnan(box_top):
            equity_curve.append(equity)
            continue

        if cheater:
            box_top = max(box_top, h[i])
            box_bot = min(box_bot, l[i])
        box_rng = box_top - box_bot
        box_mid = (box_top + box_bot) / 2.0
        buy_zone_hi = box_bot + zone_pct * box_rng
        sell_zone_lo = box_top - zone_pct * box_rng

        # first-15-minute manipulation measurement (3 x 5m bars)
        if not manip_done:
            if (ts - sess_t0).total_seconds() < 15 * 60:
                f15h, f15l = max(f15h, h[i]), min(f15l, l[i])
            if (ts - sess_t0).total_seconds() + 5 * 60 >= 15 * 60:
                manip_done = True
                manip_confirmed = (f15h - f15l) >= manip_thresh if not np.isnan(manip_thresh) else False
                if manip_confirmed:
                    diag["manip_confirmed_sessions"] += 1

        in_buy_zone = box_rng > 0 and c[i] <= buy_zone_hi
        in_sell_zone = box_rng > 0 and c[i] >= sell_zone_lo
        can_trade = manip_done and manip_confirmed

        bull_signal = can_trade and in_buy_zone and (i > 0 and down_run[i - 1] >= min_run) and (jw_bull[i] or pt_bull[i])
        bear_signal = can_trade and in_sell_zone and (i > 0 and up_run[i - 1] >= min_run) and (jw_bear[i] or pt_bear[i])

        buf = params["stop_buf_ticks"] * tick_size
        long_stop = (box_bot - buf) if params["stop_mode"] == "box_edge" else (sig_low_l - buf)
        short_stop = (box_top + buf) if params["stop_mode"] == "box_edge" else (sig_high_s + buf)

        # ---- entry trigger (only when flat) ----
        if open_trade is None:
            enter_long = can_trade and arm_l > 0 and not np.isnan(sig_close_l) and c[i] > sig_close_l
            enter_short = can_trade and arm_s > 0 and not np.isnan(sig_close_s) and c[i] < sig_close_s

            if enter_long:
                diag["confirmed"] += 1
                stop_dist = c[i] - long_stop
                rr = (box_mid - c[i]) / stop_dist if stop_dist > 0 else np.nan
                if not (stop_dist > 0 and box_mid > c[i]):
                    diag["blocked_past_mid"] += 1   # price already at/through midpoint: no reward left
                elif params["enforce_rr"] and (np.isnan(rr) or rr < params["min_rr"]):
                    diag["blocked_rr"] += 1          # confirmed with room, but R:R below min
                else:
                    qty = size_qty(equity, stop_dist, point_value, params)
                    if qty > 0:
                        open_trade = Trade(symbol, "long", ts, c[i], long_stop, box_mid, qty)
                    else:
                        diag["blocked_qty"] += 1     # passed R:R but 1 contract too expensive
                arm_l = 0
            elif enter_short:
                diag["confirmed"] += 1
                stop_dist = short_stop - c[i]
                rr = (c[i] - box_mid) / stop_dist if stop_dist > 0 else np.nan
                if not (stop_dist > 0 and box_mid < c[i]):
                    diag["blocked_past_mid"] += 1
                elif params["enforce_rr"] and (np.isnan(rr) or rr < params["min_rr"]):
                    diag["blocked_rr"] += 1
                else:
                    qty = size_qty(equity, stop_dist, point_value, params)
                    if qty > 0:
                        open_trade = Trade(symbol, "short", ts, c[i], short_stop, box_mid, qty)
                    else:
                        diag["blocked_qty"] += 1
                arm_s = 0

        # ---- (re)arm / expire signals ----
        if bull_signal:
            sig_close_l, sig_low_l, arm_l = c[i], l[i], arm_bars
            diag["bull_signals"] += 1
        elif arm_l > 0:
            arm_l -= 1

        if bear_signal:
            sig_close_s, sig_high_s, arm_s = c[i], h[i], arm_bars
            diag["bear_signals"] += 1
        elif arm_s > 0:
            arm_s -= 1

        equity_curve.append(equity)

    if open_trade is not None:
        # session ran off the end of the data with a position open — mark to last close
        open_trade.exit_time = m5.index[-1]
        open_trade.exit_price = c[-1]
        open_trade.exit_reason = "data_end"
        risk = abs(open_trade.entry_price - open_trade.stop_price)
        direction = 1 if open_trade.side == "long" else -1
        raw_pnl = direction * (open_trade.exit_price - open_trade.entry_price) * open_trade.qty * point_value
        comm = 2 * params["commission_per_contract"] * open_trade.qty
        open_trade.pnl = raw_pnl - comm
        open_trade.r_multiple = (direction * (open_trade.exit_price - open_trade.entry_price) / risk) if risk > 0 else np.nan
        trades.append(open_trade)

    trades_df = pd.DataFrame([t.__dict__ for t in trades])
    diag["entries_taken"] = len(trades_df)
    return {
        "symbol": symbol,
        "trades": trades_df,
        "final_equity": equity,
        "equity_curve": pd.Series(equity_curve, index=m5.index),
        "diag": diag,
    }


def run_backtest_2tp(symbol: str, m5: pd.DataFrame, daily: pd.DataFrame,
                      tick_size: float, point_value: float, params: dict,
                      tp1_r: float = 1.0, tp1_frac: float = 0.5) -> dict:
    """Same entry logic as run_backtest, but the exit is split into two legs:
    tp1_frac of the position closes at tp1_r * (entry-stop risk distance),
    then the stop on the remaining runner moves to breakeven and it runs to
    the box midpoint (the original single target). If the shared stop is hit
    before TP1 fills, the whole position exits together, same as baseline.
    """
    atr = daily_atr(daily, params["atr_len"])
    lookup = prev_day_lookup(daily, atr)

    m5, sess_start, sess_end, o, h, l, c = prep_bars(m5, params)
    n = len(m5)
    down_run, up_run, jw_bull, jw_bear, pt_bull, pt_bear = precompute_signals(o, h, l, c, params)

    zone_pct = params["zone_pct"]
    min_run = params["min_run"]
    arm_bars = params["arm_bars"]
    manip_pct = params["manip_pct"]

    trades: list[Trade] = []
    equity = params["initial_capital"]
    equity_curve = []

    box_top = box_bot = np.nan
    cheater = False
    manip_done = manip_confirmed = False
    f15h = f15l = np.nan
    sess_t0 = None
    box_mid = np.nan

    arm_l = arm_s = 0
    sig_close_l = sig_low_l = np.nan
    sig_close_s = sig_high_s = np.nan

    diag = dict(sessions=0, cheater_sessions=0, manip_confirmed_sessions=0,
                bull_signals=0, bear_signals=0)

    pos = None          # dict describing the open (possibly 2-legged) position
    next_pos_id = 0

    def _close(exit_price, exit_reason, leg, qty, entry_time, entry_price, orig_stop, side, ts, pos_id):
        nonlocal equity
        risk = abs(entry_price - orig_stop)
        direction = 1 if side == "long" else -1
        raw_pnl = direction * (exit_price - entry_price) * qty * point_value
        comm = 2 * params["commission_per_contract"] * qty
        pnl = raw_pnl - comm
        r_mult = (direction * (exit_price - entry_price) / risk) if risk > 0 else np.nan
        equity += pnl
        trades.append(Trade(symbol, side, entry_time, entry_price, orig_stop, np.nan, qty,
                             exit_time=ts, exit_price=exit_price, exit_reason=exit_reason,
                             r_multiple=r_mult, pnl=pnl, leg=leg, position_id=pos_id))

    for i in range(n):
        ts = m5.index[i]
        tod = m5["time_of_day"].iat[i]
        is_weekday = m5["in_weekday"].iat[i]
        in_sess = is_weekday and (sess_start <= tod < sess_end)
        prev_in_sess = False
        if i > 0:
            prev_tod = m5["time_of_day"].iat[i - 1]
            prev_wd = m5["in_weekday"].iat[i - 1]
            prev_in_sess = prev_wd and (sess_start <= prev_tod < sess_end) and m5["date"].iat[i - 1] == m5["date"].iat[i]
        new_sess = in_sess and not prev_in_sess

        # ---- manage the open position EVERY bar (in-session or not) ----
        if pos is not None:
            side = pos["side"]
            direction = 1 if side == "long" else -1
            if in_sess:
                if not pos["tp1_filled"]:
                    stop_hit = (l[i] <= pos["stop"]) if side == "long" else (h[i] >= pos["stop"])
                    tp1_hit = (h[i] >= pos["tp1_price"]) if side == "long" else (l[i] <= pos["tp1_price"])
                    if stop_hit:
                        _close(pos["stop"], "stop", "full", pos["qty1"] + pos["qty2"],
                               pos["entry_time"], pos["entry_price"], pos["orig_stop"], side, ts, pos["id"])
                        pos = None
                    elif tp1_hit:
                        _close(pos["tp1_price"], "tp1", "tp1", pos["qty1"],
                               pos["entry_time"], pos["entry_price"], pos["orig_stop"], side, ts, pos["id"])
                        pos["tp1_filled"] = True
                        pos["stop"] = pos["entry_price"]  # runner stop -> breakeven
                else:
                    stop_hit = (l[i] <= pos["stop"]) if side == "long" else (h[i] >= pos["stop"])
                    tgt_hit = (h[i] >= pos["target_price"]) if side == "long" else (l[i] <= pos["target_price"])
                    if stop_hit:
                        _close(pos["stop"], "stop_be", "runner", pos["qty2"],
                               pos["entry_time"], pos["entry_price"], pos["orig_stop"], side, ts, pos["id"])
                        pos = None
                    elif tgt_hit:
                        _close(pos["target_price"], "target", "runner", pos["qty2"],
                               pos["entry_time"], pos["entry_price"], pos["orig_stop"], side, ts, pos["id"])
                        pos = None
            elif params["flat_at_end"]:
                if not pos["tp1_filled"]:
                    _close(o[i], "session_end", "full", pos["qty1"] + pos["qty2"],
                           pos["entry_time"], pos["entry_price"], pos["orig_stop"], side, ts, pos["id"])
                else:
                    _close(o[i], "session_end", "runner", pos["qty2"],
                           pos["entry_time"], pos["entry_price"], pos["orig_stop"], side, ts, pos["id"])
                pos = None

        if new_sess:
            pd_h, pd_l, pd_atr = lookup(m5["date"].iat[i])
            manip_thresh = manip_pct * pd_atr if not np.isnan(pd_atr) else np.nan
            cheater = (not np.isnan(pd_h)) and (o[i] > pd_h or o[i] < pd_l)
            box_top = h[i] if cheater else pd_h
            box_bot = l[i] if cheater else pd_l
            manip_done = False
            manip_confirmed = False
            f15h, f15l = h[i], l[i]
            sess_t0 = ts
            arm_l = arm_s = 0
            sig_close_l = sig_low_l = sig_close_s = sig_high_s = np.nan
            diag["sessions"] += 1
            if cheater:
                diag["cheater_sessions"] += 1

        if not in_sess or np.isnan(box_top):
            equity_curve.append(equity)
            continue

        if cheater:
            box_top = max(box_top, h[i])
            box_bot = min(box_bot, l[i])
        box_rng = box_top - box_bot
        box_mid = (box_top + box_bot) / 2.0
        buy_zone_hi = box_bot + zone_pct * box_rng
        sell_zone_lo = box_top - zone_pct * box_rng

        if not manip_done:
            if (ts - sess_t0).total_seconds() < 15 * 60:
                f15h, f15l = max(f15h, h[i]), min(f15l, l[i])
            if (ts - sess_t0).total_seconds() + 5 * 60 >= 15 * 60:
                manip_done = True
                manip_confirmed = (f15h - f15l) >= manip_thresh if not np.isnan(manip_thresh) else False
                if manip_confirmed:
                    diag["manip_confirmed_sessions"] += 1

        in_buy_zone = box_rng > 0 and c[i] <= buy_zone_hi
        in_sell_zone = box_rng > 0 and c[i] >= sell_zone_lo
        can_trade = manip_done and manip_confirmed

        bull_signal = can_trade and in_buy_zone and (i > 0 and down_run[i - 1] >= min_run) and (jw_bull[i] or pt_bull[i])
        bear_signal = can_trade and in_sell_zone and (i > 0 and up_run[i - 1] >= min_run) and (jw_bear[i] or pt_bear[i])

        buf = params["stop_buf_ticks"] * tick_size
        long_stop = (box_bot - buf) if params["stop_mode"] == "box_edge" else (sig_low_l - buf)
        short_stop = (box_top + buf) if params["stop_mode"] == "box_edge" else (sig_high_s + buf)

        # ---- entry trigger (only when flat) ----
        if pos is None:
            enter_long = can_trade and arm_l > 0 and not np.isnan(sig_close_l) and c[i] > sig_close_l
            enter_short = can_trade and arm_s > 0 and not np.isnan(sig_close_s) and c[i] < sig_close_s

            if enter_long:
                stop_dist = c[i] - long_stop
                rr = (box_mid - c[i]) / stop_dist if stop_dist > 0 else np.nan
                if stop_dist > 0 and box_mid > c[i] and (not params["enforce_rr"] or (not np.isnan(rr) and rr >= params["min_rr"])):
                    qty = (equity * params["risk_pct"]) / (stop_dist * point_value)
                    if qty > 0:
                        qty1 = qty * tp1_frac
                        pos = dict(side="long", entry_time=ts, entry_price=c[i], orig_stop=long_stop,
                                   stop=long_stop, tp1_price=c[i] + tp1_r * stop_dist, target_price=box_mid,
                                   qty1=qty1, qty2=qty - qty1, tp1_filled=False, id=next_pos_id)
                        next_pos_id += 1
                arm_l = 0
            elif enter_short:
                stop_dist = short_stop - c[i]
                rr = (c[i] - box_mid) / stop_dist if stop_dist > 0 else np.nan
                if stop_dist > 0 and box_mid < c[i] and (not params["enforce_rr"] or (not np.isnan(rr) and rr >= params["min_rr"])):
                    qty = (equity * params["risk_pct"]) / (stop_dist * point_value)
                    if qty > 0:
                        qty1 = qty * tp1_frac
                        pos = dict(side="short", entry_time=ts, entry_price=c[i], orig_stop=short_stop,
                                   stop=short_stop, tp1_price=c[i] - tp1_r * stop_dist, target_price=box_mid,
                                   qty1=qty1, qty2=qty - qty1, tp1_filled=False, id=next_pos_id)
                        next_pos_id += 1
                arm_s = 0

        if bull_signal:
            sig_close_l, sig_low_l, arm_l = c[i], l[i], arm_bars
            diag["bull_signals"] += 1
        elif arm_l > 0:
            arm_l -= 1

        if bear_signal:
            sig_close_s, sig_high_s, arm_s = c[i], h[i], arm_bars
            diag["bear_signals"] += 1
        elif arm_s > 0:
            arm_s -= 1

        equity_curve.append(equity)

    if pos is not None:
        side = pos["side"]
        if not pos["tp1_filled"]:
            _close(c[-1], "data_end", "full", pos["qty1"] + pos["qty2"],
                   pos["entry_time"], pos["entry_price"], pos["orig_stop"], side, m5.index[-1], pos["id"])
        else:
            _close(c[-1], "data_end", "runner", pos["qty2"],
                   pos["entry_time"], pos["entry_price"], pos["orig_stop"], side, m5.index[-1], pos["id"])

    trades_df = pd.DataFrame([t.__dict__ for t in trades])
    diag["entries_taken"] = trades_df["position_id"].nunique() if not trades_df.empty else 0
    return {
        "symbol": symbol,
        "trades": trades_df,
        "final_equity": equity,
        "equity_curve": pd.Series(equity_curve, index=m5.index),
        "diag": diag,
    }


def aggregate_positions(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Collapse per-leg rows (from run_backtest_2tp) into one row per position,
    so results are directly comparable to the single-TP trade log. Both legs
    share the same risk basis (entry vs. original stop), so the position's
    R-multiple is just the qty-weighted average of the legs' R-multiples."""
    if trades_df.empty:
        return trades_df
    w = trades_df.assign(_wr=trades_df["r_multiple"] * trades_df["qty"])
    agg = w.groupby("position_id").agg(
        symbol=("symbol", "first"), side=("side", "first"),
        entry_time=("entry_time", "first"), entry_price=("entry_price", "first"),
        stop_price=("stop_price", "first"), qty=("qty", "sum"),
        exit_time=("exit_time", "last"), pnl=("pnl", "sum"),
        exit_reason=("exit_reason", lambda s: "+".join(s)),
        _wr=("_wr", "sum"),
    ).reset_index(drop=True)
    agg["r_multiple"] = agg["_wr"] / agg["qty"]
    return agg.drop(columns="_wr")
