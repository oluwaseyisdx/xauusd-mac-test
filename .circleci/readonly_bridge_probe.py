import json,os,subprocess,time,shutil
from pathlib import Path

output=Path('verification_reports');output.mkdir(exist_ok=True)
wine=Path('/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine64')
prefix=Path.home()/'Library/Application Support/net.metaquotes.wine.metatrader5'
root=prefix/'drive_c/Program Files/MetaTrader 5'
expert=prefix/'drive_c/CircleCIProbe/CircleCIReadOnlyProbe.mq5'
expert.parent.mkdir(parents=True,exist_ok=True)
expert.write_text(r'''#property strict
// CircleCI proof of MT5 -> native Mac Python communication. No trading functions.
int seq=0;
void Heartbeat(){
   int h=FileOpen("circleci_readonly.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ,',');
   if(h==INVALID_HANDLE){Print("CIRCLECI_PROBE_FILE_OPEN_FAILED error=",GetLastError());return;}
   MqlTick t; bool qt=SymbolInfoTick(_Symbol,t);
   long connected=TerminalInfoInteger(TERMINAL_CONNECTED);
   long account=AccountInfoInteger(ACCOUNT_LOGIN);
   bool fresh=(qt && t.time>0 && MathAbs(TimeLocal()-t.time)<180);
   FileWrite(h,++seq,TimeLocal(),connected,account,AccountInfoString(ACCOUNT_SERVER),fresh);
   FileClose(h);
}
int OnInit(){EventSetTimer(2);Heartbeat();return INIT_SUCCEEDED;}
void OnTimer(){Heartbeat();}
void OnDeinit(const int reason){EventKillTimer();}
''',encoding='ascii')
env=os.environ.copy();env['WINEPREFIX']=str(prefix)
# A short, space-free Windows source path avoids the ambiguity of the previous
# C:\Program Files\... command-line argument.
editor=r'C:\Program Files\MetaTrader 5\metaeditor64.exe'
win_source=r'C:\CircleCIProbe\CircleCIReadOnlyProbe.mq5'
ex5=expert.with_suffix('.ex5')
compile_log=expert.with_suffix('.log')
compile_attempts=[]
compiled=False
compile_exit=None
import re

# MetaQuotes documents /compile:<Windows source file> and /log; the log is
# created next to the source, not at the custom /log:<path> assumed previously.
for label,compile_argument in [
    ('short_path', '/compile:'+win_source),
    ('quoted_short_path', '/compile:"'+win_source+'"'),
]:
    for file in (ex5,compile_log):
        try:file.unlink()
        except FileNotFoundError:pass
    cmd=[str(wine),editor,compile_argument,'/log']
    exit_code=None
    timed_out=False
    try:
        proc=subprocess.run(cmd,env=env,stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,timeout=80)
        exit_code=proc.returncode
    except subprocess.TimeoutExpired:
        timed_out=True
    for _ in range(6):
        if ex5.is_file() or compile_log.is_file():break
        time.sleep(2)
    compiled=ex5.is_file() and ex5.stat().st_size>=500
    attempt={'mode':label,'exit_code':exit_code,'timed_out':timed_out,
             'compiler_log_present':compile_log.is_file(),
             'ex5_created':compiled}
    if compile_log.is_file():
        data=compile_log.read_bytes()
        enc='utf-16le' if data.count(b'\x00')>len(data)//8 else 'utf-8'
        log=data.decode(enc,errors='replace')
        # Report only diagnostic lines from controlled, non-secret probe code.
        lines=[x.strip() for x in log.splitlines() if re.search(r'\b(error|warning|result)\b',x,re.I)]
        attempt['compiler_messages']=[re.sub(r'[A-Za-z]:\\[^\s]+','<windows-path>',line)[:180] for line in lines[-8:]]
        attempt['compiler_log_bytes']=len(data)
    else:
        attempt['compiler_messages']=[]
    compile_attempts.append(attempt)
    print('MQL5_COMPILE_ATTEMPT='+json.dumps(attempt,sort_keys=True),flush=True)
    compile_exit=exit_code if not timed_out else -99
    if compiled:break

# A compiled .ex5 must be installed in the MT5 Expert directory for StartUp.
if compiled:
    target=root/'MQL5/Experts/CircleCIReadOnlyProbe.ex5'
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ex5,target)
    copied=0
    for dest in prefix.glob('drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/*/MQL5/Experts'):
        dest.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ex5,dest/ex5.name)
        copied+=1
    print('COMPILED_EX5_INSTALLED=YES; DATA_FOLDER_COPIES='+str(copied),flush=True)

details={'platform':'macOS Apple Silicon','official_mt5_app_installed':True,
         'mql5_probe_compiled':compiled,'metaeditor_process_exit_code':compile_exit,
         'compile_attempts':compile_attempts,
         'no_trades_requested':True,'order_functions_used':False}
# Optional demo credentials are read from CircleCI Project Settings > Environment Variables.
# Never echo credentials. Never store config or raw journals as artifacts.
login=os.environ.get('DERIV_MT5_LOGIN','').strip()
password=os.environ.get('DERIV_MT5_PASSWORD','')
server=os.environ.get('DERIV_MT5_SERVER','').strip()
have_demo=bool(login and password and server)
details['demo_credentials_supplied']=have_demo
details['broker_login_proven']=False
details['fresh_quote_proven']=False
details['native_python_bridge_proven']=False
config=prefix/'drive_c/circleci_readonly.ini'

# The macOS installation stage already used `open -a` to initialize the Wine
# prefix.  MT5 is a single-instance application; launching another terminal
# without first closing the old one can silently ignore the /config argument.
# The previously unverified probe also added /portable, unlike the older
# Mac test that did produce a FILE_COMMON heartbeat.

def running_terminal_pids():
    try:
        ps=subprocess.run(['ps','-axo','pid=,command='],capture_output=True,
                          text=True,timeout=10,check=True).stdout
    except (OSError,subprocess.SubprocessError):
        return []
    result=[]
    for line in ps.splitlines():
        try:
            pid,cmd=line.strip().split(None,1)
            pid=int(pid)
        except (ValueError,TypeError):
            continue
        cmd=cmd.lower()
        if 'terminal64.exe' in cmd and ('wine' in cmd or 'metatrader' in cmd):
            result.append(pid)
    return list(dict.fromkeys(result))

def common_snapshots():
    patterns=(
       'drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/Common/Files/circleci_readonly.csv',
       'drive_c/users/*/Application Data/MetaQuotes/Terminal/Common/Files/circleci_readonly.csv',
       'drive_c/ProgramData/MetaQuotes/Terminal/Common/Files/circleci_readonly.csv',
    )
    found=[]
    for pattern in patterns:
        found.extend(prefix.glob(pattern))
    return list(dict.fromkeys(found))

def read_snapshot(path):
    try:
        if not path.is_file() or path.stat().st_size>4096:
            return None
        rows=path.read_text(encoding='latin-1').replace('\ufeff','').splitlines()
        if not rows:
            return None
        fields=rows[-1].strip().split(',')
        if len(fields)<6:
            return None
        seq=int(fields[0].strip())
        if seq<=0:
            return None
        return {
          'seq':seq,
          'terminal_connected_flag':fields[2].strip().lower() in ('1','true'),
          'account_present_flag':fields[3].strip().isdigit() and int(fields[3].strip())>0,
          'account_matches_supplied_demo':bool(have_demo and fields[3].strip()==login),
          'server_matches_supplied_demo':bool(have_demo and fields[4].strip().casefold()==server.casefold()),
          'symbol_quote_flag':fields[5].strip().lower() in ('1','true'),
        }
    except (ValueError,OSError,UnicodeError,IndexError):
        return None

def journal_paths():
    dirs=[root/'logs',root/'MQL5/Logs']
    dirs.extend(prefix.glob('drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/*/logs'))
    dirs.extend(prefix.glob('drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/*/MQL5/Logs'))
    return [f for d in dirs if d.is_dir() for f in d.glob('*.log') if f.is_file()]

def inspect_journals(start):
    files=[]
    for f in journal_paths():
        try:
            if f.stat().st_mtime >= start - 5:
                files.append(f)
        except OSError:
            pass
    seen_probe=False
    seen_file_error=False
    seen_init_failure=False
    for f in files[:40]:
        try:
            data=f.read_bytes()[-100000:]
            for encoding in ('utf-8','utf-16le'):
                log=data.decode(encoding,errors='replace').lower()
                seen_probe|='circlecireadonlyprobe' in log
                seen_file_error|='file_open_failed' in log
                seen_init_failure|=any(k in log for k in ('initialization failed','cannot load expert','failed to load expert'))
        except OSError:
            pass
    # Search only predefined failure categories. Never report raw journal text;
    # it can contain account/server information.
    missing_symbol=False
    auth_failure=False
    connection_failure=False
    for f in files[:40]:
        try:
            data=f.read_bytes()[-100000:]
            log=data.decode('utf-16le' if data.count(b'\x00')>len(data)//8 else 'utf-8',errors='replace').lower()
            missing_symbol |= any(x in log for x in ('unknown symbol','invalid symbol','symbol not found','symbol does not exist','cannot open chart'))
            auth_failure |= any(x in log for x in ('authorization failed','invalid password','invalid account','authorization error','account disabled'))
            connection_failure |= any(x in log for x in ('connection failed','server not found','old version','no connection'))
        except OSError:pass
    return {
      'new_journal_count':len(files),
      'journal_mentions_probe':seen_probe,
      'journal_mentions_file_open_error':seen_file_error,
      'journal_mentions_expert_init_failure':seen_init_failure,
      'journal_mentions_invalid_symbol':missing_symbol,
      'journal_mentions_authorization_failure':auth_failure,
      'journal_mentions_connection_failure':connection_failure,
    }

details.update({
    'diagnostic_version': 'two_stage_control_then_demo',
    'chart_symbol_explicitly_supplied': bool(os.environ.get('MT5_TEST_SYMBOL', '').strip()),
    'baseline_bridge_proven': False,
    'demo_bridge_proven': False,
    'native_python_bridge_proven': False,
    'broker_login_proven': False,
    'fresh_quote_proven': False,
    'terminal_launch_attempted': False,
    'no_trades_requested': True,
})

# Each launch uses a fresh read-only MT5 startup configuration. The first
# (without credentials) isolates Mac/MQL5/FILE_COMMON from broker access.
# The second uses demo credentials and the exact Deriv chart symbol supplied
# privately in CircleCI Environment Variables. No account values are logged.
def run_stage(tag, symbol, use_demo):
    import signal
    result={
        'stage':tag,
        'symbol_explicitly_configured':bool(os.environ.get('MT5_TEST_SYMBOL','').strip()) if use_demo else False,
        'terminal_started':False,
        'prior_terminal_count':0,
        'old_terminal_processes_remaining':False,
        'file_common_heartbeat_seen':False,
        'heartbeat_sequence':0,
        'terminal_connected_flag':False,
        'account_present_flag':False,
        'account_matches_supplied_demo':False,
        'server_matches_supplied_demo':False,
        'quote_recent_flag':False,
        'broker_login_proven':False,
        'fresh_quote_proven':False,
        'new_journal_count':0,
        'journal_mentions_probe':False,
        'journal_mentions_file_open_error':False,
        'journal_mentions_expert_init_failure':False,
        'journal_mentions_invalid_symbol':False,
        'journal_mentions_authorization_failure':False,
        'journal_mentions_connection_failure':False,
    }
    if not symbol or len(symbol)>64 or any(ch in symbol for ch in '\n\r[]='):
        result['symbol_config_invalid']=True
        return result
    if use_demo and (not login.isdigit() or any(ch in password+server for ch in '\n\r')):
        result['demo_credential_format_invalid']=True
        return result

    # Terminate MT5 started by the installation smoke test or earlier stage.
    previous=running_terminal_pids()
    result['prior_terminal_count']=len(previous)
    for pid in previous:
        try:os.kill(pid,signal.SIGTERM)
        except (OSError,ValueError):pass
    for _ in range(10):
        if not running_terminal_pids():break
        time.sleep(1)
    for pid in running_terminal_pids():
        try:os.kill(pid,signal.SIGKILL)
        except (OSError,ValueError):pass
    time.sleep(3)
    result['old_terminal_processes_remaining']=bool(running_terminal_pids())
    for f in common_snapshots():
        try:f.unlink()
        except (OSError,ValueError):pass

    common=''
    if use_demo:
        common=f'[Common]\nLogin={login}\nPassword={password}\nServer={server}\nKeepPrivate=0\n'
    content=(common+'[Experts]\nEnabled=1\nAllowLiveTrading=0\nAllowDllImport=0\n'
             'Account=0\nProfile=0\n[StartUp]\nExpert=CircleCIReadOnlyProbe\n'
             'Symbol='+symbol+'\nPeriod=M1\n')
    # The config includes disposable demo credentials only in the demo stage.
    config.write_text(content,encoding='utf-8')
    os.chmod(config,0o600)
    try:
        started_at=time.time()
        p=subprocess.Popen([str(wine),r'C:\Program Files\MetaTrader 5\terminal64.exe',
                            r'/config:C:\circleci_readonly.ini'],
                           env=env,stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,start_new_session=True)
        details['terminal_launch_attempted']=True
        snapshot=None
        for i in range(58):
            if i%4==0:
                result['terminal_started'] |= bool(running_terminal_pids())
            for file in common_snapshots():
                try:
                    if file.stat().st_mtime<started_at-2:continue
                except OSError:continue
                candidate=read_snapshot(file)
                if candidate:
                    snapshot=candidate
                    result['heartbeat_sequence']=max(result['heartbeat_sequence'],candidate['seq'])
            if snapshot and result['heartbeat_sequence']>=2:break
            time.sleep(2)
        result['wine_launcher_running']=p.poll() is None
        result.update(inspect_journals(started_at))
        if snapshot and result['heartbeat_sequence']>=2:
            result['file_common_heartbeat_seen']=True
            result['terminal_connected_flag']=snapshot['terminal_connected_flag']
            result['account_present_flag']=snapshot['account_present_flag']
            result['quote_recent_flag']=snapshot['symbol_quote_flag']
            if use_demo:
                result['account_matches_supplied_demo']=snapshot['account_matches_supplied_demo']
                result['server_matches_supplied_demo']=snapshot['server_matches_supplied_demo']
                result['broker_login_proven']=bool(result['terminal_connected_flag']
                    and result['account_matches_supplied_demo']
                    and result['server_matches_supplied_demo'])
                result['fresh_quote_proven']=bool(result['broker_login_proven']
                    and result['quote_recent_flag'])
    finally:
        config.unlink(missing_ok=True)
    return result

# Broker secrets never appear in the sanitized artifact.
if compiled:
    stages=[]
    if have_demo:
        baseline=run_stage('baseline_without_broker_credentials','EURUSD',False)
        stages.append(baseline)
        details['baseline_bridge_proven']=baseline['file_common_heartbeat_seen']
        requested_symbol=os.environ.get('MT5_TEST_SYMBOL','').strip()
        if requested_symbol:
            demo_result=run_stage('demo_with_requested_chart_symbol',requested_symbol,True)
            stages.append(demo_result)
            details['demo_bridge_proven']=demo_result['file_common_heartbeat_seen']
            details['broker_login_proven']=demo_result['broker_login_proven']
            details['fresh_quote_proven']=demo_result['fresh_quote_proven']
        else:
            details['demo_stage_skipped_missing_explicit_chart_symbol']=True
    else:
        baseline=run_stage('baseline_without_broker_credentials','EURUSD',False)
        stages.append(baseline)
        details['baseline_bridge_proven']=baseline['file_common_heartbeat_seen']
    details['stages']=stages
    details['native_python_bridge_proven']=details['baseline_bridge_proven'] or details['demo_bridge_proven']

# Do not publish secret .ini, journals, stdout, server name, or account number.
(output/'circleci_m4_readonly.json').write_text(json.dumps(details,indent=2)+'\n',encoding='utf-8')
print('SAFE_MAC_MT5_RESULT='+json.dumps(details,sort_keys=True),flush=True)
if not compiled:
    raise SystemExit('MQL5 compilation not verified; inspect safe report')
if not details['baseline_bridge_proven']:
    raise SystemExit('Unauthenticated MT5 baseline heartbeat missing; inspect safe report')
if have_demo and not details['demo_bridge_proven']:
    raise SystemExit('Deriv demo-stage EA heartbeat missing; inspect safe report')
if have_demo and not details['fresh_quote_proven']:
    raise SystemExit('Deriv demo login + fresh quote not verified; inspect safe report')
