---
name: pine-publish
description: Ritual checklist for pushing a .pine file from this repo into TradingView's Pine Editor — final repaint audit, paste, save, capture screenshot, draft changelog. Trigger explicitly via /pine-publish.
disable-model-invocation: true
allowed-tools: Read Bash(rg *)
---
# Pine publish ritual
## Pre-flight
1. Run `pine-repaint-audit` on the target file. STOP if any REPAINT verdicts.
2. If file is in `src/strategies/`, run `pine-strategy-tester` checklist.
3. Verify `//@version=6` on line 1.
4. Verify filename matches convention: `snake_case.pine` (indicator/strategy) or `PascalCaseLib.pine` (library).
5. Read the file. Confirm specs/<name>.spec.md exists if file is non-trivial.
## Push
6. Copy file contents to clipboard.
7. (Cowork + Computer Use) Switch to browser → TradingView → Pine Editor → New → paste → Save As "<name>".
   (Manual) tell me to do this and wait.
8. Compile errors? Feed back to me with file:line references; do not auto-fix without confirmation.
9. Add to Chart. Confirm visual matches expectation.
## Capture
10. Screenshot chart → save to `notes/<name>-<YYYY-MM-DD>.png`.
11. If strategy: screenshot Strategy Tester Performance Summary too.
12. Draft `CHANGELOG.md` entry: date, file, one-line summary of behavior change.
## Done
13. Print summary: file, lines, audit verdict, screenshot paths, changelog entry.
