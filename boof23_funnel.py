"""
boof23_funnel.py
Funnel report showing how many setups pass each filter stage.
Uses today's live data from Alpaca.
"""
import datetime, os, sys
import pandas as pd
import numpy as np
import pytz
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
from boof23_analysis import (
    BOOF23_CFG, resample_to_5min, compute_atr, compute_vol_sma,
    compute_rvol, build_zigzag, build_clusters, nearest_cluster_dist
)

PAPER_KEY    = "PK22C5W5QQLOX2NLK3LDFVKCHW"
PAPER_SECRET = "F8TBURaRyCVY3ekXEhJ7RkF3QXJbohRxDBxPg5LiS9nX"
ET = pytz.timezone("America/New_York")
TZ = ZoneInfo("America/New_York")

SYMS = [
    'TOST','HOOD','ORCL','MSFT','V','JPM','SOUN','PODD','ENTG','GE',
    'MRNA','AI','PATH','GS','BSX','SIMO','SCHW','TEM','AMD','ABNB',
    'NEM','GILD','MCHP','UNP','ETN','LRCX','SMTC','INCY','ITW','LLY',
    'MAR','QRVO','MPC','BKR','TMO','CAT','NVDA','SOFI','XOM','DPZ',
    'FCX','VRTX','S','CSCO','DE','HUM',
]

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

data_client = StockHistoricalDataClient(PAPER_KEY, PAPER_SECRET)

def get_bars(symbols):
    now   = datetime.datetime.now(ET)
    start = now - datetime.timedelta(days=3)
    out   = {}
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i+50]
        try:
            req  = StockBarsRequest(symbol_or_symbols=chunk,
                                    timeframe=TimeFrame(1, TimeFrameUnit.Minute),
                                    start=start, end=now)
            resp = data_client.get_stock_bars(req).df
            if resp.empty: continue
            resp = resp.reset_index()
            for sym in chunk:
                sym_df = resp[resp["symbol"]==sym].copy().reset_index(drop=True)
                if sym_df.empty: continue
                sym_df = sym_df.rename(columns={"timestamp":"time"})
                sym_df["time"] = pd.to_datetime(sym_df["time"]).dt.tz_convert(ET)
                out[sym] = sym_df
        except Exception as e:
            print(f"  fetch error {chunk[:2]}: {e}")
    return out

def funnel_sym(sym, df1):
    cfg = BOOF23_CFG
    F   = cfg['FRACTAL_BARS']

    df5 = resample_to_5min(df1)
    if len(df5) < cfg['VOL_LEN'] + cfg['ATR_LEN'] + F*2 + cfg['MAX_LOOKBACK'] + 10:
        return None

    df5['atr']     = compute_atr(df5, cfg['ATR_LEN'])
    df5['vol_sma'] = compute_vol_sma(df5, cfg['VOL_LEN'])
    df5['rvol']    = compute_rvol(df5, cfg['VOL_LEN'])
    trend, zz_high_bar, zz_low_bar = build_zigzag(df5)
    atr5    = df5['atr'].values
    clusters = build_clusters(df5, atr5)
    highs5  = df5['high'].values
    lows5   = df5['low'].values
    closes5 = df5['close'].values

    counts = {
        "zigzag_candidates": 0,
        "pass_rvol":         0,
        "pass_zz_prox":      0,
        "pass_sr_dist":      0,
        "pass_atr_bounce":   0,
        "pass_cross":        0,
    }

    min_i5 = cfg['VOL_LEN'] + cfg['ATR_LEN'] + F*2 + cfg['MAX_LOOKBACK'] + 5
    for i5 in range(min_i5, len(df5) - 1):
        atr_i = atr5[i5]
        if pd.isna(atr_i) or atr_i == 0: continue

        for offset in range(F+2, F+2+cfg['MAX_LOOKBACK']+1):
            p = i5 - offset + 1
            if p < F + cfg['VOL_LEN'] or p + F >= i5: continue
            if p - F < 0 or p + F + 1 > len(highs5): continue

            atr_p = atr5[p]
            if pd.isna(atr_p) or atr_p == 0: continue

            fp = (highs5[p] > highs5[p-F:p].max()) and (highs5[p] > highs5[p+1:p+F+1].max())
            ft = (lows5[p]  < lows5[p-F:p].min())  and (lows5[p]  < lows5[p+1:p+F+1].min())
            if not fp and not ft: continue

            counts["zigzag_candidates"] += 1

            # RVOL
            if df5.iloc[i5]['rvol'] < cfg['RVOL_MIN']: continue
            if df5.iloc[p]['rvol']  < cfg['RVOL_MIN']: continue
            counts["pass_rvol"] += 1

            # ZZ proximity
            t = trend[p]
            if fp:
                zh = int(zz_high_bar[p])
                if zh < 0 or abs(p - zh) > cfg['ZZ_PROX_BARS']: continue
            elif ft:
                zl = int(zz_low_bar[p])
                if zl < 0 or abs(p - zl) > cfg['ZZ_PROX_BARS']: continue
            counts["pass_zz_prox"] += 1

            # S/R distance
            dist = nearest_cluster_dist(closes5[p], clusters, atr_p)
            if dist > cfg['SR_DIST_MAX']: continue
            counts["pass_sr_dist"] += 1

            # ATR bounce/rejection
            atr_rej = closes5[p] < highs5[p] - atr_p * cfg['ATR_MULT']
            atr_bnc = closes5[p] > lows5[p]  + atr_p * cfg['ATR_MULT']
            if fp and not atr_rej: continue
            if ft and not atr_bnc: continue
            counts["pass_atr_bounce"] += 1

            # Cross filter
            if i5 < 1: continue
            prev_c = closes5[i5-1]; cur_c = closes5[i5]
            if fp and not (prev_c >= highs5[p] and cur_c < highs5[p]): continue
            if ft and not (prev_c <= lows5[p]  and cur_c > lows5[p]):  continue
            counts["pass_cross"] += 1

    return counts

# ── Main ─────────────────────────────────────────────────────────────────────

print("Fetching bars for all 46 symbols...")
bars = get_bars(SYMS)
print(f"Got data for {len(bars)} symbols\n")

totals = {k: 0 for k in ["zigzag_candidates","pass_rvol","pass_zz_prox",
                          "pass_sr_dist","pass_atr_bounce","pass_cross"]}
sym_results = []

for sym in SYMS:
    df1 = bars.get(sym)
    if df1 is None or len(df1) < 100:
        continue
    r = funnel_sym(sym, df1)
    if r is None: continue
    for k in totals: totals[k] += r[k]
    if r["zigzag_candidates"] > 0:
        sym_results.append((sym, r))

# ── Print per-symbol table ────────────────────────────────────────────────────
print(f"{'SYM':<6} {'ZZ':>5} {'RVOL':>5} {'ZZPx':>5} {'SR':>5} {'ATR':>5} {'CROSS':>6}")
print("-" * 42)
for sym, r in sorted(sym_results, key=lambda x: -x[1]["pass_cross"]):
    print(f"{sym:<6} {r['zigzag_candidates']:>5} {r['pass_rvol']:>5} "
          f"{r['pass_zz_prox']:>5} {r['pass_sr_dist']:>5} "
          f"{r['pass_atr_bounce']:>5} {r['pass_cross']:>6}")

# ── Print funnel totals ───────────────────────────────────────────────────────
print()
print("=" * 42)
print("FUNNEL TOTALS (all symbols, today)")
print("=" * 42)
labels = [
    ("Raw ZigZag candidates", "zigzag_candidates"),
    ("Pass RVOL",             "pass_rvol"),
    ("Pass ZZ proximity",     "pass_zz_prox"),
    ("Pass S/R distance",     "pass_sr_dist"),
    ("Pass ATR bounce",       "pass_atr_bounce"),
    ("Pass cross filter",     "pass_cross"),
]
prev = None
for label, key in labels:
    n = totals[key]
    pct = f"({n/prev*100:.0f}% of prev)" if prev else ""
    print(f"  {label:<25} {n:>6}  {pct}")
    prev = n if n > 0 else prev

print(f"\n  Final trades fired today: {totals['pass_cross']}")
print("\nDone.")
