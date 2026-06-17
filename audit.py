"""
Audit the refined results for lookahead bias and logic bugs
1. Print sample trades with full detail
2. Check if ret_2h could be using future data from wrong index
3. Verify gap/RVOL calculations on specific dates
4. Cross-check a few trades manually
"""
import warnings
warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
import os

df = pd.read_csv("refined_results.csv")
print(f"Total trades: {len(df)} | Syms: {df.sym.nunique()}")
print(f"WR 2hr: {(df.ret_2h>0).sum()}/{len(df)} = {(df.ret_2h>0).mean()*100:.1f}%")
print(f"Avg EV: {df.ret_2h.mean():+.3f}%")
print(f"\nSample trades (first 20):")
print(df[["sym","date","gap_pct","rvol","ret_2h","std_result","std_ret"]].head(20).to_string())

print(f"\n\n--- MANUAL AUDIT: ORCL (7 trades, top volume) ---")
orcl = df[df.sym=="ORCL"]
print(orcl[["date","gap_pct","rvol","ret_2h","std_result"]].to_string())

# Now manually re-run ONE trade from scratch to verify
print(f"\n\n--- MANUAL RECHECK: ORCL first trade ---")
DATA_DIR = "data/1m"
raw = pd.read_parquet(os.path.join(DATA_DIR, "ORCL.parquet"))
raw.index = pd.to_datetime(raw.index)
if raw.index.tz is None:
    raw.index = raw.index.tz_localize("America/New_York")
else:
    raw.index = raw.index.tz_convert("America/New_York")
raw.columns = [c.lower() for c in raw.columns]

first_date = pd.to_datetime(orcl.iloc[0]["date"]).date()
print(f"Checking date: {first_date}")

raw["_date"] = raw.index.date
grouped = {d: g.drop(columns="_date") for d, g in raw.groupby("_date")}
dates = sorted(grouped.keys())
idx = dates.index(first_date)
prev_date = dates[idx-1]

prev_sess = grouped[prev_date].between_time("09:30","15:59")
cur_day   = grouped[first_date]
pre       = cur_day.between_time("04:00","09:29")
sess      = cur_day.between_time("09:30","15:59")

pdh = prev_sess["high"].max()
pmh = pre["high"].max() if len(pre) else None
prev_close = prev_sess["close"].iloc[-1]
open_price = sess["open"].iloc[0]
gap_pct = (open_price - prev_close) / prev_close * 100

print(f"PDH: {pdh:.4f}  PMH: {f'{pmh:.4f}' if pmh else 'N/A'}")
print(f"Prev close: {prev_close:.4f}  Open: {open_price:.4f}  Gap: {gap_pct:.3f}%")

# find break
sess_early = sess.between_time("09:30","10:00")
for j in range(1, len(sess_early)):
    pc = sess_early.iloc[j-1]["close"]
    cc = sess_early.iloc[j]["close"]
    bp = (pc <= pdh and cc > pdh) or (pmh and pc <= pmh and cc > pmh)
    if bp:
        ts = sess_early.index[j]
        pos = sess.index.get_loc(ts)
        if isinstance(pos, slice): pos = pos.start
        ep = sess.iloc[pos]["close"]
        print(f"Break at {ts.strftime('%H:%M')}  entry price: {ep:.4f}")
        fut = sess.iloc[pos+1:]
        ret_2h_bars = fut.iloc[:120]
        if len(ret_2h_bars):
            ret_2h = (ret_2h_bars.iloc[-1]["close"] - ep) / ep * 100
            exit_time = ret_2h_bars.index[-1].strftime("%H:%M")
            print(f"2hr exit bar index: {len(ret_2h_bars)} bars later at {exit_time}")
            print(f"Exit price: {ret_2h_bars.iloc[-1]['close']:.4f}")
            print(f"ret_2h calculated: {ret_2h:+.3f}%")
            print(f"ret_2h in CSV:     {orcl.iloc[0]['ret_2h']:+.3f}%")
        break

# Check distribution of ret_2h more carefully
print(f"\n--- RET_2H DISTRIBUTION CHECK ---")
print(f"Min: {df.ret_2h.min():.3f}%  Max: {df.ret_2h.max():.3f}%")
print(f"Std: {df.ret_2h.std():.3f}%")
print(f"\nAll ret_2h values sorted:")
vals = sorted(df.ret_2h.dropna().tolist())
for v in vals:
    print(f"  {v:+.3f}%")

# Check: is WR high because bad days (RVOL filter) already removed losers?
# i.e. are we selecting on outcome?
print(f"\n--- RVOL distribution of trades ---")
print(df.rvol.describe())
print(f"\n--- Gap pct distribution ---")
print(df.gap_pct.describe())
