# Pine v6 invariants
## Execution model
- Pine runs once per bar from oldest to newest. State persists only via `var`/`varip` or `[]`.
- Realtime bar re-executes on every tick; non-`varip` vars roll back before each tick.
- `barstate.isconfirmed` is true only on bar-close in realtime; it is **not valid inside `request.security` callees**.
## Type qualifiers
- Order: `const < input < simple < series`. Expressions inherit the strongest qualifier.
- `series` cannot be passed where `simple` is required (e.g., `ta.ema` length).
- Reference types (arrays, lines, labels, UDTs) are always `series`.
## request.security
- HTF non-repaint requires BOTH `[1]` offset AND `lookahead = barmerge.lookahead_on`.
- LTF (lower-tf) uses `lookahead_off` or, preferably, `request.security_lower_tf()`.
- 40 unique calls per script max; identical calls deduplicate. Tuple your reads.
## Strategy mode
- `strategy.entry` respects `pyramiding`; `strategy.order` does not.
- Default fill is next-bar open. `process_orders_on_close = true` flips to same-bar close.
- Heikin-Ashi/Renko produce fake fills unless `fill_orders_on_standard_ohlc = true`.
## Limits
- 64 plots; 500 max lines/labels/boxes (default 50); 100 polylines.
- 5,000-bar history buffer for `[]` (10,000 for OHLCV/time).
- Per-bar runtime: 20s basic, 40s other plans. 2-minute compile.
- Strategy alerts: 15 per 3 minutes hard cap.
## Alerts
- `alertcondition()` global scope, const string only.
- `alert()` inside conditional, accepts series string.
- Alert bodies are server-snapshotted at creation; re-saving the script does not update existing alerts.
- Alerts fire only on realtime bars.
## Scope rules
- `plot()`, `plotshape()`, `bgcolor()`, `alertcondition()`, `hline()`, `fill()` — global scope only.
- `ta.*` functions must run unconditionally; gating them inside `if` corrupts their bar-by-bar state.
- User-defined functions must be at root indent (not inside `if`/`for`/`switch`).
## v5 → v6 deltas to enforce
- No implicit bool casting. `if myInt` → `if myInt != 0`.
- `bool` cannot be `na`. `nz`, `na()`, `fixnan` no longer accept bool.
- `and`/`or` are now lazy (short-circuit). Order conditions defensively.
- `when=` parameter removed from strategy.entry/exit/close/order/cancel; wrap in `if`.
- `const int` division returns float. `5 / 2 == 2.5`. Wrap with `int()` to truncate.
- `dynamic_requests = true` by default; calls inside loops/conditionals are now legal.
- Default strategy margin = 100% (was 0). Set explicitly.
