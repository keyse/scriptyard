#!/usr/bin/env python3
"""
Compare two TradingView Strategy Tester "List of Trades" CSV exports
side-by-side, trade-by-trade, to attribute where v6's extra filters helped
or hurt vs v7 Lean.

Usage:
    python tools/compare_v6_v7.py path/to/v6_trades.csv path/to/v7_trades.csv \\
        [--out report.md] [--charts]

How to get the input CSVs in TradingView:
    1. Apply the strategy to a chart.
    2. Open Strategy Tester → "List of Trades" tab.
    3. Click the download icon → CSV.

The script handles minor column-naming variations (TradingView has tweaked
headers across versions). It pairs entry/exit rows into single trades,
aggregates to daily P&L, then produces an attribution report:

  - Headline stats per strategy (PF, win rate, Sharpe, max DD)
  - Daily diff (v6 day P&L − v7 day P&L)
  - Days where one strategy traded and the other didn't
    (the most diagnostic signal for whether the extra filters add value)
  - Signal-level breakdown (which exit reasons are profit centers vs sinks)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

try:
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


# ---------------------------------------------------------------------------
# CSV loading — robust to TradingView column-naming variations
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


COLUMN_ALIASES = {
    "trade_num":   ["tradenum", "trade", "trade#"],
    "type":        ["type"],
    "signal":      ["signal"],
    "datetime":    ["datetime", "date", "datetimebar", "timeentry", "timeexit"],
    "price":       ["priceusd", "price"],
    "qty":         ["positionsize", "contracts", "quantity"],
    "pnl":         ["netpnlusd", "profitusd", "netprofitusd", "pnlusd"],
    "runup":       ["runupusd"],
    "drawdown":    ["drawdownusd"],
    "cum_pnl":     ["cumulativepnlusd", "cumprofitusd"],
}


def _find_col(df_cols, key):
    norm_to_orig = { _norm(c): c for c in df_cols }
    for alias in COLUMN_ALIASES[key]:
        if alias in norm_to_orig:
            return norm_to_orig[alias]
    return None


def load_trades(csv_path: Path) -> pd.DataFrame:
    """Load a TV Strategy Tester CSV and return one row per *closed trade*.

    Columns produced:
        date, side, signal_entry, signal_exit, entry_time, exit_time,
        entry_price, exit_price, qty, pnl, runup, drawdown, bars_held
    """
    raw = pd.read_csv(csv_path)
    cols = list(raw.columns)

    c_type   = _find_col(cols, "type")
    c_sig    = _find_col(cols, "signal")
    c_dt     = _find_col(cols, "datetime")
    c_price  = _find_col(cols, "price")
    c_qty    = _find_col(cols, "qty")
    c_pnl    = _find_col(cols, "pnl")
    c_runup  = _find_col(cols, "runup")
    c_dd     = _find_col(cols, "drawdown")
    c_trade  = _find_col(cols, "trade_num")

    missing = [k for k, v in {
        "type": c_type, "signal": c_sig, "datetime": c_dt,
        "price": c_price, "qty": c_qty, "pnl": c_pnl,
    }.items() if v is None]
    if missing:
        raise SystemExit(
            f"{csv_path}: required columns missing: {missing}\n"
            f"Found columns: {cols}"
        )

    raw[c_dt] = pd.to_datetime(raw[c_dt], errors="coerce")

    # TV exports entry and exit as two consecutive rows per trade. If a trade
    # number column exists, group by it; otherwise pair adjacent entry+exit.
    if c_trade is not None:
        grouped = raw.groupby(c_trade, sort=False)
    else:
        # Fabricate trade numbers by pairing rows 0/1, 2/3, ...
        raw["_tn"] = raw.index // 2
        grouped = raw.groupby("_tn", sort=False)

    rows = []
    for tn, g in grouped:
        if len(g) < 2:
            continue
        entry = g[g[c_type].str.startswith("Entry", na=False)]
        exit_ = g[g[c_type].str.startswith("Exit",  na=False)]
        if entry.empty or exit_.empty:
            continue
        e = entry.iloc[0]
        x = exit_.iloc[0]
        side = "long" if "long" in str(e[c_type]).lower() else "short"
        rows.append({
            "trade_num":    tn,
            "date":         e[c_dt].date() if pd.notna(e[c_dt]) else None,
            "side":         side,
            "signal_entry": e[c_sig],
            "signal_exit":  x[c_sig],
            "entry_time":   e[c_dt],
            "exit_time":    x[c_dt],
            "entry_price":  float(e[c_price]),
            "exit_price":   float(x[c_price]),
            "qty":          float(e[c_qty]),
            "pnl":          float(x[c_pnl]) if pd.notna(x[c_pnl]) else 0.0,
            "runup":        float(x[c_runup])    if c_runup and pd.notna(x[c_runup])    else None,
            "drawdown":     float(x[c_dd])       if c_dd    and pd.notna(x[c_dd])       else None,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["bars_held"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 300  # 5-min bars
    return df.sort_values("entry_time").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class Stats:
    label: str
    n_trades: int
    win_rate: float
    profit_factor: float
    net_pnl: float
    avg_pnl: float
    median_pnl: float
    best_trade: float
    worst_trade: float
    max_dd: float
    sharpe_daily: float
    sortino_daily: float
    avg_bars_held: float
    n_days_traded: int


def compute_stats(trades: pd.DataFrame, label: str) -> Stats:
    if trades.empty:
        return Stats(label, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    wins   = trades[trades["pnl"] >  0]["pnl"].sum()
    losses = -trades[trades["pnl"] < 0]["pnl"].sum()
    pf     = wins / losses if losses > 0 else float("inf")

    daily = trades.groupby("date")["pnl"].sum()
    cum   = daily.cumsum()
    dd    = (cum - cum.cummax()).min()

    # Daily Sharpe/Sortino, annualized by ~252 trading days
    mean_d = daily.mean()
    std_d  = daily.std(ddof=0)
    downside = daily[daily < 0].std(ddof=0)
    sharpe  = (mean_d / std_d * (252 ** 0.5)) if std_d > 0 else 0.0
    sortino = (mean_d / downside * (252 ** 0.5)) if downside and downside > 0 else 0.0

    return Stats(
        label         = label,
        n_trades      = len(trades),
        win_rate      = (trades["pnl"] > 0).mean() * 100,
        profit_factor = pf,
        net_pnl       = trades["pnl"].sum(),
        avg_pnl       = trades["pnl"].mean(),
        median_pnl    = trades["pnl"].median(),
        best_trade    = trades["pnl"].max(),
        worst_trade   = trades["pnl"].min(),
        max_dd        = dd,
        sharpe_daily  = sharpe,
        sortino_daily = sortino,
        avg_bars_held = trades["bars_held"].mean(),
        n_days_traded = daily.shape[0],
    )


def fmt_stats_table(stats_list: list[Stats]) -> str:
    rows = [
        ("Trades",                "n_trades",      "{:d}"),
        ("Days traded",           "n_days_traded", "{:d}"),
        ("Win rate %",            "win_rate",      "{:.1f}"),
        ("Profit factor",         "profit_factor", "{:.2f}"),
        ("Net P&L $",             "net_pnl",       "{:,.2f}"),
        ("Avg P&L/trade $",       "avg_pnl",       "{:,.2f}"),
        ("Median P&L/trade $",    "median_pnl",    "{:,.2f}"),
        ("Best trade $",          "best_trade",    "{:,.2f}"),
        ("Worst trade $",         "worst_trade",   "{:,.2f}"),
        ("Max drawdown $",        "max_dd",        "{:,.2f}"),
        ("Sharpe (daily, ann.)",  "sharpe_daily",  "{:.2f}"),
        ("Sortino (daily, ann.)", "sortino_daily", "{:.2f}"),
        ("Avg bars held",         "avg_bars_held", "{:.1f}"),
    ]
    header = "| Metric | " + " | ".join(s.label for s in stats_list) + " |"
    sep    = "|" + "---|" * (len(stats_list) + 1)
    lines  = [header, sep]
    for name, key, fmt in rows:
        vals = [fmt.format(getattr(s, key)) for s in stats_list]
        lines.append(f"| {name} | " + " | ".join(vals) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Day-by-day attribution
# ---------------------------------------------------------------------------

def daily_attribution(v6: pd.DataFrame, v7: pd.DataFrame) -> pd.DataFrame:
    """Per-day side-by-side: P&L, trade count, who traded."""
    a6 = v6.groupby("date").agg(v6_pnl=("pnl", "sum"), v6_trades=("pnl", "size")) if not v6.empty else pd.DataFrame()
    a7 = v7.groupby("date").agg(v7_pnl=("pnl", "sum"), v7_trades=("pnl", "size")) if not v7.empty else pd.DataFrame()
    df = a6.join(a7, how="outer").fillna(0)
    df["diff_v6_minus_v7"] = df["v6_pnl"] - df["v7_pnl"]
    df["v6_only"] = (df["v6_trades"] > 0) & (df["v7_trades"] == 0)
    df["v7_only"] = (df["v7_trades"] > 0) & (df["v6_trades"] == 0)
    df["both"]    = (df["v6_trades"] > 0) & (df["v7_trades"] > 0)
    return df.sort_index()


def filter_value_attribution(daily: pd.DataFrame) -> str:
    """The diagnostic that matters most: when filters disagree, who's right?"""
    v6_only = daily[daily["v6_only"]]
    v7_only = daily[daily["v7_only"]]
    both    = daily[daily["both"]]

    def section(label, df, pnl_col):
        n = len(df)
        if n == 0:
            return f"- **{label}**: 0 days\n"
        total = df[pnl_col].sum()
        avg   = df[pnl_col].mean()
        wins  = (df[pnl_col] > 0).sum()
        return (
            f"- **{label}**: {n} days, total ${total:,.2f}, "
            f"avg ${avg:,.2f}/day, {wins}/{n} profitable\n"
        )

    out  = "### Attribution: when do the two strategies disagree?\n\n"
    out += section("v6 traded, v7 skipped (v6-only filters let trade through that v7 rejected)",
                   v6_only, "v6_pnl")
    out += section("v7 traded, v6 skipped (v6's extra filters blocked a trade v7 took)",
                   v7_only, "v7_pnl")
    out += section("Both traded (same break setup; differences come from exit logic)",
                   both, "diff_v6_minus_v7")

    out += "\n**Interpretation:**\n"
    if not v7_only.empty:
        net_missed = v7_only["v7_pnl"].sum()
        if net_missed > 0:
            out += (f"- v6's extra filters cost **${net_missed:,.2f}** by blocking trades "
                    f"v7 took profitably. Filters are too restrictive.\n")
        else:
            out += (f"- v6's extra filters saved **${-net_missed:,.2f}** by blocking trades "
                    f"v7 took unprofitably. Filters are doing useful work.\n")
    if not both.empty:
        net_exit = both["diff_v6_minus_v7"].sum()
        sign = "won" if net_exit > 0 else "lost"
        out += (f"- On the {len(both)} days both took the same setup, v6's exit logic "
                f"{sign} **${abs(net_exit):,.2f}** vs v7's simpler exits.\n")
    return out


# ---------------------------------------------------------------------------
# Signal-level breakdown — which exit reason makes/loses money?
# ---------------------------------------------------------------------------

def signal_breakdown(trades: pd.DataFrame, label: str) -> str:
    if trades.empty:
        return f"### {label} — no trades\n"
    g = trades.groupby("signal_exit").agg(
        n=("pnl", "size"),
        total_pnl=("pnl", "sum"),
        avg_pnl=("pnl", "mean"),
        win_rate=("pnl", lambda s: (s > 0).mean() * 100),
    ).sort_values("total_pnl", ascending=False)
    lines = [f"### {label} — exit reason breakdown\n"]
    lines.append("| Exit signal | N | Total $ | Avg $ | Win % |")
    lines.append("|---|---:|---:|---:|---:|")
    for sig, row in g.iterrows():
        lines.append(f"| {sig} | {int(row['n'])} | {row['total_pnl']:,.2f} | "
                     f"{row['avg_pnl']:,.2f} | {row['win_rate']:.1f} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Charts (optional)
# ---------------------------------------------------------------------------

def make_charts(v6: pd.DataFrame, v7: pd.DataFrame, daily: pd.DataFrame, out_dir: Path):
    if not HAS_MPL:
        print("matplotlib not installed; skipping charts", file=sys.stderr)
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    # 1. Equity curves
    fig, ax = plt.subplots(figsize=(10, 5))
    if not v6.empty:
        v6.groupby("date")["pnl"].sum().cumsum().plot(ax=ax, label="v6", linewidth=2)
    if not v7.empty:
        v7.groupby("date")["pnl"].sum().cumsum().plot(ax=ax, label="v7 Lean", linewidth=2)
    ax.set_title("Cumulative P&L")
    ax.set_ylabel("$")
    ax.axhline(0, color="gray", linewidth=0.5)
    ax.legend()
    ax.grid(alpha=0.3)
    p = out_dir / "equity_curves.png"
    fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
    paths.append(p)

    # 2. Daily diff bar
    if not daily.empty:
        fig, ax = plt.subplots(figsize=(10, 4))
        colors = ["#26a69a" if v >= 0 else "#ef5350" for v in daily["diff_v6_minus_v7"]]
        ax.bar(range(len(daily)), daily["diff_v6_minus_v7"], color=colors)
        ax.set_title("Daily P&L diff (v6 − v7). Green = v6 won that day.")
        ax.set_ylabel("$")
        ax.set_xlabel("Day index")
        ax.axhline(0, color="black", linewidth=0.5)
        ax.grid(alpha=0.3)
        p = out_dir / "daily_diff.png"
        fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
        paths.append(p)

    # 3. Scatter: v6 day P&L vs v7 day P&L
    if not daily.empty:
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.scatter(daily["v7_pnl"], daily["v6_pnl"], alpha=0.6)
        lo = min(daily["v6_pnl"].min(), daily["v7_pnl"].min())
        hi = max(daily["v6_pnl"].max(), daily["v7_pnl"].max())
        ax.plot([lo, hi], [lo, hi], "k--", linewidth=0.5)
        ax.set_xlabel("v7 day P&L $")
        ax.set_ylabel("v6 day P&L $")
        ax.set_title("Day-by-day P&L: v6 vs v7\n(above diagonal = v6 beat v7 that day)")
        ax.grid(alpha=0.3)
        p = out_dir / "scatter.png"
        fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
        paths.append(p)

    return paths


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("v6_csv", type=Path, help="TV Strategy Tester CSV for v6")
    p.add_argument("v7_csv", type=Path, help="TV Strategy Tester CSV for v7 Lean")
    p.add_argument("--out",     type=Path, default=Path("compare_report.md"),
                   help="Output markdown report path (default: compare_report.md)")
    p.add_argument("--charts",  action="store_true",
                   help="Also write PNG charts to <out>.charts/")
    args = p.parse_args()

    v6 = load_trades(args.v6_csv)
    v7 = load_trades(args.v7_csv)

    print(f"v6: {len(v6)} trades, {v6['date'].nunique() if not v6.empty else 0} days")
    print(f"v7: {len(v7)} trades, {v7['date'].nunique() if not v7.empty else 0} days")

    s6 = compute_stats(v6, "v6 (current)")
    s7 = compute_stats(v7, "v7 Lean")
    daily = daily_attribution(v6, v7)

    # Compose report
    out = []
    out.append(f"# MNQ ORB: v6 vs v7 Lean — A/B comparison\n")
    out.append(f"_Generated: {datetime.now().isoformat(timespec='seconds')}_\n")
    out.append(f"_v6 source: `{args.v6_csv}`_\n")
    out.append(f"_v7 source: `{args.v7_csv}`_\n\n")

    out.append("## Headline metrics\n")
    out.append(fmt_stats_table([s6, s7]) + "\n")

    out.append("\n## " + filter_value_attribution(daily).lstrip("#").lstrip() + "\n")

    out.append("\n## Per-strategy exit-reason breakdown\n")
    out.append(signal_breakdown(v6, "v6"))
    out.append(signal_breakdown(v7, "v7 Lean"))

    # Top 10 worst-diff days (where the two diverged most)
    if not daily.empty:
        out.append("\n## 10 biggest divergence days\n")
        worst = daily.reindex(daily["diff_v6_minus_v7"].abs().sort_values(ascending=False).index).head(10)
        out.append("| Date | v6 $ | v7 $ | Diff (v6−v7) | v6 trades | v7 trades |")
        out.append("|---|---:|---:|---:|---:|---:|")
        for date, row in worst.iterrows():
            out.append(f"| {date} | {row['v6_pnl']:,.2f} | {row['v7_pnl']:,.2f} | "
                       f"{row['diff_v6_minus_v7']:+,.2f} | {int(row['v6_trades'])} | {int(row['v7_trades'])} |")
        out.append("")

    if args.charts:
        chart_dir = args.out.with_suffix("").parent / (args.out.stem + ".charts")
        paths = make_charts(v6, v7, daily, chart_dir)
        if paths:
            out.append("\n## Charts\n")
            for p in paths:
                rel = p.relative_to(args.out.parent) if args.out.parent in p.parents else p
                out.append(f"![{p.stem}]({rel})")

    args.out.write_text("\n".join(out))
    print(f"Wrote report → {args.out}")


if __name__ == "__main__":
    main()
