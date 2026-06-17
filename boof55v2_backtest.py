"""
BOOF55 v2/v3 Backtest

v2 — Long only, gap-up stocks, PDH/PMH/30m/1H reclaim, RVOL>1.5, FIRST TOUCH only
v3 — Symbol routing: each symbol has its own "best" timeframe level
     Long reclaims only (not fades)

TP=1%  SL=0.5%  Time stop=90 bars
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

START    = "2026-04-01"
END      = "2026-06-13"
TP       = 0.010
SL       = 0.005
MAX_BARS = 90

# v3 symbol → timeframe routing (bars on 1m chart)
# "best level" per symbol determined by what type of structure they respect
SYM_LEVEL = {
    "TSLA":  "30m",    # fast mover, 30m structure
    "NVDA":  "30m",    # similar
    "AMD":   "1H",     # steadier, 1H levels hold
    "HOOD":  "PMH",    # PM high key for gap plays
    "COIN":  "1H",
    "APP":   "30m",
    "MSFT":  "1H",
    "AMZN":  "1H",
    "META":  "1H",
    "PLTR":  "4H",     # range-bound, 4H pivots matter
    "UPST":  "PMH",    # thin, PM high drives the move
    "SMCI":  "PDH",    # daily level traders
    "MSTR":  "PDH",
    "CRWD":  "1H",
    "AVGO":  "4H",
}

LEVEL_BARS = {"PMH": None, "PDH": None, "30m": 30, "1H": 60, "2H": 120, "4H": 240}

# ── Trade simulator ────────────────────────────────────────────────────────────

def run_trade(df, entry_i, side, tp, sl, max_bars):
    if entry_i >= len(df): return None
    entry = df.iloc[entry_i]["open"]
    if entry <= 0: return None
    tp_price = entry * (1 + tp) if side == "long" else entry * (1 - tp)
    sl_price = entry * (1 - sl) if side == "long" else entry * (1 + sl)
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


# ── Gap-up detection ───────────────────────────────────────────────────────────

def get_gap_up_dates(df, min_gap=0.001):  # 0.1% gap — any meaningful open above prior close
    """Return set of dates where open gapped up >0.3% vs prior day close."""
    gap_dates = set()
    dates = sorted(df.between_time("09:30","16:00").index.normalize().unique())
    for i in range(1, len(dates)):
        prev = df.between_time("09:30","16:00")[df.between_time("09:30","16:00").index.normalize() == dates[i-1]]
        curr = df.between_time("09:30","16:00")[df.between_time("09:30","16:00").index.normalize() == dates[i]]
        if prev.empty or curr.empty: continue
        prev_close = prev["close"].iloc[-1]
        curr_open  = curr["open"].iloc[0]
        if (curr_open - prev_close) / prev_close >= min_gap:
            gap_dates.add(dates[i])
    return gap_dates


# ── Level builder ──────────────────────────────────────────────────────────────

def get_level_at(df, i, level_type, date_cache):
    """Return the active level price for a given bar index and level type."""
    ts   = df.index[i]
    date = ts.normalize()

    if level_type == "PDH":
        return date_cache.get(date, {}).get("pdh", 0)
    elif level_type == "PMH":
        return date_cache.get(date, {}).get("pmh", 0)
    elif level_type in ("30m", "1H", "2H", "4H"):
        n = LEVEL_BARS[level_type]
        # Use all bars (including PM) up to this point for rolling high
        bars_before = df[df.index < ts]
        if len(bars_before) < n: return 0
        return bars_before["high"].iloc[-n:].max()
    return 0


def build_date_cache(df):
    """Pre-compute PDH and PMH for each RTH date."""
    cache = {}
    dates = sorted(df.index.normalize().unique())
    rth = df.between_time("09:30","16:00")
    for d_idx, date in enumerate(dates):
        pdh = 0
        if d_idx > 0:
            prev_date = dates[d_idx - 1]
            prev_day  = rth[rth.index.normalize() == prev_date]
            if not prev_day.empty:
                pdh = prev_day["high"].max()
        pm_bars = df[df.index.normalize() == date].between_time("04:00","09:29")
        pmh = pm_bars["high"].max() if not pm_bars.empty else 0
        cache[date] = {"pdh": pdh, "pmh": pmh}
    return cache


# ── BOOF55 v2 ─────────────────────────────────────────────────────────────────

def run_v2(df, sym):
    """
    Long only, gap-up days, PDH/PMH/30m/1H reclaim, RVOL>1.5, first touch per level per day only.
    Touch→Break→Retest→Hold state machine, but fires only ONCE per level per day.
    """
    TOUCH_ZONE   = 0.0025  # 0.25% from level = touching
    BREAK_THRESH = 0.0030  # 0.30% close beyond = break confirmed
    RETEST_ZONE  = 0.0025  # 0.25% back to level = retest

    rth = df.between_time("09:30","16:00")
    date_cache  = build_date_cache(df)
    gap_up_dates = get_gap_up_dates(df)

    df["rvol"] = df["volume"] / df["volume"].rolling(20).mean()

    trades = []
    in_trade_until = 0

    level_types = ["PDH", "PMH", "30m", "1H"]
    dates = sorted(rth.index.normalize().unique())

    for date in dates:
        if date not in gap_up_dates:
            continue  # gap-up days only

        day_bars = rth[rth.index.normalize() == date]
        fired_levels = set()  # first-touch-only: track which levels fired today

        # State machine per level type for this day
        sm = {lt: {"state": "IDLE"} for lt in level_types}

        for bar_pos in range(len(day_bars)):
            i = df.index.get_loc(day_bars.index[bar_pos])
            if i < in_trade_until:
                continue

            bar   = df.iloc[i]
            close = bar["close"]
            high  = bar["high"]
            low   = bar["low"]
            rvol  = bar["rvol"] if not np.isnan(bar["rvol"]) else 0

            if rvol < 1.5:
                continue

            for lt in level_types:
                if lt in fired_levels:
                    continue  # first touch only

                lvl = get_level_at(df, i, lt, date_cache)
                if lvl <= 0 or close < lvl * 0.85:
                    continue

                s    = sm[lt]
                dist = (close - lvl) / lvl

                if s["state"] == "IDLE":
                    if abs(dist) <= TOUCH_ZONE:
                        s["state"] = "TOUCH"

                elif s["state"] == "TOUCH":
                    if dist > BREAK_THRESH:
                        s["state"] = "BREAK"
                    elif abs(dist) > TOUCH_ZONE * 4:
                        s["state"] = "IDLE"

                elif s["state"] == "BREAK":
                    if abs(dist) <= RETEST_ZONE:
                        s["state"] = "RETEST"

                elif s["state"] == "RETEST":
                    if dist > RETEST_ZONE:
                        # Reclaim confirmed — long entry
                        t = run_trade(df, i + 1, "long", TP, SL, MAX_BARS)
                        if t:
                            t["level_type"] = lt
                            t["level_px"]   = lvl
                            trades.append(t)
                            in_trade_until = t["exit_i"]
                            fired_levels.add(lt)
                        s["state"] = "IDLE"
                    elif abs(dist) > RETEST_ZONE * 4:
                        s["state"] = "IDLE"

    return trades


# ── BOOF55 v3 ─────────────────────────────────────────────────────────────────

def run_v3(df, sym):
    """
    Symbol routing: each symbol uses its assigned level type only.
    Long reclaims, first touch per day, gap-up days, RVOL>1.5.
    """
    TOUCH_ZONE   = 0.0025
    BREAK_THRESH = 0.0030
    RETEST_ZONE  = 0.0025

    assigned_level = SYM_LEVEL.get(sym, "1H")

    rth          = df.between_time("09:30","16:00")
    date_cache   = build_date_cache(df)
    gap_up_dates = get_gap_up_dates(df)

    df["rvol"] = df["volume"] / df["volume"].rolling(20).mean()

    trades = []
    in_trade_until = 0
    dates = sorted(rth.index.normalize().unique())

    for date in dates:
        if date not in gap_up_dates:
            continue

        day_bars    = rth[rth.index.normalize() == date]
        fired_today = False
        sm          = {"state": "IDLE"}

        for bar_pos in range(len(day_bars)):
            if fired_today:
                break

            i = df.index.get_loc(day_bars.index[bar_pos])
            if i < in_trade_until:
                continue

            bar   = df.iloc[i]
            close = bar["close"]
            rvol  = bar["rvol"] if not np.isnan(bar["rvol"]) else 0

            if rvol < 1.5:
                continue

            lvl  = get_level_at(df, i, assigned_level, date_cache)
            if lvl <= 0 or close < lvl * 0.85:
                continue

            dist = (close - lvl) / lvl

            if sm["state"] == "IDLE":
                if abs(dist) <= TOUCH_ZONE:
                    sm["state"] = "TOUCH"

            elif sm["state"] == "TOUCH":
                if dist > BREAK_THRESH:
                    sm["state"] = "BREAK"
                elif abs(dist) > TOUCH_ZONE * 4:
                    sm["state"] = "IDLE"

            elif sm["state"] == "BREAK":
                if abs(dist) <= RETEST_ZONE:
                    sm["state"] = "RETEST"

            elif sm["state"] == "RETEST":
                if dist > RETEST_ZONE:
                    t = run_trade(df, i + 1, "long", TP, SL, MAX_BARS)
                    if t:
                        t["level_type"] = assigned_level
                        t["level_px"]   = lvl
                        trades.append(t)
                        in_trade_until = t["exit_i"]
                        fired_today    = True
                    sm["state"] = "IDLE"
                elif abs(dist) > RETEST_ZONE * 4:
                    sm["state"] = "IDLE"

    return trades


# ── Metrics ────────────────────────────────────────────────────────────────────

def report(trades, days, label):
    if not trades:
        print(f"  {label:<24} NO TRADES"); return
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
    print(f"  {label:<24} {n:>5}  {n/days:>5.1f}  {wr*100:>6.1f}%  {pf:>6.2f}  {ev*100:>+7.3f}%  {avg_b:>6.0f}b  {len(wins):>4}W {len(loss):>4}L {len(time):>4}T")


# ── Run ────────────────────────────────────────────────────────────────────────

print(f"Fetching {len(SYMBOLS)} symbols {START} → {END}...\n")

v2_all = []
v3_all = []
trading_days = 51

for sym in SYMBOLS:
    try:
        raw = api.get_bars(sym, '1Min', start=START, end=END, feed='iex', limit=50000).df.tz_convert(ET)
        rth = raw.between_time("09:30","16:00")
        days = rth.index.normalize().nunique()
        trading_days = max(trading_days, days)

        v2 = run_v2(raw, sym)
        v3 = run_v3(raw, sym)
        for t in v2: t["sym"] = sym
        for t in v3: t["sym"] = sym
        v2_all += v2
        v3_all += v3
        print(f"  {sym:<6}  assigned={SYM_LEVEL.get(sym,'1H'):<4}  v2={len(v2):>3} trades  v3={len(v3):>3} trades")
    except Exception as e:
        print(f"  {sym}: FAILED — {e}")

hdr = f"{'Variant':<26} {'N':>5}  {'T/d':>5}  {'WR':>7}  {'PF':>6}  {'EV':>8}  {'Hold':>7}  Outcomes"
div = "-" * 90

print(f"\n{'='*90}")
print(f"BOOF55 v2/v3  |  {START}→{END}  |  {len(SYMBOLS)} syms  |  {trading_days} days  |  TP=1.0% SL=0.5% MaxBars=90")
print(f"{'='*90}")
print(hdr); print(div)
report(v2_all, trading_days, "v2 (any reclaim, gap-up)")
report(v3_all, trading_days, "v3 (routed, gap-up)")

# Per-symbol v3
print(f"\nv3 per symbol (routed level):")
print(f"  {'Sym':<6} {'Level':<5}  {'N':>5}  {'T/d':>5}  {'WR':>6}  {'EV':>8}  W   L   T")
print(f"  {'-'*60}")
for sym in SYMBOLS:
    sym_t = [t for t in v3_all if t.get("sym") == sym]
    if not sym_t: print(f"  {sym:<6} {SYM_LEVEL.get(sym,'1H'):<5}  {'0':>5}"); continue
    df2  = pd.DataFrame(sym_t)
    n    = len(df2)
    wr   = len(df2[df2["result"]=="TP"]) / n
    ev   = df2["pnl"].mean()
    w    = len(df2[df2["result"]=="TP"])
    l    = len(df2[df2["result"]=="SL"])
    tt   = len(df2[df2["result"]=="TIME"])
    print(f"  {sym:<6} {SYM_LEVEL.get(sym,'1H'):<5}  {n:>5}  {n/trading_days:>5.2f}  {wr*100:>5.1f}%  {ev*100:>+7.3f}%  {w:>3} {l:>3} {tt:>3}")

# v2 by level type
print(f"\nv2 by level type:")
print(f"  {'Level':<6}  {'N':>5}  {'WR':>6}  {'EV':>8}")
print(f"  {'-'*35}")
for lt in ["PDH","PMH","30m","1H"]:
    lt_trades = [t for t in v2_all if t.get("level_type") == lt]
    if not lt_trades: print(f"  {lt:<6}  {'0':>5}"); continue
    df3 = pd.DataFrame(lt_trades)
    n   = len(df3)
    wr  = len(df3[df3["result"]=="TP"]) / n
    ev  = df3["pnl"].mean()
    print(f"  {lt:<6}  {n:>5}  {wr*100:>5.1f}%  {ev*100:>+7.3f}%")
