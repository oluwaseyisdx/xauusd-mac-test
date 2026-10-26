"""CircleCI M4 Pro: read-only 2-by-2 MT5 startup diagnostic.

Change ONE factor at a time: chart (EURUSD vs requested) and credentials
(absent vs disposable demo). No order-submission, no account values in reports.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

OUTPUT = Path('verification_reports')
OUTPUT.mkdir(exist_ok=True)
PREFIX = Path.home() / 'Library/Application Support/net.metaquotes.wine.metatrader5'
ROOT = PREFIX / 'drive_c/Program Files/MetaTrader 5'
WINE = Path('/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine64')
SOURCE = PREFIX / 'drive_c/CircleCIProbe/CircleCIReadOnlyProbe.mq5'
EX5 = SOURCE.with_suffix('.ex5')
COMPILER_LOG = SOURCE.with_suffix('.log')
CONFIG = PREFIX / 'drive_c/circleci_readonly.ini'
ENV = os.environ.copy()
ENV['WINEPREFIX'] = str(PREFIX)
ENV['WINEDEBUG'] = '-all'

# This MQL5 Expert never imports trading libraries or sends an order.
# It writes a small local heartbeat from MT5 to the Wine FILE_COMMON folder.
PROBE_SOURCE = r'''#property strict
#property version "1.00"
int seq=0;
void Heartbeat(){
   int h=FileOpen("circleci_readonly.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ,',');
   if(h==INVALID_HANDLE){Print("CIRCLECI_PROBE_FILE_OPEN_FAILED error=",GetLastError());return;}
   MqlTick t; bool qt=SymbolInfoTick(_Symbol,t);
   long connected=TerminalInfoInteger(TERMINAL_CONNECTED);
   long account=AccountInfoInteger(ACCOUNT_LOGIN);
   bool recent=(qt && t.time>0 && MathAbs(TimeLocal()-t.time)<180);
   FileWrite(h,++seq,TimeLocal(),connected,account,AccountInfoString(ACCOUNT_SERVER),recent);
   FileClose(h);
}
int OnInit(){EventSetTimer(2);Heartbeat();return INIT_SUCCEEDED;}
void OnTimer(){Heartbeat();}
void OnDeinit(const int reason){EventKillTimer();}
'''
assert 'OrderSend(' not in PROBE_SOURCE and 'CTrade' not in PROBE_SOURCE

LOGIN = os.environ.get('DERIV_MT5_LOGIN', '').strip()
PASSWORD = os.environ.get('DERIV_MT5_PASSWORD', '')
SERVER = os.environ.get('DERIV_MT5_SERVER', '').strip()
HAVE_DEMO = bool(LOGIN and PASSWORD and SERVER)
TARGET_SYMBOL = os.environ.get('MT5_TEST_SYMBOL', '').strip()

# These outputs contain only flags, counts and fixed stage labels.
report = {
    'diagnostic_version': 'four_way_chart_and_credentials_isolation_v2',
    'platform': 'macOS Apple Silicon',
    'official_mt5_app_installed': WINE.is_file() and (ROOT / 'terminal64.exe').is_file(),
    'demo_credentials_supplied': HAVE_DEMO,
    'target_symbol_explicitly_supplied': bool(TARGET_SYMBOL),
    'no_trades_requested': True,
    'order_functions_used': False,
    'mql5_probe_compiled': False,
    'baseline_bridge_proven': False,
    'native_python_bridge_proven': False,
    'demo_target_bridge_proven': False,
    'broker_login_proven': False,
    'fresh_quote_proven': False,
    'stages': [],
}


def safe_symbol(symbol):
    return bool(symbol and len(symbol) <= 64 and not any(c in symbol for c in '\r\n=[]'))


def compile_probe():
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    SOURCE.write_text(PROBE_SOURCE, encoding='ascii')
    editor = r'C:\Program Files\MetaTrader 5\metaeditor64.exe'
    win_source = r'C:\CircleCIProbe\CircleCIReadOnlyProbe.mq5'
    attempts = []
    for mode, arg in (
        ('short_path', '/compile:' + win_source),
        ('quoted_short_path', '/compile:"' + win_source + '"'),
    ):
        for file in (EX5, COMPILER_LOG):
            file.unlink(missing_ok=True)
        try:
            proc = subprocess.run([str(WINE), editor, arg, '/log'],
                                  env=ENV, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=85)
            exit_code = proc.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            exit_code, timed_out = None, True
        for _ in range(6):
            if EX5.exists() or COMPILER_LOG.exists():
                break
            time.sleep(2)
        good_ex5 = EX5.is_file() and EX5.stat().st_size >= 500
        summary = ''
        if COMPILER_LOG.is_file():
            data = COMPILER_LOG.read_bytes()
            enc = 'utf-16le' if data.count(b'\x00') > len(data)//8 else 'utf-8'
            msg = data.decode(enc, errors='replace')
            # Only the controlled compiler's result count; no file paths/log dumps.
            match = re.search(r'Result:\s*\d+\s+errors?,\s*\d+\s+warnings?', msg, re.I)
            summary = match.group(0) if match else 'result_not_found'
        attempts.append({
            'mode': mode, 'exit_code': exit_code, 'timed_out': timed_out,
            'compiler_log_present': COMPILER_LOG.is_file(),
            'ex5_created': good_ex5, 'compiler_result': summary,
        })
        if good_ex5:
            break
    report['compile_attempts'] = attempts
    report['mql5_probe_compiled'] = good_ex5
    print('SAFE_COMPILATION=' + json.dumps(attempts), flush=True)
    if not good_ex5:
        return False
    dest = ROOT / 'MQL5/Experts/CircleCIReadOnlyProbe.ex5'
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EX5, dest)
    for folder in PREFIX.glob('drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/*/MQL5/Experts'):
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(EX5, folder / EX5.name)
    return True


def terminal_pids():
    try:
        ps = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True,
                            text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in ps.splitlines():
        try:
            pid_text, cmd = line.strip().split(None, 1)
            pid = int(pid_text)
        except (ValueError, TypeError):
            continue
        lower = cmd.lower()
        if 'terminal64.exe' in lower and ('wine' in lower or 'metatrader' in lower):
            found.append(pid)
    return list(dict.fromkeys(found))


def close_terminal():
    old = terminal_pids()
    for pid in old:
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass
    for _ in range(10):
        if not terminal_pids():
            break
        time.sleep(1)
    for pid in terminal_pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except (OSError, ValueError):
            pass
    time.sleep(3)
    return len(old), bool(terminal_pids())


def common_files():
    patterns = (
        'drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/Common/Files/circleci_readonly.csv',
        'drive_c/users/*/Application Data/MetaQuotes/Terminal/Common/Files/circleci_readonly.csv',
        'drive_c/ProgramData/MetaQuotes/Terminal/Common/Files/circleci_readonly.csv',
    )
    found = []
    for p in patterns:
        found.extend(PREFIX.glob(p))
    return list(dict.fromkeys(found))


def read_snapshot(path, used_demo):
    try:
        if path.stat().st_size > 4096:
            return None
        rows = path.read_text(encoding='latin-1').replace('\ufeff', '').splitlines()
        values = rows[-1].strip().split(',') if rows else []
        if len(values) < 6 or int(values[0]) <= 0:
            return None
        return {
            'seq': int(values[0]),
            'terminal_connected': values[2].strip().lower() in ('1', 'true'),
            'account_present': values[3].strip().isdigit() and int(values[3]) > 0,
            'account_matches_supplied_demo': bool(used_demo and values[3].strip() == LOGIN),
            'server_matches_supplied_demo': bool(used_demo and values[4].strip().casefold() == SERVER.casefold()),
            'recent_quote': values[5].strip().lower() in ('1', 'true'),
        }
    except (IndexError, OSError, ValueError, UnicodeError):
        return None


def new_journal_flags(since):
    folders = [ROOT / 'logs', ROOT / 'MQL5/Logs']
    folders += list(PREFIX.glob('drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/*/logs'))
    folders += list(PREFIX.glob('drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/*/MQL5/Logs'))
    recent = []
    for folder in folders:
        if not folder.is_dir():
            continue
        for p in folder.glob('*.log'):
            try:
                if p.stat().st_mtime >= since - 5:
                    recent.append(p)
            except OSError:
                pass
    flags = {
        'new_journal_count': len(recent),
        'journal_mentions_probe': False,
        'journal_mentions_file_open_error': False,
        'journal_mentions_expert_init_failure': False,
        'journal_mentions_invalid_symbol': False,
        'journal_mentions_authorization_failure': False,
        'journal_mentions_connection_failure': False,
    }
    for file in recent[:40]:
        try:
            data = file.read_bytes()[-100000:]
            for enc in ('utf-8', 'utf-16le'):
                message = data.decode(enc, errors='replace').lower()
                flags['journal_mentions_probe'] |= 'circlecireadonlyprobe' in message
                flags['journal_mentions_file_open_error'] |= 'circleci_probe_file_open_failed' in message
                flags['journal_mentions_expert_init_failure'] |= any(x in message for x in (
                    'initialization failed', 'cannot load expert', 'failed to load expert'))
                flags['journal_mentions_invalid_symbol'] |= any(x in message for x in (
                    'invalid symbol', 'unknown symbol', 'symbol not found'))
                flags['journal_mentions_authorization_failure'] |= any(x in message for x in (
                    'authorization failed', 'authorization error', 'invalid account'))
                flags['journal_mentions_connection_failure'] |= any(x in message for x in (
                    'no connection', 'connection failed', 'network error'))
        except OSError:
            pass
    return flags


def run_stage(tag, symbol, use_demo):
    result = {
        'stage': tag,
        'uses_demo_credentials': use_demo,
        'uses_target_symbol': symbol == TARGET_SYMBOL and bool(TARGET_SYMBOL),
        'terminal_started': False,
        'file_common_heartbeat_seen': False,
        'heartbeat_sequence': 0,
        'old_terminal_processes_remaining': False,
        'terminal_connected_flag': False,
        'account_present_flag': False,
        'account_matches_supplied_demo': False,
        'server_matches_supplied_demo': False,
        'quote_recent_flag': False,
        'broker_login_proven': False,
        'fresh_quote_proven': False,
        'wine_launcher_running': False,
    }
    if not safe_symbol(symbol):
        result['symbol_configuration_invalid'] = True
        return result
    if use_demo and (not HAVE_DEMO or not LOGIN.isdigit() or
                     any('\r' in x or '\n' in x for x in (LOGIN, PASSWORD, SERVER))):
        result['demo_credential_format_invalid'] = True
        return result
    result['prior_terminal_count'], result['old_terminal_processes_remaining'] = close_terminal()
    for file in common_files():
        try:
            file.unlink()
        except OSError:
            pass
    config_text = ''
    if use_demo:
        config_text = (f'[Common]\nLogin={LOGIN}\nPassword={PASSWORD}\n'
                       f'Server={SERVER}\nKeepPrivate=0\n')
    config_text += ('[Experts]\nEnabled=1\nAllowLiveTrading=0\nAllowDllImport=0\n'
                    'Account=0\nProfile=0\n[StartUp]\n'
                    f'Expert=CircleCIReadOnlyProbe\nSymbol={symbol}\nPeriod=M1\n')
    CONFIG.write_text(config_text, encoding='utf-8')
    CONFIG.chmod(0o600)
    try:
        started = time.time()
        proc = subprocess.Popen([str(WINE), r'C:\Program Files\MetaTrader 5\terminal64.exe',
                                 r'/config:C:\circleci_readonly.ini'],
                                env=ENV, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        for step in range(55):
            if step % 4 == 0:
                result['terminal_started'] |= bool(terminal_pids())
            snapshot = None
            for file in common_files():
                try:
                    if file.stat().st_mtime < started - 2:
                        continue
                    found = read_snapshot(file, use_demo)
                    if found and (snapshot is None or found['seq'] >= snapshot['seq']):
                        snapshot = found
                except OSError:
                    continue
            if snapshot:
                result['heartbeat_sequence'] = max(result['heartbeat_sequence'], snapshot['seq'])
                if snapshot['seq'] >= 2:
                    result['file_common_heartbeat_seen'] = True
                    result['terminal_connected_flag'] = snapshot['terminal_connected']
                    result['account_present_flag'] = snapshot['account_present']
                    result['account_matches_supplied_demo'] = snapshot['account_matches_supplied_demo']
                    result['server_matches_supplied_demo'] = snapshot['server_matches_supplied_demo']
                    result['quote_recent_flag'] = snapshot['recent_quote']
                    result['broker_login_proven'] = bool(use_demo and snapshot['terminal_connected']
                        and snapshot['account_matches_supplied_demo']
                        and snapshot['server_matches_supplied_demo'])
                    result['fresh_quote_proven'] = bool(result['broker_login_proven'] and snapshot['recent_quote'])
                    break
            time.sleep(2)
        result['wine_launcher_running'] = proc.poll() is None
        result.update(new_journal_flags(started))
    finally:
        CONFIG.unlink(missing_ok=True)
    print('SAFE_STAGE=' + json.dumps(result, sort_keys=True), flush=True)
    return result


if __name__ == '__main__':
    try:
        if compile_probe():
            scenarios = [('A_control_EURUSD_no_credentials', 'EURUSD', False)]
            if TARGET_SYMBOL:
                scenarios.append(('B_target_symbol_no_credentials', TARGET_SYMBOL, False))
            if HAVE_DEMO:
                scenarios.append(('C_control_EURUSD_with_demo', 'EURUSD', True))
                if TARGET_SYMBOL:
                    scenarios.append(('D_target_symbol_with_demo', TARGET_SYMBOL, True))
            for name, symbol, uses_demo in scenarios:
                result = run_stage(name, symbol, uses_demo)
                report['stages'].append(result)
                if name.startswith('A_'):
                    report['baseline_bridge_proven'] = result['file_common_heartbeat_seen']
                if name.startswith('D_'):
                    report['demo_target_bridge_proven'] = result['file_common_heartbeat_seen']
                    report['broker_login_proven'] = result['broker_login_proven']
                    report['fresh_quote_proven'] = result['fresh_quote_proven']
            report['native_python_bridge_proven'] = any(s['file_common_heartbeat_seen'] for s in report['stages'])
    finally:
        # Only sanitized booleans/counts; never include login/server or raw journals.
        CONFIG.unlink(missing_ok=True)
        (OUTPUT / 'circleci_m4_readonly.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print('SAFE_MAC_MT5_RESULT=' + json.dumps(report, sort_keys=True), flush=True)

    if not report['mql5_probe_compiled']:
        raise SystemExit('MQL5 compilation not verified; see safe report')
    if not report['baseline_bridge_proven']:
        raise SystemExit('Control EURUSD bridge missing; see safe report')
    if HAVE_DEMO and TARGET_SYMBOL and not report['fresh_quote_proven']:
        raise SystemExit('Deriv target-symbol demo login + fresh quote not proven; see safe report')
    if HAVE_DEMO and not TARGET_SYMBOL:
        raise SystemExit('MT5_TEST_SYMBOL not supplied; cannot validate target demo symbol')
