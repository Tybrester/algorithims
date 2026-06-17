"""
Gap + PDH/PMH Breakout Backtest
Entry filter: gap > 1% on open
Signal: first PDH or PMH break (whichever comes first)
TP/SL combos: 1%/0.5%, 1.5%/0.5%, 2%/1%
Split results by gap bucket: 1-2% vs >2%
"""
import os, warnings
import pandas as pd
import numpy as np
warnings.filterwarnings("ignore")

DATA_DIR = "data/1m"

SCENARIOS = [
    ("TP1.0_SL0.5",  0.010, 0.005),
    ("TP1.5_SL0.5",  0.015, 0.005),
    ("TP2.0_SL1.0",  0.020, 0.010),
]

def rr_result(fut, ep, tp_pct, sl_pct):
    tp = ep * (1 + tp_pct)
    sl = ep * (1 - sl_pct)
    for _, bar in fut.iterrows():
        if bar["high"] >= tp:
            return "TP"
        if bar["low"] <= sl:
            return "SL"
    return "EOD"

def eod_ret(fut, ep):
    if len(fut) == 0:
        return 0.0
    return float((fut.iloc[-1]["close"] - ep) / ep * 100)

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
    rows = []

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
        open_price = sess["open"].iloc[0] if len(sess) else None
        if prev_close is None or open_price is None:
            continue

        gap_pct = (open_price - prev_close) / prev_close * 100

        # ── Filter: gap must be > 1% ──────────────────────────────────────────
        if gap_pct <= 1.0:
            continue

        gap_bucket = "gap_1_2" if gap_pct < 2.0 else "gap_2plus"

        # ── Find first break of PDH or PMH before noon ────────────────────────
        sess_morning = sess.between_time("09:30", "12:00")
        entry_bar = None
        level_hit = None
        level_val = None

        for j in range(1, len(sess_morning)):
            prev_c = sess_morning.iloc[j-1]["close"]
            cur_c  = sess_morning.iloc[j]["close"]

            broke_pdh = (pdh is not None) and (prev_c <= pdh) and (cur_c > pdh)
            broke_pmh = (pmh is not None) and (prev_c <= pmh) and (cur_c > pmh)

            if broke_pdh or broke_pmh:
                ts = sess_morning.index[j]
                pos = sess.index.get_loc(ts)
                if isinstance(pos, slice):
                    pos = pos.start
                entry_bar = pos
                # label which level
                if broke_pdh and broke_pmh:
                    level_hit = "BOTH"
                    level_val = min(pdh, pmh)
                elif broke_pdh:
                    level_hit = "PDH"
                    level_val = pdh
                else:
                    level_hit = "PMH"
                    level_val = pmh
                break

        if entry_bar is None:
            continue

        ep  = sess.iloc[entry_bar]["close"]
        et  = sess.index[entry_bar]
        fut = sess.iloc[entry_bar+1:].copy()
        er  = eod_ret(fut, ep)

        row = {
            "sym":        sym,
            "date":       str(cur_date),
            "gap_pct":    round(gap_pct, 3),
            "gap_bucket": gap_bucket,
            "level":      level_hit,
            "level_val":  round(level_val, 4),
            "entry_time": et.strftime("%H:%M"),
            "entry_price":round(ep, 4),
            "ret_eod":    round(er, 3),
        }

        for name, tp, sl in SCENARIOS:
            result = rr_result(fut, ep, tp, sl)
            if result == "TP":
                ret = tp * 100
            elif result == "SL":
                ret = -sl * 100
            else:
                ret = er
            row[f"{name}_result"] = result
            row[f"{name}_ret"]    = round(ret, 4)

        rows.append(row)
    return rows

# ── Run ───────────────────────────────────────────────────────────────────────
files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith(".parquet")])
print(f"Gap + PDH/PMH Breakout Backtest — {len(files)} symbols\n")

all_rows = []
for i, fname in enumerate(files, 1):
    sym = fname.replace(".parquet","")
    try:
        df = pd.read_parquet(os.path.join(DATA_DIR, fname))
        if len(df) < 500:
            continue
        rows = run(sym, df)
        all_rows.extend(rows)
        print(f"[{i}/{len(files)}] {sym}: {len(rows)} qualifying days")
    except Exception as e:
        import traceback
        print(f"[{i}/{len(files)}] {sym}: ERROR {e}")
        traceback.print_exc()

df = pd.DataFrame(all_rows)
df.to_csv("gap_breakout_results.csv", index=False)
print(f"\nTotal qualifying entries: {len(df)} across {df.sym.nunique()} symbols")

# ── Summary ───────────────────────────────────────────────────────────────────
def print_scenario(label, sub, name, tp, sl):
    if len(sub) == 0:
        return
    res_col = f"{name}_result"
    ret_col = f"{name}_ret"
    tp_n    = (sub[res_col] == "TP").sum()
    sl_n    = (sub[res_col] == "SL").sum()
    eod_n   = (sub[res_col] == "EOD").sum()
    total   = len(sub)
    wr      = tp_n / (tp_n + sl_n) * 100 if (tp_n + sl_n) > 0 else 0
    ev      = sub[ret_col].mean()
    pf_w    = sub[sub[ret_col] > 0][ret_col].sum()
    pf_l    = sub[sub[ret_col] < 0][ret_col].abs().sum()
    pf      = pf_w / pf_l if pf_l > 0 else float("inf")
    print(f"  {label:<18} N={total:>4}  TP={tp_n:>4}({tp_n/total*100:>4.1f}%)  SL={sl_n:>4}({sl_n/total*100:>4.1f}%)  EOD={eod_n:>4}({eod_n/total*100:>4.1f}%)  WR={wr:>5.1f}%  EV={ev:>+5.3f}%  PF={pf:.3f}")

print(f"\n{'='*90}")
print("RESULTS BY GAP BUCKET")
print(f"{'='*90}")

for bucket, blabel in [("all","ALL GAPS >1%"), ("gap_1_2","Gap 1-2%"), ("gap_2plus","Gap >2%")]:
    if bucket == "all":
        sub = df
    else:
        sub = df[df.gap_bucket == bucket]
    print(f"\n── {blabel} ({len(sub)} entries) ──────────────────────────────────────────────")
    for name, tp, sl in SCENARIOS:
        lbl = f"TP={tp*100:.1f}% SL={sl*100:.1f}%"
        print_scenario(lbl, sub, name, tp, sl)

# ── By level hit ──────────────────────────────────────────────────────────────
print(f"\n{'='*90}")
print("RESULTS BY LEVEL (PDH vs PMH) — all gap >1%")
print(f"{'='*90}")
for lvl in ["PDH","PMH","BOTH"]:
    sub = df[df.level == lvl]
    if len(sub) < 5:
        continue
    print(f"\n── {lvl} ({len(sub)} entries) ──")
    for name, tp, sl in SCENARIOS:
        lbl = f"TP={tp*100:.1f}% SL={sl*100:.1f}%"
        print_scenario(lbl, sub, name, tp, sl)

# ── Best symbols ──────────────────────────────────────────────────────────────
print(f"\n{'='*90}")
print("TOP SYMBOLS — TP1.5_SL0.5, gap >1%, min 5 entries")
print(f"{'='*90}")
g = df.groupby("sym").agg(
    N=("TP1.5_SL0.5_ret","count"),
    avg_ret=("TP1.5_SL0.5_ret","mean"),
    wr=("TP1.5_SL0.5_result", lambda x: (x=="TP").sum() / ((x=="TP").sum()+(x=="SL").sum()) * 100 if ((x=="TP").sum()+(x=="SL").sum()) > 0 else 0),
).query("N >= 5").sort_values("avg_ret", ascending=False)
print(f"  {'Sym':<7} {'N':>4}  {'AvgRet':>8}  {'WR':>6}")
print("  "+"-"*30)
for sym, r in g.iterrows():
    print(f"  {sym:<7} {int(r.N):>4}  {r.avg_ret:>+7.3f}%  {r.wr:>5.1f}%")

print(f"\nSaved to gap_breakout_results.csv")
