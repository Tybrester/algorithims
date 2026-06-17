"""
Expanded universe backtest — original 46 + 15 best new symbols
New additions: SO, AMAT, PANW, MCHP, ABNB, FAST, PM, MS, DHR, HD, USB, ACN, FTNT, CL, BSX
Same logic: Early (9:30-10:00) + RVOL >= 1.5 + Gap > 1% + 2hr hold
Also runs TP=1%/SL=0.5% for comparison
"""
import os, warnings
import pandas as pd
import numpy as np
warnings.filterwarnings("ignore")

DATA_DIR   = "data/1m"
RVOL_WINDOW = 20
TP = 0.010
SL = 0.005

# Original 46 + 15 new additions picked by best EV + fundamentals
NEW_SYMS = ["SO","AMAT","PANW","MCHP","ABNB","FAST","PM","MS","DHR","HD","USB","ACN","FTNT","CL","BSX"]
ORIGINAL = [
    'AAPL','ABT','AMZN','APH','AXP','BAC','BKNG','CAT','CSCO','CVX',
    'FCX','GOOGL','HON','IBM','INTU','JNJ','JPM','KO','MDT','META',
    'MSFT','NFLX','NEE','NVDA','PG','RTX','SCHW','T','TSLA',
    'TXN','UNH','V','VZ','WMT','XOM','LRCX','GS','AVGO',
    'PLTR','GE','PCAR','UNP','CME','BLK','ORCL','NOC'
]
UNIVERSE = list(set(ORIGINAL + NEW_SYMS))
print(f"Universe: {len(UNIVERSE)} symbols ({len(NEW_SYMS)} new added)\n")

def rr_result(fut, ep, tp, sl):
    tpp = ep * (1 + tp)
    slp = ep * (1 - sl)
    for _, bar in fut.iterrows():
        if bar["high"] >= tpp: return "TP"
        if bar["low"]  <= slp: return "SL"
    return "EOD"

def fixed_hold(fut, ep, minutes):
    bars = fut.iloc[:minutes]
    if len(bars) == 0: return None
    return float((bars.iloc[-1]["close"] - ep) / ep * 100)

def run_symbol(sym, df):
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
        prev_date = dates[i - 1]

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
        past_vols = vol_series.iloc[max(0, idx_loc - RVOL_WINDOW):idx_loc]
        avg_vol   = past_vols.mean() if len(past_vols) > 0 else 0
        rvol      = daily_vol.get(cur_date, 0) / avg_vol if avg_vol > 0 else 0
        if rvol < 1.5: continue  # RVOL filter

        # First break before noon
        sess_morning = sess.between_time("09:30","12:00")
        break_bar = None
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
                # Early filter: 9:30-10:00 only
                if ts.hour >= 10: break
                break_bar = pos
                if broke_pdh and broke_pmh:
                    level_val = min(pdh, pmh)
                elif broke_pdh:
                    level_val = pdh
                else:
                    level_val = pmh
                break

        if break_bar is None: continue

        ep  = sess.iloc[break_bar]["close"]
        fut = sess.iloc[break_bar+1:].copy()
        eod = float((sess.iloc[-1]["close"] - ep) / ep * 100) if len(fut) else 0.0

        res = rr_result(fut, ep, TP, SL)
        ret = (TP*100) if res=="TP" else ((-SL*100) if res=="SL" else eod)

        rows.append({
            "sym":        sym,
            "date":       str(cur_date),
            "gap_pct":    round(gap_pct, 3),
            "gap_bucket": gap_bucket,
            "rvol":       round(rvol, 2),
            "is_new":     sym in NEW_SYMS,
            "std_result": res,
            "std_ret":    round(ret, 4),
            "ret_2h":     round(fixed_hold(fut, ep, 120), 3) if fixed_hold(fut, ep, 120) is not None else None,
            "ret_1h":     round(fixed_hold(fut, ep, 60),  3) if fixed_hold(fut, ep, 60)  is not None else None,
        })
    return rows

# ── Run ───────────────────────────────────────────────────────────────────────
all_rows = []
for i, sym in enumerate(sorted(UNIVERSE), 1):
    fname = os.path.join(DATA_DIR, f"{sym}.parquet")
    if not os.path.exists(fname):
        print(f"  [{i}/{len(UNIVERSE)}] {sym}: no data file, skipping")
        continue
    try:
        raw  = pd.read_parquet(fname)
        rows = run_symbol(sym, raw)
        all_rows.extend(rows)
        tag = " (NEW)" if sym in NEW_SYMS else ""
        print(f"  [{i}/{len(UNIVERSE)}] {sym}{tag}: {len(rows)} trades")
    except Exception as e:
        print(f"  [{i}/{len(UNIVERSE)}] {sym}: ERROR {e}")

df = pd.DataFrame(all_rows)
df.to_csv("expanded_results.csv", index=False)

# ── Summary ───────────────────────────────────────────────────────────────────
def stats_2h(sub, label):
    sub = sub.dropna(subset=["ret_2h"])
    if len(sub) == 0:
        print(f"  {label:<40} N=   0")
        return
    n   = len(sub)
    wr  = (sub.ret_2h > 0).sum() / n * 100
    ev  = sub.ret_2h.mean()
    med = sub.ret_2h.median()
    w   = sub[sub.ret_2h > 0].ret_2h.sum()
    l   = sub[sub.ret_2h < 0].ret_2h.abs().sum()
    pf  = w / l if l else 999.0
    tot = sub.ret_2h.sum()
    tpw = (sub.std_result == "TP").sum()
    slw = (sub.std_result == "SL").sum()
    rr_wr = tpw/(tpw+slw)*100 if tpw+slw else 0
    print(f"  {label:<42} N={n:>4}  WR={wr:>5.1f}%  EV={ev:>+6.3f}%  Med={med:>+6.3f}%  PF={pf:.3f}  Tot={tot:>+7.2f}%  |  TP/SL WR={rr_wr:.1f}%")

orig = df[~df.is_new]
news = df[df.is_new]

print(f"\n{'='*110}")
print(f"EXPANDED UNIVERSE — Early + RVOL>=1.5 + Gap>1% + 2hr Hold")
print(f"{'='*110}")
stats_2h(df,   "ALL (original + new)")
stats_2h(orig, "Original 46 syms only")
stats_2h(news, "New 15 syms only")

print()
for bucket, lbl in [("gap_1_2","Gap 1-2%"),("gap_2plus","Gap >2%")]:
    stats_2h(df[df.gap_bucket==bucket], f"ALL — {lbl}")
    stats_2h(df[(df.gap_bucket==bucket) & (~df.is_new)], f"  Original — {lbl}")
    stats_2h(df[(df.gap_bucket==bucket) & (df.is_new)],  f"  New syms — {lbl}")

# ── Trade frequency ───────────────────────────────────────────────────────────
trading_days  = df["date"].nunique()
trading_weeks = trading_days / 5
print(f"\n{'='*110}")
print(f"TRADE FREQUENCY")
print(f"{'='*110}")
print(f"  Total trades:      {len(df)}")
print(f"  Trading days:      {trading_days}")
print(f"  Trading weeks:     {trading_weeks:.1f}")
print(f"  Trades/week (all): {len(df)/trading_weeks:.1f}")
print(f"  Trades/week (new): {len(news)/trading_weeks:.1f}")

# ── Per symbol ────────────────────────────────────────────────────────────────
print(f"\n{'='*110}")
print(f"PER SYMBOL — 2hr hold EV, sorted best to worst")
print(f"{'='*110}")
print(f"  {'Sym':<7} {'New':>4}  {'N':>4}  {'WR':>6}  {'EV':>8}  {'Med':>8}  {'PF':>6}  {'Tot':>8}")
print("  "+"-"*60)
sym_rows = []
for sym, g in df.groupby("sym"):
    g2 = g.dropna(subset=["ret_2h"])
    if len(g2) == 0: continue
    n   = len(g2)
    wr  = (g2.ret_2h > 0).sum() / n * 100
    ev  = g2.ret_2h.mean()
    med = g2.ret_2h.median()
    w   = g2[g2.ret_2h > 0].ret_2h.sum()
    l   = g2[g2.ret_2h < 0].ret_2h.abs().sum()
    pf  = w/l if l else 999.0
    tot = g2.ret_2h.sum()
    is_new = g2.is_new.iloc[0]
    sym_rows.append((sym, is_new, n, wr, ev, med, pf, tot))

sym_rows.sort(key=lambda x: x[4], reverse=True)
for sym, is_new, n, wr, ev, med, pf, tot in sym_rows:
    tag  = " NEW" if is_new else "    "
    mark = " +" if ev > 0 else "  "
    print(f"  {sym:<7} {tag}  {n:>4}  {wr:>5.1f}%  {ev:>+7.3f}%  {med:>+7.3f}%  {pf:>6.3f}  {tot:>+7.2f}%{mark}")
