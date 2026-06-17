// =========================================================
// BOOF54 Futures — NinjaTrader 8   (SHORTS ONLY)
// Globex High Reject — 09:30 to 09:44 window ONLY
// Target: N~59, WR~51%, PF~2.07  (NQ 1yr backtest)
//
// SETUP: Single data series, NQ 1-Min, 24hr ETH session
// =========================================================
#region Using declarations
using System;
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
    public class Boof54Futures : Strategy
    {
        [NinjaScriptProperty][Range(1,500)] [Display(Name="TP Points",  Order=1,GroupName="Exits")]  public double TpPoints  {get;set;}
        [NinjaScriptProperty][Range(1,200)] [Display(Name="SL Points",  Order=2,GroupName="Exits")]  public double SlPoints  {get;set;}
        [NinjaScriptProperty][Range(0.01,2)][Display(Name="Near %",     Order=3,GroupName="Params")] public double NearPct   {get;set;}
        [NinjaScriptProperty][Range(0.01,2)][Display(Name="Bounce %",   Order=4,GroupName="Params")] public double BouncePct {get;set;}
        [NinjaScriptProperty][Range(1,100)] [Display(Name="Qty",        Order=5,GroupName="Params")] public int    Qty       {get;set;}

        private double globexHigh = 0;
        private bool   ghBuilt   = false;
        private bool   touched   = false;
        private bool   used      = false;
        private double extreme   = 0;
        private bool   inTrade   = false;
        private double entryPx   = 0;
        private double tpPx      = 0;
        private double slPx      = 0;
        private bool   pending   = false;
        private int    lastDay   = -1;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name        = "Boof54Futures";
                Description = "BOOF54 Globex High Reject 09:30-09:44 shorts";
                Calculate   = Calculate.OnBarClose;
                IsOverlay   = true;
                // Use point-based exits via manual check — NOT SetProfitTarget
                EntriesPerDirection    = 1;
                EntryHandling          = EntryHandling.UniqueEntries;
                TpPoints  = 40; SlPoints = 20;
                NearPct   = 0.15; BouncePct = 0.10;
                Qty       = 1;
            }
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBar < 30) return;

            var  now  = Time[0];
            int  day  = now.DayOfYear;
            int  hhmm = now.Hour * 100 + now.Minute;

            // -- New day: scan back to build Globex high -------------------
            if (day != lastDay)
            {
                lastDay = day;
                ghBuilt = false; touched = false; used = false; extreme = 0;
                globexHigh = 0;
                ResetTrade();

                double gh = 0;
                for (int i = 1; i < Math.Min(CurrentBar, 960); i++)
                {
                    var  bt    = Time[i];
                    int  bh    = bt.Hour * 100 + bt.Minute;
                    bool isTodayPreMkt  = bt.DayOfYear == day   && bh < 930;
                    bool isYesterdayPM  = bt.DayOfYear == day-1 && bh >= 1800;
                    // also handle week boundary (Sunday night = DayOfYear differs by more)
                    bool isOvernightBar = isTodayPreMkt || isYesterdayPM ||
                                         (bt.DayOfYear < day && bh >= 1800);
                    if (isOvernightBar)
                    {
                        if (High[i] > gh) gh = High[i];
                    }
                    else if (bt.DayOfYear < day && bh >= 930 && bh < 1600)
                    {
                        break; // hit prior RTH — done
                    }
                }
                globexHigh = gh;
                ghBuilt    = gh > 0;
                Print(string.Format("DAY {0}  GlobexHigh={1:F2}", now.ToString("MM/dd"), globexHigh));
            }

            bool inWindow = hhmm >= 930 && hhmm <= 943;

            // -- EOD force close 15:55 -------------------------------------
            if (hhmm >= 1555 && inTrade)
            {
                ExitShort(Qty, "EOD", "B54");
                Print(string.Format("B54 EOD close  pnl~{0:F0}pts", entryPx - Close[0]));
                ResetTrade(); return;
            }

            // -- Manage open trade manually (avoid SetProfitTarget issues) -
            if (inTrade)
            {
                // Short: profit when price drops, loss when price rises
                if (Low[0]  <= tpPx)
                {
                    ExitShort(Qty, "TP", "B54");
                    Print(string.Format("B54 TP  +{0:F0}pts", TpPoints));
                    ResetTrade(); return;
                }
                if (High[0] >= slPx)
                {
                    ExitShort(Qty, "SL", "B54");
                    Print(string.Format("B54 SL  -{0:F0}pts", SlPoints));
                    ResetTrade(); return;
                }
                return;
            }

            // -- +1 bar pending entry --------------------------------------
            if (pending)
            {
                if (!used && inWindow)
                {
                    entryPx = Open[0];
                    tpPx    = entryPx - TpPoints;   // short TP = below entry
                    slPx    = entryPx + SlPoints;   // short SL = above entry
                    inTrade = true;
                    used    = true;
                    EnterShort(Qty, "B54");
                    Print(string.Format("B54 ENTER SHORT  @{0:F2}  TP={1:F2}(-{2})  SL={3:F2}(+{4})  [{5}]",
                        entryPx, tpPx, TpPoints, slPx, SlPoints, now.ToString("HH:mm")));
                }
                pending = false; return;
            }

            if (!inWindow || used || !ghBuilt) return;

            double near = globexHigh * NearPct / 100.0;

            // Touch detection
            if (!touched && High[0] >= globexHigh - near)
            {
                touched = true; extreme = High[0];
                Print(string.Format("B54 TOUCH  GH={0:F2}  [{1}]", globexHigh, now.ToString("HH:mm")));
            }

            if (touched)
            {
                if (High[0] > extreme) extreme = High[0];
                double bounce = (extreme - Close[0]) / extreme * 100.0;
                if (bounce >= BouncePct)
                {
                    pending = true;
                    Print(string.Format("B54 SIGNAL  GH={0:F2}  bounce={1:F2}%  [{2}]",
                        globexHigh, bounce, now.ToString("HH:mm")));
                    return;
                }
                // Reset if price escapes zone
                if (Low[0] > globexHigh + near * 2) touched = false;
            }
        }

        private void ResetTrade()
        {
            inTrade = false; entryPx = 0; tpPx = 0; slPx = 0; pending = false;
        }
    }
}
