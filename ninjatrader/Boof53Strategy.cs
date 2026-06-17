// =========================================================
// BOOF53 Strategy — NinjaTrader 8
// Gap-up > 0.5% | Fresh 1st touch of level | Bounce >= 0.15%
// +1 bar confirmation entry | TP 0.50% | SL 0.25%
// Direction: SHORT ONLY
// Levels: Previous Day High (PDH) + Pre-Market High (PMH)
// =========================================================
#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
using NinjaTrader.NinjaScript.Indicators;
using NinjaTrader.Data;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class Boof53Strategy : Strategy
    {
        // -- PARAMETERS ----------------------------------------------------
        [NinjaScriptProperty]
        [Range(0.01, 5.0)]
        [Display(Name = "TP %", Order = 1, GroupName = "BOOF53")]
        public double TpPct { get; set; }

        [NinjaScriptProperty]
        [Range(0.01, 5.0)]
        [Display(Name = "SL %", Order = 2, GroupName = "BOOF53")]
        public double SlPct { get; set; }

        [NinjaScriptProperty]
        [Range(0.01, 5.0)]
        [Display(Name = "Gap Min %", Order = 3, GroupName = "BOOF53")]
        public double GapMinPct { get; set; }

        [NinjaScriptProperty]
        [Range(0.01, 2.0)]
        [Display(Name = "Bounce Min %", Order = 4, GroupName = "BOOF53")]
        public double BounceMinPct { get; set; }

        [NinjaScriptProperty]
        [Range(0.01, 2.0)]
        [Display(Name = "Near Level %", Order = 5, GroupName = "BOOF53")]
        public double NearPct { get; set; }

        [NinjaScriptProperty]
        [Range(1, 390)]
        [Display(Name = "Max Bars Held", Order = 6, GroupName = "BOOF53")]
        public int MaxBarsHeld { get; set; }

        [NinjaScriptProperty]
        [Range(1, 100)]
        [Display(Name = "Qty", Order = 7, GroupName = "BOOF53")]
        public int Qty { get; set; }

        // -- STATE ---------------------------------------------------------
        private double prevClose   = 0;
        private double prevDayHigh = 0;
        private double sessionHigh = 0;
        private double rthOpen     = 0;
        private double gapPct      = 0;
        private bool   gapOk       = false;
        private int    lastDay     = -1;

        private List<double>            levels       = new List<double>();
        private Dictionary<double,string> levelState = new Dictionary<double,string>();
        private Dictionary<double,double> levelHigh  = new Dictionary<double,double>();
        private Dictionary<double,bool>   levelUsed  = new Dictionary<double,bool>();

        private bool   pendingEntry = false;
        private int    barsHeld     = 0;
        private bool   inTrade      = false;
        private double entryPx      = 0;
        private double tpPx         = 0;
        private double slPx         = 0;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name         = "Boof53Strategy";
                Description  = "BOOF53 gap-up level touch short";
                Calculate    = Calculate.OnBarClose;
                IsOverlay    = true;
                TpPct        = 0.50;
                SlPct        = 0.25;
                GapMinPct    = 0.50;
                BounceMinPct = 0.15;
                NearPct      = 0.15;
                MaxBarsHeld  = 60;
                Qty          = 1;
            }
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBar < 5) return;

            var  now = Time[0];
            int  hh  = now.Hour;
            int  mm  = now.Minute;
            int  day = now.DayOfYear;

            // -- New day reset ---------------------------------------------
            if (day != lastDay)
            {
                lastDay     = day;
                gapOk       = false;
                rthOpen     = 0;
                sessionHigh = 0;
                levels.Clear();
                levelState.Clear();
                levelHigh.Clear();
                levelUsed.Clear();
                ResetTrade();
                // Capture prev close and PDH from yesterday's close bar
                prevClose   = Close[1];
                prevDayHigh = MAX(High, 390)[1];
            }

            // -- Pre-market: track session high ----------------------------
            if (hh < 9 || (hh == 9 && mm < 30))
            {
                if (High[0] > sessionHigh) sessionHigh = High[0];
                return;
            }

            // -- 9:30 first RTH bar: gap check + build levels --------------
            if (hh == 9 && mm == 30 && rthOpen == 0)
            {
                rthOpen = Open[0];
                if (prevClose > 0)
                {
                    gapPct = (rthOpen - prevClose) / prevClose * 100.0;
                    gapOk  = gapPct > GapMinPct;
                }

                if (gapOk)
                {
                    if (prevDayHigh > 0) AddLevel(prevDayHigh);
                    if (sessionHigh  > 0) AddLevel(sessionHigh);
                    Print(string.Format("BOOF53 {0}  gap={1:F2}%  PDH={2:F2}  PMH={3:F2}  levels={4}",
                        Instrument.MasterInstrument.Name, gapPct, prevDayHigh, sessionHigh, levels.Count));
                }
                else
                {
                    Print(string.Format("BOOF53 {0}  gap={1:F2}%  SKIP",
                        Instrument.MasterInstrument.Name, gapPct));
                }
            }

            if (!gapOk) return;

            // -- EOD force close 15:55 -------------------------------------
            if (hh == 15 && mm >= 55 && inTrade)
            {
                ExitShort(Qty, "EOD", "B53");
                ResetTrade();
                return;
            }

            bool noNewEntry = (hh >= 15);

            // -- Manage open position --------------------------------------
            if (inTrade)
            {
                barsHeld++;
                if (Low[0] <= tpPx)
                {
                    ExitShort(Qty, "TP", "B53");
                    ResetTrade();
                    return;
                }
                if (High[0] >= slPx)
                {
                    ExitShort(Qty, "SL", "B53");
                    ResetTrade();
                    return;
                }
                if (barsHeld >= MaxBarsHeld)
                {
                    ExitShort(Qty, "TIMEOUT", "B53");
                    ResetTrade();
                    return;
                }
                return;
            }

            // -- +1 bar entry ----------------------------------------------
            if (pendingEntry && !noNewEntry)
            {
                entryPx      = Open[0];
                tpPx         = entryPx * (1.0 - TpPct / 100.0);
                slPx         = entryPx * (1.0 + SlPct / 100.0);
                inTrade      = true;
                barsHeld     = 0;
                pendingEntry = false;

                EnterShort(Qty, "B53");
                SetProfitTarget("B53", CalculationMode.Price, tpPx);
                SetStopLoss("B53",     CalculationMode.Price, slPx, false);

                Print(string.Format("BOOF53 ENTRY  entry={0:F4}  TP={1:F4}  SL={2:F4}", entryPx, tpPx, slPx));
                return;
            }
            pendingEntry = false;

            if (noNewEntry) return;

            // -- Scan levels for signal ------------------------------------
            foreach (double lvl in levels)
            {
                if (levelUsed.ContainsKey(lvl) && levelUsed[lvl]) continue;

                string st       = levelState.ContainsKey(lvl) ? levelState[lvl] : "idle";
                double nearRange = lvl * NearPct / 100.0;
                bool   touching  = (Math.Abs(High[0] - lvl) <= nearRange) || (High[0] >= lvl && Low[0] <= lvl);

                if (st == "idle")
                {
                    if (touching)
                    {
                        levelState[lvl] = "touch";
                        levelHigh[lvl]  = High[0];
                    }
                }
                else if (st == "touch")
                {
                    if (High[0] > levelHigh[lvl]) levelHigh[lvl] = High[0];

                    double bounce = (levelHigh[lvl] - Close[0]) / levelHigh[lvl] * 100.0;
                    if (bounce >= BounceMinPct)
                    {
                        levelState[lvl] = "bounce";
                        levelUsed[lvl]  = true;
                        pendingEntry    = true;
                        Print(string.Format("BOOF53 SIGNAL  level={0:F4}  bounce={1:F2}%", lvl, bounce));
                        break;
                    }
                    // Price moved far above level — reset
                    if (Low[0] > lvl * (1.0 + NearPct * 2.0 / 100.0))
                        levelState[lvl] = "idle";
                }
            }
        }

        private void AddLevel(double price)
        {
            foreach (double e in levels)
                if (Math.Abs(e - price) / price < 0.001) return;
            levels.Add(price);
            levelState[price] = "idle";
            levelHigh[price]  = 0;
            levelUsed[price]  = false;
        }

        private void ResetTrade()
        {
            inTrade      = false;
            barsHeld     = 0;
            entryPx      = 0;
            tpPx         = 0;
            slPx         = 0;
            pendingEntry = false;
        }
    }
}
