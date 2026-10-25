import json
from pathlib import Path
from strategy import backtest, load

BASE = Path(__file__).resolve().parent

def main():
    result=backtest(load(BASE/'xauusd_daily_ohlc.csv'))
    output=BASE/'backtest_result.json'
    output.write_text(json.dumps(result,indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('equity_curve','signals','skipped_signals','trade_log','assumptions')}, indent=2))
    print('Trades:', json.dumps(result['trade_log'],indent=2))
    print('Skipped:', json.dumps(result['skipped_signals'],indent=2))

if __name__=='__main__': main()
