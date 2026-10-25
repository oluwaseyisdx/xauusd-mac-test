"""Offline Apple Silicon verification. No MT5 connection and no trades."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from strategy import backtest, load

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--require-apple-silicon', action='store_true')
args = parser.parse_args()

mac = platform.system() == 'Darwin' and platform.machine().lower() == 'arm64'
prices = ROOT / 'xauusd_daily_ohlc.csv'
actual = backtest(load(prices))
reference = json.loads((ROOT / 'backtest_result.json').read_text(encoding='utf8'))
# Compare complete deterministic output on different architectures. Matches alone do
# not prove that MT5, macOS Wine, broker connections or order submission work.
assert actual == reference, 'Full backtest output differs from the checked-in reference'
assert actual['trades'] == 1 and actual['ending_balance_usd'] == 1086.56
report = {
    'runtime_os': platform.system(),
    'runtime_architecture': platform.machine(),
    'runtime_python': sys.version.split()[0],
    'real_apple_silicon_macos': mac,
    'offline_tests': 'PASS',
    'simulated_account_usd': 1000,
    'simulated_per_trade_max_risk_usd': 50,
    'backtest_final_balance_usd': actual['ending_balance_usd'],
    'backtest_trades': actual['trades'],
    'dataset_sha256': hashlib.sha256(prices.read_bytes()).hexdigest(),
    'mt5_terminal_connection': 'NOT_TESTED',
    'live_order_execution': 'NOT_TESTED',
    'macbook_battery_runtime': 'NOT_TESTED',
}
(ROOT / 'mac_verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
print(json.dumps(report, indent=2))
if args.require_apple_silicon and not mac:
    raise SystemExit('FAIL: Runner is not real ARM64 macOS')
