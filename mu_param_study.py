import os
import pandas as pd
import numpy as np
from itertools import product

SYMBOL = "MU"
LOOKBACK      = 80
SUPPORT_TOL   = 0.002
SWEEP_BUFFER  = 0.001
COOLDOWN_BARS = 30
MAX_HOLD_BARS = 60
SLIPPAGE      = 0.0002

DIRECTIONS   = ["LONG", "SHORT", "BOTH"]
TIME_WINDOWS = [("9:30-10:00", "15:30", "16:00"),
                ("9:30-10:30", "15:30", "16:30"),
                ("9:30-11:00", "15:30", "17:00"),
                ("9:30-12:00", "15:30", "18:00")]
TP1S    = [0.004, 0.005, 0.006]
RUNNERS = [0.010, 0.015, 0.020]
STOPS   = [0.003, 0.004, 0.005]


def add_indicators(day):
    typical = (day["high"] + day["low"] + day["close"]) / 3
    day["vwap"]       = (typical * day["volume"]).cumsum() / day["volume"].cumsum()
    day["avg_vol_20"] = day["volume"].rolling(20).mean()
    day["rvol"]       = day["volume"] / day["avg_vol_20"]
    day["vwap_slope"] = day["vwap"].pct_change(5) * 100
    return day


def find_support(lows):
    best_level, best_touches = None, 0
    for low in lows:
        touches = np.sum(np.abs(lows - low) / low <= SUPPORT_TOL)
        if touches > best_touches:
            best_level, best_touches = low, touches
    return (best_level, best_touches) if best_touches >= 2 else (None, 0)


def find_resistance(highs):
    best_level, best_touches = None, 0
    for h in highs:
        touches = np.sum(np.abs(highs - h) / h <= SUPPORT_TOL)
        if touches > best_touches:
            best_level, best_touches = h, touches
    return (best_level, best_touches) if best_touches >= 2 else (None, 0)


def load_data():
    cache = f"boof32_data_{SYMBOL}.csv"
    df = pd.read_csv(cache, dtype_backend="numpy_nullable")
    if "datetime" in df.columns:
        df = df.rename(columns={"datetime": "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("America/New_York")
    for col in ["open","high","low","close","volume"]:
        df[col] = df[col].astype(float)
    for col in ["vwap","trade_count"]:
        if col in df.columns:
            df = df.drop(columns=[col])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["date"]     = df["timestamp"].dt.date
    df["time_utc"] = df["timestamp"].dt.strftime("%H:%M")
    return df


def collect_setups(df, start_utc, end_utc, direction):
    setups = []
    for date, day in df.groupby("date"):
        day = day.copy().reset_index(drop=True)
        if len(day) < 150:
            continue
        day = add_indicators(day)
        last_i = -999999
        for i in range(LOOKBACK + 20, len(day) - MAX_HOLD_BARS - 2):
            t = day["time_utc"].iloc[i]
            if not (start_utc <= t < end_utc):
                continue
            if i - last_i < COOLDOWN_BARS:
                continue
            bar  = day.iloc[i]
            win  = day.iloc[max(0, i - LOOKBACK):i]
            found_dir = None
            if direction in ("LONG", "BOTH"):
                sup, _ = find_support(win["low"].values)
                if (sup is not None and
                        bar["low"]   < sup * (1 - SWEEP_BUFFER) and
                        bar["close"] > sup and
                        bar["close"] < bar["vwap"]):
                    found_dir = "LONG"
            if found_dir is None and direction in ("SHORT", "BOTH"):
                res, _ = find_resistance(win["high"].values)
                if (res is not None and
                        bar["high"]  > res * (1 + SWEEP_BUFFER) and
                        bar["close"] < res and
                        bar["close"] > bar["vwap"]):
                    found_dir = "SHORT"
            if found_dir is None:
                continue
            entry_i = i + 1
            if entry_i >= len(day):
                continue
            future = day.iloc[entry_i:entry_i + MAX_HOLD_BARS].copy()
            if future.empty:
                continue
            setups.append({"date": date, "direction": found_dir,
                           "entry_price": day["open"].iloc[entry_i] * (1 + SLIPPAGE),
                           "future": future})
            last_i = i
    return setups


def simulate(future, entry_price, direction, tp1, runner, stop):
    half_out = False
    pnl = 0.0
    for _, bar in future.iterrows():
        h = bar["high"]; l = bar["low"]
        if direction == "LONG":
            move_h = (h - entry_price) / entry_price
            move_l = (l - entry_price) / entry_price
            if not half_out:
                if move_l <= -stop:   return -stop - SLIPPAGE * 2
                if move_h >= tp1:     half_out = True; pnl += tp1 * 0.5; entry_price_be = entry_price
            if half_out:
                if l <= entry_price:  return pnl - SLIPPAGE * 2
                if move_h >= runner:  pnl += runner * 0.5; return pnl - SLIPPAGE * 2
        else:
            move_h = (h - entry_price) / entry_price
            move_l = (l - entry_price) / entry_price
            if not half_out:
                if move_h >= stop:    return -stop - SLIPPAGE * 2
                if move_l <= -tp1:    half_out = True; pnl += tp1 * 0.5
            if half_out:
                if h >= entry_price:  return pnl - SLIPPAGE * 2
                if move_l <= -runner: pnl += runner * 0.5; return pnl - SLIPPAGE * 2
    final = (future.iloc[-1]["close"] - entry_price) / entry_price
    if direction == "SHORT": final = -final
    return (pnl + final * 0.5 - SLIPPAGE * 2) if half_out else (final - SLIPPAGE * 2)


def stats(pnls):
    x = pd.Series(pnls)
    if len(x) == 0:
        return None
    wins = x[x > 0]; losses = x[x < 0]
    gw = wins.sum(); gl = abs(losses.sum())
    pf = gw / gl if gl > 0 else float("inf")
    # max drawdown
    cum = x.cumsum()
    roll_max = cum.cummax()
    dd = (cum - roll_max)
    max_dd = dd.min()
    # worst streak
    streak = worst = 0
    for v in x:
        if v < 0: streak += 1; worst = max(worst, streak)
        else: streak = 0
    return dict(n=len(x), wr=len(wins)/len(x), pf=pf,
                ev=x.mean(), total=x.sum(), max_dd=max_dd, worst_streak=worst)


print(f"Loading {SYMBOL} data...")
df = load_data()
print(f"  {len(df)} bars loaded\n")

# Pre-collect setups per (direction, window) to avoid re-scanning
setup_cache = {}
for direction in DIRECTIONS:
    for win_label, s_utc, e_utc in TIME_WINDOWS:
        key = (direction, win_label)
        print(f"  Scanning {direction} | {win_label}...")
        setup_cache[key] = collect_setups(df, s_utc, e_utc, direction)
        print(f"    -> {len(setup_cache[key])} setups")

print("\nRunning parameter grid...")
rows = []
for direction, (win_label, s_utc, e_utc), tp1, runner, stop in product(
        DIRECTIONS, TIME_WINDOWS, TP1S, RUNNERS, STOPS):
    key = (direction, win_label)
    setups = setup_cache[key]
    if not setups:
        continue
    pnls = [simulate(s["future"], s["entry_price"], s["direction"], tp1, runner, stop)
            for s in setups]
    r = stats(pnls)
    if r is None:
        continue
    rows.append(dict(direction=direction, window=win_label,
                     tp1=f"{tp1*100:.2f}%", runner=f"{runner*100:.2f}%", stop=f"{stop*100:.2f}%",
                     **r))

out = pd.DataFrame(rows).sort_values("pf", ascending=False)
out.to_csv("mu_param_study.csv", index=False)

print(f"\n{'='*100}")
print(f"  MU PARAMETER STUDY  —  top 30 configs by PF")
print(f"{'='*100}")
print(f"  {'Dir':<5}  {'Window':<12}  {'TP1':<6}  {'Runner':<7}  {'Stop':<6}  "
      f"{'n':>4}  {'WR':>6}  {'PF':>5}  {'EV':>9}  {'Total':>8}  {'MaxDD':>8}  {'Streak':>6}")
for _, r in out.head(30).iterrows():
    print(f"  {r['direction']:<5}  {r['window']:<12}  {r['tp1']:<6}  {r['runner']:<7}  {r['stop']:<6}  "
          f"{r['n']:4d}  {r['wr']:6.1%}  {r['pf']:5.2f}  {r['ev']:9.4%}  "
          f"{r['total']:8.2%}  {r['max_dd']:8.2%}  {r['worst_streak']:6d}")

print(f"\nFull results saved to mu_param_study.csv")
