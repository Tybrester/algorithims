"""
Walk-Forward Backtest
TRAIN: data/train/ (2022-2024) — rank all 72 symbols, pick top 30 by EV
FREEZE: lock universe
TEST:  data/1m/   (Dec 2025 - Jun 2026) — run identical logic, report cold results
Strategy: Early (9:30-10:00) + RVOL>=1.5 + Gap>1% + 2hr fixed hold
"""
import os, warnings
import pandas as pd
import numpy as np
warnings.filterwarnings("ignore")

TRAIN_DIR   = "data/train"
TEST_DIR    = "data/1m"
RVOL_WINDOW = 20
TOP_N       = 30

ALL_SYMS = sorted(set([
    'AAPL','ACN','AMZN','APH','AXP','BKNG','BLK','BSX','CAT','CVX',
    'DHR','GS','HD','HON','IBM','KO','LRCX','MCHP','MDT','META',
    'MS','MSFT','ORCL','PANW','PCAR','PG','PLTR','PM','SO','TXN',
    'INTU','ABNB','JPM','GOOGL','GE','NVDA','ABT','TSLA','SCHW','BAC',
    'AMAT','FTNT','CL','USB','FAST','ABBV','AMD',
    'COIN','CRWD','SMCI','ENPH','FCX','MU','ON','NXPI','MRVL',
    'AVGO','ARM','NOW','WDAY','ADSK','CRM','DASH','DDOG','HOOD',
    'RIVN','MRNA','RBLX','TTWO','LCID','FANG','APP'
]))

def run_backtest(sym, data_dir, label=""):
    fname = os.path.join(data_dir, f"{sym}.parquet")
    if not os.path.exists(fname):
        return []
    try:
        df = pd.read_parquet(fname)
    except:
        return []

    df = df.copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")
    df.columns = [c.lower() for c in df.columns]

    df["_date"] = df.index.date
    grouped = {d: g.drop(columns="_date") for d, g in df.groupby("_date")}
    dates   = sorted(grouped.keys())

    daily_vol = {}
    for d, g in grouped.items():
        s = g.between_time("09:30","15:59")
        daily_vol[d] = s["volume"].sum() if len(s) else 0
    vol_series = pd.Series(daily_vol).sort_index()

    rows = []
    for i, cur_date in enumerate(dates):
        if i == 0: continue
        prev_date = dates[i-1]

        prev_day  = grouped.get(prev_date, pd.DataFrame())
        prev_sess = prev_day.between_time("09:30","15:59") if len(prev_day) else prev_day
        pdh = prev_sess["high"].max() if len(prev_sess) else None

        cur_day = grouped.get(cur_date, pd.DataFrame())
        pre     = cur_day.between_time("04:00","09:29") if len(cur_day) else cur_day
        pmh     = pre["high"].max() if len(pre) else None

        sess = cur_day.between_time("09:30","15:59") if len(cur_day) else cur_day
        if len(sess) < 30: continue

        prev_close = prev_sess["close"].iloc[-1] if len(prev_sess) else None
        open_price = sess["open"].iloc[0]         if len(sess)      else None
        if prev_close is None or open_price is None: continue

        gap_pct = (open_price - prev_close) / prev_close * 100
        if gap_pct <= 1.0: continue
        gap_bucket = "gap_1_2" if gap_pct < 2.0 else "gap_2plus"

        # RVOL
        idx_loc   = vol_series.index.get_loc(cur_date)
        past_vols = vol_series.iloc[max(0, idx_loc-RVOL_WINDOW):idx_loc]
        avg_vol   = past_vols.mean() if len(past_vols) > 0 else 0
        rvol      = daily_vol.get(cur_date, 0) / avg_vol if avg_vol > 0 else 0
        if rvol < 1.5: continue

        # First break in 9:30-10:00
        sess_early = sess.between_time("09:30","10:00")
        break_bar  = None
        for j in range(1, len(sess_early)):
            pc = sess_early.iloc[j-1]["close"]
            cc = sess_early.iloc[j]["close"]
            if (pdh and pc <= pdh and cc > pdh) or (pmh and pc <= pmh and cc > pmh):
                ts  = sess_early.index[j]
                pos = sess.index.get_loc(ts)
                if isinstance(pos, slice): pos = pos.start
                break_bar = pos
                break

        if break_bar is None: continue

        ep  = sess.iloc[break_bar]["close"]
        fut = sess.iloc[break_bar+1:]
        bars_2h = fut.iloc[:120]
        if len(bars_2h) == 0: continue
        ret_2h = float((bars_2h.iloc[-1]["close"] - ep) / ep * 100)

        rows.append({
            "sym":        sym,
            "date":       str(cur_date),
            "gap_pct":    round(gap_pct, 3),
            "gap_bucket": gap_bucket,
            "rvol":       round(rvol, 2),
            "ret_2h":     round(ret_2h, 4),
        })
    return rows

# ── PHASE 1: TRAIN (2022-2024) ────────────────────────────────────────────────
print("=" * 70)
print("PHASE 1 — TRAINING (2022-2024)")
print("=" * 70)

train_rows = []
for i, sym in enumerate(ALL_SYMS, 1):
    rows = run_backtest(sym, TRAIN_DIR, "TRAIN")
    train_rows.extend(rows)
    if rows:
        ev = round(pd.DataFrame(rows)["ret_2h"].mean(), 3)
        print(f"  [{i}/{len(ALL_SYMS)}] {sym}: {len(rows)} trades  EV={ev:+.3f}%")
    else:
        print(f"  [{i}/{len(ALL_SYMS)}] {sym}: 0 trades (filtered out)")

train_df = pd.DataFrame(train_rows)
train_df.to_csv("walkforward_train.csv", index=False)

# Rank symbols by EV, pick top 30
sym_stats = []
for sym, g in train_df.groupby("sym"):
    n   = len(g)
    ev  = g.ret_2h.mean()
    wr  = (g.ret_2h > 0).mean() * 100
    w   = g[g.ret_2h > 0].ret_2h.sum()
    l   = g[g.ret_2h < 0].ret_2h.abs().sum()
    pf  = w/l if l > 0 else 999.0
    sym_stats.append((sym, n, ev, wr, pf))

sym_stats.sort(key=lambda x: x[2], reverse=True)

print(f"\n{'='*70}")
print("TRAINING RANKINGS — all candidates")
print(f"{'='*70}")
print(f"  {'Sym':<7} {'N':>5}  {'EV':>8}  {'WR':>6}  {'PF':>6}")
print("  "+"-"*35)
for sym, n, ev, wr, pf in sym_stats:
    mark = " <-- SELECTED" if sym_stats.index((sym,n,ev,wr,pf)) < TOP_N else ""
    print(f"  {sym:<7} {n:>5}  {ev:>+7.3f}%  {wr:>5.1f}%  {pf:>6.3f}{mark}")

# Freeze top 30
frozen = [s for s, n, ev, wr, pf in sym_stats[:TOP_N] if n >= 5]
if len(frozen) < TOP_N:
    # fill with next ranked if some had too few trades
    extras = [s for s, n, ev, wr, pf in sym_stats if s not in frozen and n >= 3]
    frozen = (frozen + extras)[:TOP_N]

print(f"\nFROZEN UNIVERSE ({len(frozen)} symbols):")
print(f"  {', '.join(frozen)}")

# ── PHASE 2: TEST (Dec 2025 - Jun 2026) ──────────────────────────────────────
print(f"\n{'='*70}")
print("PHASE 2 — TEST (Dec 2025 - Jun 2026) — COLD, frozen universe only")
print(f"{'='*70}")

test_rows = []
for i, sym in enumerate(frozen, 1):
    rows = run_backtest(sym, TEST_DIR, "TEST")
    test_rows.extend(rows)
    if rows:
        ev = round(pd.DataFrame(rows)["ret_2h"].mean(), 3)
        print(f"  [{i}/{len(frozen)}] {sym}: {len(rows)} trades  EV={ev:+.3f}%")
    else:
        print(f"  [{i}/{len(frozen)}] {sym}: 0 trades")

test_df = pd.DataFrame(test_rows)
test_df.to_csv("walkforward_test.csv", index=False)

# ── RESULTS ───────────────────────────────────────────────────────────────────
def report(df, label):
    df = df.dropna(subset=["ret_2h"])
    if len(df) == 0:
        print(f"  {label}: no data")
        return
    n   = len(df)
    wr  = (df.ret_2h > 0).mean() * 100
    ev  = df.ret_2h.mean()
    med = df.ret_2h.median()
    w   = df[df.ret_2h > 0].ret_2h.sum()
    l   = df[df.ret_2h < 0].ret_2h.abs().sum()
    pf  = w/l if l else 999.0
    tot = df.ret_2h.sum()
    tdays = df.date.nunique(); twks = tdays/5
    print(f"  {label}")
    print(f"    N={n}  WR={wr:.1f}%  EV={ev:+.3f}%  Median={med:+.3f}%  PF={pf:.3f}  TotRet={tot:+.2f}%")
    print(f"    Trades/week: {n/twks:.1f}  ({tdays} trading days)")
    for bucket, bl in [("gap_1_2","  Gap 1-2%"),("gap_2plus","  Gap >2%")]:
        sub = df[df.gap_bucket==bucket]
        if len(sub) == 0: continue
        bn=len(sub); bwr=(sub.ret_2h>0).mean()*100; bev=sub.ret_2h.mean()
        bw=sub[sub.ret_2h>0].ret_2h.sum(); bl2=sub[sub.ret_2h<0].ret_2h.abs().sum()
        bpf=bw/bl2 if bl2 else 999.0
        print(f"    {bl}: N={bn}  WR={bwr:.1f}%  EV={bev:+.3f}%  PF={bpf:.3f}")

print(f"\n{'='*70}")
print("FINAL RESULTS")
print(f"{'='*70}")
report(train_df[train_df.sym.isin(frozen)], "TRAIN 2022-2024 (frozen syms only)")
print()
report(test_df, "TEST  2025-2026 (out-of-sample, cold)")

# Per symbol test results
print(f"\n{'='*70}")
print("PER SYMBOL — TEST period, sorted by EV")
print(f"{'='*70}")
print(f"  {'Sym':<7} {'N':>4}  {'WR':>6}  {'EV':>8}  {'PF':>6}  {'Tot':>8}")
print("  "+"-"*45)
sym_test = []
for sym, g in test_df.groupby("sym"):
    n=len(g); wr=(g.ret_2h>0).mean()*100; ev=g.ret_2h.mean()
    w=g[g.ret_2h>0].ret_2h.sum(); l=g[g.ret_2h<0].ret_2h.abs().sum()
    pf=w/l if l else 999.0; tot=g.ret_2h.sum()
    sym_test.append((sym,n,wr,ev,pf,tot))
sym_test.sort(key=lambda x: x[3], reverse=True)
for sym,n,wr,ev,pf,tot in sym_test:
    mark = " +" if ev>0 else "  "
    print(f"  {sym:<7} {n:>4}  {wr:>5.1f}%  {ev:>+7.3f}%  {pf:>6.3f}  {tot:>+7.2f}%{mark}")
