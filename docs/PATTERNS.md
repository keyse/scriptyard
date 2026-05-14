# Canonical Pine v6 patterns
## Non-repainting HTF tuple
```pine
//@version=6
indicator("HTF non-repaint", overlay = true)
i_htf = input.timeframe("60", "Higher TF")
[htfO, htfH, htfL, htfC] = request.security(
     syminfo.tickerid, i_htf,
     [open[1], high[1], low[1], close[1]],
     lookahead = barmerge.lookahead_on)
plot(htfC, "HTF Close", color.orange)
```
One call, four values. Cheaper than four separate calls and respects the 40-call limit.
## Strategy declaration with explicit defaults
```pine
//@version=6
strategy("ORB ES",
     overlay              = true,
     initial_capital      = 25000,
     default_qty_type     = strategy.fixed,
     default_qty_value    = 1,
     commission_type      = strategy.commission.cash_per_contract,
     commission_value     = 2.50,
     slippage             = 1,
     margin_long          = 50,
     margin_short         = 50,
     pyramiding           = 0,
     calc_on_every_tick   = false,
     process_orders_on_close = false,
     fill_orders_on_standard_ohlc = true,
     max_lines_count      = 500,
     max_labels_count     = 500,
     max_boxes_count      = 500)
```
Never rely on defaults. Every flag here changes the backtest result.
## Daily-reset session state (ORB skeleton)
```pine
i_orMin = input.int(15, "OR length (min)", minval = 1)
i_session = input.session("0930-1600", "RTH session")
i_tz      = "America/New_York"
inSession = not na(time(timeframe.period, i_session, i_tz))
newDay    = ta.change(time("D"))
var float orHi = na
var float orLo = na
var int   orStart = na
if newDay
    orHi := na
    orLo := na
    orStart := time
if inSession and na(orHi) and time - orStart <= i_orMin * 60 * 1000
    orHi := math.max(nz(orHi, high), high)
    orLo := math.min(nz(orLo, low),  low)
plot(orHi, "OR High", color.green, style = plot.style_linebr)
plot(orLo, "OR Low",  color.red,   style = plot.style_linebr)
```
## Persistent var pattern
```pine
var float entryPrice = na
var int   entryBar   = na
if longSignal and strategy.position_size == 0
    strategy.entry("L", strategy.long)
    entryPrice := close
    entryBar   := bar_index
```
`var` initializes on first bar and survives across bars; plain `=` reassigns on every bar.
## Diagnostic table
```pine
var table dbg = table.new(position.top_right, 2, 4, bgcolor = color.new(color.black, 70))
if barstate.islast
    table.cell(dbg, 0, 0, "pos",   text_color = color.white)
    table.cell(dbg, 1, 0, str.tostring(strategy.position_size), text_color = color.white)
    table.cell(dbg, 0, 1, "entry", text_color = color.white)
    table.cell(dbg, 1, 1, str.tostring(strategy.position_avg_price, format.mintick), text_color = color.white)
```
`barstate.islast` gate is critical — without it the table redraws every bar and you'll burn the runtime budget.
## Library export skeleton
```pine
//@version=6
library("RiskLib", overwrite = true)
//@function Position size by fixed dollar risk.
//@param   equity   Account equity (USD).
//@param   riskPct  Risk as percent of equity (e.g., 0.5 = 0.5%).
//@param   stopDist Distance from entry to stop, in price units.
//@param   tickValue Dollar value of one tick for this instrument.
//@param   tickSize Price increment for this instrument.
//@returns Number of contracts (rounded down to whole units).
export sizeByRisk(simple float equity, simple float riskPct, series float stopDist,
                  simple float tickValue, simple float tickSize) =>
    riskUsd = equity * riskPct / 100
    perContract = (stopDist / tickSize) * tickValue
    perContract > 0 ? math.floor(riskUsd / perContract) : 0
```
Note `simple` qualifier on knobs that should not vary bar-by-bar; `series` for the ones that do.
## Webhook JSON alert
```pine
alertMsg = '{"symbol":"' + syminfo.ticker
         + '","action":"' + (longEntry ? "buy" : "sell")
         + '","qty":1'
         + ',"price":' + str.tostring(close, format.mintick)
         + ',"comment":"orb"}'
if longEntry or shortEntry
    alert(alertMsg, alert.freq_once_per_bar_close)
```
Use `alert()` (dynamic string, conditional) — not `alertcondition()` (const string only).
