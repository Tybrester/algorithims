"""
BOOF55 Final Backtest — A/B/C variants

55A: 30m reclaim only | 1H reclaim only | Gap-up days only (no RVOL filter)
55B: 30m + 1H reclaim | RVOL > 1.5
55C: 30m + 1H reclaim | Top 20 strongest stocks (ranked by avg daily range)

TP=1%  SL=0.5%  Time stop=90 bars  First touch per level per day only
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
    "UPST","SMCI","MSTR","CRWD","AVGO",
]

START    = "2026-04-01"
END      = "2026-06-13"
TP       = 0.010
SL       = 0.005
MAX_BARS = 90

TOUCH_ZONE   = 0.0025
BREAK_THRESH = 0.0030
RETEST_ZONE  = 0.0025

# ── Trade simulator ────────────────────────────────────────────────────────────

def run_trade(df, entry_i, side, tp, sl, max_bars):
    if entry_i >= len(df): return None
    entry = df.iloc[entry_i]["open"]
    if entry <= 0: return None
    tp_price = entry * (1 + tp)
    sl_price = entry * (1 - sl)
    for j in range(entry_i, min(entry_i + max_bars, len(df))):
        bar = df.iloc[j]
        if bar["low"]  <= sl_price: return {"entry_i": entry_i, "exit_i": j, "result": "SL",   "pnl": -sl,  "bars": j - entry_i}
        if bar["high"] >= tp_price: return {"entry_i": entry_i, "exit_i": j, "result": "TP",   "pnl":  tp,  "bars": j - entry_i}
    j = min(entry_i + max_bars, len(df) - 1)
    exit_price = df.iloc[j]["close"]
    pnl = (exit_price - entry) / entry
    return {"entry_i": entry_i, "exit_i": j, "result": "TIME", "pnl": pnl, "bars": j - entry_i}

# ── Gap-up detection ───────────────────────────────────────────────────────────

def get_gap_up_dates(rth, min_gap=0.001):
    gap_dates = set()
    dates = sorted(rth.index.normalize().unique())
    for i in range(1, len(dates)):
        prev = rth[rth.index.normalize() == dates[i-1]]
        curr = rth[rth.index.normalize() == dates[i]]
        if prev.empty or curr.empty: continue
        if (curr["open"].iloc[0] - prev["close"].iloc[-1]) / prev["close"].iloc[-1] >= min_gap:
            gap_dates.add(dates[i])
    return gap_dates

# ── Date cache (PDH/PMH) ───────────────────────────────────────────────────────

def build_date_cache(df):
    cache = {}
    rth   = df.between_time("09:30","16:00")
    dates = sorted(df.index.normalize().unique())
    for d_idx, date in enumerate(dates):
        pdh = 0
        if d_idx > 0:
            prev  = rth[rth.index.normalize() == dates[d_idx-1]]
            if not prev.empty: pdh = prev["high"].max()
        pm  = df[df.index.normalize() == date].between_time("04:00","09:29")
        pmh = pm["high"].max() if not pm.empty else 0
        cache[date] = {"pdh": pdh, "pmh": pmh}
    return cache

# ── Level price at bar i ───────────────────────────────────────────────────────

def get_level(df, i, level_type, date_cache):
    ts   = df.index[i]
    date = ts.normalize()
    if level_type == "30m":
        bars_before = df[df.index < ts]
        return bars_before["high"].iloc[-30:].max() if len(bars_before) >= 30 else 0
    elif level_type == "1H":
        bars_before = df[df.index < ts]
        return bars_before["high"].iloc[-60:].max() if len(bars_before) >= 60 else 0
    elif level_type == "PDH":
        return date_cache.get(date, {}).get("pdh", 0)
    elif level_type == "PMH":
        return date_cache.get(date, {}).get("pmh", 0)
    return 0

# ── Core state machine ─────────────────────────────────────────────────────────

def run_levels(df, level_types, gap_up_only=False, min_rvol=0.0):
    """
    Runs Touch→Break→Retest→Hold for each level type.
    First touch per level per day only. Long reclaims only.
    """
    rth          = df.between_time("09:30","16:00")
    date_cache   = build_date_cache(df)
    gap_up_dates = get_gap_up_dates(rth) if gap_up_only else None

    df["rvol"] = df["volume"] / df["volume"].rolling(20).mean()

    trades         = []
    in_trade_until = 0
    dates          = sorted(rth.index.normalize().unique())

    for date in dates:
        if gap_up_dates is not None and date not in gap_up_dates:
            continue

        day_bars     = rth[rth.index.normalize() == date]
        fired_levels = set()
        sm           = {lt: {"state": "IDLE"} for lt in level_types}

        for bar_pos in range(len(day_bars)):
            i = df.index.get_loc(day_bars.index[bar_pos])
            if i < in_trade_until:
                continue

            bar   = df.iloc[i]
            close = bar["close"]
            rvol  = bar["rvol"] if not np.isnan(bar.get("rvol", np.nan)) else 0

            if min_rvol > 0 and rvol < min_rvol:
                continue

            for lt in level_types:
                if lt in fired_levels:
                    continue

                lvl = get_level(df, i, lt, date_cache)
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
                        t = run_trade(df, i + 1, "long", TP, SL, MAX_BARS)
                        if t:
                            t["level_type"] = lt
                            trades.append(t)
                            in_trade_until = t["exit_i"]
                            fired_levels.add(lt)
                        s["state"] = "IDLE"
                    elif abs(dist) > RETEST_ZONE * 4:
                        s["state"] = "IDLE"

    return trades

# ── Metrics ────────────────────────────────────────────────────────────────────

def metrics(trades, days):
    if not trades:
        return None
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
    return dict(n=n, td=n/days, wr=wr, pf=pf, ev=ev, avg_b=avg_b,
                tp=len(wins), sl=len(loss), time=len(time))

def print_row(label, m):
    if not m:
        print(f"  {label:<30}  NO TRADES"); return
    print(f"  {label:<30}  {m['n']:>5}  {m['td']:>5.1f}  {m['wr']*100:>6.1f}%  "
          f"{m['pf']:>6.2f}  {m['ev']*100:>+7.3f}%  {m['avg_b']:>6.0f}b  "
          f"{m['tp']:>4}W {m['sl']:>4}L {m['time']:>4}T")

def print_header():
    print(f"  {'Variant':<30}  {'N':>5}  {'T/d':>5}  {'WR':>7}  {'PF':>6}  {'EV':>8}  {'Hold':>7}  Outcomes")
    print(f"  {'-'*95}")

# ── Fetch data ─────────────────────────────────────────────────────────────────

print(f"Loading {len(SYMBOLS)} symbols from cache...\n")
all_data   = {}
sym_ranges = {}

for sym in SYMBOLS:
    path = f"cache55/{sym}.parquet"
    raw  = pd.read_parquet(path).tz_convert(ET)
    rth  = raw.between_time("09:30","16:00")
    all_data[sym] = raw
    daily = rth.groupby(rth.index.normalize()).apply(
        lambda d: (d["high"].max() - d["low"].min()) / d["open"].iloc[0]
    )
    sym_ranges[sym] = daily.mean()
    print(f"  {sym:<6} {len(rth):>5} bars  range={sym_ranges[sym]*100:.2f}%")

trading_days = 51

# Top 20 strongest movers by avg daily range
top20 = sorted(sym_ranges, key=sym_ranges.get, reverse=True)[:20]
print(f"\nTop 20 by avg daily range: {', '.join(top20)}")

# ── RUN ALL VARIANTS ───────────────────────────────────────────────────────────

results = {
    "55A_30m_gapup": [],
    "55A_1H_gapup":  [],
    "55B_30m_rvol":  [],
    "55B_1H_rvol":   [],
    "55B_both_rvol": [],
    "55C_30m_top20": [],
    "55C_1H_top20":  [],
    "55C_both_top20":[],
}

for sym, raw in all_data.items():
    # 55A — gap-up only, no RVOL
    for t in run_levels(raw, ["30m"],        gap_up_only=True,  min_rvol=0.0): t["sym"] = sym; results["55A_30m_gapup"].append(t)
    for t in run_levels(raw, ["1H"],         gap_up_only=True,  min_rvol=0.0): t["sym"] = sym; results["55A_1H_gapup"].append(t)
    # 55B — RVOL>1.5, no gap filter
    for t in run_levels(raw, ["30m"],        gap_up_only=False, min_rvol=1.5): t["sym"] = sym; results["55B_30m_rvol"].append(t)
    for t in run_levels(raw, ["1H"],         gap_up_only=False, min_rvol=1.5): t["sym"] = sym; results["55B_1H_rvol"].append(t)
    for t in run_levels(raw, ["30m","1H"],   gap_up_only=False, min_rvol=1.5): t["sym"] = sym; results["55B_both_rvol"].append(t)
    # 55C — top 20 only, no extra filter
    if sym in top20:
        for t in run_levels(raw, ["30m"],      gap_up_only=False, min_rvol=0.0): t["sym"] = sym; results["55C_30m_top20"].append(t)
        for t in run_levels(raw, ["1H"],       gap_up_only=False, min_rvol=0.0): t["sym"] = sym; results["55C_1H_top20"].append(t)
        for t in run_levels(raw, ["30m","1H"], gap_up_only=False, min_rvol=0.0): t["sym"] = sym; results["55C_both_top20"].append(t)

# ── REPORT ─────────────────────────────────────────────────────────────────────

print(f"\n{'='*100}")
print(f"BOOF55 A/B/C  |  {START}→{END}  |  {trading_days} days  |  TP={TP*100:.1f}% SL={SL*100:.1f}% MaxBars={MAX_BARS}")
print(f"{'='*100}")

print_header()

print(f"\n  ── 55A: Gap-up only (no RVOL filter) ──")
print_row("55A  30m reclaim only",   metrics(results["55A_30m_gapup"], trading_days))
print_row("55A  1H reclaim only",    metrics(results["55A_1H_gapup"],  trading_days))

print(f"\n  ── 55B: RVOL > 1.5 (all days) ──")
print_row("55B  30m reclaim only",   metrics(results["55B_30m_rvol"],  trading_days))
print_row("55B  1H reclaim only",    metrics(results["55B_1H_rvol"],   trading_days))
print_row("55B  30m + 1H combined",  metrics(results["55B_both_rvol"], trading_days))

print(f"\n  ── 55C: Top 20 strongest movers ──")
print_row("55C  30m reclaim only",   metrics(results["55C_30m_top20"], trading_days))
print_row("55C  1H reclaim only",    metrics(results["55C_1H_top20"],  trading_days))
print_row("55C  30m + 1H combined",  metrics(results["55C_both_top20"],trading_days))

# Per-symbol breakdown for best variant (55B combined)
print(f"\n  ── Per-symbol: 55B 30m+1H RVOL>1.5 ──")
print(f"  {'Sym':<6}  {'N':>4}  {'WR':>6}  {'EV':>8}  {'TPs':>4}  {'SLs':>4}")
print(f"  {'-'*45}")
for sym in sorted(all_data.keys()):
    sym_t = [t for t in results["55B_both_rvol"] if t.get("sym") == sym]
    if not sym_t: continue
    df2 = pd.DataFrame(sym_t)
    n   = len(df2)
    wr  = len(df2[df2["result"]=="TP"]) / n
    ev  = df2["pnl"].mean()
    print(f"  {sym:<6}  {n:>4}  {wr*100:>5.1f}%  {ev*100:>+7.3f}%  {len(df2[df2['result']=='TP']):>4}  {len(df2[df2['result']=='SL']):>4}")

# Level type breakdown for 55B combined
print(f"\n  ── 55B combined by level ──")
for lt in ["30m","1H"]:
    lt_t = [t for t in results["55B_both_rvol"] if t.get("level_type") == lt]
    m    = metrics(lt_t, trading_days)
    if m: print_row(f"  {lt}", m)
