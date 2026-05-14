# Trading domain
## Instruments and tick sizes
| Symbol | Description       | Tick size | Tick value (USD) | Session (ET)        |
|--------|-------------------|-----------|------------------|---------------------|
| SPX    | S&P 500 cash      | 0.01      | n/a (cash)       | 0930–1600 RTH       |
| /ES    | E-mini S&P 500    | 0.25      | $12.50           | 1800–1700 ETH wrap  |
| /MES   | Micro E-mini S&P  | 0.25      | $1.25            | 1800–1700 ETH wrap  |
| /NQ    | E-mini Nasdaq 100 | 0.25      | $5.00            | 1800–1700 ETH wrap  |
| /MNQ   | Micro E-mini NQ   | 0.25      | $0.50            | 1800–1700 ETH wrap  |
| /GC    | Gold              | 0.10      | $10.00           | 1800–1700 ETH wrap  |
Always use IANA tz `"America/New_York"`. Sessions in Pine `time()` use `HHMM-HHMM:days` where days are `1=Sun … 7=Sat`. Weekday-only RTH SPX = `"0930-1600:23456"`.
## Strategy primitives in active use
- **0DTE iron condor / broken-wing butterfly on SPX** — directional bias indicator (e.g., VWAP+keltner) drives short strike selection externally. Pine's role is the bias signal and the alert webhook.
- **Credit spreads on SPX** — same pattern: Pine emits directional+volatility signal, broker bridge places the spread.
- **ORB on /ES, /NQ, /MNQ** — opening range breakout, 5- or 15-min OR window, breakout entry, time-of-day stop, EOD flatten.
- **Premium selling on /ES, /NQ, /GC** — futures-side discretionary, Pine used for regime detection (trend vs chop) and volatility regime.
## Alerts and webhooks
Broker bridge convention: alert message body is JSON with `symbol`, `action` (`buy`/`sell`/`exit`), `qty`, `price`, `comment`. Use Pine placeholders inside JSON strings:
```
{"symbol":"{{ticker}}","action":"{{strategy.order.action}}","qty":{{strategy.order.contracts}},"price":{{strategy.order.price}},"comment":"{{strategy.order.comment}}"}
```
Limits: TradingView caps strategy alerts at 15 per 3 minutes. Design entry/exit logic so multi-leg fills don't exceed this on a single bar.
## What "0DTE" means in Pine context
Pine cannot read options chains. 0DTE strategies in this repo are **bias generators** — Pine identifies the directional/volatility regime; option leg selection and order placement happen in the broker bridge. Don't try to model the option in Pine.
