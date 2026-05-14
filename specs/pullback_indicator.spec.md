# Spec: pullback_indicator

## Type
indicator (overlay)

## Instrument(s)
Designed for index futures continuation symbols — primarily /MES, /ES, /MNQ, /NQ. SPX cash works for visual study but lacks 1m liquidity in pre/post sessions. Tested target: 1m chart on /MES or /ES.

## Timeframe(s)
- Chart TF: 1m (intraday execution timeframe)
- HTF read: 5m EMAs computed via `request.security` (configurable via `ema_tf` input)
- No LTF reads.

## Signal logic
Detect a pullback entry to the 9 EMA in the prevailing 5m trend regime. Pseudocode:

```
regime = bull if ema9_5m > ema20_5m else bear if ema9_5m < ema20_5m else flat
on each 1m bar in regime:
    touch       = candle range crosses ema9_5m
    on touch:    arm setup, record touchHigh and touchLow, reset bars_since_touch
    on each subsequent bar (max_bars_to_confirm window):
        confirmation_bull = bull_armed AND bars_since >= 1 AND close > touchHigh
        confirmation_bear = bear_armed AND bars_since >= 1 AND close < touchLow
        if confirmation:
            compute risk = entry_close - touchLow (bull) | touchHigh - entry_close (bear)
            compute reward via fresh pivot (within pivot_max_age) OR breakout_mode handling
            R:R = reward / risk
            fire signal if not require_rr OR R:R >= min_rr OR breakout passthrough
            disarm regardless of R:R outcome (one-shot)
        if bars_since > max_bars_to_confirm:  disarm
        if regime invalidates (cross of 9/20):  disarm
```

Edge cases:
- No fresh pivot at all → reward stays `na`; signal blocked unless `breakout_mode = "ATR target"` (uses `atr_target_mult * ATR(atr_len)` as reward proxy).
- Pivot already broken at entry (`last_pivot_high <= close` for bull) → handled per `breakout_mode`:
  - `Pass-through` — signal fires unconditionally with `BRK ↑` / `BRK ↓` label, R:R bypass.
  - `ATR target` — synthesize reward as `atr_target_mult * ATR(atr_len)`.
  - `Block` — reward stays `na`, signal filtered.
- Re-touch while already armed → ignored (no re-arm).
- `bars_since >= 1` requirement prevents same-bar touch+confirm artifacts.
- Entry bar's close is the reference for risk/reward computation, not the touch bar.

## Entry rules (indicators don't have entries — interpretation for downstream consumers)
This file is **a bias generator**, not a strategy. The published signals are:
- `bull_signal` — long entry trigger; consumers should buy at next-bar open with stop at `touchLow`.
- `bear_signal` — short entry trigger; stop at `touchHigh`.

Position sizing is the consumer's responsibility (see `RiskLib.sizeByRisk` pattern in `docs/PATTERNS.md` once that library exists).

## Exit rules
N/A — indicator. Downstream strategy consumer would exit at:
- Stop (`touchLow` / `touchHigh` of the original touch bar)
- Target (last fresh pivot, or `atr_target_mult * ATR` if breakout mode)
- Time-based: not specified by this indicator
- EOD: not specified by this indicator

## Risk
- Risk leg: `entry_close - touchLow` (bull) — measured at the entry bar, not the touch bar; this means the risk grows with each bar of pullback before confirmation
- R:R floor: configurable via `min_rr` (default 2.0); enforced when `require_rr = true`
- `breakout_mode = "Pass-through"` is the highest-risk mode — fires signals with no R:R bound
- `breakout_mode = "Block"` is most conservative — drops signals with no fresh pivot or already-broken pivot (and `breakout_mode != "ATR target"`)

## Alerts
Two `alertcondition` calls at global scope:
- `"Bullish Entry"` — message: `9/20 EMA Pullback: Bullish entry`
- `"Bearish Entry"` — message: `9/20 EMA Pullback: Bearish entry`

Static const messages (alertcondition limitation). To get JSON webhook bodies for broker bridge, refactor to `alert()` inside `if bull_signal` / `if bear_signal` blocks per `docs/PATTERNS.md` "Webhook JSON alert".

## Inputs
| Name                  | Type           | Default     | Range            | Description |
|-----------------------|----------------|-------------|------------------|-------------|
| `ema_fast_len`        | `simple int`   | 9           | 1+               | Fast EMA period |
| `ema_slow_len`        | `simple int`   | 20          | 1+               | Slow EMA period |
| `ema_tf`              | `simple string`| "5"         | any TF           | Timeframe for EMA calculation |
| `max_bars_to_confirm` | `simple int`   | 5           | 1+               | Window length (bars) to wait for confirmation after a touch |
| `pivot_left`          | `simple int`   | 5           | 1+               | Bars left of pivot |
| `pivot_right`         | `simple int`   | 5           | 1+               | Bars right of pivot (also delays pivot detection) |
| `min_rr`              | `simple float` | 2.0         | 0.1+ step 0.1    | Minimum acceptable R:R |
| `require_rr`          | `simple bool`  | true        | bool             | Enforce `min_rr` floor |
| `breakout_mode`       | `simple string`| "Pass-through" | {"Pass-through","ATR target","Block"} | How to handle entries when last pivot is already broken |
| `atr_len`             | `simple int`   | 14          | 1+               | ATR period for fallback reward |
| `atr_target_mult`     | `simple float` | 2.0         | 0.1+ step 0.1    | Reward = atr_target_mult × ATR when no usable pivot |
| `pivot_max_age`       | `simple int`   | 50          | 1+               | Bars; pivot is "fresh" if newer than this |
| `show_debug`          | `simple bool`  | false       | bool             | Toggle debug overlays (threshold/stop lines, armed bgcolor, conf labels) |

## Outputs
- **Plots**: `9 EMA (5m)` (yellow), `20 EMA (5m)` (red); plus debug-gated threshold/stop break-line plots
- **Plotshapes**: small yellow circle for touch (below/above bar); green up-triangle / red down-triangle for entry signals
- **Labels**: at entry bar — `R/R 2.34` or `BRK ↑` / `BRK ↓` style
- **Bgcolor**: when `show_debug` AND armed — pale lime / pale red
- **Alertconditions**: bullish entry, bearish entry

## Backtest plan
Indicators don't have backtest output. The validation plan is:

- **Symbol(s)**: /MES on TradingView (free 1m data)
- **Date range**: last 30 trading days, regular trading hours (`0930-1600 ET`)
- **TF**: 1m chart
- **Visual sanity check**: scroll back through three days; for every up-triangle, verify the touch bar shows a yellow circle above/below it, and the entry bar's close is above touchHigh (bull) / below touchLow (bear). For 10 random signals, eyeball whether the labeled R:R looks correct vs the chart's pivot.
- **Repaint check**: with the chart on a closed 5m bar, note the EMA values; advance to a forming 5m bar; verify EMAs do NOT redraw history. (See INVARIANTS-REPAINT below.)
- **Once a strategy consumer exists**: backtest entries at next-bar open with stop at touchLow/High and target at last pivot; PF > 1.3, max drawdown < 10% of starting equity over 30 sessions is the go/no-go bar.

## Version history (audit-relevant)
- **v1** (initial upload) — had a CRITICAL HTF repaint bug: `request.security(..., ta.ema(close, ema_fast_len), lookahead = barmerge.lookahead_off)` without the `[1]` offset. Two separate `request.security` calls. Inputs unprefixed. `indicator()` missing `max_lines_count` / `max_boxes_count`. Audit verdict: FAIL. Never published to a live chart.
- **v2** (current) — fixes all four. Tupled non-repaint HTF read with `[1]` + `lookahead_on`; full draw declarations on `indicator()`; `i_`-prefixed inputs; camelCase internals. Audit verdict: PASS. See `CHANGELOG.md` for the diff summary.

## Open questions
- Should the regenerated v2 also switch `alertcondition` → `alert()` with JSON webhook bodies for broker-bridge integration? Worth doing if you plan to wire this up to a broker; cost is losing the static-message simplicity.
- Should `bars_since >= 1` be configurable (e.g. `min_bars_after_touch`)? Currently hardcoded.
- Should `pivot_max_age` count bars on the chart TF (1m) or HTF (5m)? Currently 1m. At 50 bars that's ~50min of intraday history — may be too short for /ES on a slow morning.
- For `breakout_mode = "ATR target"` with no fresh pivot, the synthesized reward uses ATR on the chart TF (1m). Should it use 5m ATR for consistency with the regime EMAs? Probably yes for /ES / /MES.
