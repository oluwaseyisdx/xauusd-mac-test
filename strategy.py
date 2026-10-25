"""Research-only daily XAUUSD support/resistance breakout backtest.

No broker connections, order placement, or external packages.
One position maximum. Daily next-open entry and resting stop/TP assumed;
within-bar stop wins when both stop and target are touched.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from math import floor, isfinite
from pathlib import Path


@dataclass(frozen=True)
class Bar:
    date: date
    open: float
    high: float
    low: float
    close: float


def load(path: Path) -> list[Bar]:
    with Path(path).open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    bars = [Bar(date.fromisoformat(r['Date']), *(float(r[k]) for k in ('Open', 'High', 'Low', 'Close'))) for r in rows]
    if len(bars) < 8:
        raise ValueError('Requires warm-up bars and test data')
    for i, b in enumerate(bars):
        if not all(isfinite(x) and x > 0 for x in (b.open,b.high,b.low,b.close)):
            raise ValueError('Invalid price')
        if b.low > min(b.open,b.close) or b.high < max(b.open,b.close):
            raise ValueError(f'OHLC inconsistent: {b.date}')
        if i and bars[i-1].date >= b.date:
            raise ValueError('Dates must be ascending, unique')
    return bars


def signal(bars: list[Bar], i: int, lookback: int = 3):
    """Signal using close of i and highs/lows strictly before i."""
    if i < lookback:
        return None
    past = bars[i-lookback:i]
    if bars[i].close > max(b.high for b in past):
        return 'LONG'
    if bars[i].close < min(b.low for b in past):
        return 'SHORT'
    return None


def backtest(bars: list[Bar], start: date = date(2026,10,1),
             initial_balance: float = 1000.0,
             max_risk_pct: float = 5.0,
             lookback: int = 3,
             reward_risk: float = 2.0,
             adverse_fill_usd_per_oz: float = 0.5,
             stop_buffer_usd_per_oz: float = 1.0,
             contract_oz_per_lot: float = 100.0,
             min_lot: float = 0.01,
             lot_step: float = 0.01) -> dict:
    """Daily OHLC research model, not an executable MT5 bot.

    Fixed nominal initial $50 cap per trade, bounded again to <=5% of equity.
    Typical XAUUSD CFD 0.01 lot = 1 oz is an assumption, not broker verified.
    Entry/exit fills each worse by $0.50/oz. STOP prioritized over TP.
    Position size only chosen if the entry, stop and risk can satisfy lot step.
    Signals emitted at close, entries at following bar open (no lookahead).
    """
    if not (initial_balance > 0 and 0 < max_risk_pct < 100 and lookback >= 2 and reward_risk > 0
            and adverse_fill_usd_per_oz >= 0 and stop_buffer_usd_per_oz >= 0
            and contract_oz_per_lot > 0 and lot_step > 0 and min_lot > 0):
        raise ValueError('Invalid configuration')
    if start > bars[-1].date or len([b for b in bars if b.date < start]) < lookback:
        raise ValueError('Insufficient pre-start history')
    capital = initial_balance
    position = None
    pending = None
    trades = []
    signals = []
    skips = []
    equity_curve = []
    halfspread = adverse_fill_usd_per_oz
    max_nominal_risk = initial_balance * max_risk_pct / 100
    for i, b in enumerate(bars):
        if b.date < start:
            continue
        if pending and position is None:
            direction, raw_stop, signal_date = pending
            sign = 1 if direction=='LONG' else -1
            entry = b.open + sign * halfspread
            if (entry - raw_stop)*sign <= halfspread:   # invalid or too-tight stop
                skips.append({'date':str(b.date), 'side': direction, 'reason':'stop crossed or invalid after entry gap'})
            else:
                risk_per_oz = (entry - raw_stop)*sign + halfspread
                risk_budget = min(max_nominal_risk, capital*max_risk_pct/100)
                raw_lots = risk_budget / (risk_per_oz * contract_oz_per_lot)
                lots = floor((raw_lots + 1e-12)/lot_step) * lot_step
                if lots + 1e-12 < min_lot:
                    skips.append({'date':str(b.date), 'side': direction, 'reason':'minimum lot risks >5%',
                                  'minimum_lot_risk_usd':round(min_lot*contract_oz_per_lot*risk_per_oz,2)})
                else:
                    oz = lots*contract_oz_per_lot
                    target = entry + sign * (reward_risk * risk_per_oz)
                    position = {'side':direction,'sign':sign,'entry_date':str(b.date),
                                'signal_date':signal_date,'entry':entry,'stop':raw_stop,'target':target,
                                'lot':round(lots,8),'oz':oz,'planned_risk_usd':oz*risk_per_oz,
                                'risk_budget_usd':risk_budget}
        pending = None
        if position:
            p=position
            # Account for market gap past stop/target at bar open, then OHLC.
            # Same-day entries can encounter stop/target after their opening fill.
            if p['sign'] == 1:
                stopped = b.open <= p['stop'] or b.low <= p['stop']
                hit_tp = b.open >= p['target'] or b.high >= p['target']
                stop_exit = min(b.open,p['stop']) - halfspread
                tp_exit = p['target'] - halfspread if b.open < p['target'] else b.open-halfspread
            else:
                stopped = b.open >= p['stop'] or b.high >= p['stop']
                hit_tp = b.open <= p['target'] or b.low <= p['target']
                stop_exit = max(b.open,p['stop']) + halfspread
                tp_exit = p['target'] + halfspread if b.open > p['target'] else b.open+halfspread
            if stopped or hit_tp:
                exit_px = stop_exit if stopped else tp_exit
                pnl = p['sign']*(exit_px-p['entry'])*p['oz']
                capital += pnl
                trades.append({**{k: v for k,v in p.items() if k not in ('sign','oz')},
                               'exit_date':str(b.date),'exit':round(exit_px,4),'pnl_usd':round(pnl,4),
                               'reason':'STOP' if stopped else 'TARGET', 'balance_after':round(capital,4)})
                position = None
        # mark to market (exit fill adverse) at each day close
        mtm = capital
        if position:
            mtm += position['oz'] * position['sign'] * (b.close-position['sign']*halfspread-position['entry'])
        equity_curve.append({'date':str(b.date),'equity_usd':round(mtm,4)})
        # One position at a time; no same-bar reentry after exit except pending for tomorrow.
        if position is None and i < len(bars)-1:
            direction=signal(bars,i,lookback)
            if direction:
                raw_stop = b.low - stop_buffer_usd_per_oz if direction=='LONG' else b.high + stop_buffer_usd_per_oz
                pending=(direction,raw_stop,str(b.date))
                signals.append({'date':str(b.date),'side':direction,'stop':round(raw_stop,4)})
    # Explicit close at the final observed bar; not pretending future Oct 26 data exist.
    if position:
        p=position
        b=bars[-1]
        liquidation=b.close-p['sign']*halfspread
        pnl=p['sign']*(liquidation-p['entry'])*p['oz']
        capital += pnl
        trades.append({**{k: v for k,v in p.items() if k not in ('sign','oz')},
                       'exit_date':str(b.date),'exit':round(liquidation,4),'pnl_usd':round(pnl,4),
                       'reason':'END_OF_SAMPLE','balance_after':round(capital,4)})
        equity_curve[-1]['equity_usd']=round(capital,4)
    peak=initial_balance
    worst=0.0
    for row in equity_curve:
        peak=max(peak,row['equity_usd'])
        worst=min(worst,row['equity_usd']/peak - 1)
    wins=sum(t['pnl_usd'] > 0 for t in trades)
    return {'period_start':str(start),'period_end':str(bars[-1].date),
            'initial_balance_usd':initial_balance,'ending_balance_usd':round(capital,2),
            'net_pnl_usd':round(capital-initial_balance,2),
            'return_pct':round(100*(capital/initial_balance-1),2),
            'risk_cap_usd':round(max_nominal_risk,2),'max_daily_close_drawdown_pct':round(100*worst,2),
            'signal_count':len(signals),'trades':len(trades),'wins':wins,
            'win_rate_pct':round(100*wins/len(trades),2) if trades else None,
            'signals':signals, 'skipped_signals':skips, 'trade_log':trades,
            'equity_curve':equity_curve,
            'assumptions':{'signal':'close break of previous 3 daily bar highs/lows',
                           'entry':'next bar open', 'stop':'signal-bar low/high +/- $1 per ounce',
                           'target':'2x planned stop loss distance',
                           'trading_costs':'$0.50/oz adverse on entry AND exit',
                           'lot_min':min_lot,'lot_step':lot_step,'contract_oz_per_lot':contract_oz_per_lot,
                           'gap_rule':'gap stop exit at worse opening price','same_bar_conflict':'stop first',
                           'capital_and_margin':'simulated PnL, no broker margin/swap validated'} }
