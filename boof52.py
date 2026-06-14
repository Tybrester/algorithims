"""
BOOF52 — Premarket Bias Strategy
SPY + QQQ | 9:00-12:00 ET
Setup A: PM Range Break (continuation)
Setup B: PM Fakeout Reversal
Setup C: Open Location Bias (regime filter + first green/red candle)
"""
import datetime
import pandas as pd
import numpy as np
import pytz

ET      = pytz.timezone("America/New_York")
SYMBOLS = ["QQQ", "SPY"]

TARGETS  = [0.0025, 0.0050, 0.0075]
T_LABELS = ["+0.25%", "+0.50%", "+0.75%"]
MAX_TRADES = 3
COOLDOWN   = 10
TIME_STOP  = 60


# ── Data loaders ──────────────────────────────────────────────────────────────

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
    pm_df = pm_df.copy()
    pm_df["date"] = pm_df["time"].dt.date

    daily_close = rt_df.groupby("date")["close"].last().reset_index()
    daily_close.columns = ["date", "prev_close"]
    daily_close["date"] = pd.to_datetime(daily_close["date"])
    daily_close["next_date"] = daily_close["date"] + pd.Timedelta(days=1)

    records = []
    for date, g in pm_df.groupby("date"):
        records.append({
            "date":     pd.Timestamp(date),
            "pm_high":  g["high"].max(),
            "pm_low":   g["low"].min(),
            "pm_range": (g["high"].max() - g["low"].min()) / g["low"].min() * 100,
            "pm_vol":   g["volume"].sum(),
        })
    stats = pd.DataFrame(records)
    stats = stats.merge(
        daily_close[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
        on="date", how="left"
    )
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M") == "09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index()
    rth.columns = ["date", "rth_open"]
    stats = stats.merge(rth, on="date", how="left")
    stats["gap_pct"]      = (stats["rth_open"] - stats["prev_close"]) / stats["prev_close"] * 100
    stats["pm_vol_ma20"]  = stats["pm_vol"].rolling(20).mean()
    stats["pm_vol_ratio"] = stats["pm_vol"] / stats["pm_vol_ma20"]
    stats["open_pos"]     = (stats["rth_open"] - stats["pm_low"]) / (stats["pm_high"] - stats["pm_low"])
    return stats.dropna(subset=["gap_pct"])


def add_indicators(df):
    df = df.copy().reset_index(drop=True)
    df["typ"]      = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]       = df["typ"] * df["volume"]
    df["cpv"]      = df.groupby("date")["pv"].cumsum()
    df["cvol"]     = df.groupby("date")["volume"].cumsum()
    df["vwap"]     = df["cpv"] / df["cvol"]
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    return df


# ── Excursion ─────────────────────────────────────────────────────────────────

def excursion(ddf, ei, ep, side):
    n = len(ddf); H = ddf["high"].values; L = ddf["low"].values
    res = {}
    for bars, key in [(15,"15m"),(30,"30m"),(60,"60m")]:
        end = min(ei + bars, n - 1); sl = slice(ei, end + 1)
        res[f"mfe_{key}"] = float(max((H[sl]-ep)/ep*100)) if side=="long" else float(max((ep-L[sl])/ep*100))
        res[f"mae_{key}"] = float(max((ep-L[sl])/ep*100)) if side=="long" else float(max((H[sl]-ep)/ep*100))
    end60 = min(ei + 60, n - 1)
    for tgt, lbl in zip(TARGETS, T_LABELS):
        res[f"hit_{lbl}"] = bool(any(H[ei:end60+1] >= ep*(1+tgt))) if side=="long" \
                       else bool(any(L[ei:end60+1] <= ep*(1-tgt)))
    return res


# ── Setup A: PM Range Break ───────────────────────────────────────────────────

def run_A(df, pm_stats):
    """Continuation: break PM high/low in gap direction with vol + VWAP confirm."""
    trades = []
    pm = pm_stats.set_index("date")
    for date, ddf in df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        if pd.isna(day["gap_pct"]) or pd.isna(day["pm_high"]): continue

        ddf = ddf.reset_index(drop=True)
        lc = sc = 0; lcd = scd = None
        long_fired = short_fired = False

        for i in range(20, len(ddf) - 61):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if t < "09:00" or t >= "12:00": continue
            if pd.isna(row.get("vwap")) or pd.isna(row.get("vol_ma20")): continue
            nd  = row["time"]
            vol_ok = row["volume"] > 1.5 * row["vol_ma20"]

            # Long: gap up, break PM high, vol surge, above VWAP
            if (not long_fired and lc < MAX_TRADES and (lcd is None or nd >= lcd) and
                    day["gap_pct"] > 0 and
                    row["close"] > day["pm_high"] and
                    vol_ok and row["close"] > row["vwap"]):
                long_fired = True
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"sym":ddf.iloc[0].get("symbol",""),"setup":"A","side":"long",
                               "gap_pct":round(day["gap_pct"],3),"ep":ep,**excursion(ddf,ei,ep,"long")})
                lc += 1; lcd = nd + datetime.timedelta(minutes=COOLDOWN)

            # Short: gap down, break PM low, vol surge, below VWAP
            if (not short_fired and sc < MAX_TRADES and (scd is None or nd >= scd) and
                    day["gap_pct"] < 0 and
                    row["close"] < day["pm_low"] and
                    vol_ok and row["close"] < row["vwap"]):
                short_fired = True
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"sym":ddf.iloc[0].get("symbol",""),"setup":"A","side":"short",
                               "gap_pct":round(day["gap_pct"],3),"ep":ep,**excursion(ddf,ei,ep,"short")})
                sc += 1; scd = nd + datetime.timedelta(minutes=COOLDOWN)
    return trades


# ── Setup B: PM Fakeout Reversal ──────────────────────────────────────────────

def run_B(df, pm_stats):
    """Reversal: break PM level then reclaim it — trapped traders fuel the move."""
    trades = []
    pm = pm_stats.set_index("date")
    for date, ddf in df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        if pd.isna(day["gap_pct"]) or pd.isna(day["pm_high"]): continue

        ddf = ddf.reset_index(drop=True)
        lc = sc = 0; lcd = scd = None

        broke_above = broke_below = False
        long_fired  = short_fired = False

        for i in range(1, len(ddf) - 61):
            row = ddf.iloc[i]; prev = ddf.iloc[i-1]; t = row["time"].strftime("%H:%M")
            if t < "09:00" or t >= "12:00": continue
            if pd.isna(row.get("vwap")): continue
            nd = row["time"]

            # Track if PM levels were broken
            if row["high"] > day["pm_high"]: broke_above = True
            if row["low"]  < day["pm_low"]:  broke_below = True

            # Long: broke below PM low, then reclaims it, above VWAP
            if (broke_below and not long_fired and lc < MAX_TRADES and
                    (lcd is None or nd >= lcd) and
                    prev["close"] < day["pm_low"] and
                    row["close"]  > day["pm_low"] and
                    row["close"]  > row["vwap"]):
                long_fired = True
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"setup":"B","side":"long",
                               "gap_pct":round(day["gap_pct"],3),"ep":ep,**excursion(ddf,ei,ep,"long")})
                lc += 1; lcd = nd + datetime.timedelta(minutes=COOLDOWN)

            # Short: broke above PM high, then rejects back below, below VWAP
            if (broke_above and not short_fired and sc < MAX_TRADES and
                    (scd is None or nd >= scd) and
                    prev["close"] > day["pm_high"] and
                    row["close"]  < day["pm_high"] and
                    row["close"]  < row["vwap"]):
                short_fired = True
                ei = i+1; ep = ddf.iloc[ei]["open"]
                trades.append({"date":str(date),"setup":"B","side":"short",
                               "gap_pct":round(day["gap_pct"],3),"ep":ep,**excursion(ddf,ei,ep,"short")})
                sc += 1; scd = nd + datetime.timedelta(minutes=COOLDOWN)
    return trades


# ── Setup C: Open Location Bias ───────────────────────────────────────────────

def run_C(df, pm_stats):
    """
    Regime filter based on open position within PM range:
      open_pos > 0.7 + gap up  → long continuation (first green candle)
      open_pos < 0.3 + gap down → short continuation (first red candle)
      open outside PM range then snaps back inside → reversal
    """
    trades = []
    pm = pm_stats.set_index("date")
    for date, ddf in df.groupby("date"):
        date_ts = pd.Timestamp(date)
        if date_ts not in pm.index: continue
        day = pm.loc[date_ts]
        if pd.isna(day.get("open_pos")) or pd.isna(day["gap_pct"]): continue

        ddf  = ddf.reset_index(drop=True)
        rth  = ddf[ddf["time"].dt.strftime("%H:%M") >= "09:30"].reset_index(drop=True)
        if len(rth) < 62: continue

        op   = day["open_pos"]
        gap  = day["gap_pct"]
        pmh  = day["pm_high"]
        pml  = day["pm_low"]
        rth_open = rth.iloc[0]["open"]

        # ── C1: continuation bias ─────────────────────────────────────────
        long_cont  = op > 0.70 and gap > 0
        short_cont = op < 0.30 and gap < 0

        long_fired = short_fired = False
        for j in range(len(rth) - 61):
            row = rth.iloc[j]; t = row["time"].strftime("%H:%M")
            if t >= "12:00": break
            if not long_fired and long_cont and row["close"] > row["open"]:
                long_fired = True; ei = j+1; ep = rth.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == rth.iloc[ei]["time"]].tolist()
                if fi: trades.append({"date":str(date),"setup":"C1","side":"long",
                                      "gap_pct":round(gap,3),"open_pos":round(op,3),
                                      "ep":ep,**excursion(ddf,fi[0],ep,"long")})
            if not short_fired and short_cont and row["close"] < row["open"]:
                short_fired = True; ei = j+1; ep = rth.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == rth.iloc[ei]["time"]].tolist()
                if fi: trades.append({"date":str(date),"setup":"C1","side":"short",
                                      "gap_pct":round(gap,3),"open_pos":round(op,3),
                                      "ep":ep,**excursion(ddf,fi[0],ep,"short")})

        # ── C2: outside-PM snap-back reversal ─────────────────────────────
        # Open above PM high → first red candle = short
        # Open below PM low  → first green candle = long
        open_above_pm = rth_open > pmh
        open_below_pm = rth_open < pml

        rev_long = rev_short = False
        for j in range(len(rth) - 61):
            row = rth.iloc[j]; t = row["time"].strftime("%H:%M")
            if t >= "12:00": break
            if not rev_long and open_below_pm and row["close"] > row["open"]:
                rev_long = True; ei = j+1; ep = rth.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == rth.iloc[ei]["time"]].tolist()
                if fi: trades.append({"date":str(date),"setup":"C2","side":"long",
                                      "gap_pct":round(gap,3),"open_pos":round(op,3),
                                      "ep":ep,**excursion(ddf,fi[0],ep,"long")})
            if not rev_short and open_above_pm and row["close"] < row["open"]:
                rev_short = True; ei = j+1; ep = rth.iloc[ei]["open"]
                fi = ddf.index[ddf["time"] == rth.iloc[ei]["time"]].tolist()
                if fi: trades.append({"date":str(date),"setup":"C2","side":"short",
                                      "gap_pct":round(gap,3),"open_pos":round(op,3),
                                      "ep":ep,**excursion(ddf,fi[0],ep,"short")})
    return trades


# ── Report ────────────────────────────────────────────────────────────────────

def report(all_trades, sym):
    W = 102
    print(f"\n{'='*W}")
    print(f"  BOOF52 | {sym} | Premarket Bias Strategy")
    print(f"{'='*W}")
    print(f"  {'Setup':<6} {'Style':<12} {'Side':<7} {'N':>5} {'Days':>5} {'TPD':>5}  "
          f"{'MFE15':>7} {'MFE30':>7} {'MFE60':>7}  "
          f"{'MAE60':>7}  {'≥0.25%':>7} {'≥0.50%':>7} {'≥0.75%':>7}")
    print(f"  {'-'*97}")

    STYLE = {"A":"Continuation","B":"Reversal","C1":"Cont+Regime","C2":"Rev+Regime"}

    for setup in ["A","B","C1","C2"]:
        df = pd.DataFrame([t for t in all_trades if t["setup"] == setup])
        if df.empty:
            print(f"  {setup:<6} {STYLE.get(setup,''):<12} -- no trades"); continue
        for side in ["long","short","all"]:
            s = df if side=="all" else df[df["side"]==side]
            if s.empty: continue
            n_days = s["date"].nunique(); tpd = len(s)/n_days
            m15 = s["mfe_15m"].mean(); m30 = s["mfe_30m"].mean(); m60 = s["mfe_60m"].mean()
            ma60= s["mae_60m"].mean()
            h25 = s[f"hit_{T_LABELS[0]}"].mean()*100
            h50 = s[f"hit_{T_LABELS[1]}"].mean()*100
            h75 = s[f"hit_{T_LABELS[2]}"].mean()*100
            slbl= side.upper() if side!="all" else "BOTH"
            print(f"  {setup:<6} {STYLE.get(setup,''):<12} {slbl:<7} {len(s):>5} {n_days:>5} {tpd:>5.1f}  "
                  f"{m15:>6.3f}% {m30:>6.3f}% {m60:>6.3f}%  "
                  f"{ma60:>6.3f}%  {h25:>6.1f}% {h50:>6.1f}% {h75:>6.1f}%")
        print(f"  {'-'*97}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Loading data...", flush=True)
    for sym in SYMBOLS:
        pm_df    = load_pm(sym)
        rt_df    = load_rt(sym)
        rt_df    = add_indicators(rt_df)
        pm_stats = build_pm_stats(pm_df, rt_df)
        n_days   = len(pm_stats)
        print(f"  {sym}: {len(rt_df):,} bars, {n_days} PM days", flush=True)

        print(f"  Running Setup A...", flush=True); tA = run_A(rt_df, pm_stats)
        print(f"  Running Setup B...", flush=True); tB = run_B(rt_df, pm_stats)
        print(f"  Running Setup C...", flush=True); tC = run_C(rt_df, pm_stats)

        all_trades = tA + tB + tC
        print(f"  Total: A={len(tA)} B={len(tB)} C={len(tC)}", flush=True)
        report(all_trades, sym)

        pd.DataFrame(all_trades).to_csv(f"boof52_{sym}_trades.csv", index=False)
        print(f"  Saved boof52_{sym}_trades.csv", flush=True)
