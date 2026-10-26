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
if compiled:
    # Any tested Deriv symbol may be set via MT5_TEST_SYMBOL. Otherwise EURUSD.
    symbol=os.environ.get('MT5_TEST_SYMBOL','EURUSD')
    if any(ch in symbol for ch in '\n\r[]='):
        raise ValueError('Unsafe chart symbol')
    common='[Common]\nProxyEnable=0\nKeepPrivate=0\n'
    if have_demo:
        if not login.isdigit() or any(ch in password+server for ch in '\n\r'):
            raise ValueError('Invalid demo credential format')
        common+=f'Login={login}\nPassword={password}\nServer={server}\n'
    content=common+'\n[Experts]\nEnabled=1\nAllowLiveTrading=0\nAllowDllImport=0\nAccount=0\nProfile=0\n\n[StartUp]\nExpert=CircleCIReadOnlyProbe\nSymbol='+symbol+'\nPeriod=M1\n'
    config.write_text(content,encoding='utf-8')
    os.chmod(config,0o600)
    try:
        subprocess.Popen([str(wine),r'C:\Program Files\MetaTrader 5\terminal64.exe',r'/config:C:\circleci_readonly.ini','/portable'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        time.sleep(65)
        # Only read the specially named, non-sensitive FILE_COMMON CSV.
        matches=list(prefix.glob('drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/Common/Files/circleci_readonly.csv'))
        matches+=list(prefix.glob('drive_c/users/*/Application Data/MetaQuotes/Terminal/Common/Files/circleci_readonly.csv'))
        matches+=list(prefix.glob('drive_c/ProgramData/MetaQuotes/Terminal/Common/Files/circleci_readonly.csv'))
        snapshot=None
        for file in matches:
            try:
                tokens=file.read_text(encoding='latin-1').replace('\ufeff','').strip().split(',')
                if len(tokens)>=6:
                    snapshot=tokens
                    break
            except (OSError,UnicodeError):pass
        if snapshot:
            details['native_python_bridge_proven']=True
            details['terminal_connected_flag']=snapshot[2].strip().lower() in ('1','true')
            details['account_present_flag']=snapshot[3].strip().isdigit() and int(snapshot[3].strip())>0
            details['symbol_quote_flag']=snapshot[5].strip().lower() in ('1','true')
            # Quote + terminal connection + account does not independently confirm
            # actual Deriv authentication unless demo configuration was supplied.
            details['broker_login_proven']=bool(have_demo and details['terminal_connected_flag'] and snapshot[3].strip()==login and snapshot[4].strip().casefold()==server.casefold())
            details['fresh_quote_proven']=bool(details['broker_login_proven'] and details['symbol_quote_flag'])
    finally:
        config.unlink(missing_ok=True)
(output/'circleci_m4_readonly.json').write_text(json.dumps(details,indent=2)+'\n')
print('SAFE_MAC_MT5_RESULT='+json.dumps(details,sort_keys=True),flush=True)
if not compiled:raise SystemExit('MQL5 probe compilation failed; inspect SAFE report')
if not details['native_python_bridge_proven']:
    raise SystemExit('FILE_COMMON read-only bridge not confirmed; inspect SAFE report')
if have_demo and not details['fresh_quote_proven']:
    raise SystemExit('Deriv demo connection or quote not confirmed; inspect SAFE report')
