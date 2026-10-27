#!/usr/bin/env python3
'''CircleCI Mac v8: read-only MQL5 compile, install, and automatic local PING/STATUS.

Never opens/closes/modifies trades. Does not consume or output broker credentials.
Use --prepare while the fresh CircleCI runner initializes.
Use --verify-only after manually logging into Deriv via the remote MT5 desktop.
'''
import argparse
import csv
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

MQL_SOURCE = r'''#property strict
#property version "1.00"
#property description "Read-only macOS Python-MT5 bridge probe. No order functions."

// This Expert writes a heartbeat and accepts ONLY PING / STATUS read-only requests.
// It NEVER calls any trading function. Can run with Algo Trading switched OFF.
int heartbeat_sequence = 0;
int last_command_id = -1;

void WriteHeartbeat()
{
   MqlTick tick;
   ZeroMemory(tick);
   bool has_tick = SymbolInfoTick(_Symbol, tick);
   bool quote_recent = has_tick && tick.time > 0 && MathAbs(TimeLocal()-tick.time) < 180;
   bool connected = (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   bool account_present = AccountInfoInteger(ACCOUNT_LOGIN) > 0;
   int fh = FileOpen("dualbot_mac_status.csv",
       FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ, ',');
   if(fh == INVALID_HANDLE)
   {
      Print("DUALBOT_READONLY_STATUS_FILE_OPEN_ERROR:", GetLastError());
      return;
   }
   FileWrite(fh, ++heartbeat_sequence, _Symbol, (int)connected,
             (int)account_present, (int)quote_recent,
             has_tick ? DoubleToString(tick.bid, _Digits) : "",
             has_tick ? DoubleToString(tick.ask, _Digits) : "");
   FileClose(fh);
}

void CheckReadOnlyCommand()
{
   int fh = FileOpen("dualbot_mac_command.csv",
       FILE_READ|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE, ',');
   if(fh == INVALID_HANDLE)
      return; // Python has not yet created a command.
   if(FileIsEnding(fh))
   {
      FileClose(fh);
      return;
   }
   string id_text = FileReadString(fh);
   string action = FileReadString(fh);
   FileClose(fh);
   int id = (int)StringToInteger(id_text);
   if(id <= 0 || id == last_command_id)
      return;
   last_command_id = id;
   string result = "REJECTED";
   if(action == "PING") result = "PONG";
   if(action == "STATUS") result = "STATUS_OK";
   int ack = FileOpen("dualbot_mac_ack.csv",
        FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ, ',');
   if(ack != INVALID_HANDLE)
   {
      FileWrite(ack, id, result, heartbeat_sequence);
      FileClose(ack);
      Print("DUALBOT_READONLY_ACK id=", id, " result=", result);
   }
}

int OnInit()
{
   EventSetTimer(2);
   WriteHeartbeat();
   Print("DUALBOT_READONLY_STARTED symbol=", _Symbol);
   return INIT_SUCCEEDED;
}
void OnTimer()
{
   WriteHeartbeat();
   CheckReadOnlyCommand();
}
void OnDeinit(const int reason)
{
   EventKillTimer();
}'''
assert 'OrderSend(' not in MQL_SOURCE and 'CTrade' not in MQL_SOURCE

HOME = Path.home()
PREFIX = HOME / 'Library/Application Support/net.metaquotes.wine.metatrader5'
ROOT = PREFIX / 'drive_c/Program Files/MetaTrader 5'
WINE = Path('/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine64')
SOURCE = PREFIX / 'drive_c/CircleCIProbe/DualBotMacProbe.mq5'
EX5 = SOURCE.with_suffix('.ex5')
LOG = SOURCE.with_suffix('.log')
STARTUP = PREFIX / 'drive_c/dualbot_v8_startup.ini'
OUTPUT = Path('verification_reports')
OUTPUT.mkdir(parents=True,exist_ok=True)
REPORT_FILE = OUTPUT / 'dualbot_auto_bridge_v8.json'
STATUS_NAME='dualbot_mac_status.csv'
ACK_NAME='dualbot_mac_ack.csv'
COMMAND_NAME='dualbot_mac_command.csv'


def save_report(report):
    REPORT_FILE.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print('SAFE_DUALBOT_V8_REPORT='+json.dumps(report,sort_keys=True),flush=True)


def compile_ea(report):
    if not (WINE.is_file() and (ROOT/'metaeditor64.exe').is_file()):
        raise RuntimeError('Official MT5 Wine installation not initialized')
    SOURCE.parent.mkdir(parents=True,exist_ok=True)
    SOURCE.write_text(MQL_SOURCE,encoding='ascii')
    EX5.unlink(missing_ok=True)
    LOG.unlink(missing_ok=True)
    env=os.environ.copy()
    env['WINEPREFIX']=str(PREFIX)
    env['WINEDEBUG']='-all'
    try:
        p=subprocess.run([str(WINE),r'C:\Program Files\MetaTrader 5\metaeditor64.exe',
                          r'/compile:C:\CircleCIProbe\DualBotMacProbe.mq5','/log'],
                         env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=100)
        report['compiler_process_exited']=True
        report['compiler_exit_code']=p.returncode
    except subprocess.TimeoutExpired:
        report['compiler_process_exited']=False
        raise RuntimeError('MetaEditor compile timed out')
    for _ in range(10):
        if EX5.is_file() and EX5.stat().st_size>=500:
            break
        time.sleep(1)
    compiler_ok=False
    if LOG.is_file():
        raw=LOG.read_bytes()
        enc='utf-16le' if raw.count(b'\x00')>len(raw)//8 else 'utf-8'
        log=raw.decode(enc,errors='replace')
        compiler_ok=bool(re.search(r'Result:\s*0\s+errors?,\s*0\s+warnings?',log,re.I))
    # MetaEditor may return 1 even on successful compile; verify .ex5 AND compiler log.
    report['compiler_reported_zero_errors_warnings']=compiler_ok
    report['ex5_created']=EX5.is_file() and EX5.stat().st_size>=500
    report['mql5_compiled']=compiler_ok and report['ex5_created']
    if not report['mql5_compiled']:
        raise RuntimeError('MQL5 compile not verified; no usable .ex5')


def known_experts_dirs():
    dirs={ROOT/'MQL5/Experts'}
    patterns=(
        'drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/*/MQL5/Experts',
        'drive_c/users/*/Application Data/MetaQuotes/Terminal/*/MQL5/Experts',
        'drive_c/users/*/AppData/Local/MetaQuotes/Terminal/*/MQL5/Experts',
        'drive_c/users/*/Local Settings/Application Data/MetaQuotes/Terminal/*/MQL5/Experts',
    )
    for pat in patterns:
        dirs.update(PREFIX.glob(pat))
    # Some Wine builds create a hash-level terminal data folder without MQL5 yet.
    for pat in ('drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/*',
                'drive_c/users/*/Application Data/MetaQuotes/Terminal/*'):
        for base in PREFIX.glob(pat):
            if base.is_dir() and len(base.name)>=16 and not base.name.lower().startswith('common'):
                dirs.add(base/'MQL5/Experts')
    return sorted(dirs)


def install_ea(report):
    targets=known_experts_dirs()
    copied=0
    # Do not use sudo and do not traverse unrelated home directories.
    for dest in targets:
        try:
            dest.mkdir(parents=True,exist_ok=True)
            shutil.copy2(EX5,dest/'DualBotMacProbe.ex5')
            if (dest/'DualBotMacProbe.ex5').stat().st_size==EX5.stat().st_size:
                copied+=1
        except (PermissionError,OSError):
            pass
    report['mt5_expert_directories_found']=len(targets)
    report['expert_copies_verified']=copied
    report['expert_installed']=copied>0
    if not report['expert_installed']:
        raise RuntimeError('No writable MT5 Experts destination')


def terminal_pids():
    try:
        ps=subprocess.run(['ps','-axo','pid=,command='],capture_output=True,
                         text=True,check=True,timeout=10).stdout
    except (OSError,subprocess.SubprocessError):
        return []
    out=[]
    for line in ps.splitlines():
        p=line.strip().split(None,1)
        if len(p)==2 and p[0].isdigit() and 'terminal64.exe' in p[1].lower():
            out.append(int(p[0]))
    return list(dict.fromkeys(out))


def close_preinit_terminal():
    # Fresh job only; do not use with an already manually logged-in terminal.
    for pid in terminal_pids():
        try: os.kill(pid,signal.SIGTERM)
        except OSError: pass
    for _ in range(8):
        if not terminal_pids(): return
        time.sleep(1)


def common_dirs():
    patterns=('drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/Common/Files',
              'drive_c/users/*/Application Data/MetaQuotes/Terminal/Common/Files',
              'drive_c/ProgramData/MetaQuotes/Terminal/Common/Files')
    dirs=[]
    for pat in patterns:
        dirs.extend(p for p in PREFIX.glob(pat) if p.is_dir())
    return sorted(set(dirs))


def read_row(file):
    try:
        if not file.is_file() or file.stat().st_size>4096:
            return None
        # MQL5 FILE_ANSI CSV writes a standard plain-text row.
        with file.open('r',encoding='latin-1',newline='') as f:
            records=list(csv.reader(f))
        return records[-1] if records else None
    except (OSError,UnicodeError,csv.Error):
        return None


def fresh_status(timeout):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        for folder in common_dirs():
            f=folder/STATUS_NAME
            r=read_row(f)
            if r and len(r)>=7 and r[0].strip().isdigit():
                try:
                    if f.stat().st_mtime>time.time()-20:
                        return folder,r
                except OSError:
                    pass
        time.sleep(1)
    return None,None


def send_command(folder,request_id,command):
    tmp=folder/'dualbot_mac_command.tmp'
    with tmp.open('w',encoding='ascii',newline='') as f:
        csv.writer(f,lineterminator='\r\n').writerow([request_id,command])
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp,folder/COMMAND_NAME)


def check_ack(folder,id,expected,timeout=22):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        row=read_row(folder/ACK_NAME)
        if row and len(row)>=2 and row[0]==str(id):
            return row[1]==expected
        time.sleep(.5)
    return False


def check_two_way(report,timeout=65):
    folder,original=fresh_status(timeout)
    if folder is None:
        report['fresh_heartbeat_seen']=False
        return
    report['fresh_heartbeat_seen']=True
    report['heartbeat_sequence_start']=int(original[0])
    report['mt5_connected_flag']=original[2].strip()=='1'
    report['mt5_account_present_flag']=original[3].strip()=='1'
    report['recent_chart_quote_flag']=original[4].strip()=='1'
    report['chart_symbol_is_requested_deriv_symbol']=original[1].strip()!='EURUSD'
    # Do not export broker name, symbol, account, bid/ask, or raw CSV to artifacts.
    (folder/ACK_NAME).unlink(missing_ok=True)
    nonce=int(time.time())%1000000000
    for step,(command,expected) in enumerate((('PING','PONG'),('STATUS','STATUS_OK')),1):
        rid=nonce+step
        send_command(folder,rid,command)
        ok=check_ack(folder,rid,expected)
        report['ping_pong_acknowledged' if step==1 else 'status_acknowledged']=ok
        if not ok:
            return
    final_folder,final=fresh_status(15)
    report['heartbeat_advanced']=(final_folder==folder and final is not None
                                  and int(final[0])>int(original[0]))
    report['two_way_bridge_proven']=(report['ping_pong_acknowledged'] and
        report['status_acknowledged'] and report['heartbeat_advanced'])


def start_probe(report):
    close_preinit_terminal()
    for folder in common_dirs():
        for name in (STATUS_NAME,ACK_NAME,COMMAND_NAME):
            (folder/name).unlink(missing_ok=True)
    # Deliberately no [Common] credentials: broker selection occurs interactively.
    # Expert Advisor auto-starts on EURUSD solely for the nontrading communication check.
    STARTUP.write_text('[Experts]\nEnabled=1\nAllowLiveTrading=0\nAllowDllImport=0\n'
                       'Account=0\nProfile=0\n[StartUp]\nExpert=DualBotMacProbe\nSymbol=EURUSD\nPeriod=M1\n',encoding='utf-8')
    env=os.environ.copy()
    env['WINEPREFIX']=str(PREFIX)
    env['WINEDEBUG']='-all'
    subprocess.Popen([str(WINE),r'C:\Program Files\MetaTrader 5\terminal64.exe',
                     r'/config:C:\dualbot_v8_startup.ini'],env=env,
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                     start_new_session=True)
    report['mt5_terminal_launch_requested']=True


def main():
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true')
    group.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    report={
        'version':'dualbot_mac_auto_bridge_v8',
        'stage':'prepare' if args.prepare else 'verify_only',
        'platform':'macOS Apple Silicon',
        'no_trading_functions':True,
        'mql5_compiled':False,
        'expert_installed':False,
        'fresh_heartbeat_seen':False,
        'ping_pong_acknowledged':False,
        'status_acknowledged':False,
        'heartbeat_advanced':False,
        'two_way_bridge_proven':False,
        'broker_login_verified':False,
        'demo_trading_orders_sent':False,
    }
    try:
        if args.prepare:
            compile_ea(report)
            install_ea(report)
            start_probe(report)
            check_two_way(report,timeout=65)
        else:
            check_two_way(report,timeout=25)
            report['terminal_connected_and_account_present']=bool(report.get('mt5_connected_flag')
                                                 and report.get('mt5_account_present_flag'))
        if report['two_way_bridge_proven']:
            print('TWO_WAY_BRIDGE_PROVEN=YES; NO_TRADES=YES',flush=True)
        else:
            print('TWO_WAY_BRIDGE_PROVEN=NO; SEE_SANITIZED_REPORT',flush=True)
    except Exception as e:
        report['failure_type']=type(e).__name__
        print('BRIDGE_DIAGNOSTIC_ERROR_CLASS='+type(e).__name__,flush=True)
    finally:
        save_report(report)
    # Preserve GUI access if automated EA startup fails, so interactive inspection remains possible.
    if args.prepare and not report.get('expert_installed'):
        raise SystemExit('Cannot continue: compiled EA not installed')
    if args.verify_only and not report.get('two_way_bridge_proven'):
        raise SystemExit('Two-way bridge not proven; inspect sanitized report')


if __name__=='__main__':
    main()
