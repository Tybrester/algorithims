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
using System.Drawing;
using System.Reflection;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class Boof25Strategy : Strategy
    {
        private int bbPeriod = 20;
        private double bbStdDev = 2.0;
        private int volumeLookback = 20;
        private double volumeMultiplier = 1.0;
        private int breakLookback = 15;
        private int maxTradesPerDay = 5;
        private double tpR = 2.0;
        private double slR = 1.0;
        private int minAccelScore = 60;
        private int quantity = 1;
        private int accelLookback = 10;
        
        private int dailyTradeCount = 0;
        private DateTime lastTradeDate = DateTime.MinValue;
        private double bbUpper = 0;
        private double bbLower = 0;
        private double bbMiddle = 0;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "Boof 25 Strategy - ES/MNQ with Accel Filter";
                Name = "Boof25Strategy";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 30;
                IsFillLimitOnTouch = false;
                MaximumBarsLookBack = MaximumBarsLookBack.TwoHundredFiftySix;
                OrderFillResolution = OrderFillResolution.Standard;
                Slippage = 1;
                TraceOrders = false;
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
            
            if (Time[0].Date != lastTradeDate.Date)
            {
                dailyTradeCount = 0;
                lastTradeDate = Time[0].Date;
            }
            
            if (dailyTradeCount >= maxTradesPerDay)
                return;
            
            if (Position.MarketPosition != MarketPosition.Flat)
                return;
            
            string symbol = Instrument.FullName;
            bool signal = false;
            string direction = "";
            int accelScore = 0;
            
            if (symbol.Contains("ES"))
            {
                CalculateBB();
                double avgVol = SMA(Volume, volumeLookback)[0];
                if (Volume[0] >= avgVol * 0.8)
                {
                    if (Close[0] <= bbLower * 1.005 && Close[1] > bbLower * 1.005)
                    {
                        signal = true;
                        direction = "long";
                        accelScore = CalculateAccelScore("long");
                    }
                    else if (Close[0] >= bbUpper * 0.995 && Close[1] < bbUpper * 0.995)
                    {
                        signal = true;
                        direction = "short";
                        accelScore = CalculateAccelScore("short");
                    }
                }
            }
            else if (symbol.Contains("MNQ") || symbol.Contains("NQ"))
            {
                double avgVol = SMA(Volume, volumeLookback)[0];
                if (Volume[0] >= avgVol * volumeMultiplier)
                {
                    double recentHigh = High[1];
                    double recentLow = Low[1];
                    for (int i = 2; i <= breakLookback && i <= CurrentBar; i++)
                    {
                        if (High[i] > recentHigh) recentHigh = High[i];
                        if (Low[i] < recentLow) recentLow = Low[i];
                    }
                    
                    if (Close[0] > recentHigh * 0.9995 && Close[1] <= recentHigh)
                    {
                        signal = true;
                        direction = "long";
                        accelScore = CalculateAccelScore("long");
                    }
                    else if (Close[0] < recentLow * 1.0005 && Close[1] >= recentLow)
                    {
                        signal = true;
                        direction = "short";
                        accelScore = CalculateAccelScore("short");
                    }
                }
            }
            
            if (signal && direction != "")
            {
                if (accelScore < minAccelScore)
                    return;
                
                double rValue = symbol.Contains("ES") ? 10.0 : 20.0;
                double entryPrice = Close[0];
                double stopDistance = rValue * TickSize;
                double targetDistance = rValue * tpR * TickSize;
                
                if (direction == "long")
                {
                    double stopPrice = entryPrice - stopDistance;
                    double targetPrice = entryPrice + targetDistance;
                    EnterLong(quantity, "Boof25_Long");
                    ExitLongStopMarket(quantity, stopPrice, "SL", "Boof25_Long");
                    ExitLongLimit(quantity, targetPrice, "TP", "Boof25_Long");
                }
                else
                {
                    double stopPrice = entryPrice + stopDistance;
                    double targetPrice = entryPrice - targetDistance;
                    EnterShort(quantity, "Boof25_Short");
                    ExitShortStopMarket(quantity, stopPrice, "SL", "Boof25_Short");
                    ExitShortLimit(quantity, targetPrice, "TP", "Boof25_Short");
                }
                
                dailyTradeCount++;
            }
        }
        
        private void CalculateBB()
        {
            double sma = SMA(bbPeriod)[0];
            double std = StdDev(bbPeriod)[0];
            bbMiddle = sma;
            bbUpper = sma + (std * bbStdDev);
            bbLower = sma - (std * bbStdDev);
        }
        
        private int CalculateAccelScore(string direction)
        {
            int alignedBars = 0;
            int totalBars = Math.Min(accelLookback, CurrentBar);
            
            for (int i = 0; i < totalBars; i++)
            {
                if (direction == "long")
                {
                    if (Close[i] > Open[i]) alignedBars++;
                }
                else
                {
                    if (Close[i] < Open[i]) alignedBars++;
                }
            }
            
            return (alignedBars * 100) / totalBars;
        }

        [NinjaScriptProperty]
        [Display(Name = "Max Trades Per Day", Order = 1, GroupName = "Risk")]
        public int MaxTradesPerDay
        {
            get { return maxTradesPerDay; }
            set { maxTradesPerDay = Math.Max(1, value); }
        }
        
        [NinjaScriptProperty]
        [Display(Name = "TP (R)", Order = 2, GroupName = "Risk")]
        public double TakeProfitR
        {
            get { return tpR; }
            set { tpR = Math.Max(0.5, value); }
        }
        
        [NinjaScriptProperty]
        [Display(Name = "SL (R)", Order = 3, GroupName = "Risk")]
        public double StopLossR
        {
            get { return slR; }
            set { slR = Math.Max(0.5, value); }
        }
        
        [NinjaScriptProperty]
        [Display(Name = "Min Accel Score", Order = 4, GroupName = "Filter")]
        public int MinAccelScore
        {
            get { return minAccelScore; }
            set { minAccelScore = Math.Max(0, Math.Min(100, value)); }
        }
        
        [NinjaScriptProperty]
        [Display(Name = "Quantity (Contracts)", Order = 5, GroupName = "Risk")]
        public int Quantity
        {
            get { return quantity; }
            set { quantity = Math.Max(1, value); }
        }
    }
}
