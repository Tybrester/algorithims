// =========================================================
// BOOF 23.0 — NinjaTrader 8 Strategy
// SR Cluster Entry + ZigZag Regime Filter + Engulf Confirmation
// Layer 1: ZigZag state machine — regime classifier
// Layer 2: SR cluster fractal entry gated by ZigZag regime
// Layer 3: Engulf confirmation (default off)
// Best on: AAPL, NVDA, META, GOOGL, AMD, PLTR
// =========================================================
#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using NinjaTrader.Cbi;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class Boof23 : Strategy
    {
        // ── CONFIG ──────────────────────────────────────────
        private int    AtrLen        = 14;
        private int    VolLen        = 50;
        private int    FractalBars   = 3;
        private double AtrMult       = 0.4;
        private double ClusterMerge  = 0.5;
        private int    SrStrengthMin = 2;
        private double SrDistMax     = 1.0;
        private double RvolMin       = 0.8;
        private double VolMult       = 1.3;
        private int    ZzProxBars    = 30;
        private bool   UseEngulf     = false;
        private int    MaxLookback   = 10;

        // ── PARAMETERS (editable in NT UI) ──────────────────
        [NinjaScriptProperty]
        public double TpPoints { get; set; }

        [NinjaScriptProperty]
        public double SlPoints { get; set; }

        [NinjaScriptProperty]
        public int CoreQty { get; set; }

        [NinjaScriptProperty]
        public int ExpandedQty { get; set; }

        [NinjaScriptProperty]
        public bool UseEngulfFilter { get; set; }

        // ── INDICATORS ──────────────────────────────────────
        private ATR atrInd;

        // ── CLUSTER STATE ────────────────────────────────────
        private struct Cluster { public double Price; public int Strength; }
        private List<Cluster> clusters = new List<Cluster>();

        // ── ZIGZAG STATE ─────────────────────────────────────
        private enum ZzTrend { None, Up, Down }
        private ZzTrend zzTrend      = ZzTrend.None;
        private double  zzHighPrice  = 0;
        private int     zzHighBar    = 0;
        private double  zzLowPrice   = double.MaxValue;
        private int     zzLowBar     = 0;
        private double  higherPt     = 0;
        private int     higherBar    = 0;
        private double  lowerPt      = double.MaxValue;
        private int     lowerBar     = 0;
        private double  lastHigh     = 0;
        private double  lastLow      = double.MaxValue;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name            = "Boof23";
                Description     = "Boof 23 – SR Cluster + ZigZag Regime Filter";
                Calculate       = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling   = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                TpPoints        = 4.0;
                SlPoints        = 2.0;
                CoreQty         = 2;
                ExpandedQty     = 1;
                UseEngulfFilter = false;
            }
            else if (State == State.DataLoaded)
            {
                atrInd = ATR(AtrLen);
                lastHigh = High[0];
                lastLow  = Low[0];
                higherPt = High[0];
                lowerPt  = Low[0];
            }
        }

        protected override void OnBarUpdate()
        {
            int minBars = VolLen + AtrLen + FractalBars * 2 + 5;
            if (CurrentBar < minBars) return;

            // ── Update ZigZag state machine ──────────────────
            UpdateZigZag();

            double currentATR = atrInd[0];
            if (currentATR == 0) return;

            if (zzTrend == ZzTrend.None) return;

            // Rebuild clusters on each bar
            RebuildClusters();

            // Scan lookback bars for fractal signal
            for (int offset = FractalBars + 2; offset <= FractalBars + 2 + MaxLookback; offset++)
            {
                int idx = offset; // bars ago

                if (CurrentBar - idx < FractalBars + VolLen) break;

                double vol   = Volume[idx];
                double rvol  = ComputeRvol(idx);
                double atrAt = atrInd[idx];

                if (rvol < RvolMin)  continue;
                if (atrAt == 0)      continue;
                if (vol == 0)        continue;

                // ZigZag must be established at this bar (use current state as proxy)
                if (zzTrend == ZzTrend.None) continue;

                double barClose = Close[idx];
                double barHigh  = High[idx];
                double barLow   = Low[idx];
                double barOpen  = Open[idx];

                // SR cluster proximity
                double clusterDist, clusterPrice;
                int    clusterStrength;
                if (!NearestCluster(barClose, atrAt, out clusterDist, out clusterPrice, out clusterStrength)) continue;
                if (clusterDist > SrDistMax) continue;

                // Fractal detection
                bool fractalPeak   = true;
                bool fractalTrough = true;
                for (int j = 1; j <= FractalBars; j++)
                {
                    if (High[idx] <= High[idx + j]) fractalPeak   = false;
                    if (High[idx] <= High[idx - j]) fractalPeak   = false;
                    if (Low[idx]  >= Low[idx + j])  fractalTrough = false;
                    if (Low[idx]  >= Low[idx - j])  fractalTrough = false;
                }

                double peakSlack   = atrAt > 0 ? (barHigh - barClose) / atrAt : 0;
                double troughSlack = atrAt > 0 ? (barClose - barLow)  / atrAt : 0;

                // ── SHORT signal: fractal peak + ZZ uptrend near ZZ high swing ──
                if (fractalPeak && peakSlack >= AtrMult && zzTrend == ZzTrend.Up)
                {
                    int distFromSwing = Math.Abs((CurrentBar - idx) - (CurrentBar - zzHighBar));
                    if (distFromSwing <= ZzProxBars)
                    {
                        bool engulfOk = !UseEngulfFilter || barClose < barOpen;
                        if (engulfOk)
                        {
                            int qty = peakSlack >= 0.8 ? CoreQty : ExpandedQty;
                            EnterShort(qty, "B23Short");
                            SetStopLoss("B23Short",    CalculationMode.Ticks, SlPoints / TickSize, false);
                            SetProfitTarget("B23Short", CalculationMode.Ticks, TpPoints / TickSize);
                            return;
                        }
                    }
                }

                // ── LONG signal: fractal trough + ZZ downtrend near ZZ low swing ──
                if (fractalTrough && troughSlack >= AtrMult && zzTrend == ZzTrend.Down)
                {
                    int distFromSwing = Math.Abs((CurrentBar - idx) - (CurrentBar - zzLowBar));
                    if (distFromSwing <= ZzProxBars)
                    {
                        bool engulfOk = !UseEngulfFilter || barClose > barOpen;
                        if (engulfOk)
                        {
                            int qty = troughSlack >= 0.8 ? CoreQty : ExpandedQty;
                            EnterLong(qty, "B23Long");
                            SetStopLoss("B23Long",    CalculationMode.Ticks, SlPoints / TickSize, false);
                            SetProfitTarget("B23Long",  CalculationMode.Ticks, TpPoints / TickSize);
                            return;
                        }
                    }
                }
            }
        }

        // ── ZigZag State Machine ─────────────────────────────
        // Ported from boof23.ts buildZigZag()
        private void UpdateZigZag()
        {
            double h = High[0];
            double l = Low[0];
            double c = Close[0];
            double o = Open[0];

            if (h > higherPt) { higherPt = h; higherBar = CurrentBar; }
            if (l < lowerPt)  { lowerPt  = l; lowerBar  = CurrentBar; }

            if (c > lastHigh || o > lastHigh)
            {
                if (zzTrend == ZzTrend.Down)
                {
                    zzLowPrice = lowerPt;  zzLowBar  = lowerBar;
                    higherPt   = h;        higherBar = CurrentBar;
                }
                zzTrend  = ZzTrend.Up;
                lastHigh = h; lastLow = l;
            }
            else if (c < lastLow || o < lastLow)
            {
                if (zzTrend == ZzTrend.Up)
                {
                    zzHighPrice = higherPt; zzHighBar = higherBar;
                    lowerPt     = l;        lowerBar  = CurrentBar;
                }
                zzTrend  = ZzTrend.Down;
                lastHigh = h; lastLow = l;
            }
        }

        // ── Helpers ──────────────────────────────────────────

        private void RebuildClusters()
        {
            clusters.Clear();
            double atrSum = 0; int atrCnt = 0;
            for (int k = 0; k <= Math.Min(CurrentBar, 200); k++)
            {
                double a = atrInd[k];
                if (a > 0) { atrSum += a; atrCnt++; }
            }
            double avgATR = atrCnt > 0 ? atrSum / atrCnt : 0;
            if (avgATR == 0) return;

            double mergeTol = avgATR * ClusterMerge;
            double[] volSMA = ComputeVolSMA();

            for (int i = VolLen; i <= CurrentBar; i++)
            {
                int barsAgo = CurrentBar - i;
                double vol = Volume[barsAgo];
                if (vol < volSMA[i] * VolMult) continue;
                double price = (High[barsAgo] + Low[barsAgo]) / 2.0;
                bool merged = false;
                for (int b = 0; b < clusters.Count; b++)
                {
                    if (Math.Abs(clusters[b].Price - price) <= mergeTol)
                    {
                        var cl = clusters[b];
                        cl.Price = (cl.Price * cl.Strength + price) / (cl.Strength + 1);
                        cl.Strength++;
                        clusters[b] = cl;
                        merged = true;
                        break;
                    }
                }
                if (!merged) clusters.Add(new Cluster { Price = price, Strength = 1 });
            }
            clusters.RemoveAll(c => c.Strength < SrStrengthMin);
        }

        private double[] ComputeVolSMA()
        {
            double[] sma = new double[CurrentBar + 1];
            for (int i = VolLen; i <= CurrentBar; i++)
            {
                double sum = 0;
                for (int j = 0; j < VolLen; j++) sum += Volume[CurrentBar - (i - j)];
                sma[i] = sum / VolLen;
            }
            return sma;
        }

        private double ComputeRvol(int barsAgo)
        {
            if (CurrentBar < VolLen) return 0;
            double sum = 0;
            for (int j = barsAgo; j < barsAgo + VolLen; j++) sum += Volume[j];
            double avg = sum / VolLen;
            return avg > 0 ? Volume[barsAgo] / avg : 0;
        }

        private bool NearestCluster(double price, double atr, out double dist, out double clusterPrice, out int strength)
        {
            dist = double.MaxValue; clusterPrice = 0; strength = 0;
            if (clusters.Count == 0 || atr == 0) return false;
            foreach (var c in clusters)
            {
                double d = Math.Abs(price - c.Price) / atr;
                if (d < dist) { dist = d; clusterPrice = c.Price; strength = c.Strength; }
            }
            return true;
        }

    }
}
