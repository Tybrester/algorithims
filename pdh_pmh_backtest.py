"""
PDH vs PMH Breakout Backtest — 3-4 Hour Hold
Universe: Top 100 SP500 + Top 50 Nasdaq (150 symbols)
Data: 6 months of 1m bars from data/1m/<SYM>.parquet

Signal:
  Variant A — price closes a 1m bar above Previous Day High (PDH)
  Variant B — price closes a 1m bar above Pre-Market High (PMH)

Entry: first bar that closes above level, between 09:30-12:00 ET only
Hold:  210 minutes (3.5 hours) fixed, or close at 15:59 if hit first
Exit:  also test TP=2% / SL=1% overlay

Output: per-symbol and aggregate stats for both variants
"""
import os, warnings
import pandas as pd
import numpy as np
warnings.filterwarnings("ignore")

DATA_DIR = "data/1m"
RESULTS_FILE = "pdh_pmh_results.csv"

# ── Config ────────────────────────────────────────────────────────────────────
HOLD_BARS    = 210          # 3.5 hours in minutes
ENTRY_START  = "09:30"
ENTRY_CUTOFF = "12:00"      # no entries after noon
MARKET_OPEN  = "09:30"
MARKET_CLOSE = "15:59"
PREMARKET_START = "04:00"
PREMARKET_END   = "09:29"
TP_PCT = 0.02               # 2% take profit
SL_PCT = 0.01               # 1% stop loss

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_pdh(day_df, prev_date):
    """Previous day's high from regular session."""
    prev = day_df[day_df.index.date == prev_date]
    sess = prev.between_time("09:30", "15:59")
    if len(sess) == 0:
        return None
    return sess["high"].max()

def get_pmh(day_df, cur_date):
    """Pre-market high for current date (04:00-09:29)."""
    pre = day_df[day_df.index.date == cur_date].between_time("04:00", "09:29")
    if len(pre) == 0:
        return None
    return pre["high"].max()

def simulate_trade(bars, entry_idx, entry_price, hold_bars, tp, sl):
    """Run trade from entry bar, return pct return."""
    end_idx = min(entry_idx + hold_bars, len(bars) - 1)
    for i in range(entry_idx + 1, end_idx + 1):
        hi = bars.iloc[i]["high"]
        lo = bars.iloc[i]["low"]
        ts = bars.index[i]
        # force close at market end
        if ts.strftime("%H:%M") >= MARKET_CLOSE:
            exit_price = bars.iloc[i]["close"]
            return (exit_price - entry_price) / entry_price
        # TP hit
        if hi >= entry_price * (1 + tp):
            return tp
        # SL hit
        if lo <= entry_price * (1 - sl):
            return -sl
    # time exit
    exit_price = bars.iloc[end_idx]["close"]
    return (exit_price - entry_price) / entry_price

def backtest_symbol(sym, df):
    """Run both PDH and PMH variants for one symbol."""
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")

    df.columns = [c.lower() for c in df.columns]

    trading_dates = sorted(set(df.between_time("09:30","15:59").index.date))
    if len(trading_dates) < 5:
        return [], []

    trades_pdh, trades_pmh = [], []

    for i, cur_date in enumerate(trading_dates):
        if i == 0:
            continue
        prev_date = trading_dates[i - 1]

        # full day slice (includes pre-market)
        day_slice = df[df.index.date == cur_date]
        if len(day_slice) < 10:
            continue

        # levels
        pdh = get_pdh(df, prev_date)
        pmh = get_pmh(df, cur_date)

        # session bars for entry scanning
        session = day_slice.between_time(ENTRY_START, ENTRY_CUTOFF)
        if len(session) < 5:
            continue

        # ── Variant A: PDH ────────────────────────────────────────────────────
        if pdh is not None:
            triggered_a = False
            for idx_pos in range(1, len(session)):
                bar = session.iloc[idx_pos]
                prev_bar = session.iloc[idx_pos - 1]
                # close crosses above PDH (wasn't above before)
                if prev_bar["close"] <= pdh and bar["close"] > pdh:
                    entry_price = bar["close"]
                    # find position in full df
                    bar_ts = session.index[idx_pos]
                    full_pos = df.index.get_loc(bar_ts)
                    if isinstance(full_pos, slice):
                        full_pos = full_pos.start
                    ret = simulate_trade(df, full_pos, entry_price, HOLD_BARS, TP_PCT, SL_PCT)
                    trades_pdh.append({
                        "sym": sym, "date": str(cur_date),
                        "entry_time": str(bar_ts.time()),
                        "entry_price": round(entry_price, 4),
                        "pdh": round(pdh, 4),
                        "ret_pct": round(ret * 100, 4),
                        "win": ret > 0,
                    })
                    triggered_a = True
                    break  # one trade per day

        # ── Variant B: PMH ────────────────────────────────────────────────────
        if pmh is not None:
            for idx_pos in range(1, len(session)):
                bar = session.iloc[idx_pos]
                prev_bar = session.iloc[idx_pos - 1]
                if prev_bar["close"] <= pmh and bar["close"] > pmh:
                    entry_price = bar["close"]
                    bar_ts = session.index[idx_pos]
                    full_pos = df.index.get_loc(bar_ts)
                    if isinstance(full_pos, slice):
                        full_pos = full_pos.start
                    ret = simulate_trade(df, full_pos, entry_price, HOLD_BARS, TP_PCT, SL_PCT)
                    trades_pmh.append({
                        "sym": sym, "date": str(cur_date),
                        "entry_time": str(bar_ts.time()),
                        "entry_price": round(entry_price, 4),
                        "pmh": round(pmh, 4),
                        "ret_pct": round(ret * 100, 4),
                        "win": ret > 0,
                    })
                    break

    return trades_pdh, trades_pmh

# ── Main ──────────────────────────────────────────────────────────────────────
files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith(".parquet")])
print(f"Found {len(files)} symbol files in {DATA_DIR}/")
print(f"Running PDH vs PMH breakout backtest (3.5hr hold, TP=2%, SL=1%)...\n")

all_pdh, all_pmh = [], []

for i, fname in enumerate(files, 1):
    sym = fname.replace(".parquet", "")
    path = os.path.join(DATA_DIR, fname)
    try:
        df = pd.read_parquet(path)
        if len(df) < 1000:
            print(f"[{i}/{len(files)}] {sym}: too few bars ({len(df)}) — skip")
            continue
        pdh_trades, pmh_trades = backtest_symbol(sym, df)
        all_pdh.extend(pdh_trades)
        all_pmh.extend(pmh_trades)
        print(f"[{i}/{len(files)}] {sym}: PDH={len(pdh_trades)} trades | PMH={len(pmh_trades)} trades")
    except Exception as e:
        print(f"[{i}/{len(files)}] {sym}: ERROR — {e}")

# ── Results ───────────────────────────────────────────────────────────────────
pdh_df = pd.DataFrame(all_pdh)
pmh_df = pd.DataFrame(all_pmh)

def print_summary(name, df):
    if len(df) == 0:
        print(f"\n{name}: No trades.")
        return
    print(f"\n{'='*60}")
    print(f"VARIANT {name}")
    print(f"{'='*60}")
    print(f"  Total trades:  {len(df)}")
    print(f"  Symbols:       {df.sym.nunique()}")
    print(f"  Win rate:      {df.win.mean()*100:.1f}%")
    print(f"  Avg return:    {df.ret_pct.mean():+.3f}%")
    print(f"  Median return: {df.ret_pct.median():+.3f}%")
    print(f"  Avg winner:    {df[df.win].ret_pct.mean():+.3f}%")
    print(f"  Avg loser:     {df[~df.win].ret_pct.mean():+.3f}%")
    wins  = df[df.win].ret_pct.sum()
    loss  = df[~df.win].ret_pct.abs().sum()
    pf    = wins / loss if loss > 0 else float("inf")
    print(f"  Profit factor: {pf:.3f}")
    print(f"  Total return:  {df.ret_pct.sum():+.2f}%")
    print(f"\n  Per-symbol breakdown (>=5 trades, sorted by avg ret):")
    g = df.groupby("sym").agg(
        N=("ret_pct","count"),
        avg=("ret_pct","mean"),
        wr=("win", lambda x: x.mean()*100),
        total=("ret_pct","sum"),
    ).query("N >= 5").sort_values("avg", ascending=False)
    print(f"  {'Sym':<7} {'N':>4}  {'Avg':>7}  {'WR':>6}  {'Total':>8}")
    print(f"  {'-'*40}")
    for sym, r in g.iterrows():
        print(f"  {sym:<7} {int(r.N):>4}  {r.avg:>+6.3f}%  {r.wr:>5.1f}%  {r.total:>+7.2f}%")

print_summary("A — PDH Breakout", pdh_df)
print_summary("B — PMH Breakout", pmh_df)

# ── Head to head ──────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("HEAD TO HEAD SUMMARY")
print(f"{'='*60}")
print(f"{'Metric':<20} {'PDH':>12} {'PMH':>12}")
print("-"*46)
for label, va, vb in [
    ("Trades",        len(pdh_df),                     len(pmh_df)),
    ("Win Rate %",    round(pdh_df.win.mean()*100,1) if len(pdh_df) else 0,
                      round(pmh_df.win.mean()*100,1) if len(pmh_df) else 0),
    ("Avg Return %",  round(pdh_df.ret_pct.mean(),3) if len(pdh_df) else 0,
                      round(pmh_df.ret_pct.mean(),3) if len(pmh_df) else 0),
    ("Median Ret %",  round(pdh_df.ret_pct.median(),3) if len(pdh_df) else 0,
                      round(pmh_df.ret_pct.median(),3) if len(pmh_df) else 0),
]:
    print(f"{label:<20} {str(va):>12} {str(vb):>12}")

# ── Save ──────────────────────────────────────────────────────────────────────
pdh_df["variant"] = "PDH"
pmh_df["variant"] = "PMH"
combined = pd.concat([pdh_df, pmh_df], ignore_index=True)
combined.to_csv(RESULTS_FILE, index=False)
print(f"\nSaved all trades to {RESULTS_FILE}")
