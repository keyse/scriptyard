---
name: pine-repaint-audit
description: Audit any Pine v6 script for repainting bugs, especially around request.security, ta.* in conditionals, and var/varip misuse. Use after any edit that touches request.security or whenever a backtest looks suspiciously good. Produces a written verdict.
allowed-tools: Read Bash(rg *)
---
# Repaint audit — the four canonical bugs
## Bug 1: HTF without offset
```pine
// BAD — repaints during the forming HTF bar
htfClose = request.security(syminfo.tickerid, "60", close)
// GOOD — use [1] offset + lookahead_on
htfClose = request.security(syminfo.tickerid, "60", close[1],
                            lookahead = barmerge.lookahead_on)
```
## Bug 2: lookahead_on without offset
```pine
// BAD — peeks into the future
htfClose = request.security(syminfo.tickerid, "60", close,
                            lookahead = barmerge.lookahead_on)
```
This is the worst kind of repaint — it looks great in backtest, fails live.
## Bug 3: ta.* inside conditional
```pine
// BAD — ema state corrupts because it doesn't update every bar
if inSession
    ema20 = ta.ema(close, 20)
// GOOD — compute unconditionally, gate the use
ema20 = ta.ema(close, 20)
if inSession
    plot(ema20)
```
## Bug 4: LTF (lower-tf) request without lookahead_off
```pine
// BAD on a higher-TF chart reading lower-TF data
ltfClose = request.security("BINANCE:BTCUSDT", "1", close,
                             lookahead = barmerge.lookahead_on)
// GOOD — prefer request.security_lower_tf for LTF reads
[ltfTimes, ltfCloses] = request.security_lower_tf(
                            syminfo.tickerid, "1", [time, close])
```
## Audit procedure
1. `rg "request\.security" src/` — list all call sites.
2. For each, verify EITHER `[N]` offset with `lookahead_on` (HTF), OR `request.security_lower_tf` / `lookahead_off` (LTF).
3. `rg -n "ta\.\w+" src/` and check that none are inside `if`/`for`/`switch` blocks.
4. `rg -n "varip" src/` and verify each `varip` is intentional (rare; mostly for tick-counters).
5. Report findings as: `<file>:<line> <verdict> <fix>`.
## Verdict format
```
src/strategies/orb_breakout_strat.pine:42  REPAINT  request.security missing [1] offset
src/indicators/htf_bias.pine:15            CLEAN    correct non-repaint idiom
src/indicators/htf_bias.pine:22            WARN     ta.rsi gated by `if inSession` — possible state corruption
```
## See also
- @../../../docs/INVARIANTS.md (request.security section)
- @../../../docs/PATTERNS.md (Non-repainting HTF tuple)
