# Architecture
## Three artifact types
Pine has three mutually exclusive script declarations and they gate which APIs are available:
- **Indicator** (`indicator(...)`) — overlays or panes. No `strategy.*` namespace.
- **Strategy** (`strategy(...)`) — same as indicator plus `strategy.entry`, `strategy.exit`, `strategy.order`, `strategy.close`, `strategy.cancel`, plus the Strategy Tester. One `strategy()` per script.
- **Library** (`library(...)`) — exports `export` functions/UDTs to other scripts. Cannot plot.
Repo split mirrors this:
```
src/indicators/   // *.pine, indicator() declaration
src/strategies/   // *_strat.pine, strategy() declaration
src/libraries/    // *Lib.pine, library() declaration, PascalCase
```
## Indicator/strategy pairs
Standard pattern: a signal **indicator** for visual confirmation on a chart, plus a **strategy** that consumes the same logic for backtesting and alert routing. Keep the signal logic in a library when it grows beyond ~50 lines so the indicator and strategy stay in sync via `import`.
## Library publishing
TradingView's `import user/LibName/version as alias` resolves against the TradingView cloud, not this repo. Two viable patterns:
1. **Publish-to-import** — publish the library as a Public/Private TradingView script, then `import` the published version into consumers. Versioning is via TradingView's "Publish New Version."
2. **Inline-during-dev** — keep the library code locally and copy/paste it into consumers during development; switch to `import` only after publishing. Best for solo work.
There is no good middle ground; pick one per library and document it at the top of the library file.
## Pine Editor as runtime
The Pine Editor in TradingView is the only place these scripts execute. There is no native TradingView↔git sync. Workflow:
1. Edit `.pine` locally (Claude Code).
2. Copy file contents.
3. TradingView → Pine Editor → paste → Save → Add to Chart.
4. Verify on chart / Strategy Tester.
5. Capture screenshot to `notes/` if behavior changed.
6. Commit local file.
Cowork + Computer Use can automate steps 2–5; the `pine-publish` skill encodes the ritual.
## Specs
For any non-trivial script (>30 lines), `specs/<name>.spec.md` is checked in **before** the script. The spec is the source of truth for behavior; the `.pine` file is regenerated from it. This is especially important for strategies, where one calc-flag change silently invalidates every backtest.
