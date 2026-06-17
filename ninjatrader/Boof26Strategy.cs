// =========================================================
// BOOF 26.0 — Hybrid Strategy (NinjaTrader 8)
// Layer 1: Boof 22 — Volume Cluster + Fractal Detection
// Layer 2: Boof 23 — ZigZag Regime Filter  
// Layer 3: Boof 24 — MSB Confirmation + Retest
// Layer 4: Context Filters (Volume, ATR%, VWAP)
// Result: Fewer, higher-quality trades with 2:1 R/R
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
    public class Boof26Strategy : Strategy
    {
        // ── LAYER 1 CONFIG (Boof 22) ───────────────────────
        private int atrLen = 14;
        private int volLen = 50;
        private int fractalBars = 3;
        private double atrMult = 0.6;
        private double clusterMerge = 0.5;
        private int srStrengthMin = 2;
        private double srDistMax = 1.0;
        private double volMult = 1.3;
        
        // ── LAYER 2 CONFIG (Boof 23) ──────────────────────
        private double atrRevMult = 0.75;
        
        // ── LAYER 3 CONFIG (Boof 24) ───────────────────────
        private double volMultMS = 1.25;
        private int atrPercentileMin = 40;
        private int retestBars = 5;
        
        // ── R/R CONFIG ─────────────────────────────────────
        private double tpR = 2.0;
        private double slR = 1.0;
        
        // ── STATE ───────────────────────────────────────────
        private struct Cluster { public double price; public int strength; }
        private List<Cluster> clusters = new List<Cluster>();
        
        private struct Swing { public int idx; public double price; public string type; }
        
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
                Description = "Boof 26.0 — Hybrid (22+23+24)";
                Name = "Boof26Strategy";
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
            
            if (dailyTradeCount >= maxTradesPerDay)
                return;
                
            if (Position.MarketPosition != MarketPosition.Flat)
                return;

            double currentATR = atrInd[0];
            if (currentATR == 0) return;

            // ── LAYER 1: Build Clusters ─────────────────────
            BuildClusters();
            
            // Check cluster proximity
            double close = Close[0];
            double clusterDist = NearestClusterDist(close, currentATR);
            if (clusterDist > srDistMax)
                return;

            // ── LAYER 2: Fractal + ZigZag ───────────────────
            bool peak = false, trough = false;
            CheckFractal(out peak, out trough);
            
            var zz = UpdateZigZag();
            if (string.IsNullOrEmpty(zz.trend))
                return;
            
            // Determine direction
            string direction = null;
            if (peak && zz.trend == "up")
                direction = "SHORT";
            else if (trough && zz.trend == "down")
                direction = "LONG";
            
            if (string.IsNullOrEmpty(direction))
                return;

            // ── LAYER 3: MSB + Retest ───────────────────────
            var msb = CheckMSB(zz);
            bool msbAligned = (direction == "LONG" && msb.msbBull) || 
                              (direction == "SHORT" && msb.msbBear);
            
            if (!msbAligned)
                return;
            
            if (!CheckRetest(msb.msbPrice, direction))
                return;

            // ── LAYER 4: Context Filters ────────────────────
            if (!CheckVolume())
                return;
            
            if (GetATRPercentile() < atrPercentileMin)
                return;
            
            double vwap = GetVWAPApproximation();
            if (direction == "LONG" && close < vwap) return;
            if (direction == "SHORT" && close > vwap) return;

            // All layers passed - execute trade
            ExecuteTrade(direction, currentATR, zz, clusterDist);
            dailyTradeCount++;
        }

        // ── LAYER 1: Cluster Management ────────────────────
        private void BuildClusters()
        {
            clusters.Clear();
            if (CurrentBar < volLen) return;
            
            double avgATR = 0;
            int atrCount = 0;
            for (int i = 0; i < CurrentBar && i < 200; i++)
            {
                if (atrInd[i] > 0) { avgATR += atrInd[i]; atrCount++; }
            }
            avgATR = atrCount > 0 ? avgATR / atrCount : 1;
            double mergeTol = avgATR * clusterMerge;
            
            for (int i = volLen; i < Math.Min(CurrentBar, 200); i++)
            {
                if (Volume[i] < volSMA[i] * volMult) continue;
                double price = (High[i] + Low[i]) / 2;
                bool merged = false;
                for (int c = 0; c < clusters.Count; c++)
                {
                    if (Math.Abs(clusters[c].price - price) <= mergeTol)
                    {
                        var cl = clusters[c];
                        cl.price = (cl.price * cl.strength + price) / (cl.strength + 1);
                        cl.strength++;
                        clusters[c] = cl;
                        merged = true;
                        break;
                    }
                }
                if (!merged) clusters.Add(new Cluster { price = price, strength = 1 });
            }
            
            clusters.RemoveAll(c => c.strength < srStrengthMin);
        }

        private double NearestClusterDist(double price, double atr)
        {
            if (clusters.Count == 0 || atr == 0) return double.MaxValue;
            double bestDist = double.MaxValue;
            foreach (var c in clusters)
            {
                double d = Math.Abs(c.price - price) / atr;
                if (d < bestDist) bestDist = d;
            }
            return bestDist;
        }

        // ── LAYER 2: Fractal + ZigZag ─────────────────────
        private void CheckFractal(out bool peak, out bool trough)
        {
            peak = trough = false;
            int lookback = 10;
            
            for (int offset = fractalBars + 2; offset < lookback && offset < CurrentBar; offset++)
            {
                int idx = offset;
                if (idx < fractalBars) continue;
                
                bool isPeak = true, isTrough = true;
                for (int j = 1; j <= fractalBars; j++)
                {
                    if (High[idx] <= High[idx + j]) isPeak = false;
                    if (High[idx] <= High[idx - j]) isPeak = false;
                    if (Low[idx] >= Low[idx + j]) isTrough = false;
                    if (Low[idx] >= Low[idx - j]) isTrough = false;
                }
                if (isPeak) peak = true;
                if (isTrough) trough = true;
            }
        }

        private struct ZZState { public string trend; public double zzHigh; public double zzLow; }
        
        private ZZState UpdateZigZag()
        {
            if (CurrentBar < 2) return new ZZState { trend = "", zzHigh = High[0], zzLow = Low[0] };
            
            double lastHighPrice = High[CurrentBar];
            double lastLowPrice = Low[CurrentBar];
            string trend = "";
            
            for (int i = 1; i <= Math.Min(CurrentBar, 200); i++)
            {
                double threshold = atrInd[i] * atrRevMult;
                if (High[i] > lastHighPrice) lastHighPrice = High[i];
                if (Low[i] < lastLowPrice) lastLowPrice = Low[i];
                
                double close = Close[i];
                if (trend == "up" && lastHighPrice - close > threshold)
                {
                    trend = "down";
                    lastLowPrice = Low[i];
                }
                else if (trend == "down" && close - lastLowPrice > threshold)
                {
                    trend = "up";
                    lastHighPrice = High[i];
                }
                else if (trend == "")
                {
                    if (close > High[CurrentBar] + threshold) trend = "up";
                    else if (close < Low[CurrentBar] - threshold) trend = "down";
                }
            }
            
            return new ZZState { trend = trend, zzHigh = lastHighPrice, zzLow = lastLowPrice };
        }

        // ── LAYER 3: MSB + Retest ──────────────────────────
        private struct MSBResult { public bool msbBull; public bool msbBear; public double msbPrice; }
        
        private MSBResult CheckMSB(ZZState zz)
        {
            double close = Close[0];
            bool bull = false, bear = false;
            double price = 0;
            
            if (zz.trend == "down" && close > zz.zzHigh)
            {
                bull = true;
                price = zz.zzHigh;
            }
            else if (zz.trend == "up" && close < zz.zzLow)
            {
                bear = true;
                price = zz.zzLow;
            }
            
            return new MSBResult { msbBull = bull, msbBear = bear, msbPrice = price };
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

        // ── LAYER 4: Context Filters ──────────────────────
        private bool CheckVolume()
        {
            return Volume[0] > volSMA[0] * volMultMS;
        }

        private double GetATRPercentile()
        {
            int lookback = 50;
            if (CurrentBar < lookback) return 50;
            double currentATR = atrInd[0];
            int count = 0;
            for (int i = 1; i <= lookback; i++)
                if (atrInd[i] < currentATR) count++;
            return (count / (double)lookback) * 100;
        }

        private double GetVWAPApproximation()
        {
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

        // ── Execute Trade ───────────────────────────────────
        private void ExecuteTrade(string direction, double atr, ZZState zz, double clusterDist)
        {
            double entry = Close[0];
            double sl, tp;
            
            if (direction == "LONG")
            {
                sl = entry - atr * slR;
                tp = entry + atr * tpR;
                EnterLong(1, "B26_LONG");
                SetStopLoss("B26_LONG", CalculationMode.Price, sl, false);
                SetProfitTarget("B26_LONG", CalculationMode.Price, tp);
                Print($"{Time[0]:yyyy-MM-dd HH:mm} | B26 LONG | Entry:{entry:F2} SL:{sl:F2} TP:{tp:F2} | ZZ:{zz.trend} | Cluster:{clusterDist:F2}ATR");
            }
            else
            {
                sl = entry + atr * slR;
                tp = entry - atr * tpR;
                EnterShort(1, "B26_SHORT");
                SetStopLoss("B26_SHORT", CalculationMode.Price, sl, false);
                SetProfitTarget("B26_SHORT", CalculationMode.Price, tp);
                Print($"{Time[0]:yyyy-MM-dd HH:mm} | B26 SHORT | Entry:{entry:F2} SL:{sl:F2} TP:{tp:F2} | ZZ:{zz.trend} | Cluster:{clusterDist:F2}ATR");
            }
        }
    }
}
