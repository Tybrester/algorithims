"""
BOOF55 — Level Reclaim Momentum Backtest
Levels: PMH, PDL, 30m high/low, 1H high/low, 2H high/low, 4H high/low
Signal: price breaks level, pulls back to retest, holds → entry on reclaim candle close
TP=1%  SL=0.5%  Time stop=90 bars (1m bars)
"""
import alpaca_trade_api as t
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

ET  = pytz.timezone("America/New_York")
api = t.REST('PKKPME54QJA3KBPAJ3QZZOJXDF','J4GMmrbXWozxgx5FoY6kZmeNj9tCG6kmDGmyEvnXrb1Y','https://paper-api.alpaca.markets')

SYMBOLS = [
    "TSLA","NVDA","AMD","HOOD","COIN","APP","MSFT","AMZN","META","PLTR",
    "UPST","SMCI","MSTR","CRWD","AVGO"
]

START = "2026-04-01"
END   = "2026-06-13"
TP    = 0.010   # 1%
SL    = 0.005   # 0.5%
MAX_BARS = 90   # 90 min time stop

# ── Level computation ──────────────────────────────────────────────────────────

def compute_levels(df):
    """
    For each 1m bar, compute the active structural levels visible at that point.
    Returns a list of level prices per bar index.
    """
    levels_per_bar = [[] for _ in range(len(df))]

    dates = sorted(df.index.normalize().unique())

    for d_idx, date in enumerate(dates):
        day_mask  = df.index.normalize() == date
        day_bars  = df[day_mask]
        if day_bars.empty: continue

        # RTH bars for this day
        rth = day_bars.between_time("09:30", "16:00")
        if rth.empty: continue

        # PDH / PDL — use previous day's high/low
        if d_idx > 0:
            prev_date = dates[d_idx - 1]
            prev_mask = df.index.normalize() == prev_date
            prev_day  = df[prev_mask].between_time("09:30", "16:00")
            if not prev_day.empty:
                pdh = prev_day["high"].max()
                pdl = prev_day["low"].min()
            else:
                pdh = pdl = None
        else:
            pdh = pdl = None

        # PMH / PML — pre-market high/low (04:00-09:30)
        pm = day_bars.between_time("04:00", "09:29")
        pmh = pm["high"].max() if not pm.empty else None
        pml = pm["low"].min()  if not pm.empty else None

        # For each RTH bar, compute rolling highs/lows up to that point
        rth_indices = rth.index.tolist()

        for bar_pos, ts in enumerate(rth_indices):
            i = df.index.get_loc(ts)
            active = []

            if pdh: active.append(pdh)
            if pdl: active.append(pdl)
            if pmh: active.append(pmh)
            if pml: active.append(pml)

            # 30m / 1H / 2H / 4H highs and lows from RTH bars up to this point
            bars_so_far = rth.iloc[:bar_pos + 1]
            if len(bars_so_far) >= 30:
                active.append(bars_so_far["high"].iloc[-30:].max())
                active.append(bars_so_far["low"].iloc[-30:].min())
            if len(bars_so_far) >= 60:
                active.append(bars_so_far["high"].iloc[-60:].max())
                active.append(bars_so_far["low"].iloc[-60:].min())
            if len(bars_so_far) >= 120:
                active.append(bars_so_far["high"].iloc[-120:].max())
                active.append(bars_so_far["low"].iloc[-120:].min())
            if len(bars_so_far) >= 240:
                active.append(bars_so_far["high"].iloc[-240:].max())
                active.append(bars_so_far["low"].iloc[-240:].min())

            levels_per_bar[i] = active

    return levels_per_bar


# ── Signal: Touch → Break → Retest → Hold ─────────────────────────────────────

def run_boof55(df, levels_per_bar):
    """
    State machine per level:
      IDLE  → price touches level (within 0.1%)
      TOUCH → price breaks through level (closes beyond)
      BREAK → price pulls back to retest level (within 0.15%)
      HOLD  → price closes back in original direction → FIRE entry
    """
    TOUCH_ZONE  = 0.001   # 0.1% from level = "touching"
    BREAK_THRESH= 0.002   # must close 0.2% beyond level to confirm break
    RETEST_ZONE = 0.0015  # 0.15% from level = retesting

    trades = []
    in_trade_until = 0

    # Track state per level key (rounded level price)
    sm = {}  # level_key -> {state, direction, broken_side}

    for i in range(10, len(df) - MAX_BARS):
        if i < in_trade_until:
            continue

        bar  = df.iloc[i]
        close = bar["close"]
        high  = bar["high"]
        low   = bar["low"]
        levels = levels_per_bar[i]

        for lvl in levels:
            if lvl <= 0: continue
            key = round(lvl, 2)

            if key not in sm:
                sm[key] = {"state": "IDLE", "direction": None}

            s = sm[key]
            dist = (close - lvl) / lvl  # positive = above, negative = below

            if s["state"] == "IDLE":
                # Touch — price comes within 0.1% of level
                if abs(dist) <= TOUCH_ZONE:
                    s["state"] = "TOUCH"
                    s["direction"] = "above" if close > lvl else "below"

            elif s["state"] == "TOUCH":
                # Break — price closes 0.2% beyond level
                if dist > BREAK_THRESH:       # broke above
                    s["state"] = "BREAK"
                    s["direction"] = "above"
                elif dist < -BREAK_THRESH:    # broke below
                    s["state"] = "BREAK"
                    s["direction"] = "below"
                elif abs(dist) > TOUCH_ZONE * 3:
                    s["state"] = "IDLE"       # moved away without breaking

            elif s["state"] == "BREAK":
                # Retest — price comes back within 0.15% of level
                if abs(dist) <= RETEST_ZONE:
                    s["state"] = "RETEST"

            elif s["state"] == "RETEST":
                # Hold — price closes back in break direction = entry signal
                if s["direction"] == "above" and dist > RETEST_ZONE:
                    # Was above, broke up, retested, held above → LONG
                    if i >= in_trade_until:
                        t = run_trade(df, i + 1, "long", TP, SL, MAX_BARS)
                        if t:
                            trades.append({**t, "level": lvl, "direction": "long"})
                            in_trade_until = t["exit_i"]
                    s["state"] = "IDLE"  # reset after fire

                elif s["direction"] == "below" and dist < -RETEST_ZONE:
                    # Was below, broke down, retested, held below → SHORT
                    if i >= in_trade_until:
                        t = run_trade(df, i + 1, "short", TP, SL, MAX_BARS)
                        if t:
                            trades.append({**t, "level": lvl, "direction": "short"})
                            in_trade_until = t["exit_i"]
                    s["state"] = "IDLE"

                elif abs(dist) > RETEST_ZONE * 3:
                    s["state"] = "IDLE"  # failed retest, reset

        # Prune stale levels (levels that are too far from price)
        sm = {k: v for k, v in sm.items() if abs(close - k) / close < 0.05}

    return trades


# ── Trade simulator ────────────────────────────────────────────────────────────

def run_trade(df, entry_i, side, tp, sl, max_bars):
    if entry_i >= len(df): return None
    entry = df.iloc[entry_i]["open"]
    if entry <= 0: return None
    tp_price = entry * (1 + tp) if side == "long"  else entry * (1 - tp)
    sl_price = entry * (1 - sl) if side == "long"  else entry * (1 + sl)
    for j in range(entry_i, min(entry_i + max_bars, len(df))):
        bar = df.iloc[j]
        if side == "long":
            if bar["low"]  <= sl_price: return {"side": side, "entry_i": entry_i, "exit_i": j, "result": "SL",   "pnl": -sl,  "bars": j - entry_i}
            if bar["high"] >= tp_price: return {"side": side, "entry_i": entry_i, "exit_i": j, "result": "TP",   "pnl":  tp,  "bars": j - entry_i}
        else:
            if bar["high"] >= sl_price: return {"side": side, "entry_i": entry_i, "exit_i": j, "result": "SL",   "pnl": -sl,  "bars": j - entry_i}
            if bar["low"]  <= tp_price: return {"side": side, "entry_i": entry_i, "exit_i": j, "result": "TP",   "pnl":  tp,  "bars": j - entry_i}
    j = min(entry_i + max_bars, len(df) - 1)
    exit_price = df.iloc[j]["close"]
    pnl = (exit_price - entry) / entry if side == "long" else (entry - exit_price) / entry
    return {"side": side, "entry_i": entry_i, "exit_i": j, "result": "TIME", "pnl": pnl, "bars": j - entry_i}


# ── Metrics ────────────────────────────────────────────────────────────────────

def report(trades, days, label):
    if not trades:
        print(f"{label:<22} NO TRADES")
        return
    df   = pd.DataFrame(trades)
    n    = len(df)
    wins = df[df["result"] == "TP"]
    loss = df[df["result"] == "SL"]
    time = df[df["result"] == "TIME"]
    wr   = len(wins) / n
    avg_w = wins["pnl"].mean() if len(wins) else 0
    avg_l = abs(loss["pnl"].mean()) if len(loss) else 0
    pf    = (len(wins) * avg_w) / (len(loss) * avg_l) if len(loss) > 0 and avg_l else float("inf")
    ev    = df["pnl"].mean()
    avg_b = df["bars"].mean()
    long_trades  = len(df[df["direction"] == "long"])
    short_trades = len(df[df["direction"] == "short"])
    print(f"{label:<22} {n:>6}  {n/days:>6.1f}  {wr*100:>6.1f}%  {pf:>6.2f}  {ev*100:>+7.3f}%  {avg_b:>7.0f}b  {len(wins):>5}  {len(loss):>5}  {len(time):>5}  L:{long_trades}/S:{short_trades}")


# ── Main ───────────────────────────────────────────────────────────────────────

print(f"Fetching {len(SYMBOLS)} symbols {START} → {END}...")
all_trades = []
trading_days = 51

for sym in SYMBOLS:
    try:
        raw = api.get_bars(sym, '1Min', start=START, end=END, feed='iex', limit=50000).df.tz_convert(ET)
        raw = raw.between_time("04:00", "16:00")  # include PM for level computation
        if len(raw) < 500:
            print(f"  {sym}: skip (too few bars)")
            continue
        days = raw.between_time("09:30","16:00").index.normalize().nunique()
        trading_days = max(trading_days, days)
        print(f"  {sym}: {len(raw)} bars  {days} days", end=" ", flush=True)
        lvls = compute_levels(raw)
        trades = run_boof55(raw, lvls)
        for t in trades: t["sym"] = sym
        all_trades += trades
        print(f"→ {len(trades)} trades")
    except Exception as e:
        print(f"  {sym}: FAILED — {e}")

print(f"\n{'='*100}")
print(f"BOOF55 — Level Reclaim Momentum  |  {START}→{END}  |  {len(SYMBOLS)} syms  |  {trading_days} days  |  TP={TP*100:.1f}% SL={SL*100:.1f}%")
print(f"{'='*100}")
print(f"{'Variant':<22} {'Trades':>6}  {'T/day':>6}  {'WR':>7}  {'PF':>6}  {'EV':>8}  {'Hold':>8}  {'TPs':>5}  {'SLs':>5}  {'TIME':>5}  {'L/S'}")
print("-" * 100)
report(all_trades, trading_days, "55 Level Reclaim")

# Break down by long vs short
longs  = [t for t in all_trades if t["direction"] == "long"]
shorts = [t for t in all_trades if t["direction"] == "short"]
report(longs,  trading_days, "  └ Longs only")
report(shorts, trading_days, "  └ Shorts only")

# Per symbol breakdown
print("\nPer symbol:")
print(f"{'Sym':<8} {'Trades':>6}  {'T/day':>6}  {'WR':>7}  {'EV':>8}  {'TPs':>5}  {'SLs':>5}")
print("-" * 55)
for sym in SYMBOLS:
    sym_trades = [t for t in all_trades if t.get("sym") == sym]
    if not sym_trades: continue
    df = pd.DataFrame(sym_trades)
    n  = len(df)
    wr = len(df[df["result"]=="TP"]) / n
    ev = df["pnl"].mean()
    tp = len(df[df["result"]=="TP"])
    sl = len(df[df["result"]=="SL"])
    print(f"{sym:<8} {n:>6}  {n/trading_days:>6.1f}  {wr*100:>6.1f}%  {ev*100:>+7.3f}%  {tp:>5}  {sl:>5}")
