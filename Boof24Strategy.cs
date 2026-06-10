/*
 * Boof 24.0 Strategy - NinjaTrader 8
 * ES (IMPULSE) + MNQ (BREAKOUT)
 * 
 * Risk: 1R stop, 2R target
 * No pyramids, pure edge per setup
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
using System.Reflection;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class Boof24Strategy : Strategy
    {
        #region Variables
        private double bbPeriod = 20;
        private double bbStdDev = 2.0;
        private double volumeLookback = 20;
        private double volumeMultiplier = 1.0;
        private double breakLookback = 15;
        private int maxTradesPerDay = 5;
        private double tpR = 2.0;
        private double slR = 1.0;
        
        private int dailyTradeCount = 0;
        private DateTime lastTradeDate;
        
        private double rValueES = 10.0;    // ~10 points for ES
        private double rValueMNQ = 20.0;   // ~20 points for MNQ
        
        private bool inPosition = false;
        private double entryPrice = 0;
        private string entryDirection = "";
        private double currentRValue = 0;
        
        // Bollinger Bands
        private double bbUpper = 0;
        private double bbLower = 0;
        private double bbMiddle = 0;
        #endregion

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "Boof 24.0 - ES (IMPULSE) + MNQ (BREAKOUT)";
                Name = "Boof24Strategy";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 30;
                IsFillLimitOnTouch = false;
                MaximumBarsLookBack = MaximumBarsLookBack.TwoHundredFiftySix;
                OrderFillResolution = OrderFillResolution.Standard;
                Slippage = 1;
                StartBehavior = StartBehavior.WaitUntilFlat;
                TraceOrders = false;
                WaitUntilFlat = true;
            }
            else if (State == State.Configure)
            {
                AddDataSeries(Data.BarsPeriodType.Tick, 1);
            }
        }

        protected override void OnBarUpdate()
        {
            // Only process on primary bars
            if (BarsInProgress != 0)
                return;
            
            // Need minimum bars
            if (CurrentBar < 25)
                return;
            
            // Reset daily counter
            if (Time[0].Date != lastTradeDate.Date)
            {
                dailyTradeCount = 0;
                lastTradeDate = Time[0].Date;
            }
            
            // Skip if max trades reached
            if (dailyTradeCount >= maxTradesPerDay)
                return;
            
            // Skip if already in position
            if (Position.MarketPosition != MarketPosition.Flat)
                return;
            
            // Calculate R value based on symbol
            currentRValue = Instrument.FullName.Contains("ES") ? rValueES : rValueMNQ;
            
            // Get signal based on symbol type
            string symbol = Instrument.FullName;
            bool signal = false;
            string direction = "";
            
            if (symbol.Contains("ES"))
            {
                // ES: IMPULSE (Mean Reversion at BB)
                var impulse = CheckImpulse();
                signal = impulse.signal;
                direction = impulse.direction;
            }
            else if (symbol.Contains("MNQ") || symbol.Contains("NQ"))
            {
                // MNQ: BREAKOUT (Momentum)
                var breakout = CheckBreakout();
                signal = breakout.signal;
                direction = breakout.direction;
            }
            
            // Execute if signal
            if (signal && !string.IsNullOrEmpty(direction))
            {
                ExecuteTrade(direction);
            }
        }
        
        #region Signal Detection
        
        private (bool signal, string direction) CheckImpulse()
        {
            // Calculate Bollinger Bands
            CalculateBB();
            
            // Volume check
            double avgVol = SMA(Volume, (int)volumeLookback)[0];
            double currentVol = Volume[0];
            if (currentVol < avgVol * 0.8)
                return (false, "");
            
            // Check for mean reversion at BB extremes
            double prevClose = Close[1];
            double currClose = Close[0];
            
            // Long signal: Price touches lower band then reverses
            if (currClose <= bbLower * 1.005 && prevClose > bbLower * 1.005)
            {
                return (true, "long");
            }
            
            // Short signal: Price touches upper band then reverses
            if (currClose >= bbUpper * 0.995 && prevClose < bbUpper * 0.995)
            {
                return (true, "short");
            }
            
            return (false, "");
        }
        
        private (bool signal, string direction) CheckBreakout()
        {
            // Volume check
            double avgVol = SMA(Volume, (int)volumeLookback)[0];
            double currentVol = Volume[0];
            if (currentVol < avgVol * volumeMultiplier)
                return (false, "");
            
            // Calculate recent high/low
            double recentHigh = High[1];
            double recentLow = Low[1];
            int lookback = Math.Min((int)breakLookback, CurrentBar);
            
            for (int i = 2; i <= lookback; i++)
            {
                if (High[i] > recentHigh)
                    recentHigh = High[i];
                if (Low[i] < recentLow)
                    recentLow = Low[i];
            }
            
            double prevClose = Close[1];
            double currClose = Close[0];
            
            // Long breakout: Close above recent high with momentum
            if (currClose > recentHigh * 0.9995 && prevClose <= recentHigh)
            {
                return (true, "long");
            }
            
            // Short breakout: Close below recent low with momentum
            if (currClose < recentLow * 1.0005 && prevClose >= recentLow)
            {
                return (true, "short");
            }
            
            return (false, "");
        }
        
        #endregion
        
        #region Execution
        
        private void ExecuteTrade(string direction)
        {
            entryPrice = Close[0];
            entryDirection = direction;
            
            // Calculate stop and target
            double stopDistance = currentRValue * TickSize;
            double targetDistance = currentRValue * tpR * TickSize;
            
            // Submit order based on direction
            if (direction == "long")
            {
                double stopPrice = entryPrice - stopDistance;
                double targetPrice = entryPrice + targetDistance;
                
                EnterLong(1, "Boof24_Long");
                ExitLongStopMarket(1, stopPrice, "Boof24_SL", "Boof24_Long");
                ExitLongLimit(1, targetPrice, "Boof24_TP", "Boof24_Long");
                
                // Log trade
                Print($"{Time[0]:yyyy-MM-dd HH:mm} | ES/MNQ LONG | Entry: {entryPrice:F2} | SL: {stopPrice:F2} | TP: {targetPrice:F2}");
            }
            else if (direction == "short")
            {
                double stopPrice = entryPrice + stopDistance;
                double targetPrice = entryPrice - targetDistance;
                
                EnterShort(1, "Boof24_Short");
                ExitShortStopMarket(1, stopPrice, "Boof24_SL", "Boof24_Short");
                ExitShortLimit(1, targetPrice, "Boof24_TP", "Boof24_Short");
                
                // Log trade
                Print($"{Time[0]:yyyy-MM-dd HH:mm} | ES/MNQ SHORT | Entry: {entryPrice:F2} | SL: {stopPrice:F2} | TP: {targetPrice:F2}");
            }
            
            dailyTradeCount++;
        }
        
        #endregion
        
        #region Helpers
        
        private void CalculateBB()
        {
            double sma = SMA((int)bbPeriod)[0];
            double std = StdDev((int)bbPeriod)[0];
            
            bbMiddle = sma;
            bbUpper = sma + (std * bbStdDev);
            bbLower = sma - (std * bbStdDev);
        }
        
        protected override void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity, MarketPosition marketPosition, string orderId, DateTime time)
        {
            // Track fills for P&L logging
            if (execution.Order != null && execution.Order.OrderState == OrderState.Filled)
            {
                if (execution.Order.Name.Contains("TP"))
                {
                    Print($"WIN: {time:yyyy-MM-dd HH:mm} | P&L: +{execution.Quantity * tpR}R");
                }
                else if (execution.Order.Name.Contains("SL"))
                {
                    Print($"LOSS: {time:yyyy-MM-dd HH:mm} | P&L: -{execution.Quantity * slR}R");
                }
            }
        }
        
        #endregion
        
        #region Properties
        
        [NinjaScriptProperty]
        [Display(Name = "Max Trades Per Day", Description = "Maximum trades per day", Order = 1, GroupName = "Risk")]
        public int MaxTradesPerDay
        {
            get { return maxTradesPerDay; }
            set { maxTradesPerDay = Math.Max(1, value); }
        }
        
        [NinjaScriptProperty]
        [Display(Name = "TP (R)", Description = "Take profit in R multiples", Order = 2, GroupName = "Risk")]
        public double TakeProfitR
        {
            get { return tpR; }
            set { tpR = Math.Max(0.5, value); }
        }
        
        [NinjaScriptProperty]
        [Display(Name = "SL (R)", Description = "Stop loss in R multiples", Order = 3, GroupName = "Risk")]
        public double StopLossR
        {
            get { return slR; }
            set { slR = Math.Max(0.5, value); }
        }
        
        [NinjaScriptProperty]
        [Display(Name = "BB Period", Description = "Bollinger Bands period for IMPULSE", Order = 4, GroupName = "Indicators")]
        public int BBPeriod
        {
            get { return (int)bbPeriod; }
            set { bbPeriod = Math.Max(10, value); }
        }
        
        [NinjaScriptProperty]
        [Display(Name = "BB StdDev", Description = "Bollinger Bands standard deviation", Order = 5, GroupName = "Indicators")]
        public double BBStdDev
        {
            get { return bbStdDev; }
            set { bbStdDev = Math.Max(1.0, value); }
        }
        
        [NinjaScriptProperty]
        [Display(Name = "Volume Multiplier", Description = "Minimum volume vs average", Order = 6, GroupName = "Filters")]
        public double VolumeMultiplier
        {
            get { return volumeMultiplier; }
            set { volumeMultiplier = Math.Max(0.5, value); }
        }
        
        #endregion
    }
}
