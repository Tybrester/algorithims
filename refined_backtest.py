"""
Refined backtest:
- Remove 18 losers from previous run
- Keep 30 winners
- Add 10 new: INTU, ABNB, JPM, GOOGL, GE, NVDA, ABT, TSLA, SCHW, BAC
Same filters: Early + RVOL>=1.5 + Gap>1% + 2hr hold
"""
import os, warnings
import pandas as pd
import numpy as np
warnings.filterwarnings("ignore")

DATA_DIR    = "data/1m"
RVOL_WINDOW = 20
TP = 0.010
SL = 0.005

KEEPERS = [
    'AAPL','ACN','AMZN','APH','AXP','BKNG','BLK','BSX','CAT','CVX',
    'DHR','GS','HD','HON','IBM','KO','LRCX','MCHP','MDT','META',
    'MS','MSFT','ORCL','PANW','PCAR','PG','PLTR','PM','SO','TXN'
]
NEW_10 = ['INTU','ABNB','JPM','GOOGL','GE','NVDA','ABT','TSLA','SCHW','BAC']
UNIVERSE = sorted(set(KEEPERS + NEW_10))
print(f"Universe: {len(UNIVERSE)} symbols ({len(KEEPERS)} kept + {len(NEW_10)} new)\n")

def rr_result(fut, ep):
    tpp = ep * (1 + TP); slp = ep * (1 - SL)
    for _, bar in fut.iterrows():
        if bar["high"] >= tpp: return "TP"
        if bar["low"]  <= slp: return "SL"
    return "EOD"

def fixed_hold(fut, ep, minutes):
    bars = fut.iloc[:minutes]
    return float((bars.iloc[-1]["close"] - ep) / ep * 100) if len(bars) > 0 else None

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

        # RVOL filter
        idx_loc   = vol_series.index.get_loc(cur_date)
        past_vols = vol_series.iloc[max(0, idx_loc - RVOL_WINDOW):idx_loc]
        avg_vol   = past_vols.mean() if len(past_vols) > 0 else 0
        rvol      = daily_vol.get(cur_date, 0) / avg_vol if avg_vol > 0 else 0
        if rvol < 1.5: continue

        # First break — early only (9:30-10:00)
        sess_morning = sess.between_time("09:30","10:00")
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
                break_bar = pos
                level_val = min(v for v in [pdh if broke_pdh else None, pmh if broke_pmh else None] if v is not None)
                break

        if break_bar is None: continue

        ep  = sess.iloc[break_bar]["close"]
        fut = sess.iloc[break_bar+1:].copy()
        eod = float((sess.iloc[-1]["close"] - ep) / ep * 100) if len(fut) else 0.0

        res = rr_result(fut, ep)
        ret = (TP*100) if res=="TP" else ((-SL*100) if res=="SL" else eod)

        rows.append({
            "sym":        sym,
            "date":       str(cur_date),
            "gap_pct":    round(gap_pct, 3),
            "gap_bucket": gap_bucket,
            "rvol":       round(rvol, 2),
            "is_new":     sym in NEW_10,
            "std_result": res,
            "std_ret":    round(ret, 4),
            "ret_30m":    round(v, 3) if (v := fixed_hold(fut, ep, 30))  is not None else None,
            "ret_1h":     round(v, 3) if (v := fixed_hold(fut, ep, 60))  is not None else None,
            "ret_2h":     round(v, 3) if (v := fixed_hold(fut, ep, 120)) is not None else None,
            "ret_3h":     round(v, 3) if (v := fixed_hold(fut, ep, 180)) is not None else None,
        })
    return rows

# ── Run ───────────────────────────────────────────────────────────────────────
all_rows = []
for i, sym in enumerate(UNIVERSE, 1):
    fname = os.path.join(DATA_DIR, f"{sym}.parquet")
    if not os.path.exists(fname):
        print(f"  [{i}/{len(UNIVERSE)}] {sym}: no data")
        continue
    try:
        rows = run_symbol(sym, pd.read_parquet(fname))
        all_rows.extend(rows)
        tag = " (NEW)" if sym in NEW_10 else ""
        print(f"  [{i}/{len(UNIVERSE)}] {sym}{tag}: {len(rows)} trades")
    except Exception as e:
        print(f"  [{i}/{len(UNIVERSE)}] {sym}: ERROR {e}")

df = pd.DataFrame(all_rows)
df.to_csv("refined_results.csv", index=False)

# ── Summary ───────────────────────────────────────────────────────────────────
def s(sub, label):
    sub = sub.dropna(subset=["ret_2h"])
    if len(sub) == 0: return
    n=len(sub); wr=(sub.ret_2h>0).sum()/n*100; ev=sub.ret_2h.mean()
    med=sub.ret_2h.median()
    w=sub[sub.ret_2h>0].ret_2h.sum(); l=sub[sub.ret_2h<0].ret_2h.abs().sum()
    pf=w/l if l else 999.0; tot=sub.ret_2h.sum()
    print(f"  {label:<42} N={n:>3}  WR={wr:>5.1f}%  EV={ev:>+6.3f}%  Med={med:>+6.3f}%  PF={pf:.3f}  Tot={tot:>+7.2f}%")

trading_days  = df.date.nunique()
trading_weeks = trading_days / 5

print(f"\n{'='*100}")
print(f"REFINED UNIVERSE — {df.sym.nunique()} symbols | Early+RVOL>=1.5+Gap>1%+2hr Hold")
print(f"{'='*100}")
s(df,             "ALL")
s(df[~df.is_new], "Kept 30 (proven)")
s(df[df.is_new],  "New 10")
print()
s(df[df.gap_bucket=="gap_1_2"],  "Gap 1-2%")
s(df[df.gap_bucket=="gap_2plus"],"Gap >2%")

print(f"\n  Trades/week: {len(df)/trading_weeks:.1f}  "
      f"(kept {len(df[~df.is_new])/trading_weeks:.1f}  +  new {len(df[df.is_new])/trading_weeks:.1f})")

# ── Hold time ladder ──────────────────────────────────────────────────────────
print(f"\n{'='*100}")
print("HOLD TIME LADDER — full refined universe")
print("="*100)
for col, lbl in [("ret_30m","30m"),("ret_1h","1hr"),("ret_2h","2hr"),("ret_3h","3hr")]:
    sub = df.dropna(subset=[col])
    n=len(sub); wr=(sub[col]>0).sum()/n*100; ev=sub[col].mean()
    med=sub[col].median()
    w=sub[sub[col]>0][col].sum(); l=sub[sub[col]<0][col].abs().sum()
    pf=w/l if l else 999.0; tot=sub[col].sum()
    print(f"  {lbl}   N={n:>3}  WR={wr:>5.1f}%  EV={ev:>+6.3f}%  Med={med:>+6.3f}%  PF={pf:.3f}  Tot={tot:>+7.2f}%")

# ── Per symbol ────────────────────────────────────────────────────────────────
print(f"\n{'='*100}")
print("PER SYMBOL — 2hr hold, sorted by EV")
print("="*100)
print(f"  {'Sym':<7} {'Tag':<5} {'N':>4}  {'WR':>6}  {'EV':>8}  {'Med':>8}  {'PF':>6}  {'Tot':>8}")
print("  "+"-"*58)
sym_rows = []
for sym, g in df.groupby("sym"):
    g2 = g.dropna(subset=["ret_2h"])
    if len(g2) == 0: continue
    n=len(g2); wr=(g2.ret_2h>0).sum()/n*100; ev=g2.ret_2h.mean()
    med=g2.ret_2h.median()
    w=g2[g2.ret_2h>0].ret_2h.sum(); l=g2[g2.ret_2h<0].ret_2h.abs().sum()
    pf=w/l if l else 999.0; tot=g2.ret_2h.sum()
    sym_rows.append((sym, g2.is_new.iloc[0], n, wr, ev, med, pf, tot))

sym_rows.sort(key=lambda x: x[4], reverse=True)
for sym, is_new, n, wr, ev, med, pf, tot in sym_rows:
    tag  = "NEW" if is_new else "   "
    mark = " +" if ev > 0 else "  "
    print(f"  {sym:<7} {tag}  {n:>4}  {wr:>5.1f}%  {ev:>+7.3f}%  {med:>+7.3f}%  {pf:>6.3f}  {tot:>+7.2f}%{mark}")

# ── Return distribution ───────────────────────────────────────────────────────
print(f"\n{'='*100}")
print("RETURN DISTRIBUTION — 2hr hold, full universe")
print("="*100)
sub = df.dropna(subset=["ret_2h"])
for lbl, mask in [("<-2%", sub.ret_2h<-2), ("-2 to -1%",(sub.ret_2h>=-2)&(sub.ret_2h<-1)),
                   ("-1 to -0.5%",(sub.ret_2h>=-1)&(sub.ret_2h<-0.5)),
                   ("-0.5 to 0%",(sub.ret_2h>=-0.5)&(sub.ret_2h<0)),
                   ("0 to +0.5%",(sub.ret_2h>=0)&(sub.ret_2h<0.5)),
                   ("+0.5 to +1%",(sub.ret_2h>=0.5)&(sub.ret_2h<1)),
                   ("+1 to +2%",(sub.ret_2h>=1)&(sub.ret_2h<2)),
                   (">+2%", sub.ret_2h>=2)]:
    cnt = mask.sum()
    bar = "#" * int(cnt/max(1,len(sub))*50)
    print(f"  {lbl:<14} {cnt:>3} ({cnt/len(sub)*100:>4.1f}%)  {bar}")
