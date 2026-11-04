//+------------------------------------------------------------------+
//| IndexOrbDay.mq5                                                  |
//| Opening-range breakout day trader for index CFDs, demo-only.     |
//|                                                                  |
//| Built for a ~$100 account: trades the broker's minimum lot and   |
//| skips the day if that lot would risk more than InpMaxRiskMoney.  |
//|                                                                  |
//| EVIDENCE IS WEAK (read before trusting it): on XM M15 data,      |
//| GER40Cash opening-range breakout was PF 1.25 (2022-24) and 1.20  |
//| (2025-26), ~300 trades, but it was 1 of 66 strategy/index tests, |
//| so a result this good is expected by chance ~2-3 times. Treat    |
//| this as a forward test on a demo account, not a proven edge.     |
//|                                                                  |
//|   range : high/low of the M15 bars in [InpRangeStartHour,        |
//|           InpRangeEndHour) server time, must be 0.5..3 x ATR     |
//|   entry : first M15 close beyond the range -> trade, once a day  |
//|   stop  : opposite side of the range                             |
//|   target: InpTargetR x the stop distance                         |
//|   exit  : flat at InpEndHour server time                         |
//+------------------------------------------------------------------+
#property copyright "sakagitnat/v1"
#property version   "1.04"
#property strict

#include <Trade/Trade.mqh>

input int      InpRangeStartHour = 10;     // Range start hour (server time); GER40 cash open
input int      InpRangeEndHour   = 11;     // Range end hour (server time, exclusive)
input int      InpRangeMinutes  = 0;      // 0 uses end hour; otherwise a multiple of 15
input int      InpEndHour        = 22;     // Close any open position at this hour
input double   InpTargetR        = 1.5;    // Take profit = N x stop distance
input double   InpMinRangeATR    = 0.5;    // Skip if range < N x ATR(M15)
input double   InpMaxRangeATR    = 2.5;    // Skip if range > N x ATR(M15) (v1.04: 3.0 -> 2.5, wide-range days had no edge)
input int      InpLastEntryHour  = 16;     // No new entries from this hour (server time)
input double   InpMaxSpreadPts   = 3.5;    // Skip entry if spread > N index points (backtest median ~2.3)
input double   InpMaxRiskEquityPct = 12.0; // Also cap risk at N% of current equity
input double   InpMinEquity      = 40.0;   // Kill switch: no new trades if equity falls below this
input int      InpATRPeriod      = 14;     // ATR period (M15)
input double   InpRiskMoney      = 5.0;    // Target risk per trade in account currency
input double   InpMaxRiskMoney   = 10.0;   // Skip the day if even the minimum lot risks more than this
input long     InpMagic          = 20261106; // Magic number


CTrade trade;
int hATR = INVALID_HANDLE;
datetime lastBarTime = 0;
int lastTradeDay = -1;
int rangeStartMinute, rangeEndMinute;

int OnInit()
  {
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO)
     {
      Print("IndexOrbDay: account is not a demo account -- refusing to run.");
      return(INIT_FAILED);
     }
   rangeStartMinute = 60 * InpRangeStartHour;
   rangeEndMinute = InpRangeMinutes == 0 ? 60 * InpRangeEndHour : rangeStartMinute + InpRangeMinutes;
   if(rangeStartMinute < 0 || rangeEndMinute <= rangeStartMinute ||
      rangeEndMinute % 15 != 0 || rangeEndMinute >= 60 * InpEndHour || InpEndHour > 23)
      return(INIT_PARAMETERS_INCORRECT);
   hATR = iATR(_Symbol, PERIOD_M15, InpATRPeriod);
   if(hATR == INVALID_HANDLE)
     {
      Print("IndexOrbDay: failed to create ATR handle.");
      return(INIT_FAILED);
     }
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints(100);
   PrintFormat("IndexOrbDay started on %s, range %02d:%02d-%02d:%02d, end %02d, TP %.1fR, risk %.1f (max %.1f), magic %I64d",
               _Symbol, rangeStartMinute / 60, rangeStartMinute % 60, rangeEndMinute / 60, rangeEndMinute % 60, InpEndHour, InpTargetR, InpRiskMoney, InpMaxRiskMoney, InpMagic);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   IndicatorRelease(hATR);
  }

bool SelectOwnPosition()
  {
   if(!PositionSelect(_Symbol))
      return(false);
   return(PositionGetInteger(POSITION_MAGIC) == InpMagic);
  }

// Lots for riskMoney; falls back to the minimum lot if that stays within maxRiskMoney.
double LotsForRisk(double riskMoney, double maxRiskMoney, double stopDistance)
  {
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double step      = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minLot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(tickSize <= 0 || tickValue <= 0 || stopDistance <= 0 || step <= 0)
      return(0.0);
   double lossPerLot = stopDistance / tickSize * tickValue;
   double lots = MathFloor(riskMoney / lossPerLot / step) * step;
   if(lots < minLot)
      return(minLot * lossPerLot <= maxRiskMoney ? minLot : 0.0);
   return(MathMin(lots, maxLot));
  }

bool EntryAccepted()
  {
   uint result = trade.ResultRetcode();
   return(result == TRADE_RETCODE_DONE || result == TRADE_RETCODE_DONE_PARTIAL ||
          result == TRADE_RETCODE_PLACED);
  }

// True if this EA already opened a position today (survives EA/terminal restarts).
bool TradedToday()
  {
   MqlDateTime n;
   TimeToStruct(TimeCurrent(), n);
   n.hour = 0; n.min = 0; n.sec = 0;
   if(!HistorySelect(StructToTime(n), TimeCurrent() + 3600))
      return(false);
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

// Pre-trade checks that do not depend on the signal side.
bool TradingAllowed(double stopDistance)
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity < InpMinEquity)
     {
      PrintFormat("Kill switch: equity %.2f < %.2f, no new trades", equity, InpMinEquity);
      return(false);
     }
   double spread = (double)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) * _Point;
   if(spread > InpMaxSpreadPts)
      return(false);                      // transient: try again next bar
   double minDist = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   if(stopDistance <= minDist)
      return(false);
   return(true);
  }

void OnTick()
  {
   MqlDateTime now;
   TimeToStruct(TimeCurrent(), now);

   // Day-trade flatten.
   if(SelectOwnPosition())
     {
      MqlDateTime opened;
      TimeToStruct((datetime)PositionGetInteger(POSITION_TIME), opened);
      if(now.hour >= InpEndHour || opened.year != now.year || opened.day_of_year != now.day_of_year)
        {
         if(!trade.PositionClose((ulong)PositionGetInteger(POSITION_TICKET)) ||
            trade.ResultRetcode() != TRADE_RETCODE_DONE)
            PrintFormat("Close incomplete: %u %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
        }
      return;
     }

   datetime barTime = iTime(_Symbol, PERIOD_M15, 0);
   if(barTime == lastBarTime || barTime == 0)
      return;
   lastBarTime = barTime;

   if(now.hour * 60 + now.min < rangeEndMinute || now.hour >= InpEndHour || now.hour >= InpLastEntryHour)
      return;                       // before the range is complete, or after the session
   if(lastTradeDay == now.day_of_year || PositionSelect(_Symbol))
      return;                       // one trade per day; never stack on an existing position
   if(TradedToday())
     {
      lastTradeDay = now.day_of_year;   // already traded today (e.g. EA restarted after the exit)
      return;
     }

   // Today's opening range from the closed M15 bars.
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(_Symbol, PERIOD_M15, 0, 96, rates);
   if(copied < 10)
      return;
   double hi = -DBL_MAX, lo = DBL_MAX;
   int n = 0;
   for(int i = 1; i < copied; i++)
     {
      MqlDateTime t;
      TimeToStruct(rates[i].time, t);
      if(t.day_of_year != now.day_of_year || t.year != now.year)
         continue;
      int minute = t.hour * 60 + t.min;
      if(minute >= rangeStartMinute && minute < rangeEndMinute)
        {
         hi = MathMax(hi, rates[i].high);
         lo = MathMin(lo, rates[i].low);
         n++;
        }
     }
   if(n != (rangeEndMinute - rangeStartMinute) / 15)
      return;

   double atr[1];
   if(CopyBuffer(hATR, 0, 1, 1, atr) != 1 || atr[0] <= 0)
      return;
   double range = hi - lo;
   if(range < InpMinRangeATR * atr[0] || range > InpMaxRangeATR * atr[0])
     {
      lastTradeDay = now.day_of_year;   // range unsuitable today: decided, don't re-check every bar
      return;
     }

   double close1 = rates[1].close;      // last closed bar
   bool wantBuy  = close1 > hi;
   bool wantSell = close1 < lo;
   if(!wantBuy && !wantSell)
      return;

   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   if(wantBuy)
     {
      double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double stop = lo, risk = price - stop;
      double lots = TradingAllowed(risk) ? LotsForRisk(InpRiskMoney, MathMin(InpMaxRiskMoney, AccountInfoDouble(ACCOUNT_EQUITY) * InpMaxRiskEquityPct / 100.0), risk) : -1.0;
      if(lots < 0)
         return;                    // not allowed right now (spread/stops level/kill switch): retry next bar
      if(lots <= 0)
        {
         PrintFormat("Skipping %s: minimum lot risks more than %.1f (stop %.1f points)", _Symbol, InpMaxRiskMoney, risk);
         lastTradeDay = now.day_of_year;
         return;
        }
      if(trade.Buy(lots, _Symbol, price, NormalizeDouble(stop, digits), NormalizeDouble(price + InpTargetR * risk, digits), "orb up") && EntryAccepted())
         lastTradeDay = now.day_of_year;
      else
         PrintFormat("Buy failed: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
     }
   else
     {
      double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double stop = hi, risk = stop - price;
      double lots = TradingAllowed(risk) ? LotsForRisk(InpRiskMoney, MathMin(InpMaxRiskMoney, AccountInfoDouble(ACCOUNT_EQUITY) * InpMaxRiskEquityPct / 100.0), risk) : -1.0;
      if(lots < 0)
         return;                    // not allowed right now (spread/stops level/kill switch): retry next bar
      if(lots <= 0)
        {
         PrintFormat("Skipping %s: minimum lot risks more than %.1f (stop %.1f points)", _Symbol, InpMaxRiskMoney, risk);
         lastTradeDay = now.day_of_year;
         return;
        }
      if(trade.Sell(lots, _Symbol, price, NormalizeDouble(stop, digits), NormalizeDouble(price - InpTargetR * risk, digits), "orb down") && EntryAccepted())
         lastTradeDay = now.day_of_year;
      else
         PrintFormat("Sell failed: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
     }
  }
//+------------------------------------------------------------------+

