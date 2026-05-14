# Pine trading workspace
## What this repo is
Pine Script v6 indicators, strategies, and libraries for SPX, /MES, /ES, /MNQ, /NQ, /GC.
Trading style: 0DTE, Trend Following, ORB.
## Hard rules — never violate
- **Always emit `//@version=6`.** Never v5. Never v4 (`study()`, `security()`).
- **HTF data uses the canonical non-repaint idiom**: `request.security(sym, htf, expr[1], lookahead = barmerge.lookahead_on)`. Anything else is a bug.
- **Strategies must declare** `commission_type`, `commission_value`, `slippage`, `margin_long`, `margin_short`, `default_qty_type`. Do not rely on defaults.
- **`calc_on_every_tick = true` is forbidden** in committed strategies; it produces backtests that don't match live.
- **Time logic uses explicit IANA tz** (`"America/New_York"`); never the chart default.
- **Drawing scripts declare** `max_lines_count = 500, max_labels_count = 500, max_boxes_count = 500` and gate creation by `time >= startDate`.
- **Format prices** with `str.tostring(p, format.mintick)` — never hardcoded `"#.##"`.
- **Alerts**: `alertcondition()` only at global scope with const string; `alert()` inside `if` for dynamic strings.
## Project conventions
- Source of truth = local `.pine` files in git. TradingView Pine Editor is the runtime.
- Filenames: `snake_case.pine` for indicators/strategies, `PascalCaseLib.pine` for libraries.
- New indicator/strategy → write `specs/<name>.spec.md` first, generate from spec.
- Library functions get `//@function`, `//@param`, `//@returns` docstrings.
- Identifiers: `i_` prefix for inputs, `f_` for free functions (PineCoders style).
## Workflow
- Before edits to `src/strategies/**`, read `docs/INVARIANTS.md` and the relevant `specs/*.spec.md`.
- After edits, run the `pine-repaint-audit` skill if `request.security` is touched.
- Commit `.pine` files; paste into Pine Editor manually OR use a TradingView MCP if running.
## References (loaded only when needed)
- @docs/ARCHITECTURE.md
- @docs/DOMAIN.md
- @docs/INVARIANTS.md
- @docs/PATTERNS.md
