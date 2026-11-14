//+------------------------------------------------------------------+
//| GoldTrendH1.mq5                                                  |
//| Slow trend-following Donchian breakout for gold (H1), demo-only. |
//|                                                                  |
//| Why this one: on XM tick-spread H1 data (2021-2026, GOLD) a      |
//| Donchian breakout with ATR stop/target was positive in BOTH the  |
//| 2021-24 and 2025-26 halves for 8 of 9 nearby parameter sets, and |
//| it matches the donchian_breakout@v2 parameters validated on      |
//| Deriv's data (80 / 3.5 / 6). Forex pairs and M5 mean reversion   |
//| did not hold up. See the backtest notes in the PR / chat.        |
//|                                                                  |
//|   entry : bar closes above the highest high of the prior N bars  |
//|           -> BUY (below the lowest low -> SELL), one position    |
//|   exit  : ATR stop / ATR target, or older than InpMaxHoldHours   |
//| Decisions use the last CLOSED bar, once per new bar.             |
//|                                                                  |
//| NEEDS a bigger demo balance: the H1 stop is ~$30-45 per 0.01 lot,|
//| so a $100 account cannot risk 1% per trade (the EA then skips).  |
//| Run EITHER this EA or another one per symbol (netting-safe).     |
//+------------------------------------------------------------------+
#property copyright "sakagitnat/v1"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

input ENUM_TIMEFRAMES InpTimeframe  = PERIOD_H1; // Trading timeframe
input int      InpDonchianPeriod    = 80;      // Breakout lookback (bars)
input int      InpATRPeriod         = 14;      // ATR period
input double   InpStopATR           = 3.5;     // Stop loss = N x ATR
input double   InpTargetATR         = 6.0;     // Take profit = N x ATR
input double   InpRiskPercent       = 1.0;     // Risk per trade, % of equity
input double   InpMaxDailyLossPct   = 3.0;     // Stop new entries after this % daily loss
input double   InpMaxHoldHours      = 240.0;   // Close positions older than this (0 = off)
input long     InpMagic             = 20261105; // Magic number
input bool     InpAllowReal         = false;   // Allow trading a non-demo account (leave false)

CTrade trade;
int hATR = INVALID_HANDLE;
datetime lastBarTime = 0;

int OnInit()
  {
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) != ACCOUNT_TRADE_MODE_DEMO && !InpAllowReal)
     {
      Print("GoldTrendH1: account is not a demo account and InpAllowReal=false -- refusing to run.");
      return(INIT_FAILED);
     }
   hATR = iATR(_Symbol, InpTimeframe, InpATRPeriod);
   if(hATR == INVALID_HANDLE)
     {
      Print("GoldTrendH1: failed to create ATR handle.");
      return(INIT_FAILED);
     }
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(50);
   PrintFormat("GoldTrendH1 started on %s %s, Donchian %d, SL %.1fxATR, TP %.1fxATR, magic %I64d",
               _Symbol, EnumToString(InpTimeframe), InpDonchianPeriod, InpStopATR, InpTargetATR, InpMagic);
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

void CheckMaxHold()
  {
   if(InpMaxHoldHours <= 0 || !SelectOwnPosition())
      return;
   double ageHours = (double)(TimeCurrent() - (datetime)PositionGetInteger(POSITION_TIME)) / 3600.0;
   if(ageHours >= InpMaxHoldHours)
     {
      PrintFormat("Closing %s: max hold time reached (%.1fh)", _Symbol, ageHours);
      trade.PositionClose(_Symbol);
     }
  }

double TodayRealisedProfit()
  {
   MqlDateTime t;
   TimeToStruct(TimeCurrent(), t);
   t.hour = 0; t.min = 0; t.sec = 0;
   if(!HistorySelect(StructToTime(t), TimeCurrent()))
      return(0.0);
   double sum = 0.0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpMagic || HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT)
         continue;
      sum += HistoryDealGetDouble(ticket, DEAL_PROFIT) + HistoryDealGetDouble(ticket, DEAL_COMMISSION) +
             HistoryDealGetDouble(ticket, DEAL_SWAP);
     }
   return(sum);
  }

// Lots that lose about riskMoney if price moves stopDistance against us;
// 0 if even the broker's minimum lot would risk more than the budget.
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
      return(0.0);
   return(MathMin(lots, maxLot));
  }

void OnTick()
  {
   CheckMaxHold();

   datetime barTime = iTime(_Symbol, InpTimeframe, 0);
   if(barTime == lastBarTime || barTime == 0)
      return;
   lastBarTime = barTime;

   if(PositionSelect(_Symbol))
      return; // already in (ours, or another system's on this netting symbol)

   // Signal bar = last closed bar (shift 1); channel = the N bars before it (shift 2..N+1).
   double closes[1], highs[], lows[], atr[1];
   ArraySetAsSeries(highs, true);
   ArraySetAsSeries(lows, true);
   if(CopyClose(_Symbol, InpTimeframe, 1, 1, closes) != 1 ||
      CopyHigh(_Symbol, InpTimeframe, 2, InpDonchianPeriod, highs) != InpDonchianPeriod ||
      CopyLow(_Symbol, InpTimeframe, 2, InpDonchianPeriod, lows) != InpDonchianPeriod ||
      CopyBuffer(hATR, 0, 1, 1, atr) != 1 || atr[0] <= 0)
      return;
   double chHigh = highs[ArrayMaximum(highs)];
   double chLow  = lows[ArrayMinimum(lows)];

   bool wantBuy  = closes[0] > chHigh;
   bool wantSell = closes[0] < chLow;
   if(!wantBuy && !wantSell)
      return;

   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double todayPnl = TodayRealisedProfit();
   if(todayPnl < 0 && -todayPnl >= (balance - todayPnl) * InpMaxDailyLossPct / 100.0)
     {
      PrintFormat("Skipping %s entry: daily loss limit reached (%.2f)", _Symbol, todayPnl);
      return;
     }

   double stopDist = InpStopATR * atr[0];
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double lots = LotsForRisk(equity * InpRiskPercent / 100.0, stopDist);
   if(lots <= 0)
     {
      PrintFormat("Skipping %s entry: minimum lot risks more than %.1f%% of equity (stop %.2f) -- raise the demo balance",
                  _Symbol, InpRiskPercent, stopDist);
      return;
     }

   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   if(wantBuy)
     {
      double price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(!trade.Buy(lots, _Symbol, price, NormalizeDouble(price - stopDist, digits),
                    NormalizeDouble(price + InpTargetATR * atr[0], digits), "donchian breakout up"))
         PrintFormat("Buy failed: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
     }
   else
     {
      double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if(!trade.Sell(lots, _Symbol, price, NormalizeDouble(price + stopDist, digits),
                     NormalizeDouble(price - InpTargetATR * atr[0], digits), "donchian breakout down"))
         PrintFormat("Sell failed: %d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
     }
  }
//+------------------------------------------------------------------+
