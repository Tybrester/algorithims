"""
BOOF50 Realism Study
1. Execution realism  — slippage, spread, delayed fill
2. Regime dependence  — gap up/down, time of day, long vs short
3. MFE/MAE            — is 0.75% TP leaving money on the table?
"""
import os
import numpy as np
import pandas as pd

SYMBOLS = [
    "TSLA","AMD","APP","COIN","HOOD",
    "SMCI","UPST","META","MSFT","NVDA",
    "MSTR","PLTR","CRWD","AAPL","AMZN"
]
BASE_TP  = 0.0075
BASE_SL  = 0.005
MAX_BARS = 120
TZ       = "America/New_York"


# ── Data loading ──────────────────────────────────────────────────────────────

def load_csv(sym):
    path = f"boof32_data_{sym}.csv"
    df = pd.read_csv(path, low_memory=False,
                     usecols=lambda c: c in {"timestamp","datetime","open","high","low","close","volume"})
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
    bounds = np.concatenate([[0], np.where(dates[1:] != dates[:-1])[0] + 1, [len(df)]])
    cum_pv = np.empty(len(df)); cum_vol = np.empty(len(df))
    for s, e in zip(bounds[:-1], bounds[1:]):
        cum_pv[s:e]  = np.cumsum(pv[s:e])
        cum_vol[s:e] = np.cumsum(vol[s:e])
    df["vwap"] = cum_pv / np.where(cum_vol == 0, 1, cum_vol)
    return df


def collect_entries(df):
    entries = []
    dates    = sorted(df["date"].unique())
    date_idx = {d: i for i, d in enumerate(dates)}
    # pre-extract numpy arrays for speed
    df_dates = df["date"].values
    df_times = df["time"].values
    df_close = df["close"].values
    df_high  = df["high"].values
    df_low   = df["low"].values
    df_vwap  = df["vwap"].values

    for date, day in df.groupby("date"):
        idx = np.where(df_dates == date)[0]
        full_times = df_times[idx]
        # gap calc
        di = date_idx[date]; gap = 0.0
        if di > 0:
            prev_idx = np.where(df_dates == dates[di-1])[0]
            open_mask = full_times == "09:30"
            if len(prev_idx) and open_mask.any():
                prev_cls = df_close[prev_idx[-1]]
                open_px  = df_close[idx[open_mask][0]]
                if prev_cls != 0:
                    gap = (open_px - prev_cls) / prev_cls
        # filter to trading window
        mask = (full_times >= "09:45") & (full_times <= "14:00")
        widx = idx[mask]
        if len(widx) < MAX_BARS + 10:
            continue
        close = df_close[widx]; high = df_high[widx]
        low   = df_low[widx];   vwap = df_vwap[widx]
        times = df_times[widx]
        n = len(widx)
        for side in ["long", "short"]:
            for i in range(5, n - MAX_BARS - 2):
                if side == "long":
                    hold  = bool((close[i:i+5] > vwap[i:i+5]).all())
                    cross = close[i-1] < vwap[i-1] and close[i] > vwap[i] and hold
                else:
                    hold  = bool((close[i:i+5] < vwap[i:i+5]).all())
                    cross = close[i-1] > vwap[i-1] and close[i] < vwap[i] and hold
                if cross:
                    entries.append({
                        "ep":    close[i],
                        "side":  side,
                        "highs": high[i:i+MAX_BARS].copy(),
                        "lows":  low[i:i+MAX_BARS].copy(),
                        "time":  times[i],
                        "gap":   gap,
                    })
    return entries


# ── Trade simulation ──────────────────────────────────────────────────────────

def sim_trade(e, tp, sl, slip=0.0, delay=0):
    """
    slip  = one-way slippage as fraction (e.g. 0.0002 = 0.02%)
    delay = bars to delay entry (fill on next bar open)
    """
    highs = e["highs"]; lows = e["lows"]
    if len(highs) == 0: return 0.0, 0.0, 0.0

    # delayed fill: entry price is close of bar `delay`
    if delay > 0 and delay < len(highs):
        ep = (highs[delay] + lows[delay]) / 2  # mid of delay bar
        highs = highs[delay:]; lows = lows[delay:]
    else:
        ep = e["ep"]

    # slippage worsens entry
    if e["side"] == "long":  ep = ep * (1 + slip)
    else:                     ep = ep * (1 - slip)

    mfe = mae = 0.0
    for b in range(len(highs)):
        if e["side"] == "long":
            mfe = max(mfe, (highs[b] - ep) / ep)
            mae = max(mae, (ep - lows[b])  / ep)
            if highs[b] >= ep * (1 + tp): return tp  - slip, mfe, mae
            if lows[b]  <= ep * (1 - sl): return -sl - slip, mfe, mae
        else:
            mfe = max(mfe, (ep - lows[b])  / ep)
            mae = max(mae, (highs[b] - ep) / ep)
            if lows[b]  <= ep * (1 - tp): return tp  - slip, mfe, mae
            if highs[b] >= ep * (1 + sl): return -sl - slip, mfe, mae

    if e["side"] == "long": pnl = (highs[-1] - ep) / ep
    else:                    pnl = (ep - lows[-1])  / ep
    return pnl - slip, mfe, mae


def stats(pnls):
    a = np.array(pnls)
    w = a[a > 0]; l = a[a < 0]
    pf = w.sum() / abs(l.sum()) if len(l) and l.sum() != 0 else float("inf")
    return len(a), (a > 0).mean(), pf, a.mean() * 100


def sec(t): print(f"\n{'='*60}\n  {t}\n{'='*60}")


# ── 1. Execution realism ──────────────────────────────────────────────────────

def test_execution(entries):
    sec("1. EXECUTION REALISM")

    scenarios = [
        ("Base (no cost)",         0.0000, 0),
        ("Spread 0.02%",           0.0002, 0),
        ("Spread 0.05%",           0.0005, 0),
        ("Spread 0.10%",           0.0010, 0),
        ("Spread 0.15%",           0.0015, 0),
        ("Spread 0.20%",           0.0020, 0),
        ("1-bar delay, no slip",   0.0000, 1),
        ("1-bar delay + 0.05%",    0.0005, 1),
        ("2-bar delay + 0.05%",    0.0005, 2),
    ]
    print(f"\n  {'Scenario':<28}  {'n':>5}  {'WR':>6}  {'PF':>5}  {'EV':>9}  Pass?")
    print(f"  {'-'*28}  {'-'*5}  {'-'*6}  {'-'*5}  {'-'*9}  {'-'*5}")
    for label, slip, delay in scenarios:
        pnls = [sim_trade(e, BASE_TP, BASE_SL, slip, delay)[0] for e in entries]
        n, wr, pf, ev = stats(pnls)
        ok = "✓" if pf >= 1.20 and ev > 0 else "✗"
        print(f"  {label:<28}  {n:5d}  {wr:6.1%}  {pf:5.2f}  {ev:+8.4f}%  {ok}")


# ── 2. Regime dependence ──────────────────────────────────────────────────────

def test_regime(entries):
    sec("2. REGIME DEPENDENCE")

    buckets = {
        "gap_up   (>+0.5%)":  [],
        "gap_flat (±0.5%)":   [],
        "gap_down (<-0.5%)":  [],
        "morning  (09:45-11)":[], 
        "midday   (11-13)":   [],
        "afternoon(13-14)":   [],
        "long":               [],
        "short":              [],
    }
    for e in entries:
        pnl = sim_trade(e, BASE_TP, BASE_SL)[0]
        gap = e.get("gap", 0)
        t   = e.get("time", "12:00")
        if   gap >  0.005: buckets["gap_up   (>+0.5%)"].append(pnl)
        elif gap < -0.005: buckets["gap_down (<-0.5%)"].append(pnl)
        else:              buckets["gap_flat (±0.5%)"].append(pnl)
        if   t < "11:00":  buckets["morning  (09:45-11)"].append(pnl)
        elif t < "13:00":  buckets["midday   (11-13)"].append(pnl)
        else:              buckets["afternoon(13-14)"].append(pnl)
        buckets[e["side"]].append(pnl)

    print(f"\n  {'Regime':<24}  {'n':>5}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    print(f"  {'-'*24}  {'-'*5}  {'-'*6}  {'-'*5}  {'-'*9}")
    for name, pnls in buckets.items():
        if not pnls: continue
        n, wr, pf, ev = stats(pnls)
        print(f"  {name:<24}  {n:5d}  {wr:6.1%}  {pf:5.2f}  {ev:+8.4f}%")


# ── 3. MFE / MAE — is 0.75% TP leaving money on the table? ───────────────────

def sim_timing(e):
    """Returns (bar_to_mfe, bar_to_mae, bar_to_tp, bar_to_sl) — None if not hit."""
    ep = e["ep"]; hs = e["highs"]; ls = e["lows"]
    bar_mfe = bar_mae = bar_tp = bar_sl = None
    peak_fav = peak_adv = 0.0
    for b in range(len(hs)):
        if e["side"] == "long":
            fav = (hs[b] - ep) / ep
            adv = (ep - ls[b]) / ep
            if fav > peak_fav: peak_fav = fav; bar_mfe = b + 1
            if adv > peak_adv: peak_adv = adv; bar_mae = b + 1
            if bar_tp is None and hs[b] >= ep * (1 + BASE_TP): bar_tp = b + 1
            if bar_sl is None and ls[b] <= ep * (1 - BASE_SL): bar_sl = b + 1
        else:
            fav = (ep - ls[b]) / ep
            adv = (hs[b] - ep) / ep
            if fav > peak_fav: peak_fav = fav; bar_mfe = b + 1
            if adv > peak_adv: peak_adv = adv; bar_mae = b + 1
            if bar_tp is None and ls[b] <= ep * (1 - BASE_TP): bar_tp = b + 1
            if bar_sl is None and hs[b] >= ep * (1 + BASE_SL): bar_sl = b + 1
        if bar_tp and bar_sl: break
    return bar_mfe, bar_mae, bar_tp, bar_sl


def test_timing(entries):
    sec("4. TIME TO MFE / MAE / TP / SL  (bars from entry, 1 bar = 1 min)")

    mfe_bars = []; mae_bars = []; tp_bars = []; sl_bars = []
    tp_sl_pairs = []
    for e in entries:
        bm, ba, bt, bs = sim_timing(e)
        if bm: mfe_bars.append(bm)
        if ba: mae_bars.append(ba)
        if bt: tp_bars.append(bt)
        if bs: sl_bars.append(bs)
        tp_sl_pairs.append((bt, bs))

    def dist(label, arr, hit_n, total):
        a = np.array(arr)
        print(f"\n  {label}  (hit {hit_n}/{total} = {hit_n/total:.1%})")
        print(f"  {'Percentile':<12}  {'Minutes':>8}")
        print(f"  {'-'*12}  {'-'*8}")
        for p in [10, 25, 50, 75, 90, 95]:
            v = int(np.percentile(a, p))
            print(f"  p{p:<11}  {v:>7d} min")
        print(f"  {'avg':<12}  {a.mean():>7.1f} min")

    total = len(entries)
    dist("Time to MFE (peak favor before close)", mfe_bars, len(mfe_bars), total)
    dist("Time to MAE (peak adverse before close)", mae_bars, len(mae_bars), total)
    dist("Time to TP  (+0.75% hit)", tp_bars, len(tp_bars), total)
    dist("Time to SL  (-0.50% hit)", sl_bars, len(sl_bars), total)

    tp_first = sum(1 for t, s in tp_sl_pairs if t and s and t < s)
    sl_first = sum(1 for t, s in tp_sl_pairs if t and s and s < t)
    tp_only  = sum(1 for t, s in tp_sl_pairs if t and not s)
    sl_only  = sum(1 for t, s in tp_sl_pairs if s and not t)
    neither  = sum(1 for t, s in tp_sl_pairs if not t and not s)
    print(f"\n  Outcome breakdown:")
    print(f"  TP hit first (winner):   {tp_first+tp_only:5d}  ({(tp_first+tp_only)/total:.1%})")
    print(f"  SL hit first (loser):    {sl_first+sl_only:5d}  ({(sl_first+sl_only)/total:.1%})")
    print(f"  Neither hit (time exit): {neither:5d}  ({neither/total:.1%})")
    if tp_bars and sl_bars:
        print(f"\n  Avg bars to TP: {np.mean(tp_bars):.1f} min  |  Avg bars to SL: {np.mean(sl_bars):.1f} min")
        print(f"  Median to TP:   {np.median(tp_bars):.0f} min  |  Median to SL:   {np.median(sl_bars):.0f} min")


def test_mfe_mae(entries):
    sec("3. MFE / MAE ANALYSIS")

    all_mfe = []; all_mae = []; wins = []; losses_e = []
    tp_levels = [0.0025, 0.0050, 0.0075, 0.0100, 0.0150, 0.0200]

    for e in entries:
        pnl, mfe, mae = sim_trade(e, BASE_TP, BASE_SL)
        all_mfe.append(mfe)
        all_mae.append(mae)
        if pnl > 0: wins.append((mfe, mae))
        else:       losses_e.append((mfe, mae))

    mfe_arr = np.array(all_mfe) * 100
    mae_arr = np.array(all_mae) * 100

    print(f"\n  MFE distribution (how far trades moved IN YOUR FAVOR):")
    print(f"  {'Threshold':<12}  {'% trades reached it':>20}")
    print(f"  {'-'*12}  {'-'*20}")
    for t in [0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00]:
        pct = (mfe_arr >= t).mean()
        print(f"  +{t:.2f}%       {pct:>19.1%}")

    print(f"\n  MAE distribution (how far trades moved AGAINST YOU):")
    print(f"  {'Threshold':<12}  {'% trades hit it':>20}")
    print(f"  {'-'*12}  {'-'*20}")
    for t in [0.10, 0.20, 0.30, 0.40, 0.50]:
        pct = (mae_arr >= t).mean()
        print(f"  -{t:.2f}%       {pct:>19.1%}")

    print(f"\n  Avg MFE: {mfe_arr.mean():+.3f}%   p50: {np.median(mfe_arr):+.3f}%   p95: {np.percentile(mfe_arr,95):+.3f}%")
    print(f"  Avg MAE: {mae_arr.mean():+.3f}%   p50: {np.median(mae_arr):+.3f}%   p95: {np.percentile(mae_arr,95):+.3f}%")

    print(f"\n  TP sensitivity — what if we moved the target?")
    print(f"  {'TP level':<10}  {'n':>5}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    print(f"  {'-'*10}  {'-'*5}  {'-'*6}  {'-'*5}  {'-'*9}")
    for tp in tp_levels:
        pnls = [sim_trade(e, tp, BASE_SL)[0] for e in entries]
        n, wr, pf, ev = stats(pnls)
        marker = " ◄ base" if tp == BASE_TP else ""
        print(f"  {tp*100:.2f}%      {n:5d}  {wr:6.1%}  {pf:5.2f}  {ev:+8.4f}%{marker}")

    # On winners: how much did they run past TP?
    win_entries = [e for e in entries if sim_trade(e, BASE_TP, BASE_SL)[0] > 0]
    if win_entries:
        excess = []
        for e in win_entries:
            _, mfe, _ = sim_trade(e, BASE_TP, BASE_SL)
            excess.append(mfe * 100 - BASE_TP * 100)
        ex = np.array(excess)
        print(f"\n  On winning trades: avg MFE past TP = +{ex.mean():.3f}%")
        print(f"  (trades ran {ex.mean():.3f}% further on average after hitting TP)")
        print(f"  p50={np.median(ex):.3f}%  p75={np.percentile(ex,75):.3f}%  p95={np.percentile(ex,95):.3f}%")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("BOOF50 Realism Study")
    print(f"Base TP={BASE_TP*100:.2f}%  SL={BASE_SL*100:.2f}%\n")

    all_entries = []
    for sym in SYMBOLS:
        if not os.path.exists(f"boof32_data_{sym}.csv"):
            print(f"  {sym}: no cache, skipping"); continue
        print(f"  {sym}...", end=" ", flush=True)
        df = load_csv(sym)
        df = add_vwap(df)
        entries = collect_entries(df)
        all_entries.extend(entries)
        print(f"{len(entries)} entries")

    print(f"\nTotal entries: {len(all_entries)}")
    test_execution(all_entries)
    test_regime(all_entries)
    test_mfe_mae(all_entries)
    test_timing(all_entries)
    print(f"\n{'='*60}\n  Done.\n{'='*60}\n")


if __name__ == "__main__":
    main()
