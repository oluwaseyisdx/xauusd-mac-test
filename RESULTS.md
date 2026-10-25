# XAU/USD October 2026 — $1,000 account, 5% risk per position

**Status:** Historical paper backtest executed on Linux x86-64, 11/11 tests passed.
**NOT an actual macOS run:** The included GitHub Actions Apple M1 workflow has not been invoked.
**NOT a working MT5 or broker connection test.**

## Time & instrument

- From October 1, 2026 through the last published market observation, Friday October 23, 2026 (Sunday Oct 25 is not a regular gold trading day).
- Source: ChartExchange XAU/USD *spot quote* daily Open, High, Low, Close archive at
  https://chartexchange.com/symbol/forex-xauusd/historical/ (accessed October 25, 2026).
- Sep 24–30 prices warm up rolling levels. Sunday partial UTC sessions in source are retained.
- Not a broker-specific XAUUSD CFD quote history, so spreads and precise candles may differ.

## Model selection

The earlier monthly 12-month-resistance/6-month-support design does not produce a meaningful
October-only test with a defined $50 stop budget. This is a different, newly configured
**daily 3-session support/resistance breakout** for October, without optimization.

- Long when daily close exceeds past 3 sessions' highs; short on close below past 3 lows.
- Trade on next daily open; no lookahead and max 1 position.
- Stop $1 beyond signal bar opposite extreme; target at 2x estimated initial risk distance.
- Limit planned position risk to **$50** (5% of original $1,000) and at most 5% current equity.
- Assume 100 troy ounces per lot, 0.01 minimum, 0.01 step; broker terms unverified.
- Price penalized $0.50 per oz at entry and $0.50 per oz at exit (a synthetic spread/slippage model).
- No commission, swaps, margin, forced liquidation or broker latency modeled.
- Stop takes precedence if stop and target both within same daily range.
- Gaps can cause losses >5% even with an intended $50 stop; no hard risk guarantee.
- Outstanding trades hypothetically liquidated at Oct 23 sample close.

## Results

| Metric | Simulated value |
|---|---:|
| Initial balance | $1,000.00 |
| Ending balance | **$1,086.56** |
| Net profit | **+$86.56** |
| Return on starting balance | **+8.66%** |
| Maximum planned risk/trade | $50.00 |
| Accepted trades | 1 |
| Winners | 1 |
| Win rate | 100% **of one trade** |
| Skipped signals for min lot/risk | 3 |
| Max observed close-to-close equity drawdown | −1.24% |

**Only accepted trade:** Signal short on Oct 20, enter Oct 21 at 4113.26/oz
(after $0.50 adverse fill), stop at 4156.29/oz, target at 4026.20/oz.
0.01 lot = assumed 1 oz. Planned loss if stop filled: **$43.53**, below $50 cap.
Oct 22 bar low reached the take profit, assumed exit 4026.70/oz after an
additional $0.50 adverse fill. Simulated profit: **+$86.56**. No other executed
positions in October. Three additional signals rejected because the assumed
smallest tradable lot would risk $54.29, $60.55 and $104.50 respectively.

**Caveats:** With 1 closed position, the 100% win rate is not informative.
Rules/data were selected for a retrospective exercise, not out-of-sample
forward verification. Tick-level timing is unavailable and the price source is
not your MT5 broker. CFD stop and margin constraints, swap, commission and
spread changes may materially change the result. No real trades occurred.

## Tests executed here

- `python -m unittest discover -s tests -v` — **11 passed**, Linux x86_64.
- `python run.py` — generated `backtest_result.json`, Linux x86_64.
- Code uses Python standard library only and has no `msvcrt`, `MetaTrader5`, or `.exe` dependency.

## Actual macOS test still pending

`.github/workflows/arm-macos-test.yml` launches GitHub's real Apple M1
`macos-15` runner, verifies `uname -s` = Darwin and `uname -m` = arm64,
then executes unit tests and strategy with artifact upload.
**It has not run; no CI run ID or Apple Silicon result exists.**
Use Actions > Run workflow after putting these files into a GitHub repository.
Passing this workflow would validate this *backtesting strategy* on macOS,
not MT5 execution, broker connectivity, or user's five-engine bot.

## Separate MT5 read-only compatibility probe (unexecuted)

`mac_mt5_readonly_probe.py` allows the end user to inspect basic `mt5_mac`
connectivity on an Apple Silicon Mac with MT5 installed, without order placement.
This script was *not* run on a Mac and provides **no confirmed** broker-bridge
result yet. See README for installation conditions and limitations.
