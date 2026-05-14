# Claude Code prompt — pullback strategy + dashboard

Paste the block below into a fresh `claude` session running in the repo root
(`cd /Users/mohamoudibrahim/Sammy/auto-trading && claude`). The skills
(`pine-v6`, `pine-strategy-tester`, `pine-repaint-audit`, `pine-orb`,
`pine-publish`) will auto-trigger off the description matches; the
`pine-reviewer` agent is available to be called explicitly.

---

You are working in a Pine v6 trading workspace. The hard rules in `CLAUDE.md`
and the invariants in `docs/INVARIANTS.md` are non-negotiable. Read both
before writing any Pine code.

## Context — what already exists

- `specs/pullback_indicator.spec.md` — full reverse-engineered spec for the
  9/20 EMA pullback signal logic. Read this first. The "Version history"
  section explains why v1 had a critical HTF repaint bug and how v2 fixes
  it. The "Open questions" section lists tunables I have not yet decided.
- `src/indicators/pullback_indicator.pine` v2 — the audit-clean indicator.
  Already round-tripped through TradingView; screenshot in
  `notes/pullback_indicator-2026-04-30.png`. Treat this as the canonical
  signal source.
- `docs/PATTERNS.md` has the patterns you'll need: "Strategy declaration
  with explicit defaults", "Persistent var pattern", "Diagnostic table",
  "Webhook JSON alert".
- `.claude/skills/pine-strategy-tester/SKILL.md` enumerates the calc-flag
  matrix and pre-paste checks. Apply it.

## Goal

Produce a strategy at `src/strategies/pullback_strat.pine` that turns the
indicator's `bullSignal` / `bearSignal` into actual orders, plus an
on-chart dashboard table that shows running trade stats.

## Architectural decisions — make these explicitly, do not silently default

1. **Signal source** — duplicate the indicator's signal logic into the
   strategy file (the "Inline-during-dev" pattern in
   `docs/ARCHITECTURE.md`). Do NOT try to `import` from a published
   library; we have not published one yet. When you copy the logic,
   preserve the v2 non-repaint `request.security` idiom verbatim — `[1]`
   offset, `lookahead_on`, tupled.
2. **Stops** — fixed at the original touch bar's `touchLow` (long) /
   `touchHigh` (short). These are already captured in `var float
   bullTouchLow` / `bearTouchHigh`; persist them through the open trade
   via additional `var` state at entry.
3. **Targets** — at entry bar:
   - If `bullPivotValid` → `lastPivotHigh`
   - If `bearPivotValid` → `lastPivotLow`
   - If `breakout_mode = "Pass-through"` and pivot already broken → use
     `i_atrTargetMult * ta.atr(i_atrLen)` as a synthesized target (do NOT
     leave the trade with no target).
   - If `breakout_mode = "ATR target"` → use the ATR target.
   - If `breakout_mode = "Block"` → the entry shouldn't fire in the first
     place; if it does, treat as a bug and assert.
   Capture the chosen target into a `var float entryTarget` at entry.
4. **Position sizing** — for v1, fixed 1 contract via `default_qty_value`.
   Add a TODO comment pointing at `docs/PATTERNS.md` "Library export
   skeleton" for risk-based sizing once `RiskLib` exists.
5. **Calc flags** — every flag in the strategy-tester matrix set
   explicitly. In particular: `calc_on_every_tick = false`,
   `process_orders_on_close = false`, `fill_orders_on_standard_ohlc =
   true`. Commission $2.50/contract, slippage 1 tick, margin 50%/50% per
   `CLAUDE.md` defaults.
6. **EOD flatten** — yes. Default `15:55 ET`, configurable. Use the EOD
   pattern from `.claude/skills/pine-orb/SKILL.md` (IANA tz
   `"America/New_York"`). No overnight holds.
7. **Pyramiding** — 0. One position at a time. New signal while in a
   position is ignored, not stacked.
8. **Alerts** — keep static `alertcondition` for now (matching indicator
   v2). Add a TODO comment for the v2-strat upgrade to `alert()` with
   JSON webhook bodies per `docs/PATTERNS.md` "Webhook JSON alert".
9. **Pine v6 safety** — apply the four canonical bug checks from
   `pine-repaint-audit` BEFORE asking me to publish. Specifically: no
   `ta.*` inside conditionals, no `varip` unless intentional, all
   `plot/plotshape/bgcolor/alertcondition` at global scope, all
   user-defined functions at root indent.

## Dashboard — what stats, where, when

A `var table` in `position.bottom_right` (so it doesn't collide with the
indicator's debug labels), gated by `barstate.islast` per the diagnostic
table pattern. Use `format.mintick` for any price-shaped output. Cells:

| Row | Label              | Value                                                |
|-----|--------------------|------------------------------------------------------|
| 0   | Position           | "FLAT" / "LONG x" / "SHORT x"                        |
| 1   | Entry              | `strategy.position_avg_price` (mintick) or "—"       |
| 2   | Stop / Target      | `entryStop` / `entryTarget` (mintick) or "—"         |
| 3   | Open R             | live `(close - entry) / (entry - stop)` for longs    |
| 4   | Trades             | `strategy.closedtrades`                              |
| 5   | Wins / Losses      | "W:n  L:n"                                           |
| 6   | Win rate           | `wins / closedtrades * 100` formatted "##.# %"       |
| 7   | Profit factor      | `strategy.grossprofit / abs(strategy.grossloss)`     |
| 8   | Max DD             | `strategy.max_drawdown` (mintick)                    |
| 9   | Net P&L            | `strategy.netprofit` (mintick)                       |

Use `str.format` for numeric formatting. For win rate, guard against
division by zero (closedtrades == 0). Same guard for profit factor when
grossloss == 0.

Inputs to expose for the dashboard:
- `i_showDashboard` (bool, default true)
- `i_dashbg` (color, default `color.new(color.black, 70)`)

## Spec-first

Before you write `src/strategies/pullback_strat.pine`, write
`specs/pullback_strat.spec.md` from `specs/_TEMPLATE.spec.md`, filled in.
The strategy spec should:

- Reference the indicator spec for signal logic ("see
  `pullback_indicator.spec.md` § Signal logic"), not duplicate it.
- Spell out the entry/exit/stop/target/EOD/sizing decisions above.
- List the calc-flag values you're committing to, with the WHY for each
  non-default.
- Set the backtest plan: `/MES`, last 30 RTH sessions, 1m TF; PF > 1.3,
  max DD < 10%, win rate > 40% as the go/no-go bar.

## Output deliverables

1. `specs/pullback_strat.spec.md` — written first.
2. `src/strategies/pullback_strat.pine` — generated from the spec.
3. `pine-repaint-audit` run on the new file. Include the verdict in your
   reply, formatted per `.claude/skills/pine-repaint-audit/SKILL.md`.
4. `pine-strategy-tester` pre-paste smoke-test checklist completed,
   results in your reply.
5. Use the `pine-reviewer` subagent (read-only) for an independent pass
   before pasting to TradingView. Surface its verdict in your reply.

## Checkpoints — pause and wait at each

- **CHECKPOINT A — after spec is drafted.** Print the spec path and the
  three sections most likely to need my pushback (entry condition, stop
  / target rules, calc flags). Wait for "spec go" before generating Pine.
- **CHECKPOINT B — after Pine is generated and audited.** Print the
  audit + reviewer verdicts. If FAIL, fix and re-audit. If PASS, print
  the file size and ask permission to update CHANGELOG and run
  `/pine-publish`. Wait for "publish go".
- **CHECKPOINT C — `/pine-publish` ritual.** Manual paste; the
  Claude-in-Chrome MCP can't reach `tradingview.com`. Print the file
  contents inline with === markers, give me the TradingView steps,
  expect me to drop a screenshot at
  `notes/pullback_strat-<YYYY-MM-DD>.png` and reply `published pass`.
  After that, write the CHANGELOG entry and stop.

## Constraints — do not

- Do not silently regenerate the indicator file. If you find a bug while
  duplicating the signal logic, surface it as a finding and ask before
  editing the indicator.
- Do not add Heikin-Ashi, Renko, or any non-standard chart-type
  defenses beyond `fill_orders_on_standard_ohlc = true`.
- Do not add `calc_on_every_tick = true` even temporarily.
- Do not add new repo-level conventions (file layout, naming) without
  flagging.
- Do not commit anything; I'll review the diff and commit manually.

Begin with reading `specs/pullback_indicator.spec.md` and
`src/indicators/pullback_indicator.pine`.
