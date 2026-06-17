// =========================================================
// BOOF 23.5 — NinjaTrader 8 Strategy
// SR Cluster + ZigZag Regime + Engulf + ADX Chop Detection
// ADX < 15: Chop mode — RSI2 mean reversion + tighter TP/SL
// ADX >= 15: Trend mode — falls back to Boof 23.0 logic
// Layer 1: ZigZag state machine (trend mode only)
// Layer 2: SR cluster fractal entry gated by ZigZag regime
// Layer 3: Engulf confirmation (default off)
// =========================================================
#region Using declarations
using System;
using System.Collections.Generic;
using NinjaTrader.Cbi;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
using NinjaTrader.NinjaScript.Indicators;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class Boof23_5 : Strategy
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
        
        // ── CHOP MODE CONFIG ───────────────────────────────
        private int    AdxLen           = 14;
        private double AdxChopTh       = 15.0;
        private int    Rsi2Len          = 2;
        private double Rsi2Oversold   = 10;
        private double Rsi2Overbought = 90;
        private double ChopTpPct      = 0.30;
        private double ChopSlPct      = 0.10;

        // ── PARAMETERS (editable in NT UI) ───────────────────
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
        private ADX adxInd;
        private RSI rsi2Ind;

        // ── CLUSTER STORAGE ─────────────────────────────────
        private struct Cluster { public double Price; public int Strength; }
        private List<Cluster> clusters = new List<Cluster>();
        private int lastClusterBuild = -1;

        // ── ZIGZAG STATE ────────────────────────────────────
        private string   zzTrend      = "";
        private double   zzLastHigh;
        private double   zzLastLow;
        private double   zzHigherPt;  private int zzHigherBar;
        private double   zzLowerPt;   private int zzLowerBar;
        private double   zzHighPrice; private int zzHighBar;
        private double   zzLowPrice;  private int zzLowBar;
        private bool     zzInitialized = false;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "Boof 23.5 — ZigZag + ADX Chop Detection";
                Name        = "Boof23_5";
                Calculate   = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling       = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                
                TpPoints       = 35;
                SlPoints       = 15;
                CoreQty        = 2;
                ExpandedQty    = 1;
                UseEngulfFilter = false;
            }
            else if (State == State.Configure)
            {
                atrInd  = ATR(AtrLen);
                adxInd  = ADX(AdxLen);
                rsi2Ind = RSI(Rsi2Len, 1);
            }
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBar < VolLen + AtrLen + FractalBars * 2 + 5)
                return;

            double currentATR = atrInd[0];
            double adxVal = adxInd[0];
            double rsi2Val = rsi2Ind[0];
            if (currentATR == 0 || double.IsNaN(adxVal) || double.IsNaN(rsi2Val))
                return;

            bool isChop = adxVal < AdxChopTh;

            if (isChop)
            {
                // ── CHOP MODE: Mean Reversion (RSI2 only) ───────
                double spot = Close[0];
                
                if (rsi2Val < Rsi2Oversold)
                {
                    if (Position.MarketPosition != MarketPosition.Long)
                    {
                        EnterLong(CoreQty, "B23.5-CHOP-LONG");
                        SetStopLoss("B23.5-CHOP-LONG", CalculationMode.Percent, ChopSlPct, false);
                        SetProfitTarget("B23.5-CHOP-LONG", CalculationMode.Percent, ChopTpPct);
                        Print($"[B23.5 CHOP] LONG @ {spot:F2} | RSI2={rsi2Val:F1} | ADX={adxVal:F1}");
                    }
                    return;
                }
                
                if (rsi2Val > Rsi2Overbought)
                {
                    if (Position.MarketPosition != MarketPosition.Short)
                    {
                        EnterShort(CoreQty, "B23.5-CHOP-SHORT");
                        SetStopLoss("B23.5-CHOP-SHORT", CalculationMode.Percent, ChopSlPct, false);
                        SetProfitTarget("B23.5-CHOP-SHORT", CalculationMode.Percent, ChopTpPct);
                        Print($"[B23.5 CHOP] SHORT @ {spot:F2} | RSI2={rsi2Val:F1} | ADX={adxVal:F1}");
                    }
                    return;
                }
            }
            else
            {
                // ── TREND MODE: Boof 23.0 logic ─────────────────
                UpdateZigZag();
                
                if (CurrentBar != lastClusterBuild)
                {
                    BuildClusters();
                    lastClusterBuild = CurrentBar;
                }

                if (clusters.Count == 0) return;
                if (zzTrend == "")       return;

                double sessionVolAvg = AvgVolume(VolLen);

                for (int offset = FractalBars + 2; offset <= FractalBars + 2 + MaxLookback; offset++)
                {
                    int idx = offset;
                    if (CurrentBar - idx < FractalBars + VolLen) break;

                    double barATR  = atrInd[idx];
                    double barVol  = Volume[idx];
                    double barRvol = sessionVolAvg > 0 ? barVol / sessionVolAvg : 0;

                    if (barRvol < RvolMin) continue;
                    if (barATR  == 0)      continue;

                    double barClose = Close[idx];
                    double dist = NearestClusterDist(barClose, barATR, out Cluster nearest);
                    if (dist > SrDistMax) continue;

                    bool fractalPeak = true, fractalTrough = true;
                    for (int j = 1; j <= FractalBars; j++)
                    {
                        if (High[idx] <= High[idx + j]) fractalPeak   = false;
                        if (High[idx] <= High[idx - j]) fractalPeak   = false;
                        if (Low[idx]  >= Low[idx + j])  fractalTrough = false;
                        if (Low[idx]  >= Low[idx - j])  fractalTrough = false;
                    }

                    double peakSlack   = barATR > 0 ? (High[idx]  - barClose) / barATR : 0;
                    double troughSlack = barATR > 0 ? (barClose - Low[idx])   / barATR : 0;

                    int absFractalBar = CurrentBar - idx;
                    int distFromHigh  = Math.Abs(absFractalBar - zzHighBar);
                    int distFromLow   = Math.Abs(absFractalBar - zzLowBar);

                    int qty = (peakSlack >= 0.8 || troughSlack >= 0.8) ? CoreQty : ExpandedQty;

                    // SHORT: fractal peak + ZZ trend up + near ZZ high
                    if (fractalPeak && zzTrend == "up" && distFromHigh <= ZzProxBars && peakSlack >= AtrMult)
                    {
                        bool engulfOK = !UseEngulfFilter || barClose < Open[idx];
                        if (!engulfOK) continue;
                        
                        if (Position.MarketPosition != MarketPosition.Short)
                        {
                            EnterShort(qty, "B23.5-TREND-SHORT");
                            SetStopLoss("B23.5-TREND-SHORT", CalculationMode.Ticks, SlPoints / TickSize, false);
                            SetProfitTarget("B23.5-TREND-SHORT", CalculationMode.Ticks, TpPoints / TickSize);
                            Print($"[B23.5 TREND] SHORT @ {Close[0]:F2} | ZZ={zzTrend} | ADX={adxVal:F1} | slack={peakSlack:F2}");
                        }
                        return;
                    }

                    // LONG: fractal trough + ZZ trend down + near ZZ low
                    if (fractalTrough && zzTrend == "down" && distFromLow <= ZzProxBars && troughSlack >= AtrMult)
                    {
                        bool engulfOK = !UseEngulfFilter || barClose > Open[idx];
                        if (!engulfOK) continue;
                        
                        if (Position.MarketPosition != MarketPosition.Long)
                        {
                            EnterLong(qty, "B23.5-TREND-LONG");
                            SetStopLoss("B23.5-TREND-LONG", CalculationMode.Ticks, SlPoints / TickSize, false);
                            SetProfitTarget("B23.5-TREND-LONG", CalculationMode.Ticks, TpPoints / TickSize);
                            Print($"[B23.5 TREND] LONG @ {Close[0]:F2} | ZZ={zzTrend} | ADX={adxVal:F1} | slack={troughSlack:F2}");
                        }
                        return;
                    }
                }
            }
        }

        // ── ZigZag State Machine ─────────────────────────────────────────
        private void UpdateZigZag()
        {
            if (!zzInitialized)
            {
                zzLastHigh = High[0];
                zzLastLow  = Low[0];
                zzHigherPt = High[0]; zzHigherBar = CurrentBar;
                zzLowerPt  = Low[0];  zzLowerBar  = CurrentBar;
                zzHighPrice = High[0]; zzHighBar = CurrentBar;
                zzLowPrice  = Low[0];  zzLowBar  = CurrentBar;
                zzInitialized = true;
                return;
            }

            if (High[0] > zzHigherPt) { zzHigherPt = High[0]; zzHigherBar = CurrentBar; }
            if (Low[0]  < zzLowerPt)  { zzLowerPt  = Low[0];  zzLowerBar  = CurrentBar; }

            if (Close[0] > zzLastHigh || Open[0] > zzLastHigh)
            {
                if (zzTrend == "down")
                {
                    zzLowPrice = zzLowerPt;
                    zzLowBar   = zzLowerBar;
                    zzHigherPt = High[0];
                    zzHigherBar = CurrentBar;
                }
                zzTrend    = "up";
                zzLastHigh = High[0];
                zzLastLow  = Low[0];
            }
            else if (Close[0] < zzLastLow || Open[0] < zzLastLow)
            {
                if (zzTrend == "up")
                {
                    zzHighPrice = zzHigherPt;
                    zzHighBar   = zzHigherBar;
                    zzLowerPt   = Low[0];
                    zzLowerBar  = CurrentBar;
                }
                zzTrend    = "down";
                zzLastHigh = High[0];
                zzLastLow  = Low[0];
            }
        }

        // ── Build volume-based SR clusters ───────────────────────────────
        private void BuildClusters()
        {
            clusters.Clear();
            if (CurrentBar < VolLen) return;

            double atrNow = atrInd[0];
            double mergeGap = atrNow * ClusterMerge;

            for (int i = VolLen; i < Math.Min(CurrentBar, VolLen + 200); i++)
            {
                double volAvg = AvgVolume(VolLen);
                if (Volume[i] > volAvg * VolMult)
                {
                    double price = Close[i];
                    bool merged = false;
                    for (int c = 0; c < clusters.Count; c++)
                    {
                        if (Math.Abs(price - clusters[c].Price) <= mergeGap)
                        {
                            var cl = clusters[c];
                            cl.Price = (cl.Price * cl.Strength + price) / (cl.Strength + 1);
                            cl.Strength++;
                            clusters[c] = cl;
                            merged = true;
                            break;
                        }
                    }
                    if (!merged)
                        clusters.Add(new Cluster { Price = price, Strength = 1 });
                }
            }
            clusters.RemoveAll(c => c.Strength < SrStrengthMin);
        }

        private double NearestClusterDist(double price, double atr, out Cluster nearest)
        {
            nearest = default;
            if (clusters.Count == 0 || atr == 0) return double.MaxValue;
            double bestDist = double.MaxValue;
            nearest = clusters[0];
            foreach (Cluster c in clusters)
            {
                double d = Math.Abs(c.Price - price) / atr;
                if (d < bestDist) { bestDist = d; nearest = c; }
            }
            return bestDist;
        }

        private double AvgVolume(int period)
        {
            if (CurrentBar < period) return 0;
            double sum = 0;
            for (int i = 0; i < period; i++) sum += Volume[i];
            return sum / period;
        }
    }
}
