#!/usr/bin/env python3
"""
Faithful Python port of src/strategies/mnq_orb_v6_2.pine alert flow.

Reads a TradingView-exported 5-min CSV (epoch-seconds time, OHLC, OR cols
optional) and prints the alert log the Pine script would have emitted.

Defaults match the script's input defaults. Override on the CLI if you want
to test alternative settings.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Defaults — mirror Pine input defaults
# ---------------------------------------------------------------------------

TZ = ZoneInfo("America/New_York")

OR_START = (9, 30)
OR_END = (9, 50)           # exclusive — 9:30, 9:35, 9:40, 9:45 are OR bars
SESSION_END = (15, 55)

NARROW_MAX = 120.0
MEDIUM_MAX = 200.0

ENABLE_SHAPE_FILTER = True
ALLOW = {
    "V_SHAPE":     True,
    "INV_V":       True,
    "WEAK_UP":     True,
    "WEAK_DOWN":   False,
    "STRONG_UP":   False,
    "STRONG_DOWN": True,
}

ENABLE_SCORE_FILTER = True
MIN_SCORE = 3
SCORE_BODY_ALIGNED = True
SCORE_CLOSE_POS = True
SCORE_PAT_ALIGNED = True
SCORE_WIDTH_OK = True
SCORE_BODY_SIZE = True
BODY_SIZE_MIN = 0.30
CLOSE_POS_THRESHOLD = 0.30

E0_BASE = 1
E1_BASE = 1
E2_BASE = 1
SIZE_MULT = 1

ENABLE_E0 = True
ENABLE_E1 = True
ENABLE_E2 = True
RETOUCH_TOUCH_ZONE = 10.0
MAX_ENTRIES_PER_DAY = 3
BREAK_CONFIRM_PTS = 5.0

TP_V_SHAPE_TP1 = 1.10
TP_V_SHAPE_TP2 = 2.00
TP_INV_V_TP1 = 0.75
TP_WEAK_UP_TP1 = 0.50
TP_STRONG_UP_TP1 = 0.43
TP_STRONG_DOWN_TP1 = 1.20
TP_WIDE_CAP = 0.50

ENABLE_RETOUCH_DECAY = True
E2_TARGET_FACTOR = 0.80
ENABLE_RETOUCH_MODIFIER = True
RETOUCH_REDUCE_AT = 5
RETOUCH_CAP_AFTER_N = 0.50

NARROW_STOP_TYPE = "BOTH"           # OR_LOW | TIME_BASED | BOTH
MEDIUM_E0_STOP = "OR_LOW"
MEDIUM_E1E2_STOP = "MIDPOINT"
WIDE_STOP_TYPE = "MIDPOINT"

M_E0_ADJ1 = 0.50
M_E0_ADJ2 = 0.75
M_E1_ADJ2 = 0.75
NARROW_BE = 1.00
WIDE_BE = 0.40

NARROW_TIME_STOP_MINS = 20
NARROW_TIME_STOP_E0_ONLY = True

ENABLE_OPPOSITE_EXIT = True
OPPOSITE_EXIT_ZONE = 10.0

ENABLE_DEEP_CROSSBACK = True
CROSSBACK_DEPTH = 0.30
CROSSBACK_DUR = 8
ENABLE_SHALLOW_HOLD = True
SHALLOW_DEPTH_MAX = 0.20
SHALLOW_DURATION_MAX = 2
DEEP_EXIT_FAE_GUARD = 0.50
DEEP_EXIT_E0 = True
DEEP_EXIT_E1 = True
DEEP_EXIT_E2 = False

ENABLE_CLEAN_BREAK = True
CLEAN_BREAK_MINS = 30
CLEAN_BREAK_RETEST_ZONE = 10.0
CLEAN_BREAK_TARGET = 2.00

ENABLE_WEAK_UP_PARTIAL = True

TRADERSPOST_SYMBOL = "MNQ"
ENABLE_NOTRADE_LOG = True

# ---------------------------------------------------------------------------

P_STRONG_UP, P_STRONG_DOWN = "STRONG_UP", "STRONG_DOWN"
P_V_SHAPE, P_INV_V = "V_SHAPE", "INV_V"
P_WEAK_UP, P_WEAK_DOWN = "WEAK_UP", "WEAK_DOWN"
R_NARROW, R_MEDIUM, R_WIDE = "NARROW", "MEDIUM", "WIDE"


@dataclass
class Bar:
    t: int
    o: float
    h: float
    l: float
    c: float

    @property
    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.t, tz=TZ)


@dataclass
class State:
    # OR
    or_high: float | None = None
    or_low: float | None = None
    or_mid: float | None = None
    or_open: float | None = None
    or_close: float | None = None
    or_range: float | None = None
    c1: float | None = None
    c2: float | None = None
    c3: float | None = None
    c4: float | None = None
    regime: str = ""
    pattern: str = ""
    score: int = 0
    or_classified: bool = False
    score_calculated: bool = False

    # Break
    break_dir: int = 0          # 0/1/-1
    break_idx: int | None = None
    bars_since_break: int = 0
    clean_break_act: bool = False
    cb_disqualified: bool = False
    max_fav_exc: float = 0.0
    b_in_r: int = 0             # bars closed back inside OR

    # Counters
    retouch_cnt: int = 0
    day_entry_cnt: int = 0
    last_r_b: int = 0

    # Per-entry state: qty, stop, tp, partial_taken
    entries: dict[str, dict] = field(default_factory=lambda: {
        "E0": {"qty": 0, "stop": None, "tp": None, "partial": False},
        "E1": {"qty": 0, "stop": None, "tp": None, "partial": False},
        "E2": {"qty": 0, "stop": None, "tp": None, "partial": False},
    })

    # Bar-level guard
    exit_triggered_this_bar: bool = False
    # Day-level guard
    session_end_fired: bool = False

    def reset_day(self) -> None:
        self.or_high = self.or_low = self.or_mid = None
        self.or_open = self.or_close = self.or_range = None
        self.c1 = self.c2 = self.c3 = self.c4 = None
        self.regime = ""
        self.pattern = ""
        self.score = 0
        self.or_classified = False
        self.score_calculated = False
        self.break_dir = 0
        self.break_idx = None
        self.bars_since_break = 0
        self.clean_break_act = False
        self.cb_disqualified = False
        self.max_fav_exc = 0.0
        self.b_in_r = 0
        self.retouch_cnt = 0
        self.day_entry_cnt = 0
        self.last_r_b = 0
        self.session_end_fired = False
        for e in self.entries.values():
            e["qty"] = 0
            e["stop"] = None
            e["tp"] = None
            e["partial"] = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def tval(dt: datetime) -> int:
    """HHMM as int, ET."""
    return dt.hour * 100 + dt.minute


def get_initial_stop(s: State, etype: str) -> float:
    bd = s.break_dir
    if (s.pattern == P_STRONG_UP and bd == 1) or (s.pattern == P_STRONG_DOWN and bd == -1):
        return s.or_low if bd == 1 else s.or_high
    if s.regime == R_NARROW:
        return s.or_low if bd == 1 else s.or_high
    if s.regime == R_MEDIUM:
        if etype == "E0":
            if MEDIUM_E0_STOP == "OR_LOW":
                return s.or_low if bd == 1 else s.or_high
            return s.or_mid
        if MEDIUM_E1E2_STOP == "MIDPOINT":
            return s.or_mid
        return s.or_low if bd == 1 else s.or_high
    # WIDE
    if WIDE_STOP_TYPE == "MIDPOINT":
        return s.or_mid
    return s.or_low if bd == 1 else s.or_high


def get_initial_tp(s: State, etype: str) -> float:
    mult = 0.75
    if s.pattern == P_V_SHAPE:
        mult = TP_V_SHAPE_TP1
    elif s.pattern == P_INV_V:
        mult = TP_INV_V_TP1
    elif s.pattern == P_WEAK_UP:
        mult = TP_WEAK_UP_TP1
    elif s.pattern == P_STRONG_UP:
        mult = TP_STRONG_UP_TP1
    elif s.pattern == P_STRONG_DOWN:
        mult = TP_STRONG_DOWN_TP1
    if s.regime == R_WIDE:
        mult = min(mult, TP_WIDE_CAP)
    if etype == "E2" and ENABLE_RETOUCH_DECAY:
        mult *= E2_TARGET_FACTOR
    return (s.or_high + mult * s.or_range) if s.break_dir == 1 else (s.or_low - mult * s.or_range)


def apply_ratchet(s: State, etype: str, stop: float, tp: float) -> tuple[float, float]:
    bd = s.break_dir
    # Clean break TP upgrade
    if ENABLE_CLEAN_BREAK and s.clean_break_act:
        m = TP_V_SHAPE_TP2 if s.pattern == P_V_SHAPE else CLEAN_BREAK_TARGET
        utp = (s.or_high + m * s.or_range) if bd == 1 else (s.or_low - m * s.or_range)
        tp = max(tp, utp) if bd == 1 else min(tp, utp)
    # Stop ratchets by regime
    if s.regime == R_MEDIUM:
        if etype == "E0":
            if s.max_fav_exc >= M_E0_ADJ2 * s.or_range:
                stop = max(stop, s.or_high) if bd == 1 else min(stop, s.or_low)
            elif s.max_fav_exc >= M_E0_ADJ1 * s.or_range:
                stop = max(stop, s.or_mid) if bd == 1 else min(stop, s.or_mid)
        elif s.max_fav_exc >= M_E1_ADJ2 * s.or_range:
            stop = max(stop, s.or_high) if bd == 1 else min(stop, s.or_low)
    elif s.regime == R_NARROW and s.max_fav_exc >= NARROW_BE * s.or_range:
        stop = max(stop, s.or_high) if bd == 1 else min(stop, s.or_low)
    elif s.regime == R_WIDE and s.max_fav_exc >= WIDE_BE * s.or_range:
        stop = max(stop, s.or_high) if bd == 1 else min(stop, s.or_low)
    # Retouch count cap
    if ENABLE_RETOUCH_MODIFIER and s.retouch_cnt >= RETOUCH_REDUCE_AT:
        cap = (s.or_high + RETOUCH_CAP_AFTER_N * s.or_range) if bd == 1 \
            else (s.or_low - RETOUCH_CAP_AFTER_N * s.or_range)
        tp = min(tp, cap) if bd == 1 else max(tp, cap)
    return stop, tp


# ---------------------------------------------------------------------------
# Alert builders
# ---------------------------------------------------------------------------

def entry_json(action: str, signal: str, qty: int) -> dict:
    return {"ticker": TRADERSPOST_SYMBOL, "action": action, "quantity": qty, "signalId": signal}


def exit_json(signal: str, qty: int) -> dict:
    return {"ticker": TRADERSPOST_SYMBOL, "action": "exit", "quantity": qty, "signalId": signal}


def flatten_json(signal: str) -> dict:
    return {"ticker": TRADERSPOST_SYMBOL, "action": "exit", "sentiment": "flat", "signalId": signal}


def notrade_json(s: State, slot: str, reason: str, detail: str, t_iso: str) -> dict:
    return {
        "ticker": TRADERSPOST_SYMBOL, "action": "none", "signalId": "NO_TRADE",
        "slot": slot, "reason": reason, "detail": detail,
        "or_range": round(s.or_range or 0, 2), "break_dir": s.break_dir,
        "pattern": s.pattern, "regime": s.regime, "score": s.score, "t": t_iso,
    }


def summary_json(s: State, t_iso: str) -> dict:
    return {
        "ticker": TRADERSPOST_SYMBOL, "action": "none", "signalId": "DAILY_SUMMARY",
        "entries": s.day_entry_cnt, "retouches": s.retouch_cnt,
        "or_range": round(s.or_range or 0, 2), "break_dir": s.break_dir,
        "pattern": s.pattern, "regime": s.regime, "score": s.score, "t": t_iso,
    }


# ---------------------------------------------------------------------------
# Main bar loop
# ---------------------------------------------------------------------------

def run(bars: list[Bar]) -> list[tuple[int, str, dict]]:
    s = State()
    alerts: list[tuple[int, str, dict]] = []
    prev_day: str | None = None
    prev_tval: int | None = None
    bar_index = -1

    for bar in bars:
        bar_index += 1
        dt = bar.dt
        day = dt.strftime("%Y-%m-%d")
        t = tval(dt)
        t_iso = dt.strftime("%Y-%m-%dT%H:%M")

        # --- Day reset ---
        if prev_day is not None and day != prev_day:
            s.reset_day()
        prev_day = day
        s.exit_triggered_this_bar = False

        # Window flags
        or_s = OR_START[0] * 100 + OR_START[1]   # 930
        or_e = OR_END[0] * 100 + OR_END[1]       # 950
        ses_e = SESSION_END[0] * 100 + SESSION_END[1]  # 1555
        is_or_window = or_s <= t < or_e
        is_or_complete = (t >= or_e) and (prev_tval is not None and prev_tval < or_e)
        is_trading_window = or_e <= t < ses_e

        # --- 1. OR building ---
        if is_or_window:
            if s.or_high is None:
                s.or_high = bar.h
                s.or_low = bar.l
                s.or_open = bar.o
            else:
                s.or_high = max(s.or_high, bar.h)
                s.or_low = min(s.or_low, bar.l)
            if (dt.hour, dt.minute) == (9, 30):
                s.c1 = bar.c
            elif (dt.hour, dt.minute) == (9, 35):
                s.c2 = bar.c
            elif (dt.hour, dt.minute) == (9, 40):
                s.c3 = bar.c
            elif (dt.hour, dt.minute) == (9, 45):
                s.c4 = bar.c
                s.or_close = bar.c

        # --- 2. OR classification (once per day) ---
        if is_or_complete and not s.or_classified and s.or_high is not None:
            s.or_range = s.or_high - s.or_low
            s.or_mid = (s.or_high + s.or_low) / 2
            if s.or_range < NARROW_MAX:
                s.regime = R_NARROW
            elif s.or_range < MEDIUM_MAX:
                s.regime = R_MEDIUM
            else:
                s.regime = R_WIDE
            c1, c2, c3, c4 = s.c1, s.c2, s.c3, s.c4
            if c1 is not None and c4 is not None:
                if c1 < c2 < c3 < c4:
                    s.pattern = P_STRONG_UP
                elif c1 > c2 > c3 > c4:
                    s.pattern = P_STRONG_DOWN
                elif c2 < c1 and c4 > c2:
                    s.pattern = P_V_SHAPE
                elif c2 > c1 and c4 < c2:
                    s.pattern = P_INV_V
                elif c4 > c1:
                    s.pattern = P_WEAK_UP
                else:
                    s.pattern = P_WEAK_DOWN
            s.or_classified = True

        # --- 3. Break detection ---
        if s.break_dir == 0 and is_trading_window and s.or_high is not None:
            if bar.h > s.or_high + BREAK_CONFIRM_PTS and bar.l >= s.or_low:
                s.break_dir = 1
                s.break_idx = bar_index
            elif bar.l < s.or_low - BREAK_CONFIRM_PTS and bar.h <= s.or_high:
                s.break_dir = -1
                s.break_idx = bar_index

        # --- 4. Score (once after break) ---
        if s.break_dir != 0 and not s.score_calculated and s.or_range:
            sc = 0
            bull_body = s.or_close is not None and s.or_open is not None and s.or_close > s.or_open
            close_pos = ((s.or_close - s.or_low) / s.or_range) if s.or_close is not None else 0.5
            body_pct = (abs(s.or_close - s.or_open) / s.or_range) if s.or_close is not None else 0.0
            if SCORE_BODY_ALIGNED and ((s.break_dir == 1 and bull_body) or (s.break_dir == -1 and not bull_body)):
                sc += 1
            if SCORE_CLOSE_POS:
                if (s.break_dir == 1 and close_pos >= 1.0 - CLOSE_POS_THRESHOLD) or \
                   (s.break_dir == -1 and close_pos <= CLOSE_POS_THRESHOLD):
                    sc += 1
            if SCORE_PAT_ALIGNED:
                if (s.break_dir == 1 and s.pattern in (P_STRONG_UP, P_WEAK_UP, P_V_SHAPE)) or \
                   (s.break_dir == -1 and s.pattern in (P_STRONG_DOWN, P_WEAK_DOWN, P_INV_V)):
                    sc += 1
            if SCORE_WIDTH_OK and s.regime != R_WIDE:
                sc += 1
            if SCORE_BODY_SIZE and body_pct >= BODY_SIZE_MIN:
                sc += 1
            s.score = sc
            s.score_calculated = True

        # --- 5. Filter ---
        filter_ok = True
        filter_fail: str | None = None
        if ENABLE_SHAPE_FILTER and s.pattern:
            if not ALLOW.get(s.pattern, False):
                filter_ok = False
                filter_fail = f"SHAPE:{s.pattern}"
        if ENABLE_SCORE_FILTER and s.score < MIN_SCORE:
            filter_ok = False
            tag = f"SCORE:{s.score}<{MIN_SCORE}"
            filter_fail = tag if filter_fail is None else f"{filter_fail}|{tag}"

        # --- 6. Clean break + MFE ---
        if s.break_dir != 0 and not s.clean_break_act and bar_index > (s.break_idx or -1):
            s.bars_since_break += 1
            dist = (bar.l - s.or_high) if s.break_dir == 1 else (s.or_low - bar.h)
            if dist <= CLEAN_BREAK_RETEST_ZONE:
                s.cb_disqualified = True
            if s.bars_since_break >= CLEAN_BREAK_MINS // 5 and not s.cb_disqualified:
                s.clean_break_act = True
        if s.break_dir != 0:
            curr_exc = (bar.h - s.or_high) if s.break_dir == 1 else (s.or_low - bar.l)
            s.max_fav_exc = max(s.max_fav_exc, curr_exc)

        # --- 7. ENTRIES ---
        # E0 break-bar entry
        if bar_index == s.break_idx and ENABLE_E0:
            block_reason: str | None = None
            if s.day_entry_cnt >= MAX_ENTRIES_PER_DAY:
                block_reason = "MAX_ENTRIES"
            elif not filter_ok:
                block_reason = "FILTER"
            elif s.break_dir == 0:
                block_reason = "NO_BREAK"
            if block_reason is None:
                qty = E0_BASE * SIZE_MULT
                s.entries["E0"]["qty"] = qty
                s.entries["E0"]["stop"] = get_initial_stop(s, "E0")
                s.entries["E0"]["tp"] = get_initial_tp(s, "E0")
                s.entries["E0"]["partial"] = False
                s.day_entry_cnt += 1
                alerts.append((bar_index, t_iso, entry_json(
                    "buy" if s.break_dir == 1 else "sell", "E0_ENTRY", qty)))
            elif ENABLE_NOTRADE_LOG:
                detail = filter_fail or block_reason
                alerts.append((bar_index, t_iso, notrade_json(s, "E0", block_reason, detail, t_iso)))

        # E1/E2 retouch detection (only after break)
        if s.break_dir != 0 and s.break_idx is not None and bar_index > s.break_idx:
            in_rz = (bar.l <= s.or_high + RETOUCH_TOUCH_ZONE) if s.break_dir == 1 \
                else (bar.h >= s.or_low - RETOUCH_TOUCH_ZONE)
            cn_rz = (bar.c > s.or_high + 3) if s.break_dir == 1 else (bar.c < s.or_low - 3)
            if in_rz and cn_rz and bar_index > s.last_r_b + 1:
                s.retouch_cnt += 1
                s.last_r_b = bar_index
                slot = "E1" if s.retouch_cnt == 1 else ("E2" if s.retouch_cnt == 2 else None)
                slot_enabled = (s.retouch_cnt == 1 and ENABLE_E1) or (s.retouch_cnt == 2 and ENABLE_E2)
                blocked = (not filter_ok) or s.day_entry_cnt >= MAX_ENTRIES_PER_DAY or not slot_enabled
                if slot and not blocked:
                    base = E1_BASE if slot == "E1" else E2_BASE
                    qty = base * SIZE_MULT
                    s.entries[slot]["qty"] = qty
                    s.entries[slot]["stop"] = get_initial_stop(s, slot)
                    s.entries[slot]["tp"] = get_initial_tp(s, slot)
                    s.entries[slot]["partial"] = False
                    s.day_entry_cnt += 1
                    alerts.append((bar_index, t_iso, entry_json(
                        "buy" if s.break_dir == 1 else "sell", f"{slot}_ENTRY", qty)))
                elif slot and ENABLE_NOTRADE_LOG and s.retouch_cnt <= 2:
                    reason = "MAX_ENTRIES" if s.day_entry_cnt >= MAX_ENTRIES_PER_DAY \
                        else ("SLOT_DISABLED" if not slot_enabled else "FILTER")
                    alerts.append((bar_index, t_iso, notrade_json(s, slot, reason, filter_fail or "", t_iso)))

        # --- 8. Ratchet active entries ---
        for etype in ("E0", "E1", "E2"):
            e = s.entries[etype]
            if e["qty"] > 0:
                e["stop"], e["tp"] = apply_ratchet(s, etype, e["stop"], e["tp"])

        # --- 9. Per-entry exit checks ---
        for etype in ("E0", "E1", "E2"):
            e = s.entries[etype]
            if e["qty"] <= 0:
                continue
            long_dir = s.break_dir == 1
            stop_hit = bar.l <= e["stop"] if long_dir else bar.h >= e["stop"]
            tp_hit = bar.h >= e["tp"] if (long_dir and e["tp"] is not None) \
                else (bar.l <= e["tp"] if e["tp"] is not None else False)
            if stop_hit:
                sig = f"{etype}_TRAIL" if e["partial"] else f"{etype}_STOP"
                alerts.append((bar_index, t_iso, exit_json(sig, e["qty"])))
                e["qty"] = 0
                e["stop"] = None
                e["tp"] = None
            elif tp_hit and not e["partial"] and ENABLE_WEAK_UP_PARTIAL \
                    and s.pattern == P_WEAK_UP and e["qty"] >= 2:
                half = e["qty"] // 2
                alerts.append((bar_index, t_iso, exit_json(f"{etype}_TP1", half)))
                e["qty"] -= half
                e["partial"] = True
                e["stop"] = s.or_high if long_dir else s.or_low
                e["tp"] = None
            elif tp_hit:
                alerts.append((bar_index, t_iso, exit_json(f"{etype}_TP", e["qty"])))
                e["qty"] = 0
                e["stop"] = None
                e["tp"] = None

        # --- 10. Forced flatten ---
        total_active = sum(e["qty"] for e in s.entries.values())

        # NARROW Time Stop
        if total_active > 0 and not s.exit_triggered_this_bar \
                and s.regime == R_NARROW and NARROW_STOP_TYPE != "OR_LOW":
            crossed = bar.c < s.or_high if s.break_dir == 1 else bar.c > s.or_low
            within = (bar_index - (s.break_idx or 0)) <= NARROW_TIME_STOP_MINS // 5
            e0_only_pass = (s.entries["E1"]["qty"] == 0 and s.entries["E2"]["qty"] == 0) \
                if NARROW_TIME_STOP_E0_ONLY else True
            if crossed and within and e0_only_pass:
                alerts.append((bar_index, t_iso, flatten_json("TIME_STOP")))
                _flatten_all(s)

        # Opposite OR level
        if total_active > 0 and not s.exit_triggered_this_bar and ENABLE_OPPOSITE_EXIT:
            opp = (bar.l <= s.or_low + OPPOSITE_EXIT_ZONE) if s.break_dir == 1 \
                else (bar.h >= s.or_high - OPPOSITE_EXIT_ZONE)
            if opp:
                alerts.append((bar_index, t_iso, flatten_json("OPPOSITE_LEVEL")))
                _flatten_all(s)

        # Track b_in_r
        if s.break_dir != 0 and s.or_high is not None:
            in_range_now = bar.c < s.or_high if s.break_dir == 1 else bar.c > s.or_low
            s.b_in_r = s.b_in_r + 1 if in_range_now else 0

        # Deep cross-back
        if total_active > 0 and not s.exit_triggered_this_bar \
                and ENABLE_DEEP_CROSSBACK and s.or_range:
            dep = (s.or_high - bar.c) / s.or_range if s.break_dir == 1 \
                else (bar.c - s.or_low) / s.or_range
            shallow = ENABLE_SHALLOW_HOLD and dep < SHALLOW_DEPTH_MAX and s.b_in_r < SHALLOW_DURATION_MAX
            fae_prot = DEEP_EXIT_FAE_GUARD > 0 and s.max_fav_exc >= DEEP_EXIT_FAE_GUARD * s.or_range
            elig = (s.entries["E0"]["qty"] > 0 and DEEP_EXIT_E0) \
                or (s.entries["E1"]["qty"] > 0 and DEEP_EXIT_E1) \
                or (s.entries["E2"]["qty"] > 0 and DEEP_EXIT_E2)
            if elig and not shallow and dep > CROSSBACK_DEPTH and s.b_in_r > CROSSBACK_DUR and not fae_prot:
                alerts.append((bar_index, t_iso, flatten_json("DEEP_EXIT")))
                _flatten_all(s)

        # Session end — fires once per day on first bar at/after 15:55 ET
        if t >= ses_e and not s.exit_triggered_this_bar and not s.session_end_fired:
            alerts.append((bar_index, t_iso, flatten_json("SESSION_END")))
            if ENABLE_NOTRADE_LOG:
                alerts.append((bar_index, t_iso, summary_json(s, t_iso)))
            s.session_end_fired = True
            _flatten_all(s)

        prev_tval = t

    return alerts


def _flatten_all(s: State) -> None:
    for e in s.entries.values():
        e["qty"] = 0
        e["stop"] = None
        e["tp"] = None
        e["partial"] = False
    s.exit_triggered_this_bar = True


# ---------------------------------------------------------------------------
# CSV loader
# ---------------------------------------------------------------------------

def load_csv(path: str) -> list[Bar]:
    bars: list[Bar] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                bars.append(Bar(
                    t=int(row["time"]),
                    o=float(row["open"]),
                    h=float(row["high"]),
                    l=float(row["low"]),
                    c=float(row["close"]),
                ))
            except (KeyError, ValueError):
                continue
    bars.sort(key=lambda b: b.t)
    return bars


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv", help="TradingView 5-min CSV export")
    p.add_argument("--no-notrade", action="store_true",
                   help="Suppress NO_TRADE / DAILY_SUMMARY events")
    args = p.parse_args()

    global ENABLE_NOTRADE_LOG
    if args.no_notrade:
        ENABLE_NOTRADE_LOG = False

    bars = load_csv(args.csv)
    print(f"# Loaded {len(bars)} bars from {args.csv}", file=sys.stderr)
    if not bars:
        return 1
    print(f"# First bar: {bars[0].dt}  Last bar: {bars[-1].dt}", file=sys.stderr)

    alerts = run(bars)

    # Group by day for readability
    current_day: str | None = None
    for idx, t_iso, payload in alerts:
        day = t_iso[:10]
        if day != current_day:
            print(f"\n=== {day} ===")
            current_day = day
        sig = payload.get("signalId", payload.get("action"))
        print(f"  bar#{idx:>4}  {t_iso}  {sig:<14}  {json.dumps(payload, separators=(',', ':'))}")

    print(f"\n# Total alerts: {len(alerts)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
