# Spec: pullback_strat

## Type
strategy (overlay)

## Instrument(s)
Same envelope as `pullback_indicator`: index futures continuation symbols, primarily /MES, /ES, /MNQ, /NQ. Backtest target: /MES on 1m chart.

## Timeframe(s)
- Chart TF: 1m (intraday execution)
- HTF read: 5m EMAs via `request.security` (configurable via `i_emaTf`)
- No LTF reads.

## Signal logic
**Source**: see `pullback_indicator.spec.md` § Signal logic. The strategy reproduces the v2 indicator's signal block verbatim ("Inline-during-dev" pattern from `docs/ARCHITECTURE.md`) — same inputs, same regime/touch/arm/confirm logic, same `bullSignal` / `bearSignal` boolean outputs. The non-repaint HTF idiom (`[1]` offset, tupled `request.security`, `lookahead = barmerge.lookahead_on`) is preserved exactly.

**v3 deviation from indicator**: the strategy enforces R:R against the **actual target it will submit to `strategy.exit`**, not the indicator's pivot-only reward. This eliminates the v2 footgun where `Pass-through` mode bypassed the R:R gate (`bullBreakoutPass = true`) and then the strategy synthesized an ATR target whose realized R:R could be below `i_minRr`. In v3 the gate is `realizedRr = synthesizedTarget_distance / stopDistance`, computed against the same `longTargetCandidate` / `shortTargetCandidate` used for the limit order, in **all three breakout modes**. Net effect: `Pass-through` and `ATR target` signals can now be filtered by `i_minRr` consistently.

When `RiskLib` is published and an `import` workflow exists, this duplicate block becomes the candidate for the first library extraction. Tracked as a TODO comment in the file.

## Entry rules
- **Long entry**: `bullSignal == true` AND `strategy.position_size == 0` AND not in EOD flatten window AND not in warmup window AND not in stop-cooldown AND HTF regime allows longs AND trend-quality gate passes AND late-entry cutoff not passed → `strategy.entry("L", strategy.long)` at next-bar open. New signals while a position is open are ignored (pyramiding 0).
- **Short entry**: same gates, mirror direction (`allowShort`).
- **HTF regime gate** (v2): `htfRegClose` and `htfRegSma` are pulled from `i_htfRegimeTf` (default `"D"`) using the canonical non-repaint idiom (`[1]` offset, `lookahead_on`, tupled). Long entries blocked when `htfRegClose <= htfRegSma`; short entries blocked when `htfRegClose >= htfRegSma`. Disabled by `i_useHtfRegime = false`.
- **Stop-cooldown gate** (v2): on every closed trade with exit comment `"stop"`, `lastStopBar := bar_index`. While `bar_index - lastStopBar < i_stopCooldownBars`, both directions are blocked. BE-out trades exit with comment `"be"` and don't trigger cooldown.
- **Warmup gate** (v2): block entries while `curHour < 9 OR (curHour == 9 AND curMinute < 30 + i_warmupMinutes)`. Default `i_warmupMinutes = 15` skips the first 15 minutes after the 09:30 ET RTH open.
- **Trend-quality gate** (v3): block entries unless BOTH of the following are true. Disabled wholesale by `i_useTrendQuality = false`.
  - **EMA separation**: `math.abs(emaFast - emaSlow) >= i_minEmaSepAtr * atrVal`. Default `i_minEmaSepAtr = 0.2` (i.e., the 9 and 20 EMA must be at least 0.2 × ATR apart). Filters out the "EMAs glued together / chop" regime that produces the bulk of false-signal stop-outs.
  - **ATR percentile floor**: `atrVal >= percentile_linear_interpolation(atrVal, 100, i_minAtrPct)` (i.e., chart-TF ATR is at or above the configured percentile of its own last 100 bars). Default `i_minAtrPct = 30`. Filters out "dead market" hours where ATR is unusually compressed and pivot/ATR targets become unreachable. Lookback is fixed at 100 bars to limit knob proliferation.
- **Late-entry cutoff** (v3): block new entries when `curHour > i_lastEntryHour OR (curHour == i_lastEntryHour AND curMinute >= i_lastEntryMinute)`. Default 14:30 ET. Reason: the EOD flatten at 15:30 ET gives only 60 minutes for the trade to work; entries inside the last hour either get force-flattened mid-move or scratch via BE. The late-entry cutoff and the EOD flatten time together define the "trading window" — keep `i_lastEntryHour:i_lastEntryMinute < i_flatHour:i_flatMinute` by user convention; not enforced in code.
- **Position sizing**: `default_qty_type = strategy.fixed`, `default_qty_value = 1`. TODO comment in the file pointing at `docs/PATTERNS.md` "Library export skeleton" for `RiskLib.sizeByRisk` once the library exists.

## Exit rules
- **Stop** (fixed at entry unless moved to BE; never trails further):
  - v3: `Long: bullTouchLow - i_stopAtrMult * atr(i_atrLen)`, `Short: bearTouchHigh + i_stopAtrMult * atr(i_atrLen)`.
  - **v4 distance cap**: the touch extreme is clamped toward `close` before the cushion is applied. `bullStopAnchor = max(bullTouchLow, close - i_maxStopAtr * atrVal)`, mirror for shorts. Final levels: `bullStopLevel = bullStopAnchor - i_stopAtrMult * atrVal`. With `i_maxStopAtr = 0` the clamp is disabled and behavior matches v3 exactly. Reason: long-tailed touch candles produced ~10-point stops in the 2026-05-02 MES backtest, dominating the loss column. The clamp limits worst-case risk without changing geometry on well-formed touch bars.
  - The same `bullStopLevel` / `bearStopLevel` is also used in the R:R gate so quoted R = realized R.
  - Captured at signal time into `var float entryStop` and `var float curStop`. Submitted via `strategy.exit("X-L"|"X-S", stop=curStop, limit=entryTarget, comment_loss="stop", comment_profit="target")`.
- **Breakeven move** (v2): when MFE since entry reaches `i_beAtR * initRisk` (default `1.0 * R`), `curStop` is moved to `strategy.position_avg_price` and `strategy.exit` is re-issued with `comment_loss="be"`. One-shot per trade — guarded by `var bool beMoved`. Disable via `i_useBreakeven = false`.
- **Target**:
  - **v4 pivot validity**: a pivot is target-eligible only if it sits at least `i_minPivotRewardAtr * atrVal` away from close — `bullPivotValid := phFresh and (lastPivotHigh - close) >= max(i_minPivotRewardAtr * atrVal, syminfo.mintick)` (mirror for shorts). With `i_minPivotRewardAtr = 0` the rule reduces to v3's strict-inequality check (the `max(..., mintick)` floor preserves the `pivot > close` semantic on tick-aligned prices). Reason: in the 2026-05-02 MES backtest, several "target" wins were +$0.50 — pivot sitting one tick above close — producing scratch wins that could not compensate for full-stop losses (avg win/loss ratio = 0.325).
  - If `bullPivotValid` (long) → `lastPivotHigh`.
  - If `bearPivotValid` (short) → `lastPivotLow`.
  - If `breakout_mode = "Pass-through"` and the pivot is already broken at entry → synthesize target = `entry_close + i_atrTargetMult * ta.atr(i_atrLen)` for longs (mirror for shorts). Reason: indicator's pass-through fires the signal with no usable pivot reward; the strategy still needs a price-level target for `strategy.exit`. We deliberately deviate from the indicator's "no R:R bound" semantic here because a strategy must commit to a number — the ATR fallback is the least-surprising bound.
  - If `breakout_mode = "ATR target"` → `entry_close + i_atrTargetMult * atrVal` (long) / `entry_close - i_atrTargetMult * atrVal` (short).
  - If `breakout_mode = "Block"` → in v3 this is enforced **structurally**: the strategy synthesizes a target only when `bullPivotValid` (resp. `bearPivotValid`); otherwise `bullTarget` / `bearTarget` stays `na` and the `bullSignal` / `bearSignal` boolean is gated on `not na(target)`. No defensive `log.error` or `runtime.error` is needed — Block mode without a valid pivot cannot reach the order block.
  - Captured into `var float entryTarget` at signal time, frozen for the life of the trade.
- **Time-based** (v3): max-bars-in-trade safety exit. When `i_maxBarsInTrade > 0` and the current trade has been open for `>= i_maxBarsInTrade` chart bars, `strategy.close_all(comment="time")`. Default `i_maxBarsInTrade = 30` (≈30 min on 1m chart). Set to `0` to disable. Reason: a trade that has not hit stop or target after 30 bars is, by construction, a stale trade — the regime that produced the signal has likely shifted, and holding it ties up the one-position slot. The `"time"` exit comment does NOT trigger the stop-cooldown gate (only `"stop"` exits do).
- **EOD**: hard flatten at `i_flatHour:i_flatMinute` ET (default 15:30). At that bar, `strategy.close_all(comment="EOD")`. Also block new entries from the flatten time onward to avoid one-bar trades. Note: with the v3 late-entry cutoff (default 14:30), the no-new-entries window opens an hour before flatten; both gates apply.

## Risk
- **Max position**: 1 contract (sizing is fixed for v1).
- **Max daily loss**: not enforced in v1. TODO when daily-loss-circuit becomes a need.
- **Slippage assumption**: 1 tick (per `CLAUDE.md` defaults).
- **Commission assumption**: $0.62 per contract per side, cash (models /MES round-turn). `CLAUDE.md` notes $2.50 as the historical default for cash-index research; v2 lowered this to match the actual backtest target instrument.
- **Margin**: 50% long, 50% short (per `CLAUDE.md` defaults).
- **Pyramiding**: 0.
- **Pass-through risk** (v3 update): indicator's `Pass-through` mode allows signals with no pivot-derived R:R. v2 of the strategy bounded this by deriving an ATR target but **bypassed `i_minRr`** — pass-through trades could fire with realized R:R below the configured floor. v3 closes that gap: R:R is now always computed against the synthesized target the strategy will submit, and `i_minRr` is enforced uniformly across all three breakout modes. Net: pass-through signals trade only when `i_atrTargetMult * ATR / stopDistance >= i_minRr`.

## Alerts
- `alertcondition()` calls at global scope, mirroring `pullback_indicator` v2:
  - `"Pullback Long Entry"` — message: `9/20 EMA Pullback STRAT: Long entry`
  - `"Pullback Short Entry"` — message: `9/20 EMA Pullback STRAT: Short entry`
- TODO comment in the file: refactor to `alert()` with JSON webhook bodies per `docs/PATTERNS.md` "Webhook JSON alert" once broker bridge is live.

## Inputs
| Name                  | Type           | Default     | Range            | Description |
|-----------------------|----------------|-------------|------------------|-------------|
| `i_emaFastLen`        | `simple int`   | 9           | 1+               | Fast EMA period |
| `i_emaSlowLen`        | `simple int`   | 20          | 1+               | Slow EMA period |
| `i_emaTf`             | `simple string`| "5"         | any TF           | Timeframe for EMA calc |
| `i_maxBarsToConfirm`  | `simple int`   | 5           | 1+               | Window length after touch |
| `i_pivotLeft`         | `simple int`   | 8           | 1+               | Pivot left bars |
| `i_pivotRight`        | `simple int`   | 8           | 1+               | Pivot right bars |
| `i_minRr`             | `simple float` | 3.0         | 0.1+ step 0.1    | Minimum acceptable R:R |
| `i_requireRr`         | `simple bool`  | true        | bool             | Enforce min R:R. **Off is debug-only** — disabling voids the strategy's structural edge (v4). |
| `i_minPivotRewardAtr` | `simple float` | 0.75        | 0+ step 0.05     | Min reward distance to pivot in ATR multiples; 0 reduces to v3 strict-inequality check (v4) |
| `i_breakoutMode`      | `simple string`| "Block"     | {"Pass-through","ATR target","Block"} | How to handle already-broken pivot |
| `i_atrLen`            | `simple int`   | 14          | 1+               | ATR period |
| `i_atrTargetMult`     | `simple float` | 3.0         | 0.1+ step 0.1    | ATR target multiple |
| `i_pivotMaxAge`       | `simple int`   | 20          | 1+               | Max pivot age (bars) |
| `i_stopAtrMult`       | `simple float` | 0.5         | 0+ step 0.1      | Stop cushion as multiple of ATR (v2) |
| `i_maxStopAtr`        | `simple float` | 1.5         | 0+ step 0.1      | Max distance from close to touch-extreme stop anchor in ATR multiples; 0 disables clamp (v4) |
| `i_stopCooldownBars`  | `simple int`   | 5           | 0+               | Bars to block re-entry after a stop (v2) |
| `i_useBreakeven`      | `simple bool`  | true        | bool             | Enable BE move (v2) |
| `i_beAtR`             | `simple float` | 1.0         | 0.1+ step 0.1    | Favorable-R trigger for BE move (v2) |
| `i_useHtfRegime`      | `simple bool`  | true        | bool             | Enable HTF regime gate (v2) |
| `i_htfRegimeTf`       | `simple string`| "D"         | any TF           | TF for regime SMA (v2) |
| `i_htfRegimeLen`      | `simple int`   | 20          | 1+               | SMA length on regime TF (v2) |
| `i_flatHour`          | `simple int`   | 15          | 0–23             | EOD flatten hour (ET) |
| `i_flatMinute`        | `simple int`   | 30          | 0–59             | EOD flatten minute (ET) |
| `i_warmupMinutes`     | `simple int`   | 15          | 0+               | Skip N min after 09:30 ET (v2) |
| `i_lastEntryHour`     | `simple int`   | 14          | 0–23             | Late-entry cutoff hour ET (v3) |
| `i_lastEntryMinute`   | `simple int`   | 30          | 0–59             | Late-entry cutoff minute ET (v3) |
| `i_useTrendQuality`   | `simple bool`  | true        | bool             | Master toggle for trend-quality gate (v3) |
| `i_minEmaSepAtr`      | `simple float` | 0.2         | 0+ step 0.05     | Min `\|emaFast − emaSlow\| / ATR` to allow entries (v3) |
| `i_minAtrPct`         | `simple int`   | 30          | 0–100            | Min ATR percentile rank over fixed 100-bar window (v3) |
| `i_maxBarsInTrade`    | `simple int`   | 30          | 0+               | Bars-in-trade time stop; 0 disables (v3) |
| `i_showDashboard`     | `simple bool`  | true        | bool             | Toggle dashboard table |
| `i_dashbg`            | `simple color` | `color.new(color.black, 70)` | color | Dashboard background |

## Outputs (strategy)
- **Plots**: 9 EMA (HTF), 20 EMA (HTF) — same as indicator.
- **Plotshapes**: long entry triangle (lime, "L"), short entry triangle (red, "S") — same as indicator. Touch dots omitted to keep the strategy chart clean (debug overlay can be reintroduced later).
- **Table** at `position.bottom_right`, gated by `barstate.islast`. Cells:

| Row | Label              | Value                                                |
|-----|--------------------|------------------------------------------------------|
| 0   | Position           | "FLAT" / "LONG x" / "SHORT x"                        |
| 1   | Entry              | `strategy.position_avg_price` (mintick) or "—"       |
| 2   | Stop / Target      | `entryStop` / `entryTarget` (mintick) or "—"         |
| 3   | Open R             | `(close - entry) / (entry - stop)` for longs (mirror short) |
| 4   | Trades             | `strategy.closedtrades`                              |
| 5   | Wins / Losses      | "W:n  L:n"                                           |
| 6   | Win rate           | "##.# %", guarded against 0 closed trades            |
| 7   | Profit factor      | `grossprofit / abs(grossloss)`, guarded vs `grossloss==0` |
| 8   | Max DD             | `strategy.max_drawdown` (mintick)                    |
| 9   | Net P&L            | `strategy.netprofit` (mintick)                       |

- **Alertconditions**: long entry, short entry.

## Backtest plan
- **Symbol(s)**: /MES (MES1!) on TradingView.
- **Date range**: last 30 RTH sessions (`0930–1600 ET`, weekdays).
- **TF**: 1m.
- **Calc flags** (every value committed; the WHY column is what makes this non-default):

| Flag                              | Value                          | Why |
|-----------------------------------|--------------------------------|-----|
| `calc_on_every_tick`              | `false`                        | True produces intra-bar fills that won't match live; forbidden by `CLAUDE.md`. |
| `process_orders_on_close`         | `false`                        | Default fill = next-bar open; standard for signal-on-close strategies. |
| `calc_on_order_fills`             | `false`                        | True triggers recursive fill loops. |
| `fill_orders_on_standard_ohlc`    | `true`                         | Defends against fake fills if the user accidentally switches to Heikin-Ashi/Renko. |
| `commission_type`                 | `strategy.commission.cash_per_contract` | `CLAUDE.md` default. |
| `commission_value`                | `0.62`                         | /MES round-turn ≈ $1.24 RT; matches the actual backtest instrument. |
| `slippage`                        | `1`                            | 1 tick; never zero for futures (`CLAUDE.md`). |
| `margin_long` / `margin_short`    | `50` / `50`                    | `CLAUDE.md` default; v6's 100% default would understate buying power. |
| `pyramiding`                      | `0`                            | One position at a time per spec. |
| `default_qty_type` / `_value`     | `strategy.fixed` / `1`         | Fixed sizing for v1. |
| `initial_capital`                 | `25000`                        | Standard /MES sizing room. |
| `max_lines_count`                 | `500`                          | Per `CLAUDE.md` drawing-script rule. |
| `max_labels_count`                | `500`                          | Per `CLAUDE.md` drawing-script rule. |
| `max_boxes_count`                 | `500`                          | Per `CLAUDE.md` drawing-script rule. |

- **Go/no-go bar**:
  - Profit factor > 1.3
  - Max drawdown < 10% of `initial_capital` ($2,500 absolute)
  - Win rate > 40%
  - At least 30 closed trades in the 30-session window (otherwise sample too small)

## Open questions
- Should pass-through-mode targets use 5m ATR instead of chart-TF (1m) ATR for consistency with the regime EMAs? Mirrors an open question on the indicator. v3 still uses 1m ATR for simplicity; revisit after v3 backtest baseline is set.
- ~~Should we add a max-bars-in-trade safety exit?~~ **Resolved in v3** — added with `i_maxBarsInTrade` default 30.
- ~~Is "Block" mode signals firing really an invariant or a soft warning?~~ **Resolved in v3** — structurally enforced via `not na(bullTarget)` / `not na(bearTarget)` gate on the signal booleans. Defensive `log.error` removed.
- Daily-loss circuit breaker: deferred to v3.1 per the joint-review action plan. Will be scoped after v3 establishes a backtest baseline so its marginal effect can be measured.
- v3 trend-quality gate uses ATR percentile over a fixed 100-bar lookback. Should the lookback itself be configurable, or is the parameter-explosion cost not worth it? Current bias: keep fixed.
- v3 trend-quality gate uses chart-TF (1m) ATR percentile. On /MES, would 5m ATR percentile (matching the regime EMAs) be more stable? Mirrors the pass-through-ATR question.
- Late-entry cutoff (14:30) and EOD flatten (15:30) are independent inputs, not enforced to be `cutoff < flatten`. Should the spec require it, or is "user configuration" the right scope?

## Version history (audit-relevant)
- **v1** — initial. Fixed sizing, regime gate via 9/20 EMA on 5m, signal block ported verbatim from indicator v1, Pass-through fired with no R:R bound. No HTF regime, no warmup, no BE move, no cooldown. Audit verdict: usable for visual sanity-check; PF below go/no-go on the first /MES backtest.
- **v2** (current shipped) — added: HTF daily SMA regime gate (`i_useHtfRegime`); ATR-cushioned stops (`i_stopAtrMult`); 1R breakeven move (`i_useBreakeven` / `i_beAtR`); stop-cooldown after losses (`i_stopCooldownBars`); 09:30 ET warmup (`i_warmupMinutes`). Pass-through still bypassed `i_minRr` (caller-side bug — strategy synthesized an ATR target afterward). Block-mode invariant downgraded from `runtime.error` to `log.error` + entry skip. Audit verdict: PASS.
- **v3** — derived from joint review with codex CLI on 2026-05-02. Three focused changes targeting expectancy without expanding the parameter surface beyond manageability:
  1. **Realized-fill R:R gate** — strategy now computes R:R against the same target it submits to `strategy.exit`, in all three breakout modes. Eliminates the v2 footgun where Pass-through entries traded with realized R:R below `i_minRr`.
  2. **Trend-quality gate** — `i_minEmaSepAtr` (default 0.2) and `i_minAtrPct` (default 30, fixed 100-bar lookback) added to filter "EMAs glued / dead market" regime. Master toggle `i_useTrendQuality`.
  3. **Late-entry cutoff + max-bars-in-trade** — `i_lastEntryHour:i_lastEntryMinute` (default 14:30 ET) blocks new entries in the last hour; `i_maxBarsInTrade` (default 30, 0 disables) flattens stale trades with comment `"time"` (does NOT trigger cooldown).
  - Also fixes spec-text drift: Exit rules previously said EOD default 15:55 while inputs default 15:30. Spec now consistent at 15:30.
  - Items deferred to v3.1: daily loss circuit + risk-based sizing (#4 from joint review), structure-trail or partial-at-1R replacement of fixed BE (#5). Held back so v3 backtest establishes a baseline and each subsequent change's marginal contribution is measurable.
- **v4** (this revision) — derived from analysis of `notes/9_20_EMA_Pullback_Strategy_CME_MINI_MES1!_2026-05-02-2.xlsx` (11 trades, PF 0.271, avg win/loss ratio 0.325 against a 3R design target). Two focused changes plus one documentation hardening, no new gates:
  1. **Min pivot-reward floor** — `i_minPivotRewardAtr` (default 0.75) added. Pivot is only target-eligible when it sits at least 0.75 × ATR away from close. Fixes the failure mode where +$0.50 "target" wins (pivot one tick above close) accumulated as scratches that couldn't pay for full-stop losses. With `i_requireRr = true` the R:R gate already filters most of these structurally; the explicit floor closes the gap when `i_requireRr` is off (debug runs) and removes the dependence on that one toggle.
  2. **Stop distance cap** — `i_maxStopAtr` (default 1.5) added. The stop anchor (touch-bar low/high) is clamped toward `close` before the ATR cushion is applied, so a long-tailed touch candle can't produce a 10-point stop. With `i_maxStopAtr = 0` the clamp is disabled and behavior is bit-for-bit v3.
  3. **`i_requireRr` documentation hardening** — inline comment now states that disabling the toggle voids the strategy's structural edge and is debug-only. Default unchanged (`true`); spec reinforces in the inputs table.
  - Joint-review item deferred: A/B run with `i_useBreakeven = false` to test whether 1R BE is firing meaningfully — backtest shows avg loser runs ~10 bars / ~-1R, suggesting BE rarely activates. Held back to keep v4 to two structural changes; revisit once a 6-month walk-forward run on /MES is available.
