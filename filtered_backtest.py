"""
Filtered Gap + PDH/PMH Backtest
Filters: MCap > $100B, AvgVol > 5M, ATR% < 5%, Gap > 1%
"""
import os, warnings, time
import pandas as pd
import numpy as np
import yfinance as yf
warnings.filterwarnings("ignore")

DATA_DIR = "data/1m"

SCENARIOS = [
    ("TP1.0_SL0.5",  0.010, 0.005),
    ("TP1.5_SL0.5",  0.015, 0.005),
    ("TP2.0_SL1.0",  0.020, 0.010),
]

# ── Step 1: compute ATR% and avg volume from raw data ────────────────────────
print("Computing ATR% and volume filters from 1m data...")
mkt_rows = []
files = [f for f in os.listdir(DATA_DIR) if f.endswith(".parquet")]
for fname in files:
    sym = fname.replace(".parquet", "")
    try:
        raw = pd.read_parquet(os.path.join(DATA_DIR, fname))
        raw.index = pd.to_datetime(raw.index)
        if raw.index.tz is None:
            raw.index = raw.index.tz_localize("America/New_York")
        else:
            raw.index = raw.index.tz_convert("America/New_York")
        raw.columns = [c.lower() for c in raw.columns]

        sess  = raw.between_time("09:30", "15:59")
        daily = sess.resample("D").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
        if len(daily) < 10:
            continue

        daily["tr"] = np.maximum(daily["high"] - daily["low"],
                      np.maximum(abs(daily["high"] - daily["close"].shift(1)),
                                 abs(daily["low"]  - daily["close"].shift(1))))
        atr_pct  = daily["tr"].rolling(14).mean().iloc[-1] / daily["close"].iloc[-1] * 100
        avg_vol  = daily["volume"].mean()

        mkt_rows.append({"sym": sym, "atr_pct": atr_pct, "avg_volume": avg_vol})
    except:
        pass

mkt = pd.DataFrame(mkt_rows).set_index("sym")

# ── Step 2: fetch market cap from yfinance ────────────────────────────────────
print(f"Fetching market cap for {len(mkt)} symbols...")
mcap = {}
for sym in mkt.index:
    try:
        info = yf.Ticker(sym).info
        mcap[sym] = info.get("marketCap", 0) or 0
        time.sleep(0.08)
    except:
        mcap[sym] = 0

mkt["market_cap"] = pd.Series(mcap)

# ── Step 3: apply universe filters ───────────────────────────────────────────
universe = mkt[
    (mkt["market_cap"]  >= 100e9) &
    (mkt["avg_volume"]  >= 5e6)   &
    (mkt["atr_pct"]     <  5.0)
].index.tolist()

print(f"\nUniverse after filters: {len(universe)} symbols")
print(f"  MCap > $100B, AvgVol > 5M, ATR% < 5%")
print(f"  Symbols: {', '.join(sorted(universe))}\n")

dropped = [s for s in mkt.index if s not in universe]
print(f"Dropped ({len(dropped)}): {', '.join(sorted(dropped))}\n")

# ── Step 4: run backtest on filtered universe ─────────────────────────────────
def rr_result(fut, ep, tp_pct, sl_pct):
    tp = ep * (1 + tp_pct)
    sl = ep * (1 - sl_pct)
    for _, bar in fut.iterrows():
        if bar["high"] >= tp: return "TP"
        if bar["low"]  <= sl: return "SL"
    return "EOD"

def run(sym, df):
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")
    df.columns = [c.lower() for c in df.columns]

    df["_date"] = df.index.date
    grouped = {d: g.drop(columns="_date") for d, g in df.groupby("_date")}
    df = df.drop(columns="_date")

    dates = sorted(grouped.keys())
    rows  = []

    for i, cur_date in enumerate(dates):
        if i == 0:
            continue
        prev_date = dates[i - 1]

        prev_day  = grouped.get(prev_date, pd.DataFrame())
        prev_sess = prev_day.between_time("09:30","15:59") if len(prev_day) else prev_day
        pdh = prev_sess["high"].max() if len(prev_sess) else None

        cur_day = grouped.get(cur_date, pd.DataFrame())
        pre     = cur_day.between_time("04:00","09:29") if len(cur_day) else cur_day
        pmh     = pre["high"].max() if len(pre) else None

        sess = cur_day.between_time("09:30","15:59") if len(cur_day) else cur_day
        if len(sess) < 30:
            continue

        prev_close = prev_sess["close"].iloc[-1] if len(prev_sess) else None
        open_price = sess["open"].iloc[0]        if len(sess)      else None
        if prev_close is None or open_price is None:
            continue

        gap_pct = (open_price - prev_close) / prev_close * 100
        if gap_pct <= 1.0:
            continue

        gap_bucket = "gap_1_2" if gap_pct < 2.0 else "gap_2plus"

        # first break of PDH or PMH before noon
        sess_morning = sess.between_time("09:30","12:00")
        entry_bar = None
        level_hit = None
        level_val = None

        for j in range(1, len(sess_morning)):
            prev_c = sess_morning.iloc[j-1]["close"]
            cur_c  = sess_morning.iloc[j]["close"]
            broke_pdh = (pdh is not None) and (prev_c <= pdh) and (cur_c > pdh)
            broke_pmh = (pmh is not None) and (prev_c <= pmh) and (cur_c > pmh)
            if broke_pdh or broke_pmh:
                ts  = sess_morning.index[j]
                pos = sess.index.get_loc(ts)
                if isinstance(pos, slice): pos = pos.start
                entry_bar = pos
                if broke_pdh and broke_pmh:
                    level_hit, level_val = "BOTH", min(pdh, pmh)
                elif broke_pdh:
                    level_hit, level_val = "PDH", pdh
                else:
                    level_hit, level_val = "PMH", pmh
                break

        if entry_bar is None:
            continue

        ep  = sess.iloc[entry_bar]["close"]
        et  = sess.index[entry_bar]
        fut = sess.iloc[entry_bar+1:].copy()
        eod = float((sess.iloc[-1]["close"] - ep) / ep * 100) if len(fut) else 0.0

        row = {
            "sym":        sym,
            "date":       str(cur_date),
            "gap_pct":    round(gap_pct, 3),
            "gap_bucket": gap_bucket,
            "level":      level_hit,
            "entry_time": et.strftime("%H:%M"),
            "ret_eod":    round(eod, 3),
        }
        for name, tp, sl in SCENARIOS:
            res = rr_result(fut, ep, tp, sl)
            ret = (tp * 100) if res == "TP" else ((-sl * 100) if res == "SL" else eod)
            row[f"{name}_result"] = res
            row[f"{name}_ret"]    = round(ret, 4)
        rows.append(row)
    return rows

print("Running backtest on filtered universe...")
all_rows = []
for i, sym in enumerate(sorted(universe), 1):
    fname = os.path.join(DATA_DIR, f"{sym}.parquet")
    if not os.path.exists(fname):
        continue
    try:
        df   = pd.read_parquet(fname)
        rows = run(sym, df)
        all_rows.extend(rows)
        print(f"  [{i}/{len(universe)}] {sym}: {len(rows)} qualifying days")
    except Exception as e:
        print(f"  [{i}/{len(universe)}] {sym}: ERROR {e}")

df = pd.DataFrame(all_rows)
df.to_csv("filtered_backtest_results.csv", index=False)
print(f"\nTotal entries: {len(df)} | Symbols: {df.sym.nunique()}")

# ── Step 5: summary ───────────────────────────────────────────────────────────
def summary(sub, label):
    print(f"\n  {label} (N={len(sub)}, {sub.sym.nunique()} syms)")
    print(f"  {'Scenario':<18}  {'TP%':>6}  {'SL%':>6}  {'EOD%':>6}  {'WR':>6}  {'EV':>8}  {'PF':>6}  {'TotRet':>9}")
    print("  " + "-"*70)
    for name, tp, sl in SCENARIOS:
        rc  = f"{name}_result"
        rv  = f"{name}_ret"
        tp_n  = (sub[rc]=="TP").sum()
        sl_n  = (sub[rc]=="SL").sum()
        eod_n = (sub[rc]=="EOD").sum()
        n     = len(sub)
        wr    = tp_n/(tp_n+sl_n)*100 if (tp_n+sl_n)>0 else 0
        ev    = sub[rv].mean()
        wins  = sub[sub[rv]>0][rv].sum()
        loss  = sub[sub[rv]<0][rv].abs().sum()
        pf    = wins/loss if loss>0 else 999.0
        tot   = sub[rv].sum()
        print(f"  TP={tp*100:.1f}% SL={sl*100:.1f}%        {tp_n/n*100:>5.1f}%  {sl_n/n*100:>5.1f}%  {eod_n/n*100:>5.1f}%  {wr:>5.1f}%  {ev:>+7.3f}%  {pf:>6.3f}  {tot:>+8.2f}%")

print(f"\n{'='*80}")
print("RESULTS — filtered universe (MCap>100B, Vol>5M, ATR<5%)")
print(f"{'='*80}")
for bucket, label in [("all","ALL GAP >1%"), ("gap_1_2","Gap 1-2%"), ("gap_2plus","Gap >2%")]:
    sub = df if bucket=="all" else df[df.gap_bucket==bucket]
    summary(sub, label)

# ── Per symbol ────────────────────────────────────────────────────────────────
print(f"\n{'='*80}")
print("PER SYMBOL — TP1.5%/SL0.5%, ALL GAP >1%, sorted by EV")
print(f"{'='*80}")
print(f"  {'Sym':<7} {'N':>4}  {'TP':>4}  {'SL':>4}  {'WR':>6}  {'EV':>8}  {'TotRet':>9}")
print("  "+"-"*50)
sym_rows = []
for sym, g in df.groupby("sym"):
    tp_n = (g["TP1.5_SL0.5_result"]=="TP").sum()
    sl_n = (g["TP1.5_SL0.5_result"]=="SL").sum()
    wr   = tp_n/(tp_n+sl_n)*100 if (tp_n+sl_n)>0 else 0
    ev   = g["TP1.5_SL0.5_ret"].mean()
    tot  = g["TP1.5_SL0.5_ret"].sum()
    sym_rows.append((sym, len(g), tp_n, sl_n, wr, ev, tot))
sym_rows.sort(key=lambda x: x[5], reverse=True)
for sym, n, tp_n, sl_n, wr, ev, tot in sym_rows:
    mark = " +" if ev > 0 else "  "
    print(f"  {sym:<7} {n:>4}  {tp_n:>4}  {sl_n:>4}  {wr:>5.1f}%  {ev:>+7.3f}%  {tot:>+8.2f}%{mark}")
