#!/usr/bin/env python3
"""
Local dark-mode web UI for tools/compare_v6_v7.py.

Launches a Flask server on http://localhost:8765 with a drag-and-drop
interface. Upload two TradingView Strategy Tester CSVs (v6 + v7), click
Run, get a rendered HTML report with embedded charts — no terminal output
to parse, no file shuffling.

Usage:
    pip install flask pandas matplotlib
    python3 tools/compare_ui.py [--port 8765] [--no-browser]

This is a thin wrapper. All analysis logic lives in compare_v6_v7.py;
this file just adds the HTTP layer and the styled HTML rendering.
"""

from __future__ import annotations

import argparse
import base64
import io
import sys
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path

# Allow sibling import regardless of where this is run from
sys.path.insert(0, str(Path(__file__).parent))

try:
    from flask import Flask, jsonify, request
except ImportError:
    sys.exit("Flask is required.  Install with:  pip install flask pandas matplotlib")

import matplotlib
matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt
import pandas as pd

from compare_v6_v7 import (
    compute_stats,
    daily_attribution,
    filter_value_attribution,
    load_trades,
    signal_breakdown,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def stats_to_dict(s) -> dict:
    """Flatten a Stats dataclass into label + formatted rows for the UI."""
    def fmt_money(v):
        return f"${v:,.2f}"
    return {
        "label": s.label,
        "headline": {
            "net_pnl":  fmt_money(s.net_pnl),
            "pf":       f"{s.profit_factor:.2f}",
            "trades":   f"{s.n_trades:,}",
            "win_rate": f"{s.win_rate:.1f}%",
        },
        "rows": [
            ("Trades",            f"{s.n_trades:,}"),
            ("Days traded",       f"{s.n_days_traded:,}"),
            ("Win rate",          f"{s.win_rate:.1f}%"),
            ("Profit factor",     f"{s.profit_factor:.2f}"),
            ("Net P&L",           fmt_money(s.net_pnl)),
            ("Avg P&L/trade",     fmt_money(s.avg_pnl)),
            ("Median P&L/trade",  fmt_money(s.median_pnl)),
            ("Best trade",        fmt_money(s.best_trade)),
            ("Worst trade",       fmt_money(s.worst_trade)),
            ("Max drawdown",      fmt_money(s.max_dd)),
            ("Sharpe (ann.)",     f"{s.sharpe_daily:.2f}"),
            ("Sortino (ann.)",    f"{s.sortino_daily:.2f}"),
            ("Avg bars held",     f"{s.avg_bars_held:.1f}"),
        ],
    }


def top_divergence(daily: pd.DataFrame, n: int = 15) -> list[dict]:
    if daily.empty:
        return []
    worst = daily.reindex(daily["diff_v6_minus_v7"].abs().sort_values(ascending=False).index).head(n)
    out = []
    for date, row in worst.iterrows():
        out.append({
            "date": str(date),
            "v6_pnl": float(row["v6_pnl"]),
            "v7_pnl": float(row["v7_pnl"]),
            "diff":   float(row["diff_v6_minus_v7"]),
            "v6_trades": int(row["v6_trades"]),
            "v7_trades": int(row["v7_trades"]),
        })
    return out


def _dark_axes(fig, ax, title):
    fig.patch.set_facecolor("#0f172a")
    ax.set_facecolor("#1e293b")
    ax.tick_params(colors="#cbd5e1")
    for spine in ax.spines.values():
        spine.set_color("#334155")
    ax.title.set_color("#e2e8f0")
    ax.title.set_text(title)
    ax.yaxis.label.set_color("#cbd5e1")
    ax.xaxis.label.set_color("#cbd5e1")
    ax.grid(color="#334155", alpha=0.35)


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def build_charts(v6: pd.DataFrame, v7: pd.DataFrame, daily: pd.DataFrame) -> dict:
    charts = {}

    # 1. Equity curves
    fig, ax = plt.subplots(figsize=(10, 4.5))
    if not v6.empty:
        v6.groupby("date")["pnl"].sum().cumsum().plot(ax=ax, label="v6 (current)", linewidth=2, color="#22d3ee")
    if not v7.empty:
        v7.groupby("date")["pnl"].sum().cumsum().plot(ax=ax, label="v7 Lean", linewidth=2, color="#a78bfa")
    ax.axhline(0, color="#64748b", linewidth=0.6)
    ax.legend(facecolor="#0f172a", edgecolor="#334155", labelcolor="#e2e8f0")
    ax.set_ylabel("Cumulative $")
    _dark_axes(fig, ax, "Cumulative P&L")
    charts["equity"] = _fig_to_b64(fig)

    if not daily.empty:
        # 2. Daily diff
        fig, ax = plt.subplots(figsize=(10, 3.5))
        colors = ["#26a69a" if v >= 0 else "#ef5350" for v in daily["diff_v6_minus_v7"]]
        ax.bar(range(len(daily)), daily["diff_v6_minus_v7"], color=colors)
        ax.axhline(0, color="#64748b", linewidth=0.5)
        ax.set_ylabel("$")
        ax.set_xlabel("Day index")
        _dark_axes(fig, ax, "Daily P&L diff (v6 − v7) — green = v6 won that day")
        charts["daily_diff"] = _fig_to_b64(fig)

        # 3. Scatter
        fig, ax = plt.subplots(figsize=(5.5, 5.5))
        ax.scatter(daily["v7_pnl"], daily["v6_pnl"], alpha=0.7, color="#a78bfa", s=40, edgecolor="#0f172a", linewidth=0.5)
        lo = float(min(daily["v6_pnl"].min(), daily["v7_pnl"].min()))
        hi = float(max(daily["v6_pnl"].max(), daily["v7_pnl"].max()))
        ax.plot([lo, hi], [lo, hi], "--", color="#64748b", linewidth=0.8)
        ax.set_xlabel("v7 day P&L $")
        ax.set_ylabel("v6 day P&L $")
        _dark_axes(fig, ax, "Day-by-day: above diagonal = v6 beat v7")
        charts["scatter"] = _fig_to_b64(fig)

    return charts


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return INDEX_HTML


@app.route("/run", methods=["POST"])
def run():
    v6_file = request.files.get("v6_csv")
    v7_file = request.files.get("v7_csv")
    want_charts = request.form.get("charts", "on") == "on"

    if not v6_file or not v7_file:
        return jsonify({"error": "Please upload both v6 and v7 CSV files."}), 400

    tmp = Path(tempfile.mkdtemp(prefix="orb_ab_"))
    v6_path = tmp / "v6.csv"
    v7_path = tmp / "v7.csv"
    v6_file.save(v6_path)
    v7_file.save(v7_path)

    try:
        v6 = load_trades(v6_path)
        v7 = load_trades(v7_path)
    except SystemExit as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to parse CSVs: {e}"}), 400

    s6 = compute_stats(v6, "v6 (current)")
    s7 = compute_stats(v7, "v7 Lean")
    daily = daily_attribution(v6, v7)

    payload = {
        "generated":     datetime.now().isoformat(timespec="seconds"),
        "v6_filename":   v6_file.filename,
        "v7_filename":   v7_file.filename,
        "stats":         [stats_to_dict(s6), stats_to_dict(s7)],
        "attribution":   filter_value_attribution(daily),
        "v6_signals":    signal_breakdown(v6, "v6"),
        "v7_signals":    signal_breakdown(v7, "v7 Lean"),
        "divergence":    top_divergence(daily),
        "charts":        build_charts(v6, v7, daily) if want_charts else {},
        "verdict":       _verdict(s6, s7, daily),
    }
    return jsonify(payload)


def _verdict(s6, s7, daily) -> dict:
    """A one-line summary the UI shows as a colored callout."""
    if s6.n_trades == 0 or s7.n_trades == 0:
        return {"tone": "warn", "text": "One of the CSVs has no trades — check the date range."}

    if s7.profit_factor >= s6.profit_factor and s7.net_pnl >= s6.net_pnl * 0.85:
        return {
            "tone": "good",
            "text": (
                f"v7 Lean matches or beats v6 (PF {s7.profit_factor:.2f} vs {s6.profit_factor:.2f}, "
                f"net ${s7.net_pnl:,.0f} vs ${s6.net_pnl:,.0f}). The extra filters in v6 are not paying their way."
            ),
        }
    if s6.profit_factor > s7.profit_factor * 1.15:
        return {
            "tone": "info",
            "text": (
                f"v6 beats v7 by >15% on PF ({s6.profit_factor:.2f} vs {s7.profit_factor:.2f}). "
                f"Investigate which filters carry the alpha — add them back to v7 one at a time."
            ),
        }
    return {
        "tone": "neutral",
        "text": (
            f"Mixed result: v6 PF {s6.profit_factor:.2f} vs v7 PF {s7.profit_factor:.2f}. "
            f"Use the divergence table below to dig into specific days."
        ),
    }


# ---------------------------------------------------------------------------
# HTML template — single page, dark mode, vanilla JS, marked.js for tables
# ---------------------------------------------------------------------------

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MNQ ORB · v6 vs v7 Lean</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root {
    --bg:        #0b1220;
    --panel:    #111a2e;
    --panel-2:  #162033;
    --border:   #1f2c44;
    --text:     #e2e8f0;
    --muted:    #94a3b8;
    --accent:   #22d3ee;
    --accent-2: #a78bfa;
    --good:     #26a69a;
    --bad:      #ef5350;
    --warn:     #f59e0b;
  }
  *, *::before, *::after { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    background: radial-gradient(ellipse at top, #1a2542 0%, var(--bg) 60%);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    min-height: 100vh;
    font-size: 15px;
    line-height: 1.5;
    padding: 32px 24px 80px;
  }
  .container { max-width: 1180px; margin: 0 auto; }
  h1 {
    font-size: 26px; font-weight: 600; margin: 0 0 4px;
    background: linear-gradient(90deg, var(--accent), var(--accent-2));
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .sub { color: var(--muted); font-size: 14px; margin-bottom: 28px; }
  .sub code {
    background: var(--panel); padding: 2px 6px; border-radius: 4px;
    color: var(--accent); font-size: 12.5px;
  }

  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 22px;
    margin-bottom: 22px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.25);
  }
  .card h2 {
    font-size: 16px; font-weight: 600; margin: 0 0 14px;
    color: var(--text); letter-spacing: 0.2px;
    display: flex; align-items: center; gap: 8px;
  }
  .card h2::before {
    content: ""; width: 3px; height: 16px;
    background: var(--accent); border-radius: 2px;
  }

  /* Upload */
  .uploads { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .drop {
    border: 1.5px dashed var(--border);
    border-radius: 12px;
    padding: 28px 18px;
    text-align: center;
    transition: all 150ms ease;
    cursor: pointer;
    background: var(--panel-2);
  }
  .drop:hover { border-color: var(--accent); background: #18243d; }
  .drop.dragover { border-color: var(--accent); background: #18243d; transform: translateY(-1px); }
  .drop.has-file { border-color: var(--good); border-style: solid; }
  .drop .title { font-weight: 600; font-size: 15px; margin-bottom: 4px; }
  .drop .hint  { font-size: 12.5px; color: var(--muted); }
  .drop .file  { font-size: 13px; color: var(--good); margin-top: 6px; font-family: ui-monospace, monospace; }
  .drop input[type=file] { display: none; }

  .controls {
    margin-top: 18px;
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;
  }
  .toggle { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 14px; user-select: none; cursor: pointer; }
  .toggle input { accent-color: var(--accent); width: 16px; height: 16px; }

  button.primary {
    background: linear-gradient(90deg, var(--accent), var(--accent-2));
    color: #0b1220; font-weight: 600; font-size: 14px;
    border: 0; border-radius: 8px;
    padding: 10px 22px; cursor: pointer; transition: filter 120ms ease, transform 120ms ease;
  }
  button.primary:hover:not(:disabled) { filter: brightness(1.08); transform: translateY(-1px); }
  button.primary:disabled { opacity: 0.5; cursor: not-allowed; }

  /* Results */
  #results { display: none; }
  #results.visible { display: block; }
  .error {
    background: rgba(239, 83, 80, 0.12);
    border: 1px solid rgba(239, 83, 80, 0.4);
    color: #fecaca; padding: 12px 16px; border-radius: 10px;
    font-size: 14px; margin-top: 14px; display: none;
  }
  .error.visible { display: block; }

  .verdict {
    padding: 14px 18px; border-radius: 10px; font-size: 14.5px; font-weight: 500;
    border-left: 4px solid var(--accent); background: var(--panel-2); margin-bottom: 22px;
  }
  .verdict.good { border-color: var(--good); }
  .verdict.warn { border-color: var(--warn); }
  .verdict.info { border-color: var(--accent-2); }
  .verdict.neutral { border-color: var(--muted); }

  /* Stats grid */
  .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .stat-card { background: var(--panel-2); border: 1px solid var(--border); border-radius: 10px; padding: 18px; }
  .stat-card h3 { margin: 0 0 14px; font-size: 14px; color: var(--muted); font-weight: 500; letter-spacing: 0.4px; text-transform: uppercase; }
  .headline-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 16px; }
  .hl { background: var(--panel); border-radius: 8px; padding: 10px 12px; }
  .hl .k { font-size: 11.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.4px; }
  .hl .v { font-size: 17px; font-weight: 600; font-family: ui-monospace, monospace; }

  table.stats { width: 100%; border-collapse: collapse; font-size: 13.5px; }
  table.stats td { padding: 6px 4px; border-bottom: 1px solid var(--border); }
  table.stats td:first-child { color: var(--muted); }
  table.stats td:last-child  { text-align: right; font-family: ui-monospace, monospace; }
  table.stats tr:last-child td { border-bottom: 0; }

  /* Markdown sections */
  .md { font-size: 14px; }
  .md table { width: 100%; border-collapse: collapse; margin: 8px 0 14px; }
  .md th, .md td { padding: 7px 10px; border-bottom: 1px solid var(--border); text-align: left; }
  .md th { color: var(--muted); font-weight: 500; font-size: 12.5px; text-transform: uppercase; letter-spacing: 0.4px; }
  .md td { font-family: ui-monospace, monospace; }
  .md strong { color: var(--text); }
  .md ul { padding-left: 20px; margin: 8px 0; }
  .md li { margin-bottom: 6px; color: var(--muted); }
  .md li strong { color: var(--text); }
  .md h3 { font-size: 14px; color: var(--muted); margin: 16px 0 6px; font-weight: 500; }

  /* Divergence table */
  table.div { width: 100%; border-collapse: collapse; font-size: 13px; }
  table.div th, table.div td { padding: 8px 10px; text-align: right; border-bottom: 1px solid var(--border); }
  table.div th { color: var(--muted); font-weight: 500; font-size: 12px; text-transform: uppercase; letter-spacing: 0.4px; }
  table.div td:first-child, table.div th:first-child { text-align: left; }
  table.div td { font-family: ui-monospace, monospace; }
  .pos { color: var(--good); } .neg { color: var(--bad); }

  /* Charts */
  .charts { display: grid; grid-template-columns: 1fr; gap: 16px; }
  .chart-img { display: block; max-width: 100%; border-radius: 8px; border: 1px solid var(--border); }

  /* Loading */
  .spinner {
    width: 16px; height: 16px; border-radius: 50%;
    border: 2px solid rgba(34, 211, 238, 0.25); border-top-color: var(--accent);
    display: inline-block; animation: spin 0.6s linear infinite; vertical-align: -3px; margin-right: 8px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  @media (max-width: 760px) {
    .uploads, .stats-grid { grid-template-columns: 1fr; }
    .headline-grid { grid-template-columns: 1fr 1fr; }
  }
</style>
</head>
<body>
<div class="container">
  <h1>MNQ ORB · v6 vs v7 Lean</h1>
  <div class="sub">
    Local A/B comparison runner. Reuses analysis from <code>tools/compare_v6_v7.py</code>.
  </div>

  <div class="card">
    <h2>Upload Strategy Tester exports</h2>
    <div class="uploads">
      <label class="drop" id="drop-v6">
        <div class="title">v6 (current) CSV</div>
        <div class="hint">drag & drop — or click to pick</div>
        <div class="file" id="file-v6"></div>
        <input type="file" id="csv-v6" accept=".csv">
      </label>
      <label class="drop" id="drop-v7">
        <div class="title">v7 Lean CSV</div>
        <div class="hint">drag & drop — or click to pick</div>
        <div class="file" id="file-v7"></div>
        <input type="file" id="csv-v7" accept=".csv">
      </label>
    </div>
    <div class="controls">
      <label class="toggle"><input type="checkbox" id="charts" checked> Generate charts</label>
      <button class="primary" id="run-btn" disabled>Run comparison</button>
    </div>
    <div class="error" id="err"></div>
  </div>

  <div id="results">
    <div class="verdict" id="verdict"></div>

    <div class="card">
      <h2>Headline metrics</h2>
      <div class="stats-grid" id="stats"></div>
    </div>

    <div class="card">
      <h2>Filter attribution</h2>
      <div class="md" id="attribution"></div>
    </div>

    <div class="card">
      <h2>Per-strategy exit-reason breakdown</h2>
      <div class="md" id="signals"></div>
    </div>

    <div class="card" id="divergence-card">
      <h2>Biggest divergence days</h2>
      <table class="div" id="divergence"></table>
    </div>

    <div class="card" id="charts-card">
      <h2>Charts</h2>
      <div class="charts" id="charts-grid"></div>
    </div>
  </div>
</div>

<script>
  const state = { v6: null, v7: null };

  function wireDrop(slotKey) {
    const drop  = document.getElementById('drop-' + slotKey);
    const input = document.getElementById('csv-' + slotKey);
    const label = document.getElementById('file-' + slotKey);

    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('dragover'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('dragover'));
    drop.addEventListener('drop', e => {
      e.preventDefault();
      drop.classList.remove('dragover');
      if (e.dataTransfer.files.length) setFile(slotKey, e.dataTransfer.files[0]);
    });
    input.addEventListener('change', e => {
      if (e.target.files.length) setFile(slotKey, e.target.files[0]);
    });

    function setFile(key, f) {
      state[key] = f;
      label.textContent = f.name;
      drop.classList.add('has-file');
      document.getElementById('run-btn').disabled = !(state.v6 && state.v7);
    }
  }
  wireDrop('v6'); wireDrop('v7');

  const runBtn = document.getElementById('run-btn');
  const errEl  = document.getElementById('err');
  const resultsEl = document.getElementById('results');

  runBtn.addEventListener('click', async () => {
    errEl.classList.remove('visible');
    runBtn.disabled = true;
    const origText = runBtn.textContent;
    runBtn.innerHTML = '<span class="spinner"></span>Running…';

    const fd = new FormData();
    fd.append('v6_csv', state.v6);
    fd.append('v7_csv', state.v7);
    if (document.getElementById('charts').checked) fd.append('charts', 'on');

    try {
      const res = await fetch('/run', { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Server error');
      render(data);
    } catch (e) {
      errEl.textContent = e.message;
      errEl.classList.add('visible');
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = origText;
    }
  });

  function render(d) {
    // Verdict
    const v = document.getElementById('verdict');
    v.className = 'verdict ' + (d.verdict.tone || 'neutral');
    v.textContent = d.verdict.text;

    // Stats
    const stats = document.getElementById('stats');
    stats.innerHTML = '';
    for (const s of d.stats) {
      const card = document.createElement('div');
      card.className = 'stat-card';
      const hg = `
        <div class="headline-grid">
          <div class="hl"><div class="k">Net P&L</div><div class="v">${s.headline.net_pnl}</div></div>
          <div class="hl"><div class="k">PF</div><div class="v">${s.headline.pf}</div></div>
          <div class="hl"><div class="k">Trades</div><div class="v">${s.headline.trades}</div></div>
          <div class="hl"><div class="k">Win %</div><div class="v">${s.headline.win_rate}</div></div>
        </div>`;
      const rows = s.rows.map(([k, val]) => `<tr><td>${k}</td><td>${val}</td></tr>`).join('');
      card.innerHTML = `<h3>${s.label}</h3>${hg}<table class="stats"><tbody>${rows}</tbody></table>`;
      stats.appendChild(card);
    }

    // Markdown sections
    document.getElementById('attribution').innerHTML = marked.parse(d.attribution || '');
    document.getElementById('signals').innerHTML = marked.parse((d.v6_signals || '') + '\n' + (d.v7_signals || ''));

    // Divergence table
    const divEl = document.getElementById('divergence');
    if (d.divergence && d.divergence.length) {
      const head = '<thead><tr><th>Date</th><th>v6 $</th><th>v7 $</th><th>Diff</th><th>v6 trades</th><th>v7 trades</th></tr></thead>';
      const body = d.divergence.map(r => {
        const cls = r.diff >= 0 ? 'pos' : 'neg';
        return `<tr>
          <td>${r.date}</td>
          <td>${r.v6_pnl.toLocaleString('en-US',{style:'currency',currency:'USD'})}</td>
          <td>${r.v7_pnl.toLocaleString('en-US',{style:'currency',currency:'USD'})}</td>
          <td class="${cls}">${(r.diff>=0?'+':'')}${r.diff.toLocaleString('en-US',{style:'currency',currency:'USD'})}</td>
          <td>${r.v6_trades}</td><td>${r.v7_trades}</td>
        </tr>`;
      }).join('');
      divEl.innerHTML = head + '<tbody>' + body + '</tbody>';
      document.getElementById('divergence-card').style.display = '';
    } else {
      document.getElementById('divergence-card').style.display = 'none';
    }

    // Charts
    const chartsCard = document.getElementById('charts-card');
    const grid = document.getElementById('charts-grid');
    grid.innerHTML = '';
    const chartKeys = ['equity', 'daily_diff', 'scatter'];
    let any = false;
    for (const k of chartKeys) {
      if (d.charts && d.charts[k]) {
        const img = document.createElement('img');
        img.className = 'chart-img';
        img.src = 'data:image/png;base64,' + d.charts[k];
        grid.appendChild(img);
        any = true;
      }
    }
    chartsCard.style.display = any ? '' : 'none';

    resultsEl.classList.add('visible');
    resultsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--port", type=int, default=8765, help="Port to serve on (default 8765)")
    p.add_argument("--host", default="127.0.0.1", help="Host to bind (default 127.0.0.1)")
    p.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    args = p.parse_args()

    url = f"http://{args.host}:{args.port}/"
    print(f"\n  MNQ ORB compare UI  →  {url}")
    print(f"  Press Ctrl+C to stop.\n")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
