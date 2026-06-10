// =========================================================
// BOOF 24.0 — ICT/MSB Swing Break + Retest Strategy
// NinjaTrader 8 Implementation
// Based on backtest: 0.75x ATR + Retest + 1.25x Volume + VWAP
// Target: 0.156 R/T
// =========================================================
// Architecture:
//   Step 1: ATR-based swing detection
//   Step 2: Market structure analysis (HH/HL/LH/LL)
//   Step 3: MSB (Market Structure Break) detection
//   Step 4: Volume confirmation (1.25x SMA)
//   Step 5: Retest check (price returns to broken level)
//   Step 6: Context filters (ATR percentile > 40%, VWAP)
//   Entry: 2:1 R/R (TP=2R, SL=1R)
// =========================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class Boof24Strategy : Strategy
    {
        // ── CONFIG ─────────────────────────────────────────
        private int atrLen = 14;
        private int volLen = 50;
        private double atrRevMult = 0.75;      // Swing detection threshold
        private double volMult = 1.25;           // Volume confirmation
        private int atrPercentileMin = 40;       // ATR must be > 40th percentile
        private int retestBars = 5;              // Lookback for retest
        private double tpR = 2.0;                // 2:1 R/R
        private double slR = 1.0;
        private int minSwings = 6;               // Need at least 6 swings
        
        // ── STATE ──────────────────────────────────────────
        private struct Swing { public int idx; public double price; public string type; }
        private List<Swing> swings = new List<Swing>();
        
        // Indicators
        private ATR atrInd;
        private SMA volSMA;
        
        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "Boof 24.0 — ICT/MSB Swing Break + Retest";
                Name = "Boof24Strategy";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                ExitOnSessionCloseSeconds = 30;
            }
            else if (State == State.Configure)
            {
                atrInd = ATR(atrLen);
                volSMA = SMA(Volume, volLen);
                AddChartIndicator(atrInd);
            }
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBar < Math.Max(atrLen, volLen) + 100)
                return;
                
            // Skip if in position
            if (Position.MarketPosition != MarketPosition.Flat)
                return;

            double currentATR = atrInd[0];
            if (currentATR == 0) return;

            // Step 1: Find swings
            UpdateSwings();
            if (swings.Count < minSwings)
                return;

            // Step 2 & 3: Structure + MSB
            var ms = AnalyzeStructure();
            if (ms == null || (!ms.msbBull && !ms.msbBear))
                return;

            string direction = ms.msbBull ? "LONG" : "SHORT";

            // Step 4: Volume confirmation
            if (!CheckVolume())
                return;

            // Step 5: Retest check
            if (!CheckRetest(ms.msbPrice, direction))
                return;

            // Step 6: Context filters
            if (GetATRPercentile() < atrPercentileMin)
                return;

            // VWAP filter (skip for futures if unavailable)
            double vwap = GetVWAPApproximation();
            if (direction == "LONG" && Close[0] < vwap) return;
            if (direction == "SHORT" && Close[0] > vwap) return;

            // Execute trade
            ExecuteTrade(direction, currentATR, ms);
        }

        // ── Swing Detection (ATR-based) ───────────────────
        private void UpdateSwings()
        {
            swings.Clear();
            if (CurrentBar < 2) return;

            double lastHighPrice = High[CurrentBar];
            double lastLowPrice = Low[CurrentBar];
            int lastHighIdx = CurrentBar;
            int lastLowIdx = CurrentBar;
            string dir = "";

            for (int i = 1; i <= Math.Min(CurrentBar, 200); i++)
            {
                int idx = CurrentBar - i;
                double atrAtIdx = atrInd[i];
                double threshold = atrAtIdx * atrRevMult;

                if (High[i] > lastHighPrice) { lastHighPrice = High[i]; lastHighIdx = idx; }
                if (Low[i] < lastLowPrice) { lastLowPrice = Low[i]; lastLowIdx = idx; }

                double close = Close[i];

                if (dir == "up" && lastHighPrice - close > threshold)
                {
                    swings.Add(new Swing { idx = lastHighIdx, price = lastHighPrice, type = "high" });
                    dir = "down";
                    lastLowPrice = Low[i];
                    lastLowIdx = idx;
                }
                else if (dir == "down" && close - lastLowPrice > threshold)
                {
                    swings.Add(new Swing { idx = lastLowIdx, price = lastLowPrice, type = "low" });
                    dir = "up";
                    lastHighPrice = High[i];
                    lastHighIdx = idx;
                }
                else if (dir == "")
                {
                    if (close > High[CurrentBar] + threshold) dir = "up";
                    else if (close < Low[CurrentBar] - threshold) dir = "down";
                }
            }
            
            // Sort by index ascending
            swings = swings.OrderBy(s => s.idx).ToList();
        }

        // ── Market Structure Analysis ─────────────────────
        private class MSResult
        {
            public string trend;
            public bool msbBull;
            public bool msbBear;
            public double msbPrice;
            public double lastHigh;
            public double lastLow;
        }

        private MSResult AnalyzeStructure()
        {
            if (swings.Count < 4) return null;

            var recent = swings.Skip(swings.Count - 4).ToList();
            var highs = recent.Where(s => s.type == "high").ToList();
            var lows = recent.Where(s => s.type == "low").ToList();

            if (highs.Count < 2 || lows.Count < 2) return null;

            // Trend detection
            string trend = "neutral";
            bool hh = highs[highs.Count - 1].price > highs[highs.Count - 2].price;
            bool hl = lows[lows.Count - 1].price > lows[lows.Count - 2].price;
            bool lh = highs[highs.Count - 1].price < highs[highs.Count - 2].price;
            bool ll = lows[lows.Count - 1].price < lows[lows.Count - 2].price;

            if (hh && hl) trend = "bullish";
            else if (lh && ll) trend = "bearish";

            // MSB detection
            double close = Close[0];
            bool msbBull = false;
            bool msbBear = false;
            double msbPrice = 0;

            if (trend == "bearish" && highs.Count > 0)
            {
                double lastHighPrice = highs[highs.Count - 1].price;
                if (close > lastHighPrice)
                {
                    msbBull = true;
                    msbPrice = lastHighPrice;
                }
            }
            else if (trend == "bullish" && lows.Count > 0)
            {
                double lastLowPrice = lows[lows.Count - 1].price;
                if (close < lastLowPrice)
                {
                    msbBear = true;
                    msbPrice = lastLowPrice;
                }
            }

            return new MSResult
            {
                trend = trend,
                msbBull = msbBull,
                msbBear = msbBear,
                msbPrice = msbPrice,
                lastHigh = highs[highs.Count - 1].price,
                lastLow = lows[lows.Count - 1].price
            };
        }

        // ── Volume Confirmation ───────────────────────────
        private bool CheckVolume()
        {
            double avgVol = volSMA[0];
            return Volume[0] > avgVol * volMult;
        }

        // ── Retest Check ──────────────────────────────────
        private bool CheckRetest(double msbPrice, string direction)
        {
            int lookback = Math.Min(retestBars + 5, CurrentBar);
            
            for (int i = 1; i <= lookback; i++)
            {
                if (direction == "LONG")
                {
                    // Price touched below MSB then closed above
                    if (Low[i] <= msbPrice * 1.005 && Close[i] > msbPrice)
                        return true;
                }
                else
                {
                    // Price touched above MSB then closed below
                    if (High[i] >= msbPrice * 0.995 && Close[i] < msbPrice)
                        return true;
                }
            }
            return false;
        }

        // ── ATR Percentile (approximation) ──────────────────
        private double GetATRPercentile()
        {
            int lookback = 50;
            if (CurrentBar < lookback) return 50;

            double currentATR = atrInd[0];
            int count = 0;
            
            for (int i = 1; i <= lookback; i++)
            {
                if (atrInd[i] < currentATR) count++;
            }
            
            return (count / (double)lookback) * 100;
        }

        // ── VWAP Approximation ────────────────────────────
        private double GetVWAPApproximation()
        {
            // Calculate VWAP manually (works on all instruments including futures)
            double sum = 0;
            double volSum = 0;
            int lookback = Math.Min(50, CurrentBar);
            
            for (int i = 0; i < lookback; i++)
            {
                double tp = (High[i] + Low[i] + Close[i]) / 3;
                sum += tp * (double)Volume[i];
                volSum += (double)Volume[i];
            }
            
            return volSum > 0 ? sum / volSum : Close[0];
        }

        // ── Execute Trade ──────────────────────────────────
        private void ExecuteTrade(string direction, double atr, MSResult ms)
        {
            double entry = Close[0];
            double sl, tp;
            
            if (direction == "LONG")
            {
                sl = entry - atr * slR;
                tp = entry + atr * tpR;
                
                EnterLong(1, "B24_LONG");
                SetStopLoss("B24_LONG", CalculationMode.Price, sl, false);
                SetProfitTarget("B24_LONG", CalculationMode.Price, tp);
                
                Print($"{Time[0]:yyyy-MM-dd HH:mm} | B24 LONG | Entry:{entry:F2} SL:{sl:F2} TP:{tp:F2} | Trend:{ms.trend} MSB:{ms.msbPrice:F2}");
            }
            else
            {
                sl = entry + atr * slR;
                tp = entry - atr * tpR;
                
                EnterShort(1, "B24_SHORT");
                SetStopLoss("B24_SHORT", CalculationMode.Price, sl, false);
                SetProfitTarget("B24_SHORT", CalculationMode.Price, tp);
                
                Print($"{Time[0]:yyyy-MM-dd HH:mm} | B24 SHORT | Entry:{entry:F2} SL:{sl:F2} TP:{tp:F2} | Trend:{ms.trend} MSB:{ms.msbPrice:F2}");
            }
            
            // Signal logged in Print statement above
        }
    }
}
