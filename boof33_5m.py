# BOOF33 on 5-minute bars
# Same detection: support sweep + reclaim + close < VWAP
# Exit: 50% at +0.50%, runner to +1.50%, BE stop after TP1
# Window: 9:30-10:30 ET

import os
import time as time_mod
import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta

API_KEY    = 'AKPDLKERTEC2OG42UROO65QMW7'
API_SECRET = 'MTDQmZk5KuQU5p5ZQE4YWMvksTLcxJeGJiCeA4j2vPM'

SYMBOLS = [
    "FCX", "NEM", "MU", "SCCO", "KLAC", "PANW",
    "TSLA", "CRWD", "QCOM", "HOOD", "TER", "CORZ",
    "APP", "DDOG", "COIN", "MDB", "NET", "ZS",
]

# 5m-adjusted parameters
LOOKBACK      = 80    # ~7 hours of 5m bars
SUPPORT_TOL   = 0.002
SWEEP_BUFFER  = 0.001
COOLDOWN_BARS = 6     # 30 min equivalent
MAX_HOLD_BARS = 12    # 1 hour equivalent

TP1      = 0.005
TP2      = 0.015
SL       = 0.003
SLIPPAGE = 0.0002

# 9:30-10:30 ET in UTC
WIN_LABEL = "9:30-10:30"
START_UTC = "15:30"
END_UTC   = "16:30"


def fetch_data(symbol):
    cache_file = f'boof33_5m_{symbol}.csv'
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, parse_dates=['datetime'])
    print(f"  Fetching {symbol} (5m)...")
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    end   = datetime.now()
    start = end - timedelta(days=182)
    req   = StockBarsRequest(symbol_or_symbols=symbol,
                             timeframe=TimeFrame(5, TimeFrame.Unit.Minute),
                             start=start, end=end)
    for attempt in range(5):
        try:
            bars = client.get_stock_bars(req)
            df = bars.df
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(symbol, level='symbol')
            df = df.reset_index().rename(columns={'timestamp': 'datetime'})
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.sort_values('datetime').reset_index(drop=True)
            df.to_csv(cache_file, index=False)
            print(f"  Saved {len(df):,} bars")
            return df
        except Exception as e:
            wait = 10 * (attempt + 1)
            print(f"  {symbol} retry {attempt+1}: {e.__class__.__name__}, waiting {wait}s")
            time_mod.sleep(wait)
    print(f"  {symbol}: all retries failed")
    return None


def add_indicators(day):
    typical = (day["high"] + day["low"] + day["close"]) / 3
    day["vwap"]       = (typical * day["volume"]).cumsum() / day["volume"].cumsum()
    day["avg_vol_20"] = day["volume"].rolling(20).mean()
    day["rvol"]       = day["volume"] / day["avg_vol_20"]
    day["vwap_slope"] = day["vwap"].pct_change(5) * 100
    return day


def find_support(day, i):
    window = day.iloc[max(0, i - LOOKBACK):i]
    if len(window) < 10:
        return None, 0
    lows = window["low"].values
    best_level, best_touches = None, 0
    for low in lows:
        touches = np.sum(np.abs(lows - low) / low <= SUPPORT_TOL)
        if touches > best_touches:
            best_level, best_touches = low, touches
    if best_touches < 2:
        return None, 0
    return best_level, best_touches


def detect_signal(day, i):
    support, touches = find_support(day, i)
    if support is None:
        return False, {}
    bar = day.iloc[i]
    if (bar["low"]   < support * (1 - SWEEP_BUFFER) and
            bar["close"] > support and
            bar["close"] < bar["vwap"]):
        return True, {
            "support":    support,
            "entry_i":    i + 1,
            "rvol":       bar["rvol"],
            "vwap_slope": bar["vwap_slope"],
            "time_utc":   day["time_utc"].iloc[i],
        }
    return False, {}


def exit_scale_fixed(future, entry_price, tp2):
    half_out = False
    pnl = 0.0
    for _, bar in future.iterrows():
        hm = (bar["high"]  - entry_price) / entry_price
        lm = (bar["low"]   - entry_price) / entry_price
        if not half_out and lm <= -SL:
            return -SL - SLIPPAGE * 2
        if half_out and bar["close"] <= entry_price:
            return pnl - SLIPPAGE * 2
        if not half_out and hm >= TP1:
            pnl += 0.5 * TP1
            half_out = True
        if half_out and hm >= tp2:
            pnl += 0.5 * tp2
            return pnl - SLIPPAGE * 2
    final = (future.iloc[-1]["close"] - entry_price) / entry_price
    if half_out:
        pnl += 0.5 * final
        return pnl - SLIPPAGE * 2
    return final - SLIPPAGE * 2


def run():
    for sym in SYMBOLS:
        fetch_data(sym)

    all_setups = []
    for symbol in SYMBOLS:
        cache_file = f"boof33_5m_{symbol}.csv"
        if not os.path.exists(cache_file):
            continue
        df = pd.read_csv(cache_file, parse_dates=["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        df["date"]     = df["datetime"].dt.date
        df["time_utc"] = df["datetime"].dt.strftime("%H:%M")

        for date, day in df.groupby("date"):
            day = day.copy().reset_index(drop=True)
            if len(day) < 30:
                continue
            day = add_indicators(day)
            last_i = -999999

            for i in range(LOOKBACK + 5, len(day) - MAX_HOLD_BARS - 2):
                t = day["time_utc"].iloc[i]
                if not (START_UTC <= t < END_UTC):
                    continue
                if i - last_i < COOLDOWN_BARS:
                    continue
                found, signal = detect_signal(day, i)
                if not found:
                    continue
                entry_i = signal["entry_i"]
                if entry_i >= len(day):
                    continue
                entry_price = day["open"].iloc[entry_i] * (1 + SLIPPAGE)
                future = day.iloc[entry_i:entry_i + MAX_HOLD_BARS].copy()
                if future.empty:
                    continue
                mfe = (future["high"].max() - entry_price) / entry_price
                mae = (entry_price - future["low"].min()) / entry_price
                all_setups.append(dict(
                    symbol=symbol, date=date,
                    entry_price=entry_price, future=future,
                    rvol=signal["rvol"],
                    vwap_slope=signal["vwap_slope"],
                    time_utc=signal["time_utc"],
                    mfe=mfe, mae=mae,
                ))
                last_i = i
        print(f"  {symbol}: {sum(1 for s in all_setups if s['symbol']==symbol)} setups")

    print(f"\nTotal setups: {len(all_setups)}  Window: {WIN_LABEL}  Timeframe: 5m")

    # ── Per-symbol screen ──────────────────────────────────────
    by_sym = {}
    for s in all_setups:
        by_sym.setdefault(s["symbol"], []).append(s)

    rows = []
    for sym, setups in by_sym.items():
        pnls   = [exit_scale_fixed(s["future"], s["entry_price"], TP2) for s in setups]
        x      = pd.Series(pnls)
        wins   = (x > 0).sum()
        gw     = x[x > 0].sum()
        gl     = abs(x[x < 0].sum())
        pf_v   = gw / gl if gl > 0 else float("inf")
        n_days = len(set(s["date"] for s in setups))
        rows.append(dict(
            symbol=sym, n=len(x), tpd=len(x)/n_days,
            wr=wins/len(x), pf=pf_v, ev=x.mean(),
            avg_mfe=np.mean([s["mfe"] for s in setups])*100,
            avg_mae=np.mean([s["mae"] for s in setups])*100,
        ))

    rows.sort(key=lambda r: r["pf"], reverse=True)
    print(f"\n{'='*80}")
    print(f"  BOOF33 5m  —  {WIN_LABEL}  —  Runner@1.50% BE stop  —  ranked by PF")
    print(f"{'='*80}")
    print(f"  {'Symbol':<6}  {'n':>4}  {'TPD':>5}  {'WR':>6}  {'PF':>5}  {'EV':>9}  {'AvgMFE':>7}  {'AvgMAE':>7}")
    for r in rows:
        print(f"  {r['symbol']:<6}  {r['n']:4d}  {r['tpd']:5.2f}  {r['wr']:6.1%}  "
              f"{r['pf']:5.2f}  {r['ev']:9.4%}  {r['avg_mfe']:7.3f}%  {r['avg_mae']:7.3f}%")

    # ── Exit study ─────────────────────────────────────────────
    EXIT_CONFIGS = [
        ("50%@0.50% / Runner@1.00% / BE stop", lambda f, ep: exit_scale_fixed(f, ep, 0.010)),
        ("50%@0.50% / Runner@1.50% / BE stop", lambda f, ep: exit_scale_fixed(f, ep, 0.015)),
    ]
    print(f"\n{'='*70}")
    print(f"  EXIT STUDY  ({WIN_LABEL}, {len(all_setups)} setups, 5m bars)")
    print(f"{'='*70}")
    print(f"  {'Config':<38}  {'n':>4}  {'WR':>6}  {'PF':>5}  {'EV':>9}  {'Total':>8}")
    for label, fn in EXIT_CONFIGS:
        pnls = [fn(s["future"], s["entry_price"]) for s in all_setups]
        x    = pd.Series(pnls)
        wins = (x > 0).sum()
        gw   = x[x > 0].sum()
        gl   = abs(x[x < 0].sum())
        pf_v = gw / gl if gl > 0 else float("inf")
        print(f"  {label:<38}  {len(x):4d}  {wins/len(x):6.1%}  "
              f"{pf_v:5.2f}  {x.mean():9.4%}  {x.sum():8.2%}")

    # ── Quality filters ────────────────────────────────────────
    def score(setups):
        if not setups:
            return None
        pnls = [exit_scale_fixed(s["future"], s["entry_price"], TP2) for s in setups]
        x = pd.Series(pnls)
        wins = (x > 0).sum()
        gw = x[x > 0].sum()
        gl = abs(x[x < 0].sum())
        pf_v = gw / gl if gl > 0 else float("inf")
        return dict(n=len(x), wr=wins/len(x), pf=pf_v, ev=x.mean())

    FILTERS = [
        ("No filter (baseline)",         lambda s: True),
        ("RVOL > 1.5",                   lambda s: s["rvol"] > 1.5),
        ("RVOL > 2.0",                   lambda s: s["rvol"] > 2.0),
        ("9:30-9:45 only",               lambda s: s["time_utc"] < "15:45"),
        ("VWAP slope < 0",               lambda s: s["vwap_slope"] < 0),
        ("RVOL>1.5 + 9:30-9:45",         lambda s: s["rvol"] > 1.5 and s["time_utc"] < "15:45"),
        ("RVOL>1.5 + VWAP slope<0",      lambda s: s["rvol"] > 1.5 and s["vwap_slope"] < 0),
    ]
    print(f"\n{'='*70}")
    print(f"  QUALITY FILTER STUDY  (5m bars, Runner@1.50%)")
    print(f"{'='*70}")
    print(f"  {'Filter':<35}  {'n':>4}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    for flabel, filt in FILTERS:
        filtered = [s for s in all_setups if filt(s)]
        r = score(filtered)
        if r is None:
            print(f"  {flabel:<35}  {'0':>4}")
            continue
        print(f"  {flabel:<35}  {r['n']:4d}  {r['wr']:6.1%}  {r['pf']:5.2f}  {r['ev']:9.4%}")

    pd.DataFrame([{k: v for k, v in r.items()} for r in rows]).to_csv("boof33_5m_screen.csv", index=False)
    print(f"\nSaved to boof33_5m_screen.csv")


if __name__ == "__main__":
    run()
