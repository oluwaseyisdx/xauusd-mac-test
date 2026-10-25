from __future__ import annotations
import sys
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategy import Bar, backtest, load, signal

DIR=Path(__file__).resolve().parents[1]

class StrategyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars=load(DIR/'xauusd_daily_ohlc.csv')

    def test_source_range_and_ohlc(self):
        self.assertEqual(str(self.bars[0].date), '2026-09-24')
        self.assertEqual(str(self.bars[-1].date), '2026-10-23')
        self.assertEqual(len(self.bars), 26)

    def test_applies_five_percent_of_1000(self):
        result=backtest(self.bars)
        self.assertEqual(result['risk_cap_usd'],50.0)
        self.assertTrue(all(t['planned_risk_usd'] <= 50+1e-7 for t in result['trade_log']))

    def test_one_trade_expected(self):
        result=backtest(self.bars)
        self.assertEqual(result['trades'],1)
        self.assertEqual(result['ending_balance_usd'],1086.56)
        self.assertEqual(result['trade_log'][0]['side'],'SHORT')
        self.assertEqual(result['trade_log'][0]['exit_date'],'2026-10-22')
        self.assertEqual(result['trade_log'][0]['reason'],'TARGET')

    def test_min_lot_rejects_excess_risk(self):
        result=backtest(self.bars,max_risk_pct=1)
        self.assertEqual(result['trades'],0)
        self.assertGreaterEqual(len(result['skipped_signals']),1)

    def test_small_lots_still_obey_cap(self):
        result=backtest(self.bars,min_lot=0.001,lot_step=0.001)
        self.assertTrue(all(t['planned_risk_usd'] <= t['risk_budget_usd']+1e-6 for t in result['trade_log']))

    def test_signal_excludes_current_bar_from_levels(self):
        b=[Bar(date(2026,1,i+1),100,105,95,100) for i in range(3)]
        b.append(Bar(date(2026,1,4),100,106,98,106))
        self.assertEqual(signal(b,3), 'LONG')
        b[-1]=replace(b[-1],high=106,close=104)
        self.assertIsNone(signal(b,3))

    def test_no_future_lookahead(self):
        before=signal(self.bars,10)
        altered=self.bars[:11] + [replace(b,open=b.open*1.2,high=b.high*1.2,low=b.low*1.2,close=b.close*1.2)
                                  for b in self.bars[11:]]
        self.assertEqual(signal(altered,10),before)

    def test_deterministic(self):
        self.assertEqual(backtest(self.bars),backtest(self.bars))

    def test_bad_budget_rejected(self):
        with self.assertRaises(ValueError):
            backtest(self.bars,max_risk_pct=0)

    def test_fewer_than_three_warmup_rejected(self):
        with self.assertRaises(ValueError):
            backtest(self.bars,start=date(2026,9,27))

    def test_month_only(self):
        result=backtest(self.bars)
        self.assertEqual(result['period_start'],'2026-10-01')
        self.assertEqual(result['period_end'],'2026-10-23')
        self.assertTrue(all(row['date'] >= '2026-10-01' for row in result['equity_curve']))

if __name__=='__main__':
    unittest.main()
