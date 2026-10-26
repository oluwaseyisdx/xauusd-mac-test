"""CircleCI M4 Pro: Deriv MT5 server-registration and login diagnostic.

Runs only a read-only Expert Advisor, never sends any order. The official
Deriv-Demo server-name variant is compared without revealing credentials.
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
// Read-only Apple Silicon native-Python bridge; no order functions.
// The Expert ALWAYS starts on EURUSD. The target symbol is probed separately.
int seq=0;
void Heartbeat(){
   string target="__TARGET_SYMBOL__";
   bool exists=false,selected=false,synchronized=false,tick_recent=false;
   if(StringLen(target)>0){
      exists=(bool)SymbolInfoInteger(target,SYMBOL_EXIST);
      if(exists){
         selected=SymbolSelect(target,true);
         if(selected){
            synchronized=SymbolIsSynchronized(target);
            MqlTick tt;
            ZeroMemory(tt);
            bool qt=SymbolInfoTick(target,tt);
            tick_recent=(qt && tt.time>0 && MathAbs(TimeLocal()-tt.time)<180);
         }
      }
   }
   int h=FileOpen("circleci_readonly.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ,',');
   if(h==INVALID_HANDLE){Print("CIRCLECI_PROBE_FILE_OPEN_FAILED error=",GetLastError());return;}
   MqlTick t; ZeroMemory(t);
   bool qt=SymbolInfoTick(_Symbol,t);
   long connected=TerminalInfoInteger(TERMINAL_CONNECTED);
   long account=AccountInfoInteger(ACCOUNT_LOGIN);
   bool recent=(qt && t.time>0 && MathAbs(TimeLocal()-t.time)<180);
   FileWrite(h,++seq,TimeLocal(),connected,account,AccountInfoString(ACCOUNT_SERVER),recent,
             (int)exists,(int)selected,(int)synchronized,(int)tick_recent,SymbolsTotal(false));
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
    'diagnostic_version': 'deriv_factory_broker_catalogue_same_login_comparison_v5',
    'platform': 'macOS Apple Silicon',
    'official_mt5_app_installed': WINE.is_file() and (ROOT / 'terminal64.exe').is_file(),
    'demo_credentials_supplied': HAVE_DEMO,
    'configured_server_matches_deriv_demo_label': SERVER == 'Deriv-Demo',
    'configured_server_matches_label_case_insensitive': SERVER.casefold() == 'deriv-demo',
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
    # Inject only a safe symbol into our read-only MQL5 probe. Do not emit it to logs.
    target = TARGET_SYMBOL
    if len(target) > 64 or any(c in target for c in '\\"\r\n'):
        raise SystemExit('Target symbol contains invalid characters for a MQL5 literal')
    escaped_target = target.encode('unicode_escape').decode('ascii')
    SOURCE.write_text(PROBE_SOURCE.replace('__TARGET_SYMBOL__', escaped_target), encoding='ascii')
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


def read_snapshot(path, used_demo, expected_server=SERVER):
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
            'server_matches_supplied_demo': bool(used_demo and values[4].strip().casefold() == expected_server.casefold()),
            'recent_quote': values[5].strip().lower() in ('1', 'true'),
            'target_symbol_exists': values[6].strip().lower() in ('1', 'true') if len(values)>=11 else False,
            'target_symbol_selected': values[7].strip().lower() in ('1', 'true') if len(values)>=11 else False,
            'target_symbol_synchronized': values[8].strip().lower() in ('1', 'true') if len(values)>=11 else False,
            'target_quote_recent': values[9].strip().lower() in ('1', 'true') if len(values)>=11 else False,
            'symbols_catalog_count': max(0,int(values[10].strip())) if len(values)>=11 else 0,
        }
    except (IndexError, OSError, ValueError, UnicodeError):
        return None


def broker_registry_snapshot():
    """Inspect whether MT5 registered server metadata, never export its bytes.

    `servers.dat` is a binary broker catalogue. A missing plain Deriv string
    is not definitive evidence of absent broker registration or connectivity.
    """
    candidate_dirs = [ROOT / 'config', ROOT / 'Config']
    candidate_dirs += list(PREFIX.glob(
        'drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/*/config'))
    candidate_dirs += list(PREFIX.glob(
        'drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/*/Config'))
    server_files = set()
    for directory in candidate_dirs:
        if directory.is_dir():
            server_files.update(p for p in directory.glob('servers.dat') if p.is_file())
    count = 0
    deriv_text = False
    for file in server_files:
        try:
            raw = file.read_bytes()[:2000000]
            if raw:
                count += 1
            deriv_text |= b'deriv' in raw.lower() or b'd\x00e\x00r\x00i\x00v\x00' in raw.lower()
        except OSError:
            continue
    return {
        'nonempty_servers_dat_files': count,
        'deriv_plaintext_in_server_cache': deriv_text,
        'broker_registry_detection_is_conclusive': False,
    }

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



# Test 19's verified Deriv Windows installer archive contained only a factory
# Config/servers.dat broker catalogue, extracted before logging into any account.
# It is NOT a login database, and this test does not copy account/password files.
# Compatibility across Wine/macOS terminals is an experiment, not assumed.
import base64
import hashlib
import zlib
_DERIV_REGISTRY_PAYLOAD=(
    'c-rlJ1#p~Mnq*0qEM~HpnHepMnaN^{$zo=UnVFd_28)?2W@cta3)h~Gi<|3f_w8&<Yi9Rc6;bq8Ra8{Im+#B`^8GhJ002M00'
    '$>Sn0$2l#0fqo0fGq$IzyP58+m-rnj~D<f0IKh=N&@u1AJqoP0_?tj#`gO&oA0kme1D_|paJ|>FY@2N#~NV&w_BS(IBpy>X!'
    '7G81n~d&1+?))ZEE2u_Ax0iKpzi8{WMQ3YkqtB)mwW3zIS(yql!>nSm4O=9%(bpjUJp3+T#JbjZtZLq`d$ar)rBOW~4r@n3D'
    'Qg&?_31_t3p&-FB2di_U&XJR{%|VsQN?9S+n(#6U1XwW`tQr$4^`EMGXirhO6!UX%b2dlud5x>zc&xUT&eS6NB|wokt~T6C9'
    '(iATlHG`FiGUhZ1zAQR7VakpZb$qWla8j{8@Tjg4+y3MN$S6NY>|4FwoU9k~~m|ob{uQekrQeu+}sSn?&qPb*VF)S{o#<BuJ'
    '4De|N4ik#4>hSU$X&BD1Ky!)N%*i+oK}=4@ips3}brWawz)bI@ML~J#NYDVG9!BCBIWw``&}&#|>Rocr4#yj5|7h=WN<CAPU'
    '?Kk%ylKUft+O@Qz>fZ}dpTQg-I=PO_@&>O?%<J;2m|vcFGe94XO^V)3%dLH<Z5Mp<2beGeTKRx%U;}Ef7SB*K0#`TSi@Mw4~'
    'T=0M;l9{=DL{DyRo-+^Fu;LTB~y-k|I>lx`Q_uQ_{rsr4<#p)}WVp&%{dJ1ecw>Eb5rUh|ZfQrCX4Bur&-xaiFGNTm{Hx6!#'
    '$Kd;&FHZLhcP(`Z8yIg7iqpdR(@t*gn4Om>t-z#Kv>y31&|*xcVZq9y{twGwh-+PUo9TvFaAoYL<Yv|Iz9<0efk%-z*oON9$'
    '|VJT?IxZTpTvnnGg6dz?1I9IlmE+~b^$9}P@gcJwzn1#oJX0JZFx<DR*H!A$F%wq0r5|1b@FKbP0-UHUm6*D;d^~$oaqHHvH'
    'kVqdh>70UvM1B|y4u)or!mHEiRwf|Er-Dk~>|=;<z$*TXQt9^jI$TiaK;M4uHuopyYG|+@1M`bgsc+;a!ZRBqy)`v=T%Gxka'
    'Rp2p)OmM{K8a#hs<**u^T{FwO-5PCfx%_~x`Q`yY-#AuuJlXwRKys$310dQEhnY&1T-=t<1wxOSNBK7(8Rzm^d{DpkrJU>B#'
    'UZQ2RA#&;a^9GPl^useK_h7L=^?Ck4R{!B*8^9*Avhz@~g5(#eG78J{#me^IY2vfg%9W6t3^@LUe&@q$x~L>RNmV0pk%7G9='
    'J#e5j-kY#(ag*H6pK>Go(xSA`GX!KK6$>3jeICS1mKs53tjbPIIK!&lYO^5k-xLLC&(Uf7ud`Bc}|vXZpGXiHHD#4gCJvxJI'
    '+_4bxMay$U+Lwt608>g+SbFxzW3Ej4S^A*q;PU86d?6>MG$uNOVO!*Jet~YdSEbkHJKObiO<KzB2O#`UbQOqJzGKZ-Rpdf^S'
    'seE?RYzOVV)C08=yE=Z%C#ZJwp47r?!V4-`X!J>Zr@(hDs8Xt84(F7N^l~s#c{{0Cw#9V?Q!;^(;pHETK?Lue$01Q)GnVe09'
    'KrTM>SU|T(iz$6MM4Woikp%ewE@+#g!PPfoS0;PF6{U1!TEp^b4WyoC;1f!0*q{f$hFz#T<quAf4g}zfoxi$yUt<lZk~)P{a'
    '(?Y-nt*EohM;*aqydMNln#c_$Zk%ZrU{s2gUnwC?o`iBO1S6w+Drggn$}4V=IdY@sLg81=Y&^>usd4-jSi>!hJq(_BwbG1p%'
    'u=VrohWFp-S4cvSPe%B&GF@8G~9{k*4lSGI#7@Br$9wY?qiP7w7}`Ed#zbIst_?}P;n@O2vQE9e5+2AlTuQggGrKDE73feYK'
    'lp}-LCxPJviu!Lh@Yj!B$8sM0Vr=tDAgVS{qW#BiCb+2u0UQV26upuu1un90}FQQ;$a^0{+jQPLTjLV8@<*;#aN>YqFrrpwO'
    'x&)kJCydR_+*Vymgz|S_$Z1NsT+^~LD<Q}g{ou&*rs6q;(Ael|i*j($XZLAX3`o|>gNrl7Ay|WajYTF?N26GHQCVqAO4BaTM'
    'vkaI#@@UqF}HCSjE9<%`<wjdB$+jKL>%ofz0~y7Ai+vVN177Qx1#I@YZwH0ybo_<r$eB0lk?-d-Z^@>r>iDkFzp++e*?WDNS'
    '$6@e60H>8zs_<`(9Vx<DQ9&Lk;zP*=ZiJTTOe#vPx7^LcMJbj1-9X0unA9SMBNTHQG4R$6}o|_Mc<_zu#l!W|o8^rKDg-XVn'
    'MU_AY*8Vc^!LxVmy8Y=qPZC-sV&om^=Q5)q#MklMG$^<F+W-oKjG$kIGqEO>)xUZrC1Y6~&6XL#_aV2{^}trkvLp5O9-h>Ak'
    '|wQ%}s9Ew?PMdq-mS5QEqUhX6JrOm)AxM!;T)!l8dj#p|aa%1G$W*R}D+(H8Sc-r-M<+T2-1C6`7DLGl4?yYFbu%TPn<mf`}'
    'cfbJrMQpn-rU(2k{th{~%37MAI9w)>`$aS7wx)pHzO*zgCCt%VljT3N@-u2JAY);0UbBXe`hjZ1W=6KKTRS@@D#RYqZ0a^%J'
    'fC32kIqitR9=XO@U^4MYDhX?(XcQn!pj!!XW%-NHGZCz4~dDYGA{!Yd2*YAL5E<e*gro-7=+Q!Q(s{G=wKKFCn6(dLGiH@q='
    '7y1&#(vLpd=?+;Y}>i%z3~dvCFdlyu8@!bt9dly3gnAXP=Gp{)2`)yYo0wpGd~+<|L47O>^U7{4AXnY2FhHAH#=vBusRUE0('
    'YkUl8?}jEH77D<_8p`ItlM4V{Mbr(?{xk(sIMigU4G-nKU~>Jm<u)Xa<ua54pZ={WX3$Nu>dXAZ-<%6ON@(Z@CuOHo73mDO<'
    '+p;stvdVT!axvH^#K6aYMf;i`aiHA;O76BcN?Sd&}$QxKSDlM#$#lpcZPBv<va!sr5^x+UaW@u{Svg}mkCAiEh%>6UT2Sa^7'
    'Uaxt~F`0tZ!$k<6=I+kT^i?(|+S1qDVjPC+n1uLzkKA!Hq0o9M1qt0ePM)7K)KV^)4@^4lUSAWY&8#dv)!)fQi+;sZ)>H6&V'
    '1CP~j;36GmQUjTrK561H99%5!R`yJG^o!aG9LWfy0f42<bQVFW0AQP;VLW02?JYxg=poD8=mjKvHo0DF&;WhVu+n`NySE{I0'
    '}IPM|VKw)9rF67Zm4LMPq1T7A6|BPB^DrzI(Ze5Yjy~aG1Z#<H`C3R!EM|VxN$bTntnwZ6y}jG^adcNW?SHzd$$V;q8TW|Ie'
    '|1diYT%RvPWRbMUswz*JCIbzyNBf$tGaomv}va;j{on~RyEHYduyXM9JiJ_G*-mGzu4c+d+-B{DU%f!W;NHdZEbk7D&h?aBS'
    'Yo9MyG@r%+E;Q;Pt6iF3P`!fm#I$3DR-0c)ho6oiRlhOeZVPz(tUkThfjX|J*GL&o|AHsZv(9Tkxp*6J8jeru65c^1C*b4Z<'
    '9NInBer%joRM6+sjjf3seLzTyE71!8e@(hh=+b0;Ch8gLRz$36py$iuIfpSSoxgIh0Pfw?)v=Mb!uk?i`g@-IW9*&AOdXYd8'
    '9r*Ly_vA;bEN6QBA}tuXuOP$TuEAEmjbDUv-Pk{eIu*#-jUIE5T=taX?%J3-oC81W;$}5;v;^>Egct?$|MX564MD?K;Ne)rL'
    'd%+T857{R#B2++oVhC)rYscC=q>QBd4Da1$;Rh5XF>)Y>r83sih#qvNjUmSpFRQ$9t@qH<lHK+uZhE*6A4XYAVjm_QP=90x6'
    'TLqmPai^|iCnlT>DeS$7QFG-}guXecaa3_$~)0Og33ka{LFJDV8kh+Xm(%`eAy`)E-E6JzHk$3p&Zn~)`xMeI(=>1k!4ByzT'
    'rF|3Qe<V{HVhliFL7XkBsa~uUn2B9zBIy!*v1=q@aKTTs`trHH(FD`0AY|!#t!xYjr+ID1=S(yLTy9-MLDQcg921mT-84Q$U'
    'jlj9l>Quxd#I=w}LtoeDoyRQth*aM4{ydmhV`uw%>N1N1bukE+2%G*YIzBGXJy*<BFr-dWUR)=)!zZ^im85gVJ)^c;kW2iOs'
    'ilR7+FO}O;T{|%9l1|;jGXMMC`zR#xkRqjZRJbKk%{qjHr3FQue|0FabP*WoZMWYjv<<S)?Q_^bTv&xmQ<9trTuOG{xSBhlP'
    '2~ec3zEnIawO_@^|HGRen($@ZT6@rBO!pn?v~z1#l^CGp&jO{Gz2AkzRJ*KipwXqgj+2Y`wMfv`RylQ&o0ivKxZ!;!mDf8F_'
    'Fhulq6+H9=`gkok@NEw$<tEGjbdDScqS$MgH}<ls6+Q(Nn3sqh`LWsRDnZ+obb{o|u&#YcjET#ZQL?}cqo$mnRKA;q&dlhCa'
    'SYjVdW{lY>@j0%DHZXHIzkY3S!-aOog>H+(Zp)^IUZ>1du!6znSOr+oZRLvONInsJ)m{E||>(z;=ju^RzPmL|s{q!1ycopBN'
    '!SY1-Q?N?`p}L-qH}|KRH^Y*-OM7##JsUdO)>4+3?WsP$;uL1pTX}<r^X`r_dNK$?J25x5<E_2BYpQbM8N;q&>&>eRyyVHn`'
    'TH+7(h)-4*oxY+?%x<V*i?`eOOA60U8-8k7T-rC#MN3?K}i66&LLpKaMT=MU!sg67#C@+uv)l$OhA%Qkh7t&=ml?i8~exD8?'
    '{BJXN{0)3kw1_CtnCXAev0BK2df*85?e8EHLt1^CqqzFGKmY_I7V)u5-B1mxJ?2a2ao66B7zN^CZlL!y2R&CH3;Tczb4Pq+P'
    'QfnRY#Z-x6oct*rnW9~5H6`w3JHl)Rr<-@VmDSFOA#B=e~2s$Nr%O-*icsDqaU^IQIV@4=cHN_RTMZOX_NmA~bt@t%+fJGV-'
    'QSUWP1VrFpMaQPFEc*hvr(Nhl1CX0R9V3n4w(G@XbNu*w%cJKwT{A)^lxU4us9fM7KyY;9}|B+|Qg)_nFgehp0aHvH;*P!9T'
    'V~nC+pdRr!IrqJfvKFD=H6qRCYt7Bmz%Rlcc{zF7L&Q++T6Ild$DWWSxj1O|rSg90f*6rNqZzlv(6zX4GmT`jJD(l4nn~GEc'
    'nAo=HXDd>_3AIPa}v#_B%iM*(8RwQ^h)hGyOkJiTN0J=MkLFYje>z+yuqsxt?8EXXe|I_jhMj2DYlpI*A+-VM$FI$Tk6(X7='
    '@U1oAKJa-l&7)_{YU(rA~q4z+=5D^mx@?%k!K76+i~6&AhanKr1tfv2qTFBPhz_CE}3|s<o0Cy{bk=%BE0~+MK8~SxY1`Exa'
    'sTguP^RZOIgFMJIlSTaHGy!3H1e6k9WVihH{nHKGcar#MFE%*OT;uJ#OtVDV|*-L|Dgv+!W?U*Qnqvq&7@-(|bNu$~DuZV!$'
    '>##}{*gW-Qtt?c{MPhjr+!^^;T$KFylDF1AL5oX=6zEoyE0IkkjlI$#BxR9A&d&oe{t-Xb{eMwlP16%}qCwk*`?_tX97M>-H'
    'UskUcAAs0y;1<fZ9PypUgcz*Xb5Dlv1rD9u<cpxtH)KzGkvlYoRrHY!4zsfe#Kc%swH<<70z#HFSSwGgdJ8XV@eoB(1*rjPv'
    'y5TZ21Rl~c3>??o5+b%HVl+j-u2-pIrB%`<S=^NO;FZJs^<m-72$W$Y}Ibe@8{wAc7Twic^V*wLG^j^5?rK;5Px|OFYY~X*k'
    'EBm^)QESB${@GCpYfO1vfX=*^H6D876Y=7>;OG47)fZ+kiJpmH+Ft-!JdsWxWSZTXZxPWcJAC8sYTvCa*Fn|NUJT799I_hgm'
    'vM1ieTW3w~ZDgqP9Tzr2T+_Z~o6^_mi-TG2=t6g<bFEX`MwD<CXMBKJ`638ed9K|xS#k+`?oT}t>wc$AQ78yg1j`z&Hl$QAv'
    'wYm;Bz!^?XQ|0nkDuD4agB=QhV$S++#|MDJQ-g^LP)oF+lDFjm1BayE?ot})7eN?=!fYd2%NE>*`I_j7A@Uq?mjUfya)(pAl'
    'Nv=#mbb8Byi09FPF%g=@T)5*X2?MXWUu#jpMd=Uy`PcL7FYn<cy@#w38be5MHB|1n%=fo42R8vV8gV&UH<i7(@(=;5Z-|h2o'
    '337N&ix$wpVzJZ(>)jF`DG=;f&B!!=n1D}OhmGSpfFHWJ7ga14%bqCQC?*fx*v^$1pStArxc1ePgh|A+WUHUvp2ci7%L(9q_'
    '{tB<B}2!0r4d*M8X?o6sPnFxcPeLe8{+EKQZrlg1jTmTG&_vZhlgVmmDNgH&XTmu=Bpt!c?!m`b^=~(DP+OGd?}F#i;@DU-6'
    '&)qdfKZ*pq1ko~)>#^=3lthA3GDth}2F^Uq7>8H68Ser@_W_CK#%`=+|j&GJf%hXVTWb>76EkTMd=41hpGQf`xeYO}wR^o{f'
    '^CD$=A3KZ~N!kLu+ym7Ju?cesbXD4fe)0LqDf>-jb$rcU?ksyFKaXtdhF#U7#SAJI?uWZfq8@6M!?nj7kB$@N;t3XYUig6MH'
    'gldNGeV*BPxIbX1Rb3X5d)9Z?tZT%jr8GO%BgldKub>ek@ibok`|{N9IUlGg{RVZA)_;CGXN*`A9u}x6?OGXjl}${^I-SPw<'
    '?5<G^LEHLiQQUkFT}mWKNXW|85#KVc`sm%%NDL3EkXLW^mJ`ytg$=Om4Uqz=QP^DA|l{_dKW(%2BV)^nApSX?B$WEo_fV{__'
    '6aI?1m_Pc6Ir=;a)yQtPfvBU(xH4g_}#`jY`FN0qLjO&Z<?ln3SYO`&u}e*S<?A_z2wf=l^rOrN76XOdAdcXYSv9y}!Htchy'
    'Y)-Mpp0$DYv?1qpr9ei(m-At=9U><M0!l-P(6?8At!aeL=Ta2*)WU*|FXey#p9?0<3iKd09Gd+fRFV4<;Qm_rLRFT{5){HoM'
    'rFVFSyr1OJ$%fRF`Z8OQVHPl|}cl{amFXb=&zW0SnfcUQA;{F@P6smcd{wCL7-D5AP&KZ;N4Gk_fECBG{*bl!(1g0(8IM{>i'
    'eyy3VI7y{vsTB&&D=KV6sMqvZ#Sqjn+;U)$o}b&}*@2;k5V4C#g(cec2>Oa>1<$eG;#lbSnbY5MKA<t}S`+zE@$fdOm(x~G2'
    '60HcK3?)#s<I`i*Q%(pd@N*$*Z?c}f|8X~VFVl=mUf@gyUY2TY+$T!CAERMX{box8o})QvYm?!_~5R={)4=ocOEP?FoLqY=6'
    'eJbWTGH~smn1)AG6ES2ZcQX{PK0O@43#c`hZ{_DRP&$H$mHgRFY&yNdFA`e?`7m0Wxq6ofw6$`TBp3xAcEwpKz)Gc`v_yTrl'
    'NcyEq>s{is;1Ges?{@v>{{pJD$?v;A|trQdTt_AI6MUb;y~U~Ki8_2-$XXsJiV=Ni7G2k_*tRQiA?;#Cy0B$>ayZuv9p|0=H'
    'e@KG(`6_)^?F3yMA+fr)Z=DzxE?WC-XcGqSUCFtM{Oj0y~)?2_6?mVVVwaFf@ldoMCwvwj08=KP@;#cAHnT-j6OLbGjLfj0k'
    'B}wihGcUd793sXW_Dkl_VV_rO(dpq$td@@U@p91zRO{OHXOBl1vBT4oSLJ7-K|HN!(rV(47gS6P^03nRyJ^^VCG~~VvO!T16'
    '{aPiLJuwzP-tLGWxJ=xaQ#raIjVE?#&-HqFhWuiW@N_gz;&$Qy%U|MA9IR}2K;()wNPV^i0SdA`hX$9f2NE6XuU7eIuqSG^Q'
    'q8`zrNJPvFbC%Jrg~=9e<YcZ>)bQKK(Q7|Fe4#1Y~&3cJawcMP3P{EJY)lWR<232z~PR&C|}h<2<wc3V?nf&so~q0BHp%CrS'
    '^KXqu?{19S58>R@YrxhbLYY5H2XrInbO-saMT{9{iC2FZ_H%m18S((nCzj42}52%!oH25wx5Jpw5S@J{<-1FR!K`43bojhB('
    '(Kl0<BnE(2k_s_8ZckPM(ck`Bhjy;a}4IL`7EHs%%m9giXp^c<-!dO$oTFM^p7t_DKfBCaKS@huM`j39Ro#+wKkc<hBgAUA8'
    'py1HXw~X^@5$CW__cw<s7@0w6Zul^lBB_T_Pt4{f8P3(EP9nL<tjsd$0l=XGNyN>YT5b6h<`$#ZC0fV{4#^A=F4wk@5Z?H7e'
    'DI=VUEk~SQ2zX9L0K}zyp_J*V4+=}!z>_`rM>bcW^-I@F;GI6A6^lJMpt5|C%m^{9E~jb4QYbQDQGygrVYI%xD+3IzfylAqX'
    'z^wXWSepOU{Ae6ocddo$B4JlOYPC&U%rhgNk-qmUbNdN-6sDWlg0T0)rqLRnU5hzW>|nr;Z@3jXiqE(ldLv1rkxph>~*)>dH'
    '|0uNd<l75O#&4RRDlD|<jaV)WBawaa@m5-5BVDjnT$$QZy()U}UkJ-{3}_j{RMc@^8tol1MrZ$jm2iLFC1weC2K`bZV|tUD<'
    '1Nb56)&w)@qX{F|*yRPIuwvTTKtMBuf#_lZj{A8@ZMzqhS)Z={z)RcSy(g3Mb-8Kn?E=NW}v!`CY5NR`D>IljZKYF<T?(RoD'
    'f~B+?w-N*bMk8lFs5sCx#~mU@RLX7)qg&LwtclqRHsxbDu1_pco0OO5GdFYSS)`Q&eZEB=i@WVlqdJm)Lth}h9*B?pA+IBCl'
    '3ESAohKnK;{0*x+XxF10S4SFq{Q9MG;Pt*fiOOfh;A2|T)zkRHorYk(S<DWAXG+vabjq1lC4|-rL%c|!QRSkYE;4(Bgke+Pg'
    'as_F~n9I%nC<Fzi)l3og^Lo0VSMmZegy+;AwkPo;K^8d{4R;HjgQc+;53jv$M>D@bFjaQ05arf91(uJWuw&JjcT<!PN4mWvC'
    'M}Ap!B%M6TljCLL{q0W~0RUrsyy%9Fipp6oa5Y5exmoyRR)(1i-t(o-YEPlR_;t@=2HU(uz{zMNM2l_z`IJlSvA0t&C=9Nxr'
    'dsPsVsH3T>nWI~rHk(>uLLk`1P1Zql0#+UhDe&xwtHc$3*?2CXueAEtmYcD49U(K)lqkG?e<;h+)Pxc$<)B10xe3~(_N9LV^'
    ')zXxOrtvG#EC+Y?<Fi;sdpSP*GY#@%yp+@Ow{oDG&Jl8pr!W<fBoaD7P79I6N!9LR@w+F;H+i5XgE`==r*2cI)16IcE1n$nH'
    'FR(K(BLZ{m5Jdkj#}-sGlIIeU^Bx4Ck!KMlOxb~p$d<#ao-c^ix-3p5fjWZ1eG^+pJOUmTb`GA&N)zrY|5w;%Vo?3_)UZr0s'
    'rU~Y!xeGDL{jG?l7sXL$XF%jniQET3m-Vd^TTm@jWA{elOFu$;Yz{O1K*eO9oY^p{WYrn^ZK_b2Wapq2QLAB6jIZRLXXIwI@'
    'R~tbkb{XrkH%he}Zsrn0{`08cC#)8m@jB&I9`11iI1@Ks)mncK@qT8tr;#`n(nK!8{>2gB4%qJ<~UO;jZ13z2u*5(WdC;WR<'
    '20Xm{=wB=GwvB9LBKoCH)M)1v~J9x5@WLiJZ`vwku7L+V}`D#f!QxhM%>e8=ig5-EHEiu8fQ(}<tpW;+~HS2$(XMfDS^x2_-'
    'bkzriI`fcC25vEj_|c+*47Gi}65a3}XFmz2wr|XgKWbkMffa2hq($#LCPY3M5cq8686%0|Cmw~o@p|lUCRa)_K#JtA+onj5B'
    'Y^X?69C~{Hp-(>QI?MLev!s7+in<Lp>N-E<Y0e1x1Gnxt)Bgu@xA_{D>gUa3Q@E0#uAPgPxfXkpm13WflZhk!AJ{DJG-uo(V'
    'E`Z8hw==-iD^WyyCJF;}@;J%D^MjxO^Q+;byLhC%`?8HF+>1FAy)Y?p<Y*KyWZtOak6Ts{^Z{X>8DeOy;KwsH>8f7I7%X$zL'
    'd&T)qI+;#e(LV^Ok#oC<UQbv})M&7Kz2F`EH`S;pYJ%F#yzF(LvpG7$CKQZ$R`^v2znT$g`okeAgUKXMNstt?^d3ATe2EPNK'
    '>U$Zg_bjK+K@6oM##>*DX@{$rlMP8;K^h<-htOofFd)DyBDxtL8ipUly0UfQa44*{{;vr&6RtT1HC|Bp}im!NzP%Wr`HGlom'
    'ATO&ye#4$E;-OM7HLo(N6`a>le?7GkiDZ!>sJbm}fLId(Oc3BQfj6yP|BvP?{?T)K{n8*WtwEq6F{g>$qD2dV&<GuJoU8hJJ'
    '-MKCgLuX%z>wGtreF#1{#oZo`+xQ(f9+{`(LF6c$9{<!9GUy$I20-IORcTH_O!h0`80lx{UXyVxTsbDyPZvj+ROBT{{!P70&'
    'D'
)
_DERIV_REGISTRY_SHA256='ec6fe1c76d56f6a83f93579e798977daa0ab3f08bf199d1c04ac652864d2fff3'


def install_deriv_server_catalogue():
    data=zlib.decompress(base64.b85decode(''.join(_DERIV_REGISTRY_PAYLOAD)))
    if hashlib.sha256(data).hexdigest()!=_DERIV_REGISTRY_SHA256 or len(data)!=21880:
        raise ValueError('Deriv broker catalogue integrity check failed')
    old_count, old_remaining = close_terminal()
    if old_remaining:
        raise RuntimeError('MT5 still running; cannot safely replace broker catalogue')
    dests=[ROOT/'Config/servers.dat']
    # MetaTrader may use a roaming profile rather than the installation tree.
    # Copy only into EXISTING terminal configuration directories, if any.
    for parent in PREFIX.glob('drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/*'):
        if (parent/'config').is_dir():
            dests.append(parent/'config/servers.dat')
        elif (parent/'Config').is_dir():
            dests.append(parent/'Config/servers.dat')
    imported=0
    for dest in dict.fromkeys(dests):
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            backup=dest.with_name('servers.dat.pre_v5_backup')
            if not backup.exists():
                shutil.copy2(dest,backup)
        dest.write_bytes(data)
        if hashlib.sha256(dest.read_bytes()).hexdigest()!=_DERIV_REGISTRY_SHA256:
            raise IOError('Broker catalogue copy verification failed')
        imported+=1
    # Never include the binary or binary contents in artifacts or logs.
    return {'broker_directory_imported': imported>=1,
            'imported_config_locations':imported,
            'original_terminal_was_stopped':not old_remaining,
            'deriv_factory_catalogue_bytes':len(data),
            'deriv_factory_catalogue_reference_build':6286,
            'broker_directory_proves_connection':False}

def run_stage(tag, symbol, use_demo, server_override=None):
    active_server = SERVER if server_override is None else server_override
    result = {
        'stage': tag,
        'uses_demo_credentials': use_demo,
        'server_variant': ('none' if not use_demo else ('official_Deriv_Demo' if server_override is not None else 'as_configured')),
        'server_name_matches_official_label': bool(use_demo and active_server == 'Deriv-Demo'),
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
        'target_symbol_exists': False,
        'target_symbol_selected': False,
        'target_symbol_synchronized': False,
        'target_quote_recent': False,
        'symbols_catalog_count': 0,
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
                       f'Server={active_server}\nKeepPrivate=0\n')
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
                    found = read_snapshot(file, use_demo, active_server)
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
                    result['target_symbol_exists'] = snapshot['target_symbol_exists']
                    result['target_symbol_selected'] = snapshot['target_symbol_selected']
                    result['target_symbol_synchronized'] = snapshot['target_symbol_synchronized']
                    result['target_quote_recent'] = snapshot['target_quote_recent']
                    result['symbols_catalog_count'] = snapshot['symbols_catalog_count']
                    result['broker_login_proven'] = bool(use_demo and snapshot['terminal_connected']
                        and snapshot['account_matches_supplied_demo']
                        and snapshot['server_matches_supplied_demo'])
                    result['fresh_quote_proven'] = bool(result['broker_login_proven'] and snapshot['target_quote_recent'])
                    break
            time.sleep(2)
        result['wine_launcher_running'] = proc.poll() is None
        result.update(new_journal_flags(started))
        result.update(broker_registry_snapshot())
    finally:
        CONFIG.unlink(missing_ok=True)
    print('SAFE_STAGE=' + json.dumps(result, sort_keys=True), flush=True)
    return result


if __name__ == '__main__':
    try:
        if compile_probe():
            # Compare same EURUSD startup chart with/without broker credentials.
            # If the saved server differs from the published demo label, attempt
            # an additional controlled connection with Deriv-Demo, unchanged
            # account ID and password. Never report passwords/IDs/server text.
            scenarios = [('A_control_no_credentials', False, None)]
            if HAVE_DEMO:
                scenarios.append(('B_demo_with_saved_server', True, None))
                if SERVER.casefold() != 'deriv-demo':
                    scenarios.append(('C_demo_with_official_server_label', True, 'Deriv-Demo'))
            for name, uses_demo, server_override in scenarios:
                result = run_stage(name, 'EURUSD', uses_demo, server_override=server_override)
                report['stages'].append(result)
                if name.startswith('A_'):
                    report['baseline_bridge_proven'] = result['file_common_heartbeat_seen']
                if uses_demo:
                    report['demo_target_bridge_proven'] |= result['file_common_heartbeat_seen']
                    report['broker_login_proven'] |= result['broker_login_proven']
                    report['fresh_quote_proven'] |= result['fresh_quote_proven']
            # The only controlled change in Stage C is the factory Deriv
            # broker server catalogue (same demo credentials and EURUSD chart).
            report['deriv_factory_broker_catalogue_test_attempted']=False
            if HAVE_DEMO:
                try:
                    registry_summary=install_deriv_server_catalogue()
                    report['deriv_factory_broker_catalogue_test_attempted']=True
                    report['broker_catalogue_bootstrap']=registry_summary
                    stage=run_stage('C_same_demo_after_Deriv_factory_broker_catalogue',
                                    'EURUSD',True)
                    report['stages'].append(stage)
                    report['broker_login_proven'] |= stage['broker_login_proven']
                    report['fresh_quote_proven'] |= stage['fresh_quote_proven']
                    report['demo_target_bridge_proven'] |= stage['file_common_heartbeat_seen']
                except (OSError,ValueError,RuntimeError) as ex:
                    # Never publish binary content or private environment details.
                    report['broker_catalogue_bootstrap_error_class']=type(ex).__name__
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
        raise SystemExit('Deriv connection or target symbol fresh quote not proven; inspect safe report')
    if HAVE_DEMO and not TARGET_SYMBOL:
        raise SystemExit('MT5_TEST_SYMBOL not supplied; cannot validate target demo symbol')
