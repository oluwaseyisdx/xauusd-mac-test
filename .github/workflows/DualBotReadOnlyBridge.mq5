// DualBot Test 14 — read-only MT5 -> native macOS Python bridge
// Writes a heartbeat and minimal quote/account flags to FILE_COMMON.
// Deliberately has no CTrade, OrderSend, WebRequest, sockets, or DLL imports.
#property strict
#property version "1.00"
#property description "Read-only qualification bridge; never submits trades"

#define BRIDGE_RUN_ID "__BRIDGE_RUN_ID__"

int g_sequence=0;

void PublishSnapshot()
{
   const bool connected=(bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   const bool is_demo=(AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO);
   MqlTick tick;
   ZeroMemory(tick);
   const bool tick_present=SymbolInfoTick(_Symbol,tick);
   const bool quote_available=(connected && tick_present && tick.bid>0.0 && tick.ask>0.0 && tick.time>0);
   int handle=FileOpen("DUALBOT_TEST14_BRIDGE.csv",
            FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_SHARE_READ|FILE_COMMON,
            ';',CP_UTF8);
   if(handle==INVALID_HANDLE)
   {
      Print("DUALBOT_TEST14_FILE_OPEN_FAILED error=",GetLastError());
      return;
   }
   g_sequence++;
   FileWrite(handle,"run_id","seq","terminal_connected","demo_account","quotes_available","symbol","bid","ask","tick_unix_seconds","orders_sent");
   FileWrite(handle,BRIDGE_RUN_ID,g_sequence,(int)connected,(int)is_demo,(int)quote_available,
             _Symbol,DoubleToString(tick.bid,8),DoubleToString(tick.ask,8),
             (long)tick.time,0);
   FileFlush(handle);
   FileClose(handle);
   if(g_sequence==1)
      Print("DUALBOT_TEST14_MQL5_FILE_BRIDGE_WRITTEN");
}

int OnInit()
{
   EventSetTimer(2);
   PublishSnapshot();
   return INIT_SUCCEEDED;
}

void OnTimer()
{
   PublishSnapshot();
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}
