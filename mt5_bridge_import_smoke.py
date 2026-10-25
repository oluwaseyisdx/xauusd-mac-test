"""Only check third-party mt5_mac import/API shape; does NOT connect to terminal."""
from __future__ import annotations
import json
import platform
from pathlib import Path

status = {
  'platform': platform.platform(),
  'checked_package': 'mt5_mac==0.3.0',
  'test_scope': 'Import and basic API presence only. No initialize/login/orders.',
  'mt5_terminal_connection': 'NOT_TESTED',
  'order_execution': 'NOT_TESTED',
}
try:
    import mt5_mac as mt5
    expected = ('initialize', 'shutdown', 'account_info', 'symbol_info',
                'copy_rates_from_pos', 'positions_get', 'order_send')
    missing = [s for s in expected if not hasattr(mt5, s)]
    status['missing_expected_functions'] = missing
    status['bridge_import'] = 'PASS' if not missing else 'FAIL'
except Exception as exc:
    status['bridge_import'] = 'FAIL'
    status['error'] = f'{type(exc).__name__}: {exc}'
Path('mt5_bridge_import_result.json').write_text(json.dumps(status, indent=2) + '\n', encoding='utf8')
print(json.dumps(status, indent=2))
if status['bridge_import'] != 'PASS':
    raise SystemExit(1)
