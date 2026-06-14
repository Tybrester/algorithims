"""
BOOF52b — Tight vs Loose threshold comparison
Tests B, C1, C2, D on QQQ with two configs:
  TIGHT: original thresholds
  LOOSE: widened thresholds + multi-entry + Setup D
"""
import datetime
import pandas as pd
import numpy as np
import pytz

ET = pytz.timezone("America/New_York")

TARGETS  = [0.0025, 0.0050, 0.0075]
T_LABELS = ["+0.25%", "+0.50%", "+0.75%"]


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
    daily_close = rt_df.groupby("date")["close"].last().reset_index()
    daily_close.columns = ["date","prev_close"]
    daily_close["date"] = pd.to_datetime(daily_close["date"])
    daily_close["next_date"] = daily_close["date"] + pd.Timedelta(days=1)
    records = [{"date":pd.Timestamp(d),"pm_high":g["high"].max(),"pm_low":g["low"].min(),
                "pm_range":(g["high"].max()-g["low"].min())/g["low"].min()*100,"pm_vol":g["volume"].sum()}
               for d,g in pm_df.groupby("date")]
    stats = pd.DataFrame(records)
    stats = stats.merge(daily_close[["next_date","prev_close"]].rename(columns={"next_date":"date"}),on="date",how="left")
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M")=="09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index(); rth.columns=["date","rth_open"]
    stats = stats.merge(rth,on="date",how="left")
    stats["gap_pct"]      = (stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    stats["pm_vol_ma20"]  = stats["pm_vol"].rolling(20).mean()
    stats["pm_vol_ratio"] = stats["pm_vol"]/stats["pm_vol_ma20"]
    stats["open_pos"]     = (stats["rth_open"]-stats["pm_low"])/(stats["pm_high"]-stats["pm_low"])
    return stats.dropna(subset=["gap_pct"])


def add_indicators(df):
    df = df.copy().reset_index(drop=True)
    df["typ"]      = (df["high"]+df["low"]+df["close"])/3
    df["pv"]       = df["typ"]*df["volume"]
    df["cpv"]      = df.groupby("date")["pv"].cumsum()
    df["cvol"]     = df.groupby("date")["volume"].cumsum()
    df["vwap"]     = df["cpv"]/df["cvol"]
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    return df


def excursion(ddf, ei, ep, side):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values
    res={}
    for bars,key in [(15,"15m"),(30,"30m"),(60,"60m")]:
        end=min(ei+bars,n-1); sl=slice(ei,end+1)
        res[f"mfe_{key}"]=float(max((H[sl]-ep)/ep*100)) if side=="long" else float(max((ep-L[sl])/ep*100))
        res[f"mae_{key}"]=float(max((ep-L[sl])/ep*100)) if side=="long" else float(max((H[sl]-ep)/ep*100))
    end60=min(ei+60,n-1)
    for tgt,lbl in zip(TARGETS,T_LABELS):
        res[f"hit_{lbl}"]=bool(any(H[ei:end60+1]>=ep*(1+tgt))) if side=="long" \
                     else bool(any(L[ei:end60+1]<=ep*(1-tgt)))
    return res


# ── Setup B ───────────────────────────────────────────────────────────────────

def run_B(df, pm_stats, max_trades=1, vol_filter=False):
    trades=[]; pm=pm_stats.set_index("date")
    for date,ddf in df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day=pm.loc[date_ts]
        if pd.isna(day["gap_pct"]) or pd.isna(day["pm_high"]): continue
        ddf=ddf.reset_index(drop=True)
        lc=sc=0; lcd=scd=None
        broke_above=broke_below=False
        for i in range(1,len(ddf)-61):
            row=ddf.iloc[i]; prev=ddf.iloc[i-1]; t=row["time"].strftime("%H:%M")
            if t<"09:00" or t>="12:00": continue
            if pd.isna(row.get("vwap")): continue
            nd=row["time"]
            if row["high"]>day["pm_high"]: broke_above=True
            if row["low"] <day["pm_low"]:  broke_below=True
            vol_ok = (not vol_filter) or (row["vol_ma20"]>0 and row["volume"]>1.5*row["vol_ma20"])
            if (broke_below and lc<max_trades and (lcd is None or nd>=lcd) and
                    prev["close"]<day["pm_low"] and row["close"]>day["pm_low"] and
                    row["close"]>row["vwap"] and vol_ok):
                ei=i+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"setup":"B","side":"long",
                               "gap_pct":round(day["gap_pct"],3),"ep":ep,**excursion(ddf,ei,ep,"long")})
                lc+=1; lcd=nd+datetime.timedelta(minutes=10)
            if (broke_above and sc<max_trades and (scd is None or nd>=scd) and
                    prev["close"]>day["pm_high"] and row["close"]<day["pm_high"] and
                    row["close"]<row["vwap"] and vol_ok):
                ei=i+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"setup":"B","side":"short",
                               "gap_pct":round(day["gap_pct"],3),"ep":ep,**excursion(ddf,ei,ep,"short")})
                sc+=1; scd=nd+datetime.timedelta(minutes=10)
    return trades


# ── Setup C1 ──────────────────────────────────────────────────────────────────

def run_C1(df, pm_stats, op_thresh=0.30, max_trades=1):
    """Regime continuation. Tight: op<0.30/op>0.70. Loose: op<0.40/op>0.60."""
    trades=[]; pm=pm_stats.set_index("date")
    for date,ddf in df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day=pm.loc[date_ts]
        if pd.isna(day.get("open_pos")) or pd.isna(day["gap_pct"]): continue
        op=day["open_pos"]; gap=day["gap_pct"]
        long_cont  = op>(1-op_thresh) and gap>0
        short_cont = op<op_thresh and gap<0
        if not long_cont and not short_cont: continue
        ddf=ddf.reset_index(drop=True)
        rth=ddf[ddf["time"].dt.strftime("%H:%M")>="09:30"].reset_index(drop=True)
        if len(rth)<62: continue
        lc=sc=0; lcd=scd=None
        for j in range(len(rth)-61):
            row=rth.iloc[j]; t=row["time"].strftime("%H:%M")
            if t>="12:00": break
            nd=row["time"]
            if long_cont and lc<max_trades and (lcd is None or nd>=lcd) and row["close"]>row["open"]:
                ei=j+1; ep=rth.iloc[ei]["open"]
                fi=ddf.index[ddf["time"]==rth.iloc[ei]["time"]].tolist()
                if fi:
                    trades.append({"date":str(date),"setup":"C1","side":"long",
                                   "gap_pct":round(gap,3),"open_pos":round(op,3),
                                   "ep":ep,**excursion(ddf,fi[0],ep,"long")})
                    lc+=1; lcd=nd+datetime.timedelta(minutes=10)
            if short_cont and sc<max_trades and (scd is None or nd>=scd) and row["close"]<row["open"]:
                ei=j+1; ep=rth.iloc[ei]["open"]
                fi=ddf.index[ddf["time"]==rth.iloc[ei]["time"]].tolist()
                if fi:
                    trades.append({"date":str(date),"setup":"C1","side":"short",
                                   "gap_pct":round(gap,3),"open_pos":round(op,3),
                                   "ep":ep,**excursion(ddf,fi[0],ep,"short")})
                    sc+=1; scd=nd+datetime.timedelta(minutes=10)
    return trades


# ── Setup C2 ──────────────────────────────────────────────────────────────────

def run_C2(df, pm_stats, edge_pct=0.0, max_trades=1):
    """
    Tight:  open strictly outside PM range (edge_pct=0.0)
    Loose:  open in outer 15% of PM range (edge_pct=0.15)
    """
    trades=[]; pm=pm_stats.set_index("date")
    for date,ddf in df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day=pm.loc[date_ts]
        if pd.isna(day.get("open_pos")) or pd.isna(day["pm_high"]): continue
        op=day["open_pos"]; pmh=day["pm_high"]; pml=day["pm_low"]
        rth_open=day["rth_open"]
        # Tight: open outside PM range
        # Loose: open in outer edge_pct of PM range OR outside
        open_above = rth_open>pmh or (edge_pct>0 and op>(1-edge_pct))
        open_below = rth_open<pml or (edge_pct>0 and op<edge_pct)
        if not open_above and not open_below: continue
        ddf=ddf.reset_index(drop=True)
        rth=ddf[ddf["time"].dt.strftime("%H:%M")>="09:30"].reset_index(drop=True)
        if len(rth)<62: continue
        lc=sc=0; lcd=scd=None
        for j in range(len(rth)-61):
            row=rth.iloc[j]; t=row["time"].strftime("%H:%M")
            if t>="12:00": break
            nd=row["time"]
            if open_below and lc<max_trades and (lcd is None or nd>=lcd) and row["close"]>row["open"]:
                ei=j+1; ep=rth.iloc[ei]["open"]
                fi=ddf.index[ddf["time"]==rth.iloc[ei]["time"]].tolist()
                if fi:
                    trades.append({"date":str(date),"setup":"C2","side":"long",
                                   "gap_pct":round(day["gap_pct"],3),"open_pos":round(op,3),
                                   "ep":ep,**excursion(ddf,fi[0],ep,"long")})
                    lc+=1; lcd=nd+datetime.timedelta(minutes=10)
            if open_above and sc<max_trades and (scd is None or nd>=scd) and row["close"]<row["open"]:
                ei=j+1; ep=rth.iloc[ei]["open"]
                fi=ddf.index[ddf["time"]==rth.iloc[ei]["time"]].tolist()
                if fi:
                    trades.append({"date":str(date),"setup":"C2","side":"short",
                                   "gap_pct":round(day["gap_pct"],3),"open_pos":round(op,3),
                                   "ep":ep,**excursion(ddf,fi[0],ep,"short")})
                    sc+=1; scd=nd+datetime.timedelta(minutes=10)
    return trades


# ── Setup D: OR5 Break on High PM Volume ─────────────────────────────────────

def run_D(df, pm_stats, vol_ratio_thresh=1.5, max_trades=2):
    """First 5-min range break on high PM volume days."""
    trades=[]; pm=pm_stats.set_index("date")
    for date,ddf in df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day=pm.loc[date_ts]
        if pd.isna(day.get("pm_vol_ratio")): continue
        if day["pm_vol_ratio"]<vol_ratio_thresh: continue
        ddf=ddf.reset_index(drop=True)
        rth=ddf[ddf["time"].dt.strftime("%H:%M")>="09:30"].reset_index(drop=True)
        if len(rth)<62: continue
        or5=rth[rth["time"].dt.strftime("%H:%M")<"09:35"]
        if len(or5)<2: continue
        or5h=or5["high"].max(); or5l=or5["low"].min()
        post=rth[rth["time"].dt.strftime("%H:%M")>="09:35"].reset_index(drop=True)
        lc=sc=0; lcd=scd=None
        for j in range(len(post)-61):
            row=post.iloc[j]; t=row["time"].strftime("%H:%M")
            if t>="12:00": break
            nd=row["time"]
            if lc<max_trades and (lcd is None or nd>=lcd) and row["close"]>or5h and row["close"]>row.get("vwap",0):
                ei=j+1; ep=post.iloc[ei]["open"]
                fi=ddf.index[ddf["time"]==post.iloc[ei]["time"]].tolist()
                if fi:
                    trades.append({"date":str(date),"setup":"D","side":"long",
                                   "gap_pct":round(day["gap_pct"],3),"ep":ep,**excursion(ddf,fi[0],ep,"long")})
                    lc+=1; lcd=nd+datetime.timedelta(minutes=10)
            if sc<max_trades and (scd is None or nd>=scd) and row["close"]<or5l and row["close"]<row.get("vwap",999):
                ei=j+1; ep=post.iloc[ei]["open"]
                fi=ddf.index[ddf["time"]==post.iloc[ei]["time"]].tolist()
                if fi:
                    trades.append({"date":str(date),"setup":"D","side":"short",
                                   "gap_pct":round(day["gap_pct"],3),"ep":ep,**excursion(ddf,fi[0],ep,"short")})
                    sc+=1; scd=nd+datetime.timedelta(minutes=10)
    return trades


# ── Report ────────────────────────────────────────────────────────────────────

def row_line(label, version, trades):
    if not trades:
        print(f"  {label:<22} {version:<8} {'--':>5}"); return
    df=pd.DataFrame(trades)
    n=len(df); nd=df["date"].nunique(); tpd=n/nd
    m15=df["mfe_15m"].mean(); m30=df["mfe_30m"].mean(); m60=df["mfe_60m"].mean()
    ma60=df["mae_60m"].mean()
    h25=df[f"hit_{T_LABELS[0]}"].mean()*100
    h50=df[f"hit_{T_LABELS[1]}"].mean()*100
    h75=df[f"hit_{T_LABELS[2]}"].mean()*100
    print(f"  {label:<22} {version:<8} {n:>5} {nd:>5} {tpd:>5.1f}  "
          f"{m15:>6.3f}% {m30:>6.3f}% {m60:>6.3f}%  "
          f"{ma60:>6.3f}%  {h25:>6.1f}% {h50:>6.1f}% {h75:>6.1f}%")


def report_all(results):
    W=105
    print(f"\n{'='*W}")
    print(f"  BOOF52b | QQQ | Tight vs Loose Threshold Comparison")
    print(f"{'='*W}")
    print(f"  {'Setup':<22} {'Ver':<8} {'N':>5} {'Days':>5} {'TPD':>5}  "
          f"{'MFE15':>7} {'MFE30':>7} {'MFE60':>7}  "
          f"{'MAE60':>7}  {'≥0.25%':>7} {'≥0.50%':>7} {'≥0.75%':>7}")
    print(f"  {'-'*100}")
    for label,version,trades in results:
        row_line(label,version,trades)
    print(f"{'='*W}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Loading QQQ...", flush=True)
    pm_df    = load_pm("QQQ")
    rt_df    = load_rt("QQQ")
    rt_df    = add_indicators(rt_df)
    pm_stats = build_pm_stats(pm_df, rt_df)
    print(f"  {len(pm_stats)} PM days", flush=True)

    configs = [
        # (label, version, trades)
        ("B Fakeout",    "TIGHT",  run_B(rt_df, pm_stats, max_trades=1, vol_filter=False)),
        ("B Fakeout",    "LOOSE",  run_B(rt_df, pm_stats, max_trades=3, vol_filter=True)),
        ("C1 Cont+Regime","TIGHT", run_C1(rt_df, pm_stats, op_thresh=0.30, max_trades=1)),
        ("C1 Cont+Regime","LOOSE", run_C1(rt_df, pm_stats, op_thresh=0.40, max_trades=2)),
        ("C2 Rev+Regime", "TIGHT", run_C2(rt_df, pm_stats, edge_pct=0.00, max_trades=1)),
        ("C2 Rev+Regime", "LOOSE", run_C2(rt_df, pm_stats, edge_pct=0.15, max_trades=2)),
        ("D OR5 HiVol",  "1.5x",  run_D(rt_df, pm_stats, vol_ratio_thresh=1.5, max_trades=2)),
        ("D OR5 HiVol",  "1.2x",  run_D(rt_df, pm_stats, vol_ratio_thresh=1.2, max_trades=2)),
    ]

    report_all(configs)

    # Per-side detail for best setups
    print("\n--- SIDE DETAIL: LOOSE configs only ---")
    for label, version, trades in configs:
        if version not in ("LOOSE","1.2x") or not trades: continue
        df = pd.DataFrame(trades)
        print(f"\n  {label} {version}  (N={len(df)})")
        for side in ["long","short"]:
            s=df[df["side"]==side]
            if s.empty: continue
            h50=s[f"hit_{T_LABELS[1]}"].mean()*100; h75=s[f"hit_{T_LABELS[2]}"].mean()*100
            print(f"    {side.upper():<6} N={len(s):>3}  MFE60={s['mfe_60m'].mean():.3f}%  "
                  f"MAE60={s['mae_60m'].mean():.3f}%  ≥0.50%={h50:.1f}%  ≥0.75%={h75:.1f}%")
