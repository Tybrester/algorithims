"""
BOOF50 Monte Carlo — standalone, no fetch, reads CSVs directly
"""
import os, random
import numpy as np
import pandas as pd

SYMBOLS = [
    "TSLA","AMD","APP","COIN","HOOD",
    "SMCI","UPST","META","MSFT","NVDA",
    "MSTR","PLTR","CRWD","AAPL","AMZN"
]
TP       = 0.0075
SL       = 0.005
MAX_BARS = 120
TZ       = "America/New_York"
N_SIMS   = 1000


def load_csv(sym):
    path = f"boof32_data_{sym}.csv"
    df = pd.read_csv(path, low_memory=False)
    if "datetime" in df.columns:
        df = df.rename(columns={"datetime": "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(TZ)
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open","high","low","close","volume"])
    df["date"] = df["timestamp"].dt.date
    df["time"] = df["timestamp"].dt.strftime("%H:%M")
    df = df[(df["time"] >= "09:30") & (df["time"] <= "16:00")].reset_index(drop=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def add_vwap(df):
    df    = df.copy()
    pv    = (df["high"].values + df["low"].values + df["close"].values) / 3 * df["volume"].values
    vol   = df["volume"].values
    dates = df["date"].values
    # find day boundaries
    bounds = np.where(dates[1:] != dates[:-1])[0] + 1
    bounds = np.concatenate([[0], bounds, [len(df)]])
    cum_pv  = np.empty(len(df))
    cum_vol = np.empty(len(df))
    for s, e in zip(bounds[:-1], bounds[1:]):
        cum_pv[s:e]  = np.cumsum(pv[s:e])
        cum_vol[s:e] = np.cumsum(vol[s:e])
    df["vwap"] = cum_pv / np.where(cum_vol == 0, 1, cum_vol)
    return df


def collect_entries(df, side):
    entries = []
    dates   = sorted(df["date"].unique())
    date_idx = {d: i for i, d in enumerate(dates)}
    for date, day in df.groupby("date"):
        full_day = day.copy()
        day = day[(day["time"] >= "09:45") & (day["time"] <= "14:00")].reset_index(drop=True)
        if len(day) < MAX_BARS + 10:
            continue
        # gap vs prev close
        di = date_idx[date]
        gap = 0.0
        if di > 0:
            prev_day = df[df["date"] == dates[di-1]]
            open_row = full_day[full_day["time"] == "09:30"]
            if not prev_day.empty and not open_row.empty:
                prev_cls = prev_day["close"].iloc[-1]
                open_px  = open_row["close"].iloc[0]
                gap = (open_px - prev_cls) / prev_cls
        for i in range(5, len(day) - MAX_BARS - 2):
            prev = day.iloc[i-1]; row = day.iloc[i]
            if side == "long":
                hold  = all(day.iloc[i:i+5]["close"] > day.iloc[i:i+5]["vwap"])
                cross = prev["close"] < prev["vwap"] and row["close"] > row["vwap"] and hold
            else:
                hold  = all(day.iloc[i:i+5]["close"] < day.iloc[i:i+5]["vwap"])
                cross = prev["close"] > prev["vwap"] and row["close"] < row["vwap"] and hold
            if cross:
                future = day.iloc[i:i+MAX_BARS]
                entries.append({
                    "ep":    row["close"],
                    "side":  side,
                    "highs": future["high"].values,
                    "lows":  future["low"].values,
                    "time":  row["time"],
                    "gap":   gap,
                })
    return entries


def sim_pnl(e):
    ep = e["ep"]; hs = e["highs"]; ls = e["lows"]
    for b in range(len(hs)):
        if e["side"] == "long":
            if hs[b] >= ep*(1+TP): return TP
            if ls[b] <= ep*(1-SL): return -SL
        else:
            if ls[b] <= ep*(1-TP): return TP
            if hs[b] >= ep*(1+SL): return -SL
    if e["side"] == "long": return (hs[-1]-ep)/ep if len(hs) else 0
    else:                   return (ep-ls[-1])/ep if len(ls) else 0


def slippage_test(arr):
    print(f"\n{'='*55}")
    print(f"  3. SLIPPAGE STRESS TEST  (TP=0.75%, SL=0.50%)")
    print(f"{'='*55}")
    print(f"  {'Cost/trade':<12}  {'n':>5}  {'WR':>6}  {'PF':>5}  {'EV':>9}  Pass?")
    print(f"  {'-'*12}  {'-'*5}  {'-'*6}  {'-'*5}  {'-'*9}  {'-'*5}")
    for c in [0.0, 0.0002, 0.0005, 0.0010, 0.0015, 0.0020]:
        adj = arr - c
        w   = adj[adj>0]; l = adj[adj<0]
        pf  = w.sum()/abs(l.sum()) if len(l) else float("inf")
        wr  = (adj>0).mean()
        ev  = adj.mean()*100
        ok  = "✓" if pf >= 1.20 and ev > 0 else "✗"
        print(f"  {c*100:.3f}%       {len(adj):5d}  {wr:6.1%}  {pf:5.2f}  {ev:+8.4f}%  {ok}")


def oos_folds(sym_pnls):
    print(f"\n{'='*55}")
    print(f"  4. OUT-OF-SAMPLE SYMBOL FOLDS")
    print(f"{'='*55}")
    folds = [
        ["AAPL","AMD","TSLA","COIN","MSTR"],
        ["NVDA","META","PLTR","HOOD","APP"],
        ["MU","SMCI","CRWD","UPST","HIMS"],
        ["AMZN","MSFT","ARM","AFRM","RKLB"],
        ["ASTS","LUNR","RIOT","CLSK","IREN"],
    ]
    print(f"  {'Held-out symbols':<38}  {'n':>5}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    print(f"  {'-'*38}  {'-'*5}  {'-'*6}  {'-'*5}  {'-'*9}")
    for fold in folds:
        pnls = []
        for sym in fold:
            if sym in sym_pnls: pnls.extend(sym_pnls[sym])
        if not pnls: continue
        a  = np.array(pnls)
        w  = a[a>0]; l = a[a<0]
        pf = w.sum()/abs(l.sum()) if len(l) else float("inf")
        print(f"  {', '.join(fold):<38}  {len(a):5d}  {(a>0).mean():6.1%}  {pf:5.2f}  {a.mean()*100:+8.4f}%")


def regime_split(sym_entries):
    print(f"\n{'='*55}")
    print(f"  5. REGIME SPLIT")
    print(f"{'='*55}")
    buckets = {"gap_up":[],"gap_down":[],"gap_flat":[],
               "morning":[],"midday":[],"afternoon":[],
               "long":[],"short":[]}
    for sym, entries in sym_entries.items():
        for e in entries:
            pnl = sim_pnl(e)
            gap = e.get("gap", 0)
            if   gap >  0.005: buckets["gap_up"].append(pnl)
            elif gap < -0.005: buckets["gap_down"].append(pnl)
            else:              buckets["gap_flat"].append(pnl)
            t = e.get("time","12:00")
            if   t < "11:00": buckets["morning"].append(pnl)
            elif t < "13:00": buckets["midday"].append(pnl)
            else:              buckets["afternoon"].append(pnl)
            buckets[e["side"]].append(pnl)
    print(f"  {'Regime':<12}  {'n':>5}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    print(f"  {'-'*12}  {'-'*5}  {'-'*6}  {'-'*5}  {'-'*9}")
    for name, pnls in buckets.items():
        if not pnls: continue
        a  = np.array(pnls)
        w  = a[a>0]; l = a[a<0]
        pf = w.sum()/abs(l.sum()) if len(l) else float("inf")
        print(f"  {name:<12}  {len(a):5d}  {(a>0).mean():6.1%}  {pf:5.2f}  {a.mean()*100:+8.4f}%")


def kill_switch(arr):
    print(f"\n{'='*55}")
    print(f"  6. KILL-SWITCH ANALYSIS")
    print(f"{'='*55}")
    rules = [
        ("No kill switch",        None, None),
        ("Stop after 3 losses",   3,    None),
        ("Stop after 4 losses",   4,    None),
        ("Stop after 5 losses",   5,    None),
        ("Stop after -1.5% day",  None, -0.015),
        ("Stop after -2.0% day",  None, -0.020),
    ]
    TRADES_PER_DAY = 36
    print(f"  {'Rule':<26}  {'Used':>6}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    print(f"  {'-'*26}  {'-'*6}  {'-'*6}  {'-'*5}  {'-'*9}")
    for label, max_streak, daily_limit in rules:
        filtered = []; streak = 0; day_pnl = 0.0; day_cnt = 0
        for p in arr:
            if day_cnt > 0 and day_cnt % TRADES_PER_DAY == 0:
                streak = 0; day_pnl = 0.0
            if max_streak and streak >= max_streak:
                day_cnt += 1; continue
            if daily_limit and day_pnl <= daily_limit:
                day_cnt += 1; continue
            filtered.append(p); day_pnl += p; day_cnt += 1
            streak = streak+1 if p < 0 else 0
        a  = np.array(filtered)
        w  = a[a>0]; l = a[a<0]
        pf = w.sum()/abs(l.sum()) if len(l) else float("inf")
        print(f"  {label:<26}  {len(a):6d}  {(a>0).mean():6.1%}  {pf:5.2f}  {a.mean()*100:+8.4f}%")


def main():
    print("BOOF50 Full Validation  (tests 3–6)")
    print(f"TP={TP*100:.2f}%  SL={SL*100:.2f}%\n")

    all_pnls  = []
    sym_pnls  = {}
    sym_entries = {}
    for sym in SYMBOLS:
        path = f"boof32_data_{sym}.csv"
        if not os.path.exists(path):
            print(f"  {sym}: no cache, skipping"); continue
        print(f"  {sym}...", end=" ", flush=True)
        df = load_csv(sym)
        df = add_vwap(df)
        entries = collect_entries(df,"long") + collect_entries(df,"short")
        pnls    = [sim_pnl(e) for e in entries]
        all_pnls.extend(pnls)
        sym_pnls[sym]    = pnls
        sym_entries[sym] = entries
        w = [p for p in pnls if p > 0]
        print(f"n={len(pnls)}  WR={len(w)/len(pnls):.1%}  EV={np.mean(pnls)*100:+.4f}%")

    arr = np.array(all_pnls)
    n   = len(arr)
    print(f"\nTotal trades: {n}")
    base_pf = arr[arr>0].sum()/abs(arr[arr<0].sum())
    print(f"Base WR={(arr>0).mean():.1%}  PF={base_pf:.3f}  EV={arr.mean()*100:+.4f}%")

    slippage_test(arr)
    oos_folds(sym_pnls)
    regime_split(sym_entries)
    kill_switch(arr)
    print(f"\n{'='*55}\n  Done.\n{'='*55}\n")


if __name__ == "__main__":
    main()
