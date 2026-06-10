/*
 * Boof 25 Strategy - NinjaTrader 8
 * ES + MNQ with ACCELERATION FILTER
 * 
 * Only enters on high-quality acceleration signals (score 60+)
 * Risk: 1R stop, 2R target
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
    public class Boof25AccelFilterStrategy : Strategy
    {
        #region Variables
        private double bbPeriod = 20;
        private double bbStdDev = 2.0;
        private int volumeLookback = 20;
        private double volumeMultiplier = 1.0;
        private int breakLookback = 15;
        private int maxTradesPerDay = 5;
        private double tpR = 2.0;
        private double slR = 1.0;
        
        // ACCELERATION FILTER CONFIG
        private int accelLookback = 5;          // Bars to analyze pre-entry
        private int minAccelScore = 60;         // Minimum score to trade
        private double trendStrong = 0.8;       // 80%+ bars in direction
        private double trendGood = 0.7;         // 70%+ bars in direction
        private double volumeHigh = 1.5;        // 1.5x volume
        private double volumeGood = 1.2;        // 1.2x volume
        
        private int dailyTradeCount = 0;
        private DateTime lastTradeDate;
        
        private double rValueES = 10.0;
        private double rValueMNQ = 20.0;
        
        // Bollinger Bands
        private double bbUpper = 0;
        private double bbLower = 0;
        private double bbMiddle = 0;
        
        // Acceleration tracking
        private List<double> recentCloses = new List<double>();
        private List<double> recentVolumes = new List<double>();
        private List<double> recentHighs = new List<double>();
        private List<double> recentLows = new List<double>();
        #endregion

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "Boof 25 - ES/MNQ with ACCELERATION FILTER (Score 60+)";
                Name = "Boof25AccelFilter";
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
            if (BarsInProgress != 0)
                return;
            
            if (CurrentBar < 25)
                return;
            
            // Update recent data for acceleration calc
            UpdateRecentData();
            
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
            
            // Get R value
            double currentRValue = Instrument.FullName.Contains("ES") ? rValueES : rValueMNQ;
            
            // Get base signal
            string symbol = Instrument.FullName;
            bool baseSignal = false;
            string direction = "";
            
            if (symbol.Contains("ES"))
            {
                var impulse = CheckImpulse();
                baseSignal = impulse.signal;
                direction = impulse.direction;
            }
            else if (symbol.Contains("MNQ") || symbol.Contains("NQ"))
            {
                var breakout = CheckBreakout();
                baseSignal = breakout.signal;
                direction = breakout.direction;
            }
            
            // ACCELERATION FILTER: Check quality score
            if (baseSignal && !string.IsNullOrEmpty(direction))
            {
                int accelScore = CalculateAccelScore(direction);
                
                if (accelScore >= minAccelScore)
                {
                    ExecuteTrade(direction, currentRValue, accelScore);
                }
                else
                {
                    // Log filtered trade for analysis
                    Print($"{Time[0]:yyyy-MM-dd HH:mm} | FILTERED | Score: {accelScore}/100 | Dir: {direction}");
                }
            }
        }
        
        #region Signal Detection (Same as Boof 24)
        
        private (bool signal, string direction) CheckImpulse()
        {
            CalculateBB();
            
            double avgVol = SMA(Volume, volumeLookback)[0];
            double currentVol = Volume[0];
            if (currentVol < avgVol * 0.8)
                return (false, "");
            
            double prevClose = Close[1];
            double currClose = Close[0];
            
            if (currClose <= bbLower * 1.005 && prevClose > bbLower * 1.005)
                return (true, "long");
            
            if (currClose >= bbUpper * 0.995 && prevClose < bbUpper * 0.995)
                return (true, "short");
            
            return (false, "");
        }
        
        private (bool signal, string direction) CheckBreakout()
        {
            double avgVol = SMA(Volume, volumeLookback)[0];
            double currentVol = Volume[0];
            if (currentVol < avgVol * volumeMultiplier)
                return (false, "");
            
            double recentHigh = High[1];
            double recentLow = Low[1];
            int lookback = Math.Min(breakLookback, CurrentBar);
            
            for (int i = 2; i <= lookback; i++)
            {
                if (High[i] > recentHigh) recentHigh = High[i];
                if (Low[i] < recentLow) recentLow = Low[i];
            }
            
            double prevClose = Close[1];
            double currClose = Close[0];
            
            if (currClose > recentHigh * 0.9995 && prevClose <= recentHigh)
                return (true, "long");
            
            if (currClose < recentLow * 1.0005 && prevClose >= recentLow)
                return (true, "short");
            
            return (false, "");
        }
        
        #endregion
        
        #region Acceleration Filter
        
        private void UpdateRecentData()
        {
            // Maintain rolling window of data
            recentCloses.Insert(0, Close[0]);
            recentVolumes.Insert(0, (double)Volume[0]);
            recentHighs.Insert(0, High[0]);
            recentLows.Insert(0, Low[0]);
            
            // Keep only needed history
            int maxBars = Math.Max(accelLookback + 10, 20);
            while (recentCloses.Count > maxBars)
            {
                recentCloses.RemoveAt(recentCloses.Count - 1);
                recentVolumes.RemoveAt(recentVolumes.Count - 1);
                recentHighs.RemoveAt(recentHighs.Count - 1);
                recentLows.RemoveAt(recentLows.Count - 1);
            }
        }
        
        private int CalculateAccelScore(string direction)
        {
            if (recentCloses.Count < accelLookback + 5)
                return 0;
            
            // Get pre-entry bars (skip current, look at history)
            List<double> preCloses = recentCloses.Skip(1).Take(accelLookback + 5).ToList();
            List<double> preVolumes = recentVolumes.Skip(1).Take(accelLookback + 5).ToList();
            List<double> preHighs = recentHighs.Skip(1).Take(accelLookback + 5).ToList();
            List<double> preLows = recentLows.Skip(1).Take(accelLookback + 5).ToList();
            
            if (preCloses.Count < 5)
                return 0;
            
            int score = 0;
            
            // 1. TREND STRENGTH (0-25 pts)
            double trendStrength;
            bool momentum;
            
            if (direction == "long")
            {
                int higherBars = 0;
                for (int i = 1; i < preCloses.Count; i++)
                {
                    if (preCloses[i] > preCloses[i-1])
                        higherBars++;
                }
                trendStrength = (double)higherBars / (preCloses.Count - 1);
                double avgPre = preCloses.Take(preCloses.Count - 1).Average();
                momentum = preCloses.Last() > avgPre;
            }
            else // short
            {
                int lowerBars = 0;
                for (int i = 1; i < preCloses.Count; i++)
                {
                    if (preCloses[i] < preCloses[i-1])
                        lowerBars++;
                }
                trendStrength = (double)lowerBars / (preCloses.Count - 1);
                double avgPre = preCloses.Take(preCloses.Count - 1).Average();
                momentum = preCloses.Last() < avgPre;
            }
            
            if (trendStrength >= trendStrong)
                score += 25;
            else if (trendStrength >= trendGood)
                score += 20;
            else if (trendStrength >= 0.6)
                score += 15;
            
            // 2. MOMENTUM (0-20 pts)
            if (momentum)
                score += 20;
            
            // 3. VOLUME ACCELERATION (0-25 pts)
            List<double> ranges = new List<double>();
            for (int i = 0; i < preHighs.Count && i < preLows.Count; i++)
            {
                ranges.Add(preHighs[i] - preLows[i]);
            }
            
            if (ranges.Count >= 2)
            {
                double avgRange = ranges.Take(ranges.Count - 1).Average();
                double currentRange = ranges.Last();
                double volumeSignal = avgRange > 0 ? currentRange / avgRange : 1.0;
                
                if (volumeSignal >= volumeHigh)
                    score += 25;
                else if (volumeSignal >= volumeGood)
                    score += 20;
                else if (volumeSignal >= 1.0)
                    score += 10;
            }
            
            // 4. VELOCITY (0-15 pts)
            List<double> velocity = new List<double>();
            for (int i = 1; i < preCloses.Count; i++)
            {
                velocity.Add(Math.Abs(preCloses[i] - preCloses[i-1]));
            }
            
            if (velocity.Count > 0)
            {
                double avgVelocity = velocity.Average();
                double stdDev = CalculateStdDev(preCloses);
                
                if (avgVelocity > stdDev * 0.5)
                    score += 15;
            }
            
            // 5. CONSECUTIVE BARS (0-15 pts) - bonus for strong consecutiveness
            int consecutive = 0;
            if (direction == "long")
            {
                for (int i = preCloses.Count - 1; i > 0; i--)
                {
                    if (preCloses[i] > preCloses[i-1])
                        consecutive++;
                    else
                        break;
                }
            }
            else
            {
                for (int i = preCloses.Count - 1; i > 0; i--)
                {
                    if (preCloses[i] < preCloses[i-1])
                        consecutive++;
                    else
                        break;
                }
            }
            
            if (consecutive >= 4)
                score += 15;
            else if (consecutive >= 3)
                score += 10;
            else if (consecutive >= 2)
                score += 5;
            
            return Math.Min(score, 100); // Cap at 100
        }
        
        private double CalculateStdDev(List<double> values)
        {
            if (values.Count < 2)
                return 0;
            
            double avg = values.Average();
            double sumSquares = values.Sum(v => (v - avg) * (v - avg));
            return Math.Sqrt(sumSquares / values.Count);
        }
        
        #endregion
        
        #region Execution
        
        private void ExecuteTrade(string direction, double currentRValue, int accelScore)
        {
            double entryPrice = Close[0];
            double stopDistance = currentRValue * TickSize;
            double targetDistance = currentRValue * tpR * TickSize;
            
            string signalType = Instrument.FullName.Contains("ES") ? "IMPULSE" : "BREAKOUT";
            
            if (direction == "long")
            {
                double stopPrice = entryPrice - stopDistance;
                double targetPrice = entryPrice + targetDistance;
                
                EnterLong(1, $"Boof25_Long_{signalType}");
                ExitLongStopMarket(1, stopPrice, "Boof25_SL", $"Boof25_Long_{signalType}");
                ExitLongLimit(1, targetPrice, "Boof25_TP", $"Boof25_Long_{signalType}");
                
                Print($"{Time[0]:yyyy-MM-dd HH:mm} | Boof25 LONG | {signalType} | Score: {accelScore}/100 | Entry: {entryPrice:F2} | SL: {stopPrice:F2} | TP: {targetPrice:F2}");
            }
            else if (direction == "short")
            {
                double stopPrice = entryPrice + stopDistance;
                double targetPrice = entryPrice - targetDistance;
                
                EnterShort(1, $"Boof25_Short_{signalType}");
                ExitShortStopMarket(1, stopPrice, "Boof25_SL", $"Boof25_Short_{signalType}");
                ExitShortLimit(1, targetPrice, "Boof25_TP", $"Boof25_Short_{signalType}");
                
                Print($"{Time[0]:yyyy-MM-dd HH:mm} | Boof25 SHORT | {signalType} | Score: {accelScore}/100 | Entry: {entryPrice:F2} | SL: {stopPrice:F2} | TP: {targetPrice:F2}");
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
        [Display(Name = "Min Accel Score", Description = "Minimum acceleration score (0-100)", Order = 4, GroupName = "Acceleration Filter")]
        public int MinAccelScore
        {
            get { return minAccelScore; }
            set { minAccelScore = Math.Max(0, Math.Min(100, value)); }
        }
        
        [NinjaScriptProperty]
        [Display(Name = "Accel Lookback", Description = "Bars to analyze for acceleration", Order = 5, GroupName = "Acceleration Filter")]
        public int AccelLookback
        {
            get { return accelLookback; }
            set { accelLookback = Math.Max(3, value); }
        }
        
        #endregion
    }
}
