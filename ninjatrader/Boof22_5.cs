// =========================================================
// BOOF 22.5 — NinjaTrader 8 Strategy
// Volume Cluster Array + ATR Fractal Reversal + ADX Chop Detection
// ADX < 15: Chop mode — RSI2 mean reversion + tighter TP/SL
// ADX >= 15: Trend mode — falls back to Boof 22.0 logic
// Best on: TSLA, NVDA, COIN, PLTR, AMD, AAPL, AMZN, META, GOOGL
// Options: TP=35% SL=15% | Core (slack>=1.4) 2x size, Expanded 1x
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
    public class Boof22_5 : Strategy
    {
        // ── CONFIG ─────────────────────────────────────────
        private int    AtrLen         = 14;
        private int    VolLen         = 50;
        private double VolMult        = 1.3;
        private int    FractalBars    = 3;
        private double AtrMult        = 0.6;
        private double ClusterMerge   = 0.5;
        private int    SrStrengthMin  = 2;
        private double SrDistMax      = 1.0;
        private double RvolMin        = 0.8;
        private double SlackMax       = 0.8;
        private int    MaxLookback    = 10;
        
        // ── CHOP MODE CONFIG ──────────────────────────────
        private int    AdxLen           = 14;
        private double AdxChopTh       = 15.0;    // ADX < 15 = chop
        private int    Rsi2Len          = 2;
        private double Rsi2Oversold   = 10;      // Buy when RSI2 < 10
        private double Rsi2Overbought = 90;      // Sell when RSI2 > 90
        private double ChopTpPct      = 0.30;    // 30% TP in chop
        private double ChopSlPct      = 0.10;    // 10% SL in chop

        // ── PARAMETERS (editable in NT UI) ─────────────────
        [NinjaScriptProperty]
        public double TpPoints { get; set; }

        [NinjaScriptProperty]
        public double SlPoints { get; set; }

        [NinjaScriptProperty]
        public int CoreQty { get; set; }

        [NinjaScriptProperty]
        public int ExpandedQty { get; set; }

        // ── INDICATORS ─────────────────────────────────────
        private ATR atrInd;
        private ADX adxInd;
        private RSI rsi2Ind;

        // ── CLUSTER STORAGE ────────────────────────────────
        private struct Cluster { public double Price; public int Strength; }
        private List<Cluster> clusters = new List<Cluster>();
        private int lastClusterBuild = -1;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "Boof 22.5 — Cluster Fractal + ADX Chop Detection";
                Name        = "Boof22_5";
                Calculate   = Calculate.OnBarClose;
                EntriesPerDirection = 1;
                EntryHandling       = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;
                
                TpPoints     = 35;
                SlPoints     = 15;
                CoreQty      = 2;
                ExpandedQty  = 1;
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
                
                // Buy: RSI2 < 10 (oversold bounce)
                if (rsi2Val < Rsi2Oversold)
                {
                    if (Position.MarketPosition != MarketPosition.Long)
                    {
                        EnterLong(CoreQty, "B22.5-CHOP-LONG");
                        SetStopLoss("B22.5-CHOP-LONG", CalculationMode.Percent, ChopSlPct, false);
                        SetProfitTarget("B22.5-CHOP-LONG", CalculationMode.Percent, ChopTpPct);
                        Print($"[B22.5 CHOP] LONG @ {spot:F2} | RSI2={rsi2Val:F1} | ADX={adxVal:F1}");
                    }
                    return;
                }
                
                // Sell: RSI2 > 90 (overbought fade)
                if (rsi2Val > Rsi2Overbought)
                {
                    if (Position.MarketPosition != MarketPosition.Short)
                    {
                        EnterShort(CoreQty, "B22.5-CHOP-SHORT");
                        SetStopLoss("B22.5-CHOP-SHORT", CalculationMode.Percent, ChopSlPct, false);
                        SetProfitTarget("B22.5-CHOP-SHORT", CalculationMode.Percent, ChopTpPct);
                        Print($"[B22.5 CHOP] SHORT @ {spot:F2} | RSI2={rsi2Val:F1} | ADX={adxVal:F1}");
                    }
                    return;
                }
            }
            else
            {
                // ── TREND MODE: Boof 22.0 logic ─────────────────
                if (CurrentBar != lastClusterBuild)
                {
                    BuildClusters();
                    lastClusterBuild = CurrentBar;
                }

                if (clusters.Count == 0) return;

                double sessionVolAvg = AvgVolume(VolLen);

                for (int offset = FractalBars + 2; offset <= FractalBars + 2 + MaxLookback; offset++)
                {
                    int idx = offset;
                    if (CurrentBar - idx < FractalBars + VolLen) break;

                    double barATR  = atrInd[idx];
                    double barVol  = Volume[idx];
                    double barRvol = sessionVolAvg > 0 ? barVol / sessionVolAvg : 0;

                    if (barRvol < RvolMin)  continue;
                    if (barATR  == 0)       continue;

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
                    bool atrRejectedPeak  = barClose < High[idx] - barATR * AtrMult;
                    bool atrBouncedTrough = barClose > Low[idx]  + barATR * AtrMult;

                    int qty = (peakSlack >= 1.4 || troughSlack >= 1.4) ? CoreQty : ExpandedQty;

                    if (fractalPeak && atrRejectedPeak && peakSlack < SlackMax)
                    {
                        if (Position.MarketPosition != MarketPosition.Short)
                        {
                            EnterShort(qty, "B22.5-TREND-SHORT");
                            SetStopLoss("B22.5-TREND-SHORT", CalculationMode.Ticks, SlPoints / TickSize, false);
                            SetProfitTarget("B22.5-TREND-SHORT", CalculationMode.Ticks, TpPoints / TickSize);
                            Print($"[B22.5 TREND] SHORT @ {Close[0]:F2} | ADX={adxVal:F1} | cluster={nearest.Price:F2} | slack={peakSlack:F2}");
                        }
                        return;
                    }

                    if (fractalTrough && atrBouncedTrough && troughSlack < SlackMax)
                    {
                        if (Position.MarketPosition != MarketPosition.Long)
                        {
                            EnterLong(qty, "B22.5-TREND-LONG");
                            SetStopLoss("B22.5-TREND-LONG", CalculationMode.Ticks, SlPoints / TickSize, false);
                            SetProfitTarget("B22.5-TREND-LONG", CalculationMode.Ticks, TpPoints / TickSize);
                            Print($"[B22.5 TREND] LONG @ {Close[0]:F2} | ADX={adxVal:F1} | cluster={nearest.Price:F2} | slack={troughSlack:F2}");
                        }
                        return;
                    }
                }
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
