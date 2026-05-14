---
name: pine-strategy-tester
description: Encodes the calc-flag matrix, commission/slippage discipline, and Strategy Tester smoke-test plan for any Pine v6 strategy. Use when creating or editing files in src/strategies/. Walks through which flags affect backtest fidelity and produces a smoke-test checklist.
allowed-tools: Read Edit Write
---
# Pine strategy tester discipline
## Calc-flag matrix (set every one explicitly)
| Flag                              | Default | Use this              | Why                                                              |
|-----------------------------------|---------|------------------------|------------------------------------------------------------------|
| `calc_on_every_tick`              | false   | **false** (committed)  | true => intra-bar fills that won't match live; allowed only in dev |
| `process_orders_on_close`         | false   | strategy-dependent     | true = fills at current bar close, not next bar open             |
| `calc_on_order_fills`             | false   | false                  | true causes recursive fill loops                                 |
| `use_bar_magnifier`               | false   | true on intraday       | uses 1m data to refine fills on higher-TF charts (Premium plan)  |
| `fill_orders_on_standard_ohlc`    | false   | true                   | prevents fake Heikin-Ashi/Renko fills                             |
| `bar_magnifier_resolution`        | "1"     | "1"                    | only meaningful with use_bar_magnifier=true                       |
## Required declarations
Every committed strategy must declare:
- `commission_type` and `commission_value` (no zero-cost backtests)
- `slippage` (in ticks, never zero for futures)
- `margin_long` and `margin_short` (default is 100% in v6 — set to your broker's actual)
- `default_qty_type` and `default_qty_value`
- `initial_capital`
## Pre-paste smoke-test checklist
Before pasting into Pine Editor:
1. Search for `calc_on_every_tick\s*=\s*true` — must be absent.
2. Search for `commission_value` — must be present and > 0.
3. Search for `margin_long` and `margin_short` — must be present.
4. Search for hardcoded session strings — must include explicit IANA tz.
5. All `strategy.entry/exit/order/close/cancel` calls inside `if` blocks (no `when=`).
## In-Pine-Editor smoke test
After paste + Add to Chart, verify in Strategy Tester:
1. **List of Trades** tab — pick three random trades, eyeball entry bar / exit bar against the chart. Entries should be on the bar after the signal (next-bar open) unless `process_orders_on_close = true`.
2. **Performance Summary** — net profit must be commission-aware. Cross-check: `gross profit + gross loss + commission == net profit`.
3. **Toggle `calc_on_every_tick = true` in a separate copy** and re-run. Divergence in net profit between modes proves your strategy depends on intra-bar fills somewhere — find and fix.
4. **Bar Replay** over a session you remember (e.g., last FOMC) — step bar-by-bar, verify signals fire when expected. Capture `log.info()` output.
## See also
- @../../../docs/INVARIANTS.md (strategy mode section)
