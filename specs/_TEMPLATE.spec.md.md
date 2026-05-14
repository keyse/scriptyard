# Spec: <name>
## Type
indicator | strategy | library
## Instrument(s)
SPX | /ES | /NQ | /MNQ | /GC | other
## Timeframe(s)
chart TF + any HTF/LTF reads
## Signal logic
What the script computes and when it fires. Plain English. Include edge cases.
## Entry rules (strategies)
- Long entry condition:
- Short entry condition:
- Position sizing:
## Exit rules (strategies)
- Stop:
- Target:
- Time-based:
- EOD:
## Risk
- Max position:
- Max daily loss:
- Slippage assumption:
- Commission assumption:
## Alerts
- Alert message format:
- Webhook destination:
## Inputs
| Name | Type | Default | Range | Description |
|------|------|---------|-------|-------------|
## Outputs (indicators)
- Plots:
- Tables:
- Labels:
## Backtest plan
- Date range:
- Symbol(s):
- TF:
- Calc flags:
- What "good enough" looks like (PF, drawdown, win rate):
## Open questions
-
