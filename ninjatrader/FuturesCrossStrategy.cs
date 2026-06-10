/*
 * Futures Cross-Reference Strategy for NinjaTrader 8
 * Watches ES, NQ, MES, MNQ for correlated/divergent moves
 * Signal Types:
 *   1. All Aligned - All 4 futures moving same direction (high conviction)
 *   2. Micro Divergence - MES/MNQ diverging from ES/NQ (arbitrage)
 *   3. ES Lead - ES moves, NQ follows (lead/lag play)
 *   4. Relative Strength - Trade the stronger index
 */

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.Gui.SuperDom;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.Core.FloatingPoint;
using NinjaTrader.NinjaScript.DrawingTools;
using System.Diagnostics;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class FuturesCrossStrategy : Strategy
    {
        // Required for NinjaTrader to recognize the strategy
        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "Futures Cross-Reference Strategy - Watches ES/NQ/MES/MNQ for signals";
                Name = "FuturesCrossStrategy";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 30;
                IsFillLimitOnTouch = false;
                MaximumBarsLookBack = MaximumBarsLookBack.TwoHundredFiftySix;
                OrderFillResolution = OrderFillResolution.Standard;
                Slippage = 0;
                StartBehavior = StartBehavior.WaitUntilFlat;
                TimeInForce = TimeInForce.Gtc;
                TraceOrders = false;
                WaitForOcoClosingBracket = false;
                RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
                StopTargetHandling = StopTargetHandling.PerEntryExecution;
                BarsRequiredToTrade = 50;
            }
            else if (State == State.Configure)
            {
                // Add additional futures for cross-reference
                // Primary instrument is user-selected (index 0)
                // TEST: Only add NQ to see if data loads
                AddDataSeries("NQ26", Data.BarsPeriodType.Minute, 5);
                // AddDataSeries("MES26", Data.BarsPeriodType.Minute, 5);
                // AddDataSeries("MNQ26", Data.BarsPeriodType.Minute, 5);
            }
            else if (State == State.DataLoaded)
            {
                esCloses.Clear();
                nqCloses.Clear();
            }
        }

        // Price history for all 4 instruments (indices 1-4 in BarsArray)
        private List<double> esCloses = new List<double>();
        private List<double> nqCloses = new List<double>();
        private List<double> mesCloses = new List<double>();
        private List<double> mnqCloses = new List<double>();
        
        // Boof 23 ZigZag regime tracking
        private double lastZZHigh = 0;
        private double lastZZLow = 0;
        private string trend = "";
        private List<double> zzHighs = new List<double>();
        private List<double> zzLows = new List<double>();
        
        // Trade tracking
        private int dailyTrades = 0;
        private DateTime lastTradeDate = DateTime.MinValue;
        private List<double> returns5 = new List<double>();
        
        // Config
        private const int ATR_LEN = 14;
        private const int RETURN_BARS = 5;
        private const int CORR_WINDOW = 20;
        private const double ALL_ALIGNED_THRESH = 0.05;  // 0.05% move
        private const double DIVERGENCE_THRESH = 0.15;    // 0.15% divergence
        private const double LEAD_THRESH = 0.10;          // ES leads by 0.10%
        private const double RS_THRESH = 0.10;            // 0.10% relative strength
        
        // Risk
        private const int MAX_DAILY_TRADES = 5;
        private const double TP_R = 2.0;  // 2:1 R/R
        private const double SL_R = 1.0;

        protected override void OnBarUpdate()
        {
            // Only process on primary bars and when we have enough data on all series
            if (BarsInProgress != 0)
                return;
            
            if (CurrentBars[0] < BarsRequiredToTrade ||
                CurrentBars[1] < BarsRequiredToTrade)
                return;

            // Reset daily counter
            if (Time[0].Date != lastTradeDate.Date)
            {
                dailyTrades = 0;
                lastTradeDate = Time[0];
            }

            // Max trades check
            if (dailyTrades >= MAX_DAILY_TRADES)
                return;

            // Already in position
            if (Position.MarketPosition != MarketPosition.Flat)
                return;

            // Get prices from ES (index 1) and NQ (index 2 for now, will fix)
            double esClose = Closes[0][0];  // Primary = user selected
            double nqClose = Closes[1][0];  // Additional data series
            
            // Add to history
            esCloses.Add(esClose);
            nqCloses.Add(nqClose);
            
            // Keep history limited
            if (esCloses.Count > 100)
            {
                esCloses.RemoveAt(0);
                nqCloses.RemoveAt(0);
            }

            // Need enough history for returns
            if (esCloses.Count < RETURN_BARS + 10)
                return;

            // Calculate ATR on primary instrument for stops
            double atr = CalcATR(0, ATR_LEN);
            if (atr == 0) return;

            // Calculate returns over last N bars
            double esRet5 = (esClose - esCloses[esCloses.Count - 1 - RETURN_BARS]) / esCloses[esCloses.Count - 1 - RETURN_BARS] * 100;
            double nqRet5 = (nqClose - nqCloses[nqCloses.Count - 1 - RETURN_BARS]) / nqCloses[nqCloses.Count - 1 - RETURN_BARS] * 100;

            // Update Boof 23 ZigZag on ES
            UpdateZigZag(esClose, Highs[0][0], Lows[0][0], atr);
            
            // Detect cross-reference signals (using ES and NQ only for test)
            CrossSignal signal = DetectSignal(esRet5, nqRet5, esRet5, nqRet5);
            
            if (signal == null || signal.Strength < 2)
                return;
            
            // Boof 23 Regime Filter: Only trade if signal aligns with trend
            if (trend == "")
                return; // No trend established
            
            bool trendAligned = (signal.Direction == "LONG" && trend == "up") || 
                               (signal.Direction == "SHORT" && trend == "down");
            
            if (!trendAligned)
            {
                Print($"{Time[0]} | Signal {signal.Type} filtered - against {trend} trend");
                return;
            }

            // Entry on ES (ATR already calculated above)
            double entry = esClose;
            double sl = signal.Direction == "LONG" ? entry - atr * SL_R : entry + atr * SL_R;
            double tp = signal.Direction == "LONG" ? entry + atr * TP_R : entry - atr * TP_R;

            // Log signal
            Print($"{Time[0]} | {signal.Type} ({signal.Direction}) | ES:{esRet5:F2}% NQ:{nqRet5:F2}%");

            // Execute trade
            if (signal.Direction == "LONG")
            {
                EnterLong(1, "CrossLong");
                SetStopLoss("CrossLong", CalculationMode.Price, sl, false);
                SetProfitTarget("CrossLong", CalculationMode.Price, tp, false);
            }
            else
            {
                EnterShort(1, "CrossShort");
                SetStopLoss("CrossShort", CalculationMode.Price, sl, false);
                SetProfitTarget("CrossShort", CalculationMode.Price, tp, false);
            }
            
            dailyTrades++;
        }

        private CrossSignal DetectSignal(double esRet, double nqRet, double mesRet, double mnqRet)
        {
            // STRATEGY 1: All 4 aligned (high conviction)
            bool allUp = esRet > ALL_ALIGNED_THRESH && nqRet > ALL_ALIGNED_THRESH && 
                         mesRet > ALL_ALIGNED_THRESH && mnqRet > ALL_ALIGNED_THRESH;
            bool allDown = esRet < -ALL_ALIGNED_THRESH && nqRet < -ALL_ALIGNED_THRESH &&
                           mesRet < -ALL_ALIGNED_THRESH && mnqRet < -ALL_ALIGNED_THRESH;

            if (allUp)
                return new CrossSignal { Direction = "LONG", Type = "AllAlignedUp", Strength = 3 };
            if (allDown)
                return new CrossSignal { Direction = "SHORT", Type = "AllAlignedDown", Strength = 3 };

            // STRATEGY 2: Micro divergence from full (arbitrage)
            double esMesSpread = Math.Abs(esRet - mesRet);
            double nqMnqSpread = Math.Abs(nqRet - mnqRet);
            bool microDiv = esMesSpread > DIVERGENCE_THRESH || nqMnqSpread > DIVERGENCE_THRESH;

            if (microDiv)
            {
                // Trade toward the full contract direction (micros catch up)
                if (esRet > mesRet)
                    return new CrossSignal { Direction = "LONG", Type = "MicroCatchUpLong", Strength = 2 };
                else
                    return new CrossSignal { Direction = "SHORT", Type = "MicroCatchUpShort", Strength = 2 };
            }

            // STRATEGY 3: ES leads, NQ follows (lag play)
            bool esLeadsUp = esRet > LEAD_THRESH && nqRet < esRet - 0.05;
            bool esLeadsDown = esRet < -LEAD_THRESH && nqRet > esRet + 0.05;

            if (esLeadsUp)
                return new CrossSignal { Direction = "LONG", Type = "ESLeadsUp", Strength = 2 };
            if (esLeadsDown)
                return new CrossSignal { Direction = "SHORT", Type = "ESLeadsDown", Strength = 2 };

            // STRATEGY 4: Relative strength - trade stronger index
            bool esStronger = esRet > nqRet + RS_THRESH;
            bool nqStronger = nqRet > esRet + RS_THRESH;

            if (esStronger)
                return new CrossSignal { Direction = "LONG", Type = "ESStronger", Strength = 1 };
            if (nqStronger)
                return new CrossSignal { Direction = "LONG", Type = "NQStronger", Strength = 1 };

            return null;
        }

        private double CalcATR(int dataSeriesIndex, int period)
        {
            if (CurrentBars[dataSeriesIndex] < period)
                return 0;

            double sumTR = 0;
            for (int i = 0; i < period; i++)
            {
                double high = Highs[dataSeriesIndex][i];
                double low = Lows[dataSeriesIndex][i];
                double close = Closes[dataSeriesIndex][i + 1];
                double prevClose = Closes[dataSeriesIndex][i + 1];
                
                double tr = Math.Max(high - low, Math.Max(Math.Abs(high - prevClose), Math.Abs(low - prevClose)));
                sumTR += tr;
            }
            return sumTR / period;
        }

        private void UpdateZigZag(double close, double high, double low, double atr)
        {
            // Initialize on first call
            if (lastZZHigh == 0) lastZZHigh = Highs[0][0];
            if (lastZZLow == 0) lastZZLow = Lows[0][0];
            
            double currentHigh = Highs[0][0];
            double currentLow = Lows[0][0];
            
            // Update last swing points
            if (currentHigh > lastZZHigh) lastZZHigh = currentHigh;
            if (currentLow < lastZZLow) lastZZLow = currentLow;
            
            double threshold = atr * 0.75; // ATR_MULT from Boof 23
            
            // Check for swing reversals
            if (trend == "up" || trend == "")
            {
                // In uptrend - check for break below last swing low
                if (close < lastZZLow - threshold)
                {
                    trend = "down";
                    lastZZLow = currentLow;
                    Print($"{Time[0]} | ZigZag: Trend changed to DOWN");
                }
            }
            
            if (trend == "down" || trend == "")
            {
                // In downtrend - check for break above last swing high
                if (close > lastZZHigh + threshold)
                {
                    trend = "up";
                    lastZZHigh = currentHigh;
                    Print($"{Time[0]} | ZigZag: Trend changed to UP");
                }
            }
        }

        protected override void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity, 
            MarketPosition marketPosition, string orderId, DateTime time)
        {
            if (execution.Order != null && execution.Order.OrderState == OrderState.Filled)
            {
                if (execution.Order.Name.Contains("CrossLong") || execution.Order.Name.Contains("CrossShort"))
                {
                    Print($"FILLED: {execution.Order.Name} @ {price:F2} | Qty: {quantity} | Time: {time}");
                }
            }
        }

        private class CrossSignal
        {
            public string Direction { get; set; }
            public string Type { get; set; }
            public int Strength { get; set; }  // 1-3, higher is stronger
        }
    }
}
