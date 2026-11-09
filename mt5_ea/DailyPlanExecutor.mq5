//+------------------------------------------------------------------+
//| DailyPlanExecutor.mq5                                            |
//| Executes ONE trade per day from a plan file written each morning |
//| by the AI supervisor (Claude). The EA has no market opinion; the |
//| plan (symbol, side, SL, TP, optional trigger) comes from chart,  |
//| indicator and news analysis. Demo-only.                          |
//|                                                                  |
//| Plan file: <MT5 Common>\Files\plan_<SYMBOL>.txt, key=value lines |
//|   date=2026.11.06      server date the plan is valid for         |
//|   side=BUY|SELL                                                  |
//|   sl=<price>  tp=<price>                                         |
//|   trigger=<price>      0 = enter at market from start_hour       |
//|   trigger_dir=ABOVE|BELOW  enter when price crosses the trigger   |
//|   start_hour=10        server hour when entry is allowed         |
//|   force_hour=19        if still flat at this hour, enter at mkt  |
//|                        (guarantees >= 1 trade/day); -1 = never   |
//|   risk=5               money to risk (capped by inputs)          |
//|   reason=free text                                               |
//| Attach one copy per symbol (one EA per chart).                   |
//+------------------------------------------------------------------+
#property copyright "sakagitnat/v1"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

input int      InpEndHour          = 22;       // Close any open position at this server hour
input double   InpMaxRiskMoney     = 10.0;     // Hard cap on money risked per trade
input double   InpMaxRiskEquityPct = 12.0;     // Also cap at N% of equity
input double   InpMaxSpreadPts     = 6.0;      // Skip entry if spread > N points (non-forced)
input double   InpMinEquity        = 40.0;     // Kill switch
input long     InpMagic            = 20261108; // Magic number

CTrade trade;
string planDate = "", side = "", reason = "";
double planSL = 0, planTP = 0, planTrigger = 0, planRisk = 5.0;
string triggerDir = "";
int startHour = 0, forceHour = -1;
bool planOk = false;
string doneDate = "";                 // date for which we already entered (or gave up)

int OnInit()
  {
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO)
     {
      Print("DailyPlanExecutor: account is not demo -- refusing to run.");
      return(INIT_FAILED);
     }
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(100);
   EventSetTimer(5);
   PrintFormat("DailyPlanExecutor started on %s, plan file plan_%s.txt, magic %I64d", _Symbol, _Symbol, InpMagic);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason) { EventKillTimer(); }

string Today() { return TimeToString(TimeCurrent(), TIME_DATE); }

bool LoadPlan()
  {
   planOk = false;
   string fn = "plan_" + _Symbol + ".txt";
   int h = FileOpen(fn, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
      return(false);
   planDate = ""; side = ""; reason = ""; triggerDir = "";
   planSL = 0; planTP = 0; planTrigger = 0; planRisk = 5.0; startHour = 0; forceHour = -1;
   while(!FileIsEnding(h))
     {
      string line = FileReadString(h);
      int p = StringFind(line, "=");
      if(p <= 0) continue;
      string k = line; StringSetLength(k, p);
      string v = StringSubstr(line, p + 1);
      StringTrimLeft(k); StringTrimRight(k); StringTrimLeft(v); StringTrimRight(v);
      StringToLower(k);
      if(k == "date") planDate = v;
      else if(k == "side") { StringToUpper(v); side = v; }
      else if(k == "sl") planSL = StringToDouble(v);
      else if(k == "tp") planTP = StringToDouble(v);
      else if(k == "trigger") planTrigger = StringToDouble(v);
      else if(k == "trigger_dir") { StringToUpper(v); triggerDir = v; }
      else if(k == "start_hour") startHour = (int)StringToInteger(v);
      else if(k == "force_hour") forceHour = (int)StringToInteger(v);
      else if(k == "risk") planRisk = StringToDouble(v);
      else if(k == "reason") reason = v;
     }
   FileClose(h);
   planOk = (planDate != "" && (side == "BUY" || side == "SELL") && planSL > 0);
   return(planOk);
  }

bool SelectOwnPosition()
  {
   if(!PositionSelect(_Symbol)) return(false);
   return(PositionGetInteger(POSITION_MAGIC) == InpMagic);
  }

bool TradedToday()
  {
   MqlDateTime n;
   TimeToStruct(TimeCurrent(), n);
   n.hour = 0; n.min = 0; n.sec = 0;
   if(!HistorySelect(StructToTime(n), TimeCurrent() + 3600)) return(false);
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
     {
      ulong tk = HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(tk, DEAL_MAGIC) == InpMagic &&
         HistoryDealGetString(tk, DEAL_SYMBOL) == _Symbol &&
         HistoryDealGetInteger(tk, DEAL_ENTRY) == DEAL_ENTRY_IN)
         return(true);
     }
   return(false);
  }

double LotsForRisk(double riskMoney, double maxRiskMoney, double stopDistance)
  {
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double step      = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minLot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(tickSize <= 0 || tickValue <= 0 || stopDistance <= 0 || step <= 0) return(0.0);
   double lossPerLot = stopDistance / tickSize * tickValue;
   double lots = MathFloor(riskMoney / lossPerLot / step) * step;
   if(lots < minLot)
      return(minLot * lossPerLot <= maxRiskMoney ? minLot : 0.0);
   return(MathMin(lots, maxLot));
  }

void TryEnter(bool forced)
  {
   if(AccountInfoDouble(ACCOUNT_EQUITY) < InpMinEquity)
     {
      Print("Kill switch: equity too low, no entry");
      return;
     }
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double spread = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) * _Point;
   if(!forced && spread > InpMaxSpreadPts) return;
   bool buy = (side == "BUY");
   double price = buy ? ask : bid;
   double risk = buy ? price - planSL : planSL - price;
   double minDist = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   if(risk <= minDist)
     {
      PrintFormat("Plan SL %.2f invalid vs price %.2f (distance %.2f); will retry", planSL, price, risk);
      return;
     }
   double tp = planTP;
   if(tp > 0 && ((buy && tp <= price + minDist) || (!buy && tp >= price - minDist))) tp = 0;
   double cap = MathMin(InpMaxRiskMoney, AccountInfoDouble(ACCOUNT_EQUITY) * InpMaxRiskEquityPct / 100.0);
   double lots = LotsForRisk(MathMin(planRisk, cap), cap, risk);
   if(lots <= 0)
     {
      PrintFormat("Skipping today: minimum lot risks more than %.2f (stop %.2f)", cap, risk);
      doneDate = Today();
      return;
     }
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   string cmt = "plan " + StringSubstr(reason, 0, 20);
   bool ok = buy ? trade.Buy(lots, _Symbol, price, NormalizeDouble(planSL, digits), tp > 0 ? NormalizeDouble(tp, digits) : 0, cmt)
                 : trade.Sell(lots, _Symbol, price, NormalizeDouble(planSL, digits), tp > 0 ? NormalizeDouble(tp, digits) : 0, cmt);
   uint rc = trade.ResultRetcode();
   if(ok && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_DONE_PARTIAL || rc == TRADE_RETCODE_PLACED))
     {
      doneDate = Today();
      PrintFormat("Entered %s %.2f lots %s @ %.2f SL %.2f TP %.2f (%s)%s", side, lots, _Symbol, price, planSL, tp, reason, forced ? " [forced]" : "");
     }
   else
      PrintFormat("Entry failed: %u %s", rc, trade.ResultRetcodeDescription());
  }

void OnTimer()
  {
   MqlDateTime now;
   TimeToStruct(TimeCurrent(), now);

   // Day-trade flatten.
   if(SelectOwnPosition())
     {
      MqlDateTime opened;
      TimeToStruct((datetime)PositionGetInteger(POSITION_TIME), opened);
      if(now.hour >= InpEndHour || opened.year != now.year || opened.day_of_year != now.day_of_year)
         if(!trade.PositionClose((ulong)PositionGetInteger(POSITION_TICKET)))
            PrintFormat("Close incomplete: %u %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
      return;
     }

   if(doneDate == Today() || now.hour >= InpEndHour) return;
   if(!LoadPlan() || planDate != Today()) return;      // no valid plan for today
   if(TradedToday()) { doneDate = Today(); return; }   // restart-safe
   if(now.hour < startHour) return;

   bool forced = (forceHour >= 0 && now.hour >= forceHour);
   bool triggered = true;
   if(planTrigger > 0 && !forced)
     {
      double px = (side == "BUY") ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
      triggered = (triggerDir == "BELOW") ? (px <= planTrigger) : (px >= planTrigger);
     }
   if(triggered || forced)
      TryEnter(forced);
  }
//+------------------------------------------------------------------+
