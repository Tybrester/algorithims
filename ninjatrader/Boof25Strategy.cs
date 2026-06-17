// =========================================================
// BOOF 25.0 — Boof 24 + Acceleration Filter
// NinjaTrader 8 Implementation
// Only takes trades with acceleration score >= 60
// Target: Improve R/T by filtering low-quality entries
// =========================================================
// Architecture:
//   Step 1-6: Same as Boof 24 (MSB + Retest + Volume + Context)
//   Step 7: ACCELERATION FILTER (0-100 score)
//     - Trend strength (0-25 pts): % bars in direction
//     - Momentum (0-20 pts): price vs mean aligned
//     - Volume/Range (0-25 pts): expansion vs avg
//     - Velocity (0-15 pts): movement speed
//   Entry only if score >= 60
//   2:1 R/R (TP=2R, SL=1R)
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
    public class Boof25Strategy : Strategy
    {
        // ── BOOF 24 CONFIG ─────────────────────────────────
        private int atrLen = 14;
        private int volLen = 50;
        private double atrRevMult = 0.75;
        private double volMult = 1.25;
        private int atrPercentileMin = 40;
        private int retestBars = 5;
        private double tpR = 2.0;
        private double slR = 1.0;
        private int minSwings = 6;
        
        // ── ACCELERATION FILTER CONFIG ─────────────────────
        private int accelLookback = 5;           // Bars to analyze pre-entry
        private int minAccelScore = 60;          // Minimum score to trade
        private double trendStrong = 0.80;       // 80%+ bars = 25 pts
        private double trendGood = 0.70;         // 70%+ bars = 20 pts
        private double trendModerate = 0.60;     // 60%+ bars = 15 pts
        private double volHigh = 1.5;            // 1.5x range = 25 pts
        private double volGood = 1.2;            // 1.2x range = 20 pts
        private int momentumPts = 20;
        private int velocityPts = 15;
        
        // ── STATE ──────────────────────────────────────────
        private struct Swing { public int idx; public double price; public string type; }
        private List<Swing> swings = new List<Swing>();
        
        private int dailyTradeCount = 0;
        private DateTime lastTradeDate = DateTime.MinValue;
        private int maxTradesPerDay = 5;
        
        // Indicators
        private ATR atrInd;
        private SMA volSMA;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "Boof 25.0 — Boof 24 + Acceleration Filter";
                Name = "Boof25Strategy";
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
            
            // Reset daily counter
            if (Time[0].Date != lastTradeDate.Date)
            {
                dailyTradeCount = 0;
                lastTradeDate = Time[0].Date;
            }
            
            // Skip if max trades reached
            if (dailyTradeCount >= maxTradesPerDay)
                return;
                
            // Skip if in position
            if (Position.MarketPosition != MarketPosition.Flat)
                return;

            double currentATR = atrInd[0];
            if (currentATR == 0) return;

            // Step 1: Find swings (Boof 24)
            UpdateSwings();
            if (swings.Count < minSwings)
                return;

            // Step 2 & 3: Structure + MSB (Boof 24)
            var ms = AnalyzeStructure();
            if (ms == null || (!ms.msbBull && !ms.msbBear))
                return;

            string direction = ms.msbBull ? "LONG" : "SHORT";

            // Step 4: Volume confirmation (Boof 24)
            if (!CheckVolume())
                return;

            // Step 5: Retest check (Boof 24)
            if (!CheckRetest(ms.msbPrice, direction))
                return;

            // Step 6: Context filters (Boof 24)
            if (GetATRPercentile() < atrPercentileMin)
                return;

            double vwap = GetVWAPApproximation();
            if (direction == "LONG" && Close[0] < vwap) return;
            if (direction == "SHORT" && Close[0] > vwap) return;

            // Step 7: ACCELERATION FILTER (Boof 25 addition)
            int accelScore = CalculateAccelScore(direction);
            if (accelScore < minAccelScore)
            {
                Print($"{Time[0]:HH:mm} | B25 {direction} | Score:{accelScore} < {minAccelScore} | FILTERED");
                return;
            }

            // Execute trade (passed all filters including acceleration)
            ExecuteTrade(direction, currentATR, ms, accelScore);
            dailyTradeCount++;
        }

        // ── Acceleration Score Calculator (Boof 25) ────────
        private int CalculateAccelScore(string direction)
        {
            if (CurrentBar < accelLookback + 1)
                return 0;

            int score = 0;
            
            // Get pre-entry bars
            double[] closes = new double[accelLookback];
            double[] ranges = new double[accelLookback];
            double[] velocities = new double[accelLookback - 1];
            
            for (int i = 0; i < accelLookback; i++)
            {
                closes[i] = Close[i];
                ranges[i] = High[i] - Low[i];
            }
            
            for (int i = 0; i < accelLookback - 1; i++)
            {
                velocities[i] = Math.Abs(closes[i] - closes[i + 1]);
            }
            
            // Trend strength (0-25 pts)
            int barsInDirection = 0;
            for (int i = 0; i < accelLookback - 1; i++)
            {
                if (direction == "LONG" && closes[i] > closes[i + 1])
                    barsInDirection++;
                else if (direction == "SHORT" && closes[i] < closes[i + 1])
                    barsInDirection++;
            }
            double trendStrength = (double)barsInDirection / (accelLookback - 1);
            
            if (trendStrength >= trendStrong) score += 25;
            else if (trendStrength >= trendGood) score += 20;
            else if (trendStrength >= trendModerate) score += 15;
            
            // Momentum (0-20 pts)
            double meanPrice = closes.Skip(1).Take(accelLookback - 1).Average();
            bool momentum = (direction == "LONG" && closes[0] > meanPrice) || 
                           (direction == "SHORT" && closes[0] < meanPrice);
            if (momentum) score += momentumPts;
            
            // Volume/Range (0-25 pts)
            double avgRange = ranges.Skip(1).Take(accelLookback - 1).Average();
            double currentRange = ranges[0];
            double rangeRatio = avgRange > 0 ? currentRange / avgRange : 1.0;
            
            if (rangeRatio >= volHigh) score += 25;
            else if (rangeRatio >= volGood) score += 20;
            else if (rangeRatio >= 1.0) score += 10;
            
            // Velocity (0-15 pts)
            double avgVelocity = velocities.Length > 0 ? velocities.Average() : 0;
            double stdDev = CalculateStdDev(closes);
            if (avgVelocity > stdDev * 0.5) score += velocityPts;
            
            return Math.Min(100, score);
        }
        
        private double CalculateStdDev(double[] values)
        {
            if (values.Length == 0) return 0;
            double avg = values.Average();
            double sumSq = values.Sum(v => (v - avg) * (v - avg));
            return Math.Sqrt(sumSq / values.Length);
        }

        // ── Boof 24 Methods (unchanged) ───────────────────
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
            
            swings = swings.OrderBy(s => s.idx).ToList();
        }

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

            string trend = "neutral";
            bool hh = highs[highs.Count - 1].price > highs[highs.Count - 2].price;
            bool hl = lows[lows.Count - 1].price > lows[lows.Count - 2].price;
            bool lh = highs[highs.Count - 1].price < highs[highs.Count - 2].price;
            bool ll = lows[lows.Count - 1].price < lows[lows.Count - 2].price;

            if (hh && hl) trend = "bullish";
            else if (lh && ll) trend = "bearish";

            double close = Close[0];
            bool msbBull = false;
            bool msbBear = false;
            double msbPrice = 0;

            if (trend == "bearish" && highs.Count > 0)
            {
                double lastHighPrice = highs[highs.Count - 1].price;
                if (close > lastHighPrice) { msbBull = true; msbPrice = lastHighPrice; }
            }
            else if (trend == "bullish" && lows.Count > 0)
            {
                double lastLowPrice = lows[lows.Count - 1].price;
                if (close < lastLowPrice) { msbBear = true; msbPrice = lastLowPrice; }
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

        private bool CheckVolume()
        {
            double avgVol = volSMA[0];
            return Volume[0] > avgVol * volMult;
        }

        private bool CheckRetest(double msbPrice, string direction)
        {
            int lookback = Math.Min(retestBars + 5, CurrentBar);
            
            for (int i = 1; i <= lookback; i++)
            {
                if (direction == "LONG")
                {
                    if (Low[i] <= msbPrice * 1.005 && Close[i] > msbPrice)
                        return true;
                }
                else
                {
                    if (High[i] >= msbPrice * 0.995 && Close[i] < msbPrice)
                        return true;
                }
            }
            return false;
        }

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

        private void ExecuteTrade(string direction, double atr, MSResult ms, int accelScore)
        {
            double entry = Close[0];
            double sl, tp;
            
            if (direction == "LONG")
            {
                sl = entry - atr * slR;
                tp = entry + atr * tpR;
                
                EnterLong(1, "B25_LONG");
                SetStopLoss("B25_LONG", CalculationMode.Price, sl, false);
                SetProfitTarget("B25_LONG", CalculationMode.Price, tp);
                
                Print($"{Time[0]:yyyy-MM-dd HH:mm} | B25 LONG | Entry:{entry:F2} SL:{sl:F2} TP:{tp:F2} | Accel:{accelScore} | Trend:{ms.trend}");
            }
            else
            {
                sl = entry + atr * slR;
                tp = entry - atr * tpR;
                
                EnterShort(1, "B25_SHORT");
                SetStopLoss("B25_SHORT", CalculationMode.Price, sl, false);
                SetProfitTarget("B25_SHORT", CalculationMode.Price, tp);
                
                Print($"{Time[0]:yyyy-MM-dd HH:mm} | B25 SHORT | Entry:{entry:F2} SL:{sl:F2} TP:{tp:F2} | Accel:{accelScore} | Trend:{ms.trend}");
            }
        }
    }
}
