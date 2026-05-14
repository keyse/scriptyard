---
name: pine-v6
description: Pine Script v6 syntax rules, type qualifiers, and the most common compile errors. Use when writing, editing, or reviewing any .pine file. Covers v5→v6 breaking changes, request.security non-repaint idioms, var/varip semantics, and strategy declaration defaults.
allowed-tools: Read Edit Write Bash(rg *)
---
# Pine Script v6 — hard rules
## Always
- `//@version=6` at top, even for snippets.
- Functions defined at root indentation (never inside if/for/switch).
- `plot()`, `plotshape()`, `bgcolor()`, `alertcondition()`, `hline()`, `fill()`: global scope only.
- `ta.*` outside conditional blocks; their state is bar-by-bar and corrupts if gated.
- For HTF data: `request.security(sym, tf, expr[1], lookahead = barmerge.lookahead_on)`.
## v5 → v6 deltas to enforce
- No implicit bool casting. `if myInt` → `if myInt != 0`.
- `bool` cannot be `na`. `nz`, `na()`, `fixnan` no longer accept bool.
- `and`/`or` are now lazy (short-circuit). Order conditions defensively.
- `when=` parameter removed from strategy.entry/exit/close/order/cancel; wrap in `if`.
- `const int` division returns float. `5 / 2 == 2.5`. Wrap with `int()` to truncate.
- `dynamic_requests = true` by default; calls inside loops/conditionals are now legal.
- Default strategy margin = 100% (was 0). Set explicitly.
## Strategy declaration template (copy verbatim, edit values)
```pine
//@version=6
strategy("<name>",
     overlay                      = true,
     initial_capital              = 25000,
     default_qty_type             = strategy.fixed,
     default_qty_value            = 1,
     commission_type              = strategy.commission.cash_per_contract,
     commission_value             = 2.50,
     slippage                     = 1,
     margin_long                  = 50,
     margin_short                 = 50,
     pyramiding                   = 0,
     calc_on_every_tick           = false,
     process_orders_on_close      = false,
     fill_orders_on_standard_ohlc = true,
     max_lines_count              = 500,
     max_labels_count             = 500,
     max_boxes_count              = 500)
```
## Type qualifiers (the #1 compile-error source)
- Order: `const < input < simple < series`.
- `ta.ema(src, len)` — `len` must be `simple int`. Passing a `series int` (e.g., one read via `request.security`) fails to compile.
- Reference types (arrays, lines, labels, UDTs) are always `series`.
## Identifier conventions (PineCoders)
- `i_` prefix for `input.*` results.
- `f_` prefix for free functions (optional but recommended).
- camelCase for everything else.
## See also
- @../../../docs/INVARIANTS.md
- @../../../docs/PATTERNS.md
