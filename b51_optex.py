"""
BOOF52 Options Exit Study
Exit based on OPTION P&L % not underlying move
Reprices option at every bar using BS, exits when option hits TP% or SL%
Exit A: TP+20% / SL-10%
Exit B: TP+30% / SL-15%
Exit C: TP+40% / SL-20%
Time stop: 60 bars
"""
import pandas as pd
import numpy as np
import pytz
from scipy.stats import norm

ET = pytz.timezone("America/New_York")

EXITS = [
    {"label": "A  TP+20/SL-10", "tp": 0.20, "sl": -0.10},
    {"label": "B  TP+30/SL-15", "tp": 0.30, "sl": -0.15},
    {"label": "C  TP+40/SL-20", "tp": 0.40, "sl": -0.20},
]
TIME_STOP  = 60
IV_ENTRY   = 0.25
IV_EXIT    = 0.22   # slight crush as day goes on
R          = 0.05
BARS_IN_DAY= 390


def load_rt(sym):
    df = pd.read_csv(f"boof51_{sym}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df["date"] = df["time"].dt.date
    return df

def load_pm(sym):
    df = pd.read_csv(f"boof51_{sym}_pm.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    return df

def build_pm_stats(pm_df, rt_df):
    pm_df = pm_df.copy(); pm_df["date"] = pm_df["time"].dt.date
    dc = rt_df.groupby("date")["close"].last().reset_index()
    dc.columns = ["date","prev_close"]; dc["date"] = pd.to_datetime(dc["date"])
    dc["next_date"] = dc["date"] + pd.Timedelta(days=1)
    records = [{"date":pd.Timestamp(d),"pm_high":g["high"].max(),"pm_low":g["low"].min()}
               for d,g in pm_df.groupby("date")]
    stats = pd.DataFrame(records)
    stats = stats.merge(dc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),on="date",how="left")
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M")=="09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index(); rth.columns=["date","rth_open"]
    stats = stats.merge(rth,on="date",how="left")
    stats["gap_pct"]  = (stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    stats["open_pos"] = (stats["rth_open"]-stats["pm_low"])/(stats["pm_high"]-stats["pm_low"])
    return stats.dropna(subset=["gap_pct"])

def add_vwap(df):
    df = df.copy().reset_index(drop=True)
    df["typ"]=(df["high"]+df["low"]+df["close"])/3; df["pv"]=df["typ"]*df["volume"]
    df["cpv"]=df.groupby("date")["pv"].cumsum(); df["cvol"]=df.groupby("date")["volume"].cumsum()
    df["vwap"]=df["cpv"]/df["cvol"]
    return df

def collect_and_dedupe(df, pm_stats):
    pm = pm_stats.set_index("date"); raw = []
    for date, ddf in df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        if pd.isna(day.get("open_pos")) or pd.isna(day["gap_pct"]): continue
        op=day["open_pos"]; gap=day["gap_pct"]
        pmh=day["pm_high"]; pml=day["pm_low"]; rth_open=day["rth_open"]
        ddf=ddf.reset_index(drop=True)
        rth=ddf[ddf["time"].dt.strftime("%H:%M")>="09:30"].reset_index(drop=True)
        if len(rth)<62: continue
        c1l=op>0.60 and gap>0; c1s=op<0.40 and gap<0
        c2l=rth_open<pml or op<0.15; c2s=rth_open>pmh or op>0.85
        for j in range(len(rth)-61):
            row=rth.iloc[j]; t=row["time"].strftime("%H:%M")
            if t>="12:00": break
            green=row["close"]>row["open"]; red=row["close"]<row["open"]
            for side,flag,c1,c2 in [("long",green,c1l,c2l),("short",red,c1s,c2s)]:
                if flag and (c1 or c2):
                    ei=j+1; ep=rth.iloc[ei]["open"]
                    fi=ddf.index[ddf["time"]==rth.iloc[ei]["time"]].tolist()
                    if fi:
                        s="C1" if (c1 and not c2) else ("C2" if not c1 else "C1+C2")
                        raw.append({"date":str(date),"side":side,"setup":s,
                                    "entry_time":rth.iloc[j]["time"],"bar_idx":fi[0],"ep":ep})
    rdf = pd.DataFrame(raw) if raw else pd.DataFrame()
    if rdf.empty: return rdf
    out=[]
    for date,grp in rdf.groupby("date"):
        for side in ["long","short"]:
            s=grp[grp["side"]==side].sort_values("entry_time").reset_index(drop=True)
            count=0; last_time=None
            for _,row in s.iterrows():
                if count>=2: break
                if last_time and (row["entry_time"]-last_time).total_seconds()/60<10: continue
                out.append(row); count+=1; last_time=row["entry_time"]
    return pd.DataFrame(out).reset_index(drop=True)


def bs_price(S, K, T, r, sigma, opt):
    if T <= 1e-7: return max(0.0, S-K) if opt=="call" else max(0.0, K-S)
    d1=(np.log(S/K)+(r+0.5*sigma**2)*T)/(sigma*np.sqrt(T)); d2=d1-sigma*np.sqrt(T)
    return (S*norm.cdf(d1)-K*np.exp(-r*T)*norm.cdf(d2)) if opt=="call" \
      else (K*np.exp(-r*T)*norm.cdf(-d2)-S*norm.cdf(-d1))


def sim_option_exit(ddf, ei, ep, side, tp_pct, sl_pct, dte=0):
    """Price option at every bar, exit when option P&L hits TP or SL."""
    n   = len(ddf)
    opt = "call" if side == "long" else "put"
    K   = round(ep)

    # Time remaining at entry
    T_entry = max((dte + (BARS_IN_DAY - ei) / BARS_IN_DAY) / 252, 1/(252*BARS_IN_DAY))
    p_entry = bs_price(ep, K, T_entry, R, IV_ENTRY, opt)
    if p_entry < 0.01:
        return {"et":"skip","pnl_pct":0,"pnl_dollar":0,"bars_held":0,"p_entry":p_entry,"xp":ep}

    tp_price = p_entry * (1 + tp_pct)
    sl_price = p_entry * (1 + sl_pct)   # sl_pct is negative

    et = "time"; xp = ddf["close"].values[min(ei+TIME_STOP, n-1)]
    bars_held = TIME_STOP

    for j in range(ei, min(ei + TIME_STOP, n)):
        bars_elapsed = j - ei
        T_now = max(T_entry - bars_elapsed/(252*BARS_IN_DAY), 1/(252*BARS_IN_DAY))

        # Use high and low to check intrabar hits
        S_high = ddf["high"].values[j]
        S_low  = ddf["low"].values[j]
        S_close= ddf["close"].values[j]

        # Price at high and low of bar
        p_high = bs_price(S_high if side=="long" else S_low,  K, T_now, R, IV_EXIT, opt)
        p_low  = bs_price(S_low  if side=="long" else S_high, K, T_now, R, IV_EXIT, opt)
        p_close= bs_price(S_close, K, T_now, R, IV_EXIT, opt)

        # Check TP first (favorable direction)
        if p_high >= tp_price:
            et = "tp"; xp = S_high; bars_held = bars_elapsed; break
        # Then SL
        if p_low <= sl_price:
            et = "sl"; xp = S_low; bars_held = bars_elapsed; break

    # Final option price at exit
    T_exit = max(T_entry - bars_held/(252*BARS_IN_DAY), 1/(252*BARS_IN_DAY))
    p_exit = bs_price(xp, K, T_exit, R, IV_EXIT, opt)
    if et == "tp": p_exit = tp_price
    if et == "sl": p_exit = sl_price

    pnl_pct    = (p_exit - p_entry) / p_entry * 100
    pnl_dollar = (p_exit - p_entry) * 100

    return {"et":et, "pnl_pct":round(pnl_pct,2), "pnl_dollar":round(pnl_dollar,2),
            "bars_held":bars_held, "p_entry":round(p_entry,3), "p_exit":round(p_exit,3),
            "xp":round(xp,2)}


def run_all(rt_df, signals_df):
    rt_df = rt_df.copy(); rt_df["date"] = pd.to_datetime(rt_df["date"])
    day_map = {date:ddf.reset_index(drop=True) for date,ddf in rt_df.groupby("date")}

    results = {ex["label"]: [] for ex in EXITS}

    for _, sig in signals_df.iterrows():
        date_ts = pd.Timestamp(sig["date"])
        if date_ts not in day_map: continue
        ddf = day_map[date_ts]; ei = int(sig["bar_idx"]); ep = sig["ep"]
        if ei+1 >= len(ddf): continue

        for ex in EXITS:
            r = sim_option_exit(ddf, ei, ep, sig["side"], ex["tp"], ex["sl"], dte=0)
            if r["et"] == "skip": continue
            results[ex["label"]].append({
                "date": sig["date"], "side": sig["side"], "setup": sig["setup"],
                **r
            })

    return results


def report(results):
    W = 82
    print(f"\n{'='*W}")
    print(f"  0DTE Options | Exit on Option P&L % | C1+C2 Loose | IV entry=25% exit=22%")
    print(f"{'='*W}")
    print(f"  {'Exit Config':<18} {'Side':<7} {'N':>5}  {'WR%':>6}  "
          f"{'AvgPnL%':>8} {'AvgPnL$':>8} {'Total$':>8}  "
          f"{'AvgBars':>8} {'Best$':>7} {'Worst$':>7}")
    print(f"  {'-'*78}")

    for label, trades in results.items():
        if not trades: continue
        df = pd.DataFrame(trades)
        for side in ["long","short","all"]:
            s = df if side=="all" else df[df["side"]==side]
            if s.empty: continue
            slbl = side.upper() if side!="all" else "BOTH"
            wr   = (s["pnl_dollar"]>0).mean()*100
            ap   = s["pnl_pct"].mean(); ad = s["pnl_dollar"].mean()
            tot  = s["pnl_dollar"].sum(); ab = s["bars_held"].mean()
            best = s["pnl_dollar"].max(); worst = s["pnl_dollar"].min()
            print(f"  {label:<18} {slbl:<7} {len(s):>5}  {wr:>6.1f}%  "
                  f"{ap:>+7.1f}% {ad:>+8.2f} {tot:>+8.0f}  "
                  f"{ab:>8.1f} {best:>+7.0f} {worst:>+7.0f}")

        # Exit type breakdown
        df2 = pd.DataFrame(trades)
        tp_n  = (df2["et"]=="tp").sum()
        sl_n  = (df2["et"]=="sl").sum()
        ti_n  = (df2["et"]=="time").sum()
        tp_avg= df2[df2["et"]=="tp"]["pnl_dollar"].mean() if tp_n else 0
        sl_avg= df2[df2["et"]=="sl"]["pnl_dollar"].mean() if sl_n else 0
        ti_avg= df2[df2["et"]=="time"]["pnl_dollar"].mean() if ti_n else 0
        tp_bar= df2[df2["et"]=="tp"]["bars_held"].mean() if tp_n else 0
        sl_bar= df2[df2["et"]=="sl"]["bars_held"].mean() if sl_n else 0
        ti_bar= df2[df2["et"]=="time"]["bars_held"].mean() if ti_n else 0
        print(f"  {'':18} TP={tp_n}({tp_avg:+.0f}$ avg, {tp_bar:.0f}m)  "
              f"SL={sl_n}({sl_avg:+.0f}$ avg, {sl_bar:.0f}m)  "
              f"Time={ti_n}({ti_avg:+.0f}$ avg, {ti_bar:.0f}m)")
        print(f"  {'-'*78}")

    # Side-by-side EV summary
    print(f"\n  SUMMARY — Avg PnL$ per trade")
    print(f"  {'Exit':<18} {'LONG':>10} {'SHORT':>10} {'BOTH':>10} {'Total 6m':>12}")
    print(f"  {'-'*55}")
    for label, trades in results.items():
        if not trades: continue
        df = pd.DataFrame(trades)
        lv = df[df["side"]=="long"]["pnl_dollar"].mean()
        sv = df[df["side"]=="short"]["pnl_dollar"].mean()
        bv = df["pnl_dollar"].mean()
        tv = df["pnl_dollar"].sum()
        print(f"  {label:<18} {lv:>+10.2f} {sv:>+10.2f} {bv:>+10.2f} {tv:>+12.0f}")


if __name__ == "__main__":
    print("Loading QQQ...", flush=True)
    rt_df    = load_rt("QQQ"); rt_df = add_vwap(rt_df)
    pm_df    = load_pm("QQQ")
    pm_stats = build_pm_stats(pm_df, rt_df)
    signals  = collect_and_dedupe(rt_df, pm_stats)
    print(f"  {len(signals)} signals", flush=True)

    print("Simulating option exits...", flush=True)
    results = run_all(rt_df, signals)
    report(results)
