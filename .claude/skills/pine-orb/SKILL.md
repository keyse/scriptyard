---
name: pine-orb
description: Opening Range Breakout strategy patterns for /ES, /NQ, /MNQ, /GC. Use when writing or editing ORB indicators or strategies in src/. Encodes session strings, daily-reset idiom, breakout/fakeout filters, and EOD flatten.
allowed-tools: Read Edit Write
---
# ORB patterns
## Session strings (IANA tz "America/New_York")
| Window      | Session string         | Use case                              |
|-------------|------------------------|---------------------------------------|
| ORB-5       | `"0930-0935:23456"`    | Aggressive intraday on /ES, /NQ       |
| ORB-15      | `"0930-0945:23456"`    | Default; balances signal and noise    |
| ORB-30      | `"0930-1000:23456"`    | Conservative; fewer trades            |
| RTH         | `"0930-1600:23456"`    | Trading window                        |
| EOD flatten | `t >= 1555` check      | Force-flat 5 min before close         |
## Daily-reset state idiom
See `docs/PATTERNS.md` "Daily-reset session state (ORB skeleton)" — load that pattern as the starting template.
## Breakout vs fakeout filters
Layer these on top of the bare breakout signal; recommend at least one:
- **Volume confirmation** — breakout bar volume > 1.5× SMA(volume, 20).
- **Time-of-day floor** — no entries before ORB window closes.
- **Time-of-day ceiling** — no entries after 1430 ET (avoid late-day chop).
- **Range filter** — skip days where OR width > 1.5× ATR(20) (already extended).
- **Higher-TF bias** — only longs if HTF (e.g., 60m) close > HTF EMA(20).
## EOD flatten
```pine
i_tz = "America/New_York"
flatHour   = 15
flatMinute = 55
isFlatTime = hour(time, i_tz) == flatHour and minute(time, i_tz) >= flatMinute
if isFlatTime and strategy.position_size != 0
    strategy.close_all(comment = "EOD")
```
Always present in committed ORB strategies. Never hold overnight on intraday signals.
## Templates
See `templates/orb_skeleton.pine` for a complete working example.
## See also
- @../../../docs/DOMAIN.md (instrument tick sizes)
- @../../../docs/PATTERNS.md (Daily-reset session state)
