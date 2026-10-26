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
   if(h==INVALID_HANDLE) return;
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
    return {
      'new_journal_count':len(files),
      'journal_mentions_probe':seen_probe,
      'journal_mentions_file_open_error':seen_file_error,
      'journal_mentions_expert_init_failure':seen_init_failure,
    }

details.update({
    'prior_terminal_processes_seen':0,
    'preexisting_processes_terminated':0,
    'previous_portable_mode_removed':True,
    'terminal_launch_attempted':False,
    'terminal_process_seen_after_launch':False,
    'heartbeat_sequence':0,
    'common_file_found':False,
    'new_journal_count':0,
    'journal_mentions_probe':False,
    'journal_mentions_file_open_error':False,
    'journal_mentions_expert_init_failure':False,
})

if compiled:
    # Use the proven macOS MQL5 startup pattern: no /portable, a single running
    # terminal, and the compiled Expert present in the terminal data directories.
    symbol=os.environ.get('MT5_TEST_SYMBOL','EURUSD')
    if not symbol or len(symbol)>64 or any(ch in symbol for ch in '\n\r[]='):
        raise ValueError('Invalid chart symbol')
    common=''
    if have_demo:
        if not login.isdigit() or any(ch in password+server for ch in '\n\r'):
            raise ValueError('Invalid demo credential format')
        common=f'[Common]\nLogin={login}\nPassword={password}\nServer={server}\nKeepPrivate=0\n'
    ini=(common+'[Experts]\nEnabled=1\nAllowLiveTrading=0\nAllowDllImport=0\n'
         'Account=0\nProfile=0\n[StartUp]\nExpert=CircleCIReadOnlyProbe\n'
         'Symbol='+symbol+'\nPeriod=M1\n')
    config.write_text(ini,encoding='utf-8')
    os.chmod(config,0o600)
    try:
        previous=running_terminal_pids()
        details['prior_terminal_processes_seen']=len(previous)
        import signal
        for pid in previous:
            try:
                os.kill(pid,signal.SIGTERM)
                details['preexisting_processes_terminated']+=1
            except (OSError,ValueError):
                pass
        for _ in range(8):
            if not running_terminal_pids():
                break
            time.sleep(1)
        # The runner is a dedicated disposable Mac; prevent a lingering old
        # Wine terminal from redirecting the startup configuration.
        for pid in running_terminal_pids():
            try: os.kill(pid,signal.SIGKILL)
            except (OSError,ValueError): pass
        time.sleep(3)
        details['old_terminal_processes_remaining']=bool(running_terminal_pids())

        # Ensure any snapshot comes from this launch, not an old process.
        for f in common_snapshots():
            try:f.unlink()
            except (OSError,ValueError):pass

        start=time.time()
        details['terminal_launch_attempted']=True
        proc=subprocess.Popen([
            str(wine),r'C:\Program Files\MetaTrader 5\terminal64.exe',
            r'/config:C:\circleci_readonly.ini',
        ],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
          start_new_session=True)
        print('MT5_READONLY_LAUNCHED_STANDARD_MODE=YES',flush=True)
        snap=None
        for tick in range(70):
            if tick%5==0:
                details['terminal_process_seen_after_launch'] |= bool(running_terminal_pids())
            for f in common_snapshots():
                try:
                    if f.stat().st_mtime < start-2:
                        continue
                except OSError:
                    continue
                candidate=read_snapshot(f)
                if candidate:
                    snap=candidate
                    details['common_file_found']=True
                    details['heartbeat_sequence']=max(details['heartbeat_sequence'],candidate['seq'])
            if snap and snap['seq']>=2:
                break
            time.sleep(2)
        details['wine_launcher_exit_code']=proc.poll()
        details.update(inspect_journals(start))
        if snap and snap['seq']>=2:
            details['native_python_bridge_proven']=True
            details['terminal_connected_flag']=snap['terminal_connected_flag']
            details['account_present_flag']=snap['account_present_flag']
            details['symbol_quote_flag']=snap['symbol_quote_flag']
            details['broker_login_proven']=bool(have_demo and snap['terminal_connected_flag']
                                                and snap['account_matches_supplied_demo']
                                                and snap['server_matches_supplied_demo'])
            details['fresh_quote_proven']=bool(details['broker_login_proven']
                                                and snap['symbol_quote_flag'])
    finally:
        config.unlink(missing_ok=True)

# Only a tightly controlled boolean/numeric report is retained.  Never upload
# the account's config file, private logs, raw CSV, or process command lines.
(output/'circleci_m4_readonly.json').write_text(json.dumps(details,indent=2)+'\n',encoding='utf-8')
print('SAFE_MAC_MT5_RESULT='+json.dumps(details,sort_keys=True),flush=True)
if not compiled:
    raise SystemExit('MQL5 probe compilation failed; inspect SAFE report')
if not details['native_python_bridge_proven']:
    raise SystemExit('Read-only FILE_COMMON heartbeat not confirmed; inspect SAFE report')
if have_demo and not details['fresh_quote_proven']:
    raise SystemExit('Demo authentication or fresh quote not confirmed; inspect SAFE report')
