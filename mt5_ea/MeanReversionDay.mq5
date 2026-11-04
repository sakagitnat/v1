//+------------------------------------------------------------------+
//| MeanReversionDay.mq5                                             |
//| Day-trading Bollinger mean-reversion EA, demo-only by default.   |
//|                                                                  |
//| Mirrors scripts/run_mt5_service.py + src/trading/cfd/            |
//| mean_reversion.py so the two can be compared:                    |
//|   entry  : bar closes below lower band -> BUY, above upper -> SELL|
//|   exit   : close reaches the middle band, ATR stop/target, or    |
//|            the position is older than InpMaxHoldHours            |
//|   filter : only enter when the regime timeframe is "ranging"     |
//|            (ADX < threshold and no volatility spike)            |
//| Decisions use the last CLOSED bar (shift 1), once per new bar.   |
//|                                                                  |
//| Run EITHER this EA OR the Python bot on a symbol, never both:    |
//| the account is Netting, so two systems would merge positions.    |
//+------------------------------------------------------------------+
#property copyright "sakagitnat/v1"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

input ENUM_TIMEFRAMES InpTimeframe       = PERIOD_M5;   // Trading timeframe
input ENUM_TIMEFRAMES InpRegimeTimeframe = PERIOD_M15;  // Regime-filter timeframe
input int      InpBBPeriod        = 20;     // Bollinger period
input double   InpBBDeviation     = 2.0;    // Bollinger deviations
input int      InpATRPeriod       = 14;     // ATR period
input double   InpStopATR         = 2.0;    // Stop loss = N x ATR
input double   InpTargetATR       = 1.5;    // Take profit = N x ATR
input int      InpADXPeriod       = 14;     // Regime ADX period
input double   InpADXTrend        = 25.0;   // ADX >= this -> trending (no entries)
input double   InpUnstableRatio   = 2.5;    // ATR% / median >= this -> unstable (no entries)
input double   InpRiskPercent     = 1.0;    // Risk per trade, % of equity
input double   InpMaxDailyLossPct = 3.0;    // Stop new entries after this % daily loss
input double   InpMaxHoldHours    = 12.0;   // Close positions older than this (0 = off)
input long     InpMagic           = 20261104; // Magic number
input bool     InpAllowReal       = false;  // Allow trading a non-demo account (leave false)

CTrade trade;
int hBands = INVALID_HANDLE, hATR = INVALID_HANDLE, hADX = INVALID_HANDLE, hRegimeATR = INVALID_HANDLE;
datetime lastBarTime = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO && !InpAllowReal)
     {
      Print("MeanReversionDay: account is not a demo account and InpAllowReal=false -- refusing to run.");
      return(INIT_FAILED);
     }
   hBands     = iBands(_Symbol, InpTimeframe, InpBBPeriod, 0, InpBBDeviation, PRICE_CLOSE);
   hATR       = iATR(_Symbol, InpTimeframe, InpATRPeriod);
   hADX       = iADX(_Symbol, InpRegimeTimeframe, InpADXPeriod);
   hRegimeATR = iATR(_Symbol, InpRegimeTimeframe, InpATRPeriod);
   if(hBands == INVALID_HANDLE || hATR == INVALID_HANDLE || hADX == INVALID_HANDLE || hRegimeATR == INVALID_HANDLE)
     {
      Print("MeanReversionDay: failed to create indicator handles.");
      return(INIT_FAILED);
     }
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(30);
   PrintFormat("MeanReversionDay started on %s %s (regime %s), magic %I64d",
               _Symbol, EnumToString(InpTimeframe), EnumToString(InpRegimeTimeframe), InpMagic);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   IndicatorRelease(hBands);
   IndicatorRelease(hATR);
   IndicatorRelease(hADX);
   IndicatorRelease(hRegimeATR);
  }

//+------------------------------------------------------------------+
bool SelectOwnPosition()
  {
   if(!PositionSelect(_Symbol))
      return(false);
   return(PositionGetInteger(POSITION_MAGIC) == InpMagic);
  }

// Max-hold check runs on every tick so the flatten happens on time.
void CheckMaxHold()
  {
   if(InpMaxHoldHours <= 0 || !SelectOwnPosition())
      return;
   double ageHours = (double)(TimeCurrent() - (datetime)PositionGetInteger(POSITION_TIME)) / 3600.0;
   if(ageHours >= InpMaxHoldHours)
     {
      PrintFormat("Closing %s: max hold time reached (%.1fh >= %.1fh)", _Symbol, ageHours, InpMaxHoldHours);
      trade.PositionClose(_Symbol);
     }
  }

// True when the regime timeframe looks ranging: ADX below the trend
// threshold and ATR% not spiking versus its own recent median.
bool RegimeIsRanging()
  {
   double adx[1];
   if(CopyBuffer(hADX, 0, 1, 1, adx) != 1)
      return(false);
   if(adx[0] >= InpADXTrend)
      return(false);

   const int lookback = 100;
   double atrVals[];
   double closes[];
   ArraySetAsSeries(atrVals, true);
   ArraySetAsSeries(closes, true);
   if(CopyBuffer(hRegimeATR, 0, 1, lookback, atrVals) != lookback ||
      CopyClose(_Symbol, InpRegimeTimeframe, 1, lookback, closes) != lookback)
      return(true); // not enough history for the spike check: ADX alone decides
   double pct[];
   ArrayResize(pct, lookback);
   for(int i = 0; i < lookback; i++)
      pct[i] = closes[i] > 0 ? atrVals[i] / closes[i] : 0;
   double latest = pct[0];
   ArraySort(pct);
   double median = (pct[lookback / 2 - 1] + pct[lookback / 2]) / 2.0;
   if(median > 0 && latest / median >= InpUnstableRatio)
      return(false);
   return(true);
  }

// Realised P&L (this EA's deals) since the start of the server day.
double TodayRealisedProfit()
  {
   MqlDateTime t;
   TimeToStruct(TimeCurrent(), t);
   t.hour = 0; t.min = 0; t.sec = 0;
   datetime dayStart = StructToTime(t);
   if(!HistorySelect(dayStart, TimeCurrent()))
      return(0.0);
   double sum = 0.0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic)
         continue;
      if(HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT)
         continue;
      sum += HistoryDealGetDouble(ticket, DEAL_PROFIT) +
             HistoryDealGetDouble(ticket, DEAL_COMMISSION) +
             HistoryDealGetDouble(ticket, DEAL_SWAP);
     }
   return(sum);
  }

// Lots that lose about riskMoney if price moves stopDistance against us.
double LotsForRisk(double riskMoney, double stopDistance)
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
      return(0.0); // risk budget below the broker's minimum lot: skip, don't oversize
   return(MathMin(lots, maxLot));
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   CheckMaxHold();

   datetime barTime = iTime(_Symbol, InpTimeframe, 0);
   if(barTime == lastBarTime || barTime == 0)
      return;
   lastBarTime = barTime;

   double mid[1], upper[1], lower[1], atr[1], close[1];
   if(CopyBuffer(hBands, 0, 1, 1, mid) != 1 || CopyBuffer(hBands, 1, 1, 1, upper) != 1 ||
      CopyBuffer(hBands, 2, 1, 1, lower) != 1 || CopyBuffer(hATR, 0, 1, 1, atr) != 1 ||
      CopyClose(_Symbol, InpTimeframe, 1, 1, close) != 1)
      return; // indicators still warming up
   if(atr[0] <= 0)
      return;

   if(SelectOwnPosition())
     {
      long type = PositionGetInteger(POSITION_TYPE);
      if(type == POSITION_TYPE_BUY && close[0] >= mid[0])
        {
         Print(_Symbol, ": reverted to the mean (close long)");
         trade.PositionClose(_Symbol);
        }
      else if(type == POSITION_TYPE_SELL && close[0] <= mid[0])
        {
         Print(_Symbol, ": reverted to the mean (cover short)");
         trade.PositionClose(_Symbol);
        }
      return;
     }
   if(PositionSelect(_Symbol))
      return; // a position from another system holds this netting symbol

   bool wantBuy  = close[0] < lower[0];
   bool wantSell = close[0] > upper[0];
   if(!wantBuy && !wantSell)
      return;

   if(!RegimeIsRanging())
     {
      PrintFormat("Skipping %s entry: regime is not ranging", _Symbol);
      return;
     }

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double todayPnl = TodayRealisedProfit();
   if(todayPnl < 0 && -todayPnl >= (balance - todayPnl) * InpMaxDailyLossPct / 100.0)
     {
      PrintFormat("Skipping %s entry: daily loss limit reached (%.2f)", _Symbol, todayPnl);
      return;
     }

   double stopDist = InpStopATR * atr[0];
   double lots = LotsForRisk(equity * InpRiskPercent / 100.0, stopDist);
   if(lots <= 0)
     {
      PrintFormat("Skipping %s entry: lot size is 0 (risk budget below the minimum lot)", _Symbol);
      return;
     }

   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   if(wantBuy)
     {
      double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double sl = NormalizeDouble(price - stopDist, digits);
      double tp = NormalizeDouble(price + InpTargetATR * atr[0], digits);
      if(!trade.Buy(lots, _Symbol, price, sl, tp, "mean_reversion lower band"))
         PrintFormat("Buy failed: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
     }
   else
     {
      double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double sl = NormalizeDouble(price + stopDist, digits);
      double tp = NormalizeDouble(price - InpTargetATR * atr[0], digits);
      if(!trade.Sell(lots, _Symbol, price, sl, tp, "mean_reversion upper band"))
         PrintFormat("Sell failed: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
     }
  }
//+------------------------------------------------------------------+
