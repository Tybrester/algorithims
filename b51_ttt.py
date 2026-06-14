"""BOOF52 Time-to-Target — how long does it take to hit each level"""
import pandas as pd
import pytz

ET = pytz.timezone("America/New_York")
TARGETS  = [0.0025, 0.0050, 0.0075, 0.0100]
T_LABELS = ["+0.25%", "+0.50%", "+0.75%", "+1.00%"]


def load_rt():
    df = pd.read_csv("boof51_QQQ_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df["date"] = df["time"].dt.date
    return df

def load_pm():
    df = pd.read_csv("boof51_QQQ_pm.csv")
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
    df["typ"] = (df["high"]+df["low"]+df["close"])/3
    df["pv"]  = df["typ"]*df["volume"]
    df["cpv"] = df.groupby("date")["pv"].cumsum()
    df["cvol"]= df.groupby("date")["volume"].cumsum()
    df["vwap"]= df["cpv"]/df["cvol"]
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
        c1_long=op>0.60 and gap>0; c1_short=op<0.40 and gap<0
        c2_long=rth_open<pml or op<0.15; c2_short=rth_open>pmh or op>0.85
        for j in range(len(rth)-61):
            row=rth.iloc[j]; t=row["time"].strftime("%H:%M")
            if t>="12:00": break
            green=row["close"]>row["open"]; red=row["close"]<row["open"]
            if (c1_long or c2_long) and green:
                ei=j+1; ep=rth.iloc[ei]["open"]
                fi=ddf.index[ddf["time"]==rth.iloc[ei]["time"]].tolist()
                if fi:
                    s="C1" if c1_long else "C2"
                    if c1_long and c2_long: s="C1+C2"
                    raw.append({"date":str(date),"side":"long","setup":s,
                                "entry_time":rth.iloc[j]["time"],"bar_idx":fi[0],"ep":ep})
            if (c1_short or c2_short) and red:
                ei=j+1; ep=rth.iloc[ei]["open"]
                fi=ddf.index[ddf["time"]==rth.iloc[ei]["time"]].tolist()
                if fi:
                    s="C1" if c1_short else "C2"
                    if c1_short and c2_short: s="C1+C2"
                    raw.append({"date":str(date),"side":"short","setup":s,
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
                if last_time is not None and (row["entry_time"]-last_time).total_seconds()/60<10: continue
                out.append(row); count+=1; last_time=row["entry_time"]
    return pd.DataFrame(out).reset_index(drop=True) if out else pd.DataFrame()


def time_to_target(df, signals_df):
    df=df.copy(); df["date"]=pd.to_datetime(df["date"])
    day_map={date:ddf.reset_index(drop=True) for date,ddf in df.groupby("date")}
    results=[]
    for _,sig in signals_df.iterrows():
        date_ts=pd.Timestamp(sig["date"])
        if date_ts not in day_map: continue
        ddf=day_map[date_ts]; ei=int(sig["bar_idx"]); ep=sig["ep"]; side=sig["side"]
        H=ddf["high"].values; L=ddf["low"].values; n=len(ddf)
        row={"date":sig["date"],"side":side,"setup":sig["setup"],"ep":ep}
        for tgt,lbl in zip(TARGETS, T_LABELS):
            tp_p=ep*(1+tgt) if side=="long" else ep*(1-tgt)
            hit_bar=None
            for j in range(ei, min(ei+120, n)):
                if side=="long" and H[j]>=tp_p: hit_bar=j-ei; break
                if side=="short" and L[j]<=tp_p: hit_bar=j-ei; break
            row[f"bars_{lbl}"]=hit_bar
        results.append(row)
    return pd.DataFrame(results)


if __name__ == "__main__":
    print("Loading...", flush=True)
    rt_df=load_rt(); rt_df=add_vwap(rt_df)
    pm_df=load_pm(); pm_stats=build_pm_stats(pm_df, rt_df)
    signals=collect_and_dedupe(rt_df, pm_stats)
    print(f"  Signals: {len(signals)}", flush=True)

    tdf=time_to_target(rt_df, signals)

    W=72
    print(f"\n{'='*W}")
    print(f"  QQQ C1+C2 Loose | Time-to-Target  (1 bar = 1 minute)")
    print(f"{'='*W}")
    print(f"  {'Target':<10} {'Hit%':>6}  {'AvgMin':>8} {'MedMin':>8} {'p25':>6} {'p75':>6} {'Max':>6}")
    print(f"  {'-'*65}")
    for lbl in T_LABELS:
        col=f"bars_{lbl}"; hit=tdf[col].dropna()
        pct=len(hit)/len(tdf)*100
        if len(hit)==0:
            print(f"  {lbl:<10} {pct:>6.1f}%  -- never hit within 120m"); continue
        print(f"  {lbl:<10} {pct:>6.1f}%  {hit.mean():>8.1f} {hit.median():>8.1f} "
              f"{hit.quantile(0.25):>6.1f} {hit.quantile(0.75):>6.1f} {hit.max():>6.0f}")

    for side in ["long","short"]:
        s=tdf[tdf["side"]==side]
        print(f"\n  {side.upper()} (N={len(s)})")
        print(f"  {'Target':<10} {'Hit%':>6}  {'AvgMin':>8} {'MedMin':>8} {'p25':>6} {'p75':>6}")
        print(f"  {'-'*55}")
        for lbl in T_LABELS:
            col=f"bars_{lbl}"; hit=s[col].dropna()
            pct=len(hit)/len(s)*100
            if len(hit)==0:
                print(f"  {lbl:<10} {pct:>6.1f}%  --"); continue
            print(f"  {lbl:<10} {pct:>6.1f}%  {hit.mean():>8.1f} {hit.median():>8.1f} "
                  f"{hit.quantile(0.25):>6.1f} {hit.quantile(0.75):>6.1f}")

    print(f"\n  DISTRIBUTION — minutes to reach +0.50% (on trades that hit)")
    col=f"bars_{T_LABELS[1]}"; hit=tdf[col].dropna()
    for label,lo,hi in [("0-5m",0,5),("6-15m",6,15),("16-30m",16,30),("31-60m",31,60),("61-120m",61,120)]:
        n_b=int(((hit>=lo)&(hit<=hi)).sum())
        print(f"  {label:<10} {n_b:>4} trades  ({n_b/len(hit)*100:.1f}% of hits)  "
              f"{'█'*int(n_b/len(hit)*40)}")
