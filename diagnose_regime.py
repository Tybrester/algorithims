"""
Diagnose regime distribution for April 2026 vs March 2025
"""
import numpy as np
import pandas as pd
from datetime import datetime
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

REGIME_EMA_FAST  = 20
REGIME_EMA_SLOW  = 50
REGIME_SLOPE_MIN = 0.0002
REGIME_ATR_MAX   = 90

def compute_atr(df, period=14):
    hl = df['high'] - df['low']
    hc = np.abs(df['high'] - df['close'].shift())
    lc = np.abs(df['low']  - df['close'].shift())
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(period).mean()

def regime_distribution(df):
    df = df.copy()
    df['atr']      = compute_atr(df)
    df['ema_fast'] = df['close'].ewm(span=REGIME_EMA_FAST, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=REGIME_EMA_SLOW, adjust=False).mean()
    df['atr_pct']  = df['atr'].rolling(100).rank(pct=True) * 100

    regimes = []
    for i in range(REGIME_EMA_SLOW + 10, len(df)):
        price   = df['close'].iloc[i]
        ef_now  = df['ema_fast'].iloc[i]
        ef_prev = df['ema_fast'].iloc[i - 5]
        es_now  = df['ema_slow'].iloc[i]
        atr_pct = df['atr_pct'].iloc[i]

        if np.isnan(ef_now) or np.isnan(es_now):
            regimes.append('choppy'); continue
        if not np.isnan(atr_pct) and atr_pct > REGIME_ATR_MAX:
            regimes.append('choppy_atr'); continue

        slope = (ef_now - ef_prev) / (price * 5) if price > 0 else 0
        if abs(slope) < REGIME_SLOPE_MIN:
            regimes.append('choppy_slope'); continue

        if slope > 0 and price > es_now:
            regimes.append('trending_up')
        elif slope < 0 and price < es_now:
            regimes.append('trending_down')
        else:
            regimes.append('choppy_mixed')

    counts = {}
    for r in regimes:
        counts[r] = counts.get(r, 0) + 1
    total = len(regimes)
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:<20} {v:>6}  ({v/total*100:.1f}%)")

creds = get_alpaca_credentials()
sym   = 'QQQ'

for label, start, end in [
    ('Mar 2025', datetime(2025,3,1), datetime(2025,3,31)),
    ('Apr 2026', datetime(2026,4,1), datetime(2026,4,30)),
]:
    df = fetch_alpaca_bars(sym, start, end, '1Min',
                           api_key=creds['api_key'], secret_key=creds['secret_key'])
    print(f"\n{sym} {label}  ({len(df)} bars)")
    regime_distribution(df)
