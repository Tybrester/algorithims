"""
BOOF51 Event Scanner — Pure Excursion Study
Find events that already create 0.5%+ moves in 30 minutes
No exits. No PF. Just N, MFE15, MFE30, MFE60, % >= 0.50%, % >= 0.75%
"""
import pandas as pd
import numpy as np
import pytz

ET  = pytz.timezone("America/New_York")
SYM = "QQQ"

TARGETS  = [0.0050, 0.0075]
T_LABELS = ["+0.50%", "+0.75%"]


def load_rt():
    df = pd.read_csv(f"boof51_{SYM}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df["date"] = df["time"].dt.date
    return df

def load_pm():
    df = pd.read_csv(f"boof51_{SYM}_pm.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    return df

def build_pm_stats(pm_df, rt_df):
    pm_df = pm_df.copy(); pm_df["date"] = pm_df["time"].dt.date
    dc = rt_df.groupby("date")["close"].last().reset_index()
    dc.columns = ["date","prev_close"]; dc["date"] = pd.to_datetime(dc["date"])
    dc["next_date"] = dc["date"] + pd.Timedelta(days=1)
    records = [{"date":pd.Timestamp(d),"pm_high":g["high"].max(),"pm_low":g["low"].min(),
                "pm_vol":g["volume"].sum()}
               for d,g in pm_df.groupby("date")]
    stats = pd.DataFrame(records)
    stats = stats.merge(dc[["next_date","prev_close"]].rename(columns={"next_date":"date"}),on="date",how="left")
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M")=="09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index(); rth.columns=["date","rth_open"]
    stats = stats.merge(rth,on="date",how="left")
    stats["gap_pct"]      = (stats["rth_open"]-stats["prev_close"])/stats["prev_close"]*100
    stats["pm_vol_ma20"]  = stats["pm_vol"].rolling(20).mean()
    stats["pm_vol_ratio"] = stats["pm_vol"]/stats["pm_vol_ma20"]
    return stats.dropna(subset=["gap_pct"])

def add_indicators(df):
    df = df.copy().reset_index(drop=True)
    df["typ"]=(df["high"]+df["low"]+df["close"])/3
    df["pv"]=df["typ"]*df["volume"]
    df["cpv"]=df.groupby("date")["pv"].cumsum()
    df["cvol"]=df.groupby("date")["volume"].cumsum()
    df["vwap"]=df["cpv"]/df["cvol"]
    df["vol_ma20"]=df["volume"].rolling(20).mean()
    # ADX (14)
    df["prev_close"]=df.groupby("date")["close"].shift(1)
    df["tr"]=np.maximum(df["high"]-df["low"],
             np.maximum(abs(df["high"]-df["prev_close"]),
                        abs(df["low"]-df["prev_close"])))
    df["dm_plus"] =np.where((df["high"]-df["high"].shift(1))>(df["low"].shift(1)-df["low"]),
                             np.maximum(df["high"]-df["high"].shift(1),0),0)
    df["dm_minus"]=np.where((df["low"].shift(1)-df["low"])>(df["high"]-df["high"].shift(1)),
                             np.maximum(df["low"].shift(1)-df["low"],0),0)
    period=14
    df["atr"]   =df["tr"].rolling(period).mean()
    df["di_plus"]=(df["dm_plus"].rolling(period).mean()/df["atr"].replace(0,np.nan))*100
    df["di_minus"]=(df["dm_minus"].rolling(period).mean()/df["atr"].replace(0,np.nan))*100
    df["dx"]=abs(df["di_plus"]-df["di_minus"])/(df["di_plus"]+df["di_minus"].replace(0,np.nan))*100
    df["adx"]=df["dx"].rolling(period).mean()
    return df


# ── Core excursion ────────────────────────────────────────────────────────────

def exc(ddf, ei, ep, side):
    n=len(ddf); H=ddf["high"].values; L=ddf["low"].values
    res={}
    for bars,key in [(15,"mfe15"),(30,"mfe30"),(60,"mfe60")]:
        end=min(ei+bars,n-1); sl=slice(ei,end+1)
        res[key]=float(max((H[sl]-ep)/ep*100)) if side=="long" else float(max((ep-L[sl])/ep*100))
    end30=min(ei+30,n-1)
    for tgt,lbl in zip(TARGETS,T_LABELS):
        res[f"hit_{lbl}"]=bool(any(H[ei:end30+1]>=ep*(1+tgt))) if side=="long" \
                     else bool(any(L[ei:end30+1]<=ep*(1-tgt)))
    return res


# ══════════════════════════════════════════════════════════════════════════════
# EVENT DEFINITIONS
# Each returns list of {"side","ep","date", ...exc} dicts
# ══════════════════════════════════════════════════════════════════════════════

def ev_prev_day_hl(rt_df):
    """Break of previous day high (long) or low (short) — first break only."""
    rt_df=rt_df.copy(); rt_df["date"]=pd.to_datetime(rt_df["date"])
    trades=[]
    dates=sorted(rt_df["date"].unique())
    for i in range(1,len(dates)):
        prev_d=dates[i-1]; curr_d=dates[i]
        prev=rt_df[rt_df["date"]==prev_d]
        curr=rt_df[rt_df["date"]==curr_d].reset_index(drop=True)
        if prev.empty or curr.empty: continue
        pdh=prev["high"].max(); pdl=prev["low"].min()
        lf=sf=False
        for j in range(len(curr)-61):
            row=curr.iloc[j]; t=row["time"].strftime("%H:%M")
            if t<"09:00" or t>="12:00": continue
            if not lf and row["close"]>pdh:
                lf=True; ei=j+1; ep=curr.iloc[ei]["open"]
                trades.append({"date":str(curr_d.date()),"side":"long","ep":ep,**exc(curr,ei,ep,"long")})
            if not sf and row["close"]<pdl:
                sf=True; ei=j+1; ep=curr.iloc[ei]["open"]
                trades.append({"date":str(curr_d.date()),"side":"short","ep":ep,**exc(curr,ei,ep,"short")})
            if lf and sf: break
    return trades


def ev_pm_hl(rt_df, pm_stats):
    """Break of premarket high (long) or low (short) — first break only."""
    rt_df=rt_df.copy(); rt_df["date"]=pd.to_datetime(rt_df["date"])
    pm=pm_stats.set_index("date"); trades=[]
    for date,ddf in rt_df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day=pm.loc[date_ts]
        ddf=ddf.reset_index(drop=True)
        lf=sf=False
        for j in range(len(ddf)-61):
            row=ddf.iloc[j]; t=row["time"].strftime("%H:%M")
            if t<"09:00" or t>="12:00": continue
            if not lf and row["close"]>day["pm_high"]:
                lf=True; ei=j+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date.date()),"side":"long","ep":ep,**exc(ddf,ei,ep,"long")})
            if not sf and row["close"]<day["pm_low"]:
                sf=True; ei=j+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date.date()),"side":"short","ep":ep,**exc(ddf,ei,ep,"short")})
            if lf and sf: break
    return trades


def ev_gap(rt_df, pm_stats, thresh=1.0):
    """Gap > thresh% days — enter at open, measure both directions, keep best."""
    rt_df=rt_df.copy(); rt_df["date"]=pd.to_datetime(rt_df["date"])
    pm=pm_stats.set_index("date"); trades=[]
    for date,ddf in rt_df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day=pm.loc[date_ts]
        if abs(day["gap_pct"])<thresh: continue
        side="long" if day["gap_pct"]>0 else "short"
        ddf2=ddf.reset_index(drop=True)
        open_bar=ddf2[ddf2["time"].dt.strftime("%H:%M")=="09:30"]
        if open_bar.empty: continue
        ei=open_bar.index[0]
        if ei+61>=len(ddf2): continue
        ep=ddf2.iloc[ei]["open"]
        trades.append({"date":str(date.date()),"side":side,"gap_pct":round(day["gap_pct"],3),
                       "ep":ep,**exc(ddf2,ei,ep,side)})
    return trades


def ev_or15(rt_df):
    """First break of 9:30-9:44 opening range."""
    rt_df=rt_df.copy(); rt_df["date"]=pd.to_datetime(rt_df["date"])
    trades=[]
    for date,ddf in rt_df.groupby("date"):
        ddf=ddf.reset_index(drop=True)
        or15=ddf[ddf["time"].dt.strftime("%H:%M")<"09:45"]
        if len(or15)<5: continue
        orh=or15["high"].max(); orl=or15["low"].min()
        post=ddf[ddf["time"].dt.strftime("%H:%M")>="09:45"].reset_index(drop=True)
        lf=sf=False
        for j in range(len(post)-61):
            row=post.iloc[j]; t=row["time"].strftime("%H:%M")
            if t>="12:00": break
            fi=ddf.index[ddf["time"]==post.iloc[j]["time"]].tolist()
            if not fi: continue
            if not lf and row["close"]>orh:
                lf=True; ei_p=j+1; ep=post.iloc[ei_p]["open"]
                fi2=ddf.index[ddf["time"]==post.iloc[ei_p]["time"]].tolist()
                if fi2: trades.append({"date":str(date.date()),"side":"long","ep":ep,**exc(ddf,fi2[0],ep,"long")})
            if not sf and row["close"]<orl:
                sf=True; ei_p=j+1; ep=post.iloc[ei_p]["open"]
                fi2=ddf.index[ddf["time"]==post.iloc[ei_p]["time"]].tolist()
                if fi2: trades.append({"date":str(date.date()),"side":"short","ep":ep,**exc(ddf,fi2[0],ep,"short")})
            if lf and sf: break
    return trades


def ev_vwap_reclaim_gap_down(rt_df, pm_stats):
    """Gap down day: first VWAP reclaim = long, first VWAP rejection = short."""
    rt_df=rt_df.copy(); rt_df["date"]=pd.to_datetime(rt_df["date"])
    pm=pm_stats.set_index("date"); trades=[]
    for date,ddf in rt_df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day=pm.loc[date_ts]
        if day["gap_pct"]>=-0.5: continue   # gap down only
        ddf=ddf.reset_index(drop=True)
        lf=sf=False
        for j in range(1,len(ddf)-61):
            row=ddf.iloc[j]; prev=ddf.iloc[j-1]; t=row["time"].strftime("%H:%M")
            if t<"09:00" or t>="12:00": continue
            if pd.isna(row.get("vwap")): continue
            if not lf and prev["close"]<prev["vwap"] and row["close"]>row["vwap"]:
                lf=True; ei=j+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date.date()),"side":"long","ep":ep,**exc(ddf,ei,ep,"long")})
            if not sf and prev["close"]>prev["vwap"] and row["close"]<row["vwap"]:
                sf=True; ei=j+1; ep=ddf.iloc[ei]["open"]
                trades.append({"date":str(date.date()),"side":"short","ep":ep,**exc(ddf,ei,ep,"short")})
            if lf and sf: break
    return trades


def ev_adx_expansion(rt_df, adx_thresh=25):
    """First bar ADX crosses above threshold — trade direction of DI."""
    rt_df=rt_df.copy(); rt_df["date"]=pd.to_datetime(rt_df["date"])
    trades=[]
    for date,ddf in rt_df.groupby("date"):
        ddf=ddf.reset_index(drop=True)
        lf=sf=False
        for j in range(1,len(ddf)-61):
            row=ddf.iloc[j]; prev=ddf.iloc[j-1]; t=row["time"].strftime("%H:%M")
            if t<"09:00" or t>="12:00": continue
            if pd.isna(row.get("adx")) or pd.isna(prev.get("adx")): continue
            if prev["adx"]<adx_thresh and row["adx"]>=adx_thresh:
                side="long" if row["di_plus"]>row["di_minus"] else "short"
                if side=="long" and not lf:
                    lf=True; ei=j+1; ep=ddf.iloc[ei]["open"]
                    trades.append({"date":str(date.date()),"side":"long","ep":ep,**exc(ddf,ei,ep,"long")})
                elif side=="short" and not sf:
                    sf=True; ei=j+1; ep=ddf.iloc[ei]["open"]
                    trades.append({"date":str(date.date()),"side":"short","ep":ep,**exc(ddf,ei,ep,"short")})
                if lf and sf: break
    return trades


def ev_overnight_continuation(rt_df, pm_stats, gap_thresh=0.5):
    """Large gap day: continue in gap direction — OR5 break confirmation."""
    rt_df=rt_df.copy(); rt_df["date"]=pd.to_datetime(rt_df["date"])
    pm=pm_stats.set_index("date"); trades=[]
    for date,ddf in rt_df.groupby("date"):
        date_ts=pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day=pm.loc[date_ts]
        if abs(day["gap_pct"])<gap_thresh: continue
        side="long" if day["gap_pct"]>0 else "short"
        ddf=ddf.reset_index(drop=True)
        or5=ddf[ddf["time"].dt.strftime("%H:%M")<"09:35"]
        if len(or5)<2: continue
        orh=or5["high"].max(); orl=or5["low"].min()
        post=ddf[ddf["time"].dt.strftime("%H:%M")>="09:35"].reset_index(drop=True)
        fired=False
        for j in range(len(post)-61):
            row=post.iloc[j]; t=row["time"].strftime("%H:%M")
            if t>="12:00": break
            fi=ddf.index[ddf["time"]==post.iloc[j]["time"]].tolist()
            if not fi: continue
            if not fired:
                if side=="long" and row["close"]>orh:
                    fired=True; ei_p=j+1; ep=post.iloc[ei_p]["open"]
                    fi2=ddf.index[ddf["time"]==post.iloc[ei_p]["time"]].tolist()
                    if fi2: trades.append({"date":str(date.date()),"side":"long","gap_pct":round(day["gap_pct"],3),
                                           "ep":ep,**exc(ddf,fi2[0],ep,"long")})
                elif side=="short" and row["close"]<orl:
                    fired=True; ei_p=j+1; ep=post.iloc[ei_p]["open"]
                    fi2=ddf.index[ddf["time"]==post.iloc[ei_p]["time"]].tolist()
                    if fi2: trades.append({"date":str(date.date()),"side":"short","gap_pct":round(day["gap_pct"],3),
                                           "ep":ep,**exc(ddf,fi2[0],ep,"short")})
            if fired: break
    return trades


# ── Report ────────────────────────────────────────────────────────────────────

def row_stats(trades, label):
    if not trades: return
    df=pd.DataFrame(trades)
    for side in ["long","short","all"]:
        s=df if side=="all" else df[df["side"]==side]
        if s.empty: continue
        n=len(s)
        m15=s["mfe15"].mean(); m30=s["mfe30"].mean(); m60=s["mfe60"].mean()
        h50=s[f"hit_{T_LABELS[0]}"].mean()*100
        h75=s[f"hit_{T_LABELS[1]}"].mean()*100
        slbl=side.upper() if side!="all" else "BOTH"
        name=label if side=="long" else ""
        print(f"  {name:<32} {slbl:<7} {n:>5}  {m15:>6.3f}%  {m30:>6.3f}%  {m60:>6.3f}%   {h50:>6.1f}%   {h75:>6.1f}%")


if __name__ == "__main__":
    print(f"Loading {SYM}...", flush=True)
    pm_df    = load_pm()
    rt_df    = load_rt(); rt_df = add_indicators(rt_df)
    pm_stats = build_pm_stats(pm_df, rt_df)
    print(f"  {len(pm_stats)} days", flush=True)

    EVENTS = [
        ("Prev Day H/L Break",        ev_prev_day_hl(rt_df)),
        ("PM High/Low Break",          ev_pm_hl(rt_df, pm_stats)),
        ("Gap > 1% (open entry)",      ev_gap(rt_df, pm_stats, thresh=1.0)),
        ("Gap > 0.5% (open entry)",    ev_gap(rt_df, pm_stats, thresh=0.5)),
        ("OR15 Break",                 ev_or15(rt_df)),
        ("VWAP Reclaim (gap-down)",    ev_vwap_reclaim_gap_down(rt_df, pm_stats)),
        ("ADX > 25 Expansion",         ev_adx_expansion(rt_df, adx_thresh=25)),
        ("Overnight Cont. (OR5 break)",ev_overnight_continuation(rt_df, pm_stats, gap_thresh=0.5)),
    ]

    W=96
    print(f"\n{'='*W}")
    print(f"  BOOF51 Event Scanner | {SYM} | 9:00-12:00 ET | Pure Excursion")
    print(f"{'='*W}")
    print(f"  {'Event':<32} {'Side':<7} {'N':>5}  {'MFE15':>7}  {'MFE30':>7}  {'MFE60':>7}   {'>=0.50%':>7}   {'>=0.75%':>7}")
    print(f"  {'-'*90}")

    for label, trades in EVENTS:
        row_stats(trades, label)
        print(f"  {'-'*90}")
