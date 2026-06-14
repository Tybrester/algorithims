# BOOF33 optimized
# Setup: support sweep + reclaim, below VWAP, 9:30-10:00 ET
# Universe: APP, MSTR, AFRM, RDDT, HOOD, NET
# Exit: 50% at +0.50%, 50% at +1.50%, SL -0.30%

import os
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
    "AAPL", "MSFT", "NVDA", "AMD", "META",
    "AMZN", "AVGO", "PLTR", "SMCI", "PLTR",
]
NEW_SYMBOLS = []

LOOKBACK      = 80
SUPPORT_TOL   = 0.002
SWEEP_BUFFER  = 0.001
COOLDOWN_BARS = 30

# Time windows in UTC (ET -> UTC +6)
WINDOWS = [
    ("9:30-10:30",  "15:30", "16:30"),
]

TP1          = 0.005    # +0.50%
TP2          = 0.015    # +1.50%
SL           = 0.003    # -0.30%
MAX_HOLD_BARS = 60
SLIPPAGE     = 0.0002


def add_indicators(day):
    typical = (day["high"] + day["low"] + day["close"]) / 3
    day["vwap"]       = (typical * day["volume"]).cumsum() / day["volume"].cumsum()
    day["avg_vol_20"] = day["volume"].rolling(20).mean()
    day["rvol"]       = day["volume"] / day["avg_vol_20"]          # relative volume
    day["vwap_slope"] = day["vwap"].pct_change(5) * 100           # VWAP slope over 5 bars
    return day


def slack(bar, support):
    """Distance from close to support as % of close."""
    return (bar["close"] - support) / bar["close"]


def find_support(day, i):
    window = day.iloc[max(0, i - LOOKBACK):i]
    if len(window) < 30:
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


def find_resistance(day, i):
    window = day.iloc[max(0, i - LOOKBACK):i]
    if len(window) < 30:
        return None, 0
    highs = window["high"].values
    best_level, best_touches = None, 0
    for h in highs:
        touches = np.sum(np.abs(highs - h) / h <= SUPPORT_TOL)
        if touches > best_touches:
            best_level, best_touches = h, touches
    if best_touches < 2:
        return None, 0
    return best_level, best_touches


def detect_signal(day, i):
    support, touches = find_support(day, i)
    bar = day.iloc[i]
    if (support is not None and
            bar["low"]   < support * (1 - SWEEP_BUFFER) and
            bar["close"] > support and
            bar["close"] < bar["vwap"]):
        return True, "LONG", {
            "support":    support,
            "touches":    touches,
            "entry_i":    i + 1,
            "rvol":       bar["rvol"],
            "slack":      slack(bar, support),
            "vwap_slope": bar["vwap_slope"],
            "time_utc":   day["time_utc"].iloc[i],
        }
    return False, None, {}


def simulate_exit(day, entry_i, entry_price):
    future = day.iloc[entry_i:entry_i + MAX_HOLD_BARS]
    if future.empty:
        return 0.0, "no_future"
    half_out = False
    pnl = 0.0
    for _, bar in future.iterrows():
        high_move = (bar["high"]  - entry_price) / entry_price
        low_move  = (bar["low"]   - entry_price) / entry_price
        if not half_out and low_move <= -SL:
            return -SL - SLIPPAGE * 2, "stop"
        if half_out and bar["close"] <= entry_price:
            # second half stopped at breakeven
            pnl += 0.0
            return pnl - SLIPPAGE * 2, "scale_be"
        if not half_out and high_move >= TP1:
            pnl += 0.5 * TP1
            half_out = True
        if half_out and high_move >= TP2:
            pnl += 0.5 * TP2
            return pnl - SLIPPAGE * 2, "scale"
    final_move = (future.iloc[-1]["close"] - entry_price) / entry_price
    if half_out:
        pnl += 0.5 * final_move
        return pnl - SLIPPAGE * 2, "scale_time"
    return final_move - SLIPPAGE * 2, "time"


def exit_scale_fixed(future, entry_price, tp2):
    """50% off at +0.50%, runner to tp2, BE stop after TP1."""
    half_out = False
    pnl = 0.0
    for _, bar in future.iterrows():
        high_move = (bar["high"] - entry_price) / entry_price
        low_move  = (bar["low"]  - entry_price) / entry_price
        if not half_out and low_move <= -SL:
            return -SL - SLIPPAGE * 2, "stop"
        if half_out and bar["close"] <= entry_price:
            return pnl - SLIPPAGE * 2, "scale_be"
        if not half_out and high_move >= TP1:
            pnl += 0.5 * TP1
            half_out = True
        if half_out and high_move >= tp2:
            pnl += 0.5 * tp2
            return pnl - SLIPPAGE * 2, "scale"
    final = (future.iloc[-1]["close"] - entry_price) / entry_price
    if half_out:
        pnl += 0.5 * final
        return pnl - SLIPPAGE * 2, "scale_time"
    return final - SLIPPAGE * 2, "time"


def exit_trailing(future, entry_price):
    """50% off at +0.50%, runner with trailing stop (peak - 0.30%)."""
    half_out = False
    pnl = 0.0
    trail_stop = None
    peak = entry_price
    for _, bar in future.iterrows():
        high_move = (bar["high"] - entry_price) / entry_price
        low_move  = (bar["low"]  - entry_price) / entry_price
        if not half_out and low_move <= -SL:
            return -SL - SLIPPAGE * 2, "stop"
        if not half_out and high_move >= TP1:
            pnl += 0.5 * TP1
            half_out = True
            peak = bar["high"]
            trail_stop = peak * (1 - SL)
        if half_out:
            if bar["high"] > peak:
                peak = bar["high"]
                trail_stop = peak * (1 - SL)
            if bar["low"] <= trail_stop:
                exit_pnl = (trail_stop - entry_price) / entry_price
                pnl += 0.5 * exit_pnl
                return pnl - SLIPPAGE * 2, "trail_stop"
    final = (future.iloc[-1]["close"] - entry_price) / entry_price
    if half_out:
        pnl += 0.5 * final
        return pnl - SLIPPAGE * 2, "trail_time"
    return final - SLIPPAGE * 2, "time"


def fetch_data(symbol):
    import time
    cache_file = f'boof32_data_{symbol}.csv'
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, parse_dates=['datetime'])
    print(f"  Fetching {symbol} from Alpaca...")
    client = StockHistoricalDataClient(API_KEY, API_SECRET)
    end   = datetime.now()
    start = end - timedelta(days=182)
    req   = StockBarsRequest(symbol_or_symbols=symbol,
                             timeframe=TimeFrame.Minute,
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
            print(f"  {symbol} attempt {attempt+1} failed: {e.__class__.__name__}. Retrying in {wait}s...")
            time.sleep(wait)
    print(f"  {symbol}: all retries failed, skipping.")
    return None


def backtest_symbol_mfe(symbol, start_utc, end_utc):
    cache_file = f"boof32_data_{symbol}.csv"
    if not os.path.exists(cache_file):
        print(f"  {symbol}: no data file found")
        return [], []

    df = pd.read_csv(cache_file, parse_dates=["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    df["date"] = df["datetime"].dt.date
    df["time_utc"] = df["datetime"].dt.strftime("%H:%M")

    trades, mfes = [], []

    for date, day in df.groupby("date"):
        day = day.copy().reset_index(drop=True)
        if len(day) < 150:
            continue
        day = add_indicators(day)
        last_trade_i = -999999

        for i in range(LOOKBACK + 20, len(day) - MAX_HOLD_BARS - 2):
            t = day["time_utc"].iloc[i]
            if not (start_utc <= t < end_utc):
                continue
            if i - last_trade_i < COOLDOWN_BARS:
                continue
            found, direction, signal = detect_signal(day, i)
            if not found:
                continue
            entry_i = signal["entry_i"]
            if entry_i >= len(day):
                continue
            entry_price = day["open"].iloc[entry_i] * (1 + SLIPPAGE)
            pnl, exit_reason = simulate_exit(day, entry_i, entry_price)
            future_highs = day["high"].iloc[entry_i:entry_i + MAX_HOLD_BARS].values
            mfe = (future_highs.max() - entry_price) / entry_price if len(future_highs) else 0
            trades.append({
                "symbol":      symbol,
                "date":        date,
                "direction":   direction,
                "entry_time":  day["datetime"].iloc[entry_i],
                "support":     signal["support"],
                "touches":     signal["touches"],
                "entry_price": entry_price,
                "pnl":         pnl,
                "exit_reason": exit_reason,
            })
            mfes.append(mfe)
            last_trade_i = i

    return trades, mfes


def symbol_stats(trades_list, mfe_list):
    df = pd.DataFrame(trades_list)
    wins = df[df["pnl"] > 0]
    loss = df[df["pnl"] < 0]
    gw = wins["pnl"].sum()
    gl = abs(loss["pnl"].sum())
    pf_val  = gw / gl if gl > 0 else float("inf")
    wr      = len(wins) / len(df)
    ev      = df["pnl"].mean()
    n_days  = df["date"].nunique()
    tpd     = len(df) / n_days if n_days else 0
    avg_mfe = np.mean(mfe_list) * 100 if mfe_list else 0
    med_mfe = np.median(mfe_list) * 100 if mfe_list else 0
    return dict(n=len(df), tpd=tpd, wr=wr, pf=pf_val,
                ev=ev, avg_mfe=avg_mfe, med_mfe=med_mfe)


def run():
    for symbol in SYMBOLS:
        fetch_data(symbol)

    win_label, start_utc, end_utc = WINDOWS[0]

    # Collect all raw setups (entry price + future bars)
    all_setups = []
    for symbol in SYMBOLS:
        cache_file = f"boof32_data_{symbol}.csv"
        if not os.path.exists(cache_file):
            continue
        df = pd.read_csv(cache_file, parse_dates=["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        df["date"] = df["datetime"].dt.date
        df["time_utc"] = df["datetime"].dt.strftime("%H:%M")
        for date, day in df.groupby("date"):
            day = day.copy().reset_index(drop=True)
            if len(day) < 150:
                continue
            day = add_indicators(day)
            last_trade_i = -999999
            for i in range(LOOKBACK + 20, len(day) - MAX_HOLD_BARS - 2):
                t = day["time_utc"].iloc[i]
                if not (start_utc <= t < end_utc):
                    continue
                if i - last_trade_i < COOLDOWN_BARS:
                    continue
                found, direction, signal = detect_signal(day, i)
                if not found:
                    continue
                entry_i = signal["entry_i"]
                if entry_i >= len(day):
                    continue
                entry_price = day["open"].iloc[entry_i] * (1 + SLIPPAGE)
                future = day.iloc[entry_i:entry_i + MAX_HOLD_BARS].copy()
                if future.empty:
                    continue
                future_h = future["high"].values
                future_l = future["low"].values
                mfe = (future_h.max() - entry_price) / entry_price if len(future_h) else 0
                mae = (entry_price - future_l.min()) / entry_price if len(future_l) else 0
                all_setups.append(dict(
                    symbol=symbol, date=date, direction=direction,
                    entry_price=entry_price, future=future,
                    rvol=signal["rvol"], slack=signal["slack"],
                    vwap_slope=signal["vwap_slope"], time_utc=signal["time_utc"],
                    mfe=mfe, mae=mae,
                ))
                last_trade_i = i
        print(f"  {symbol}: {sum(1 for s in all_setups if s['symbol']==symbol)} setups")

    print(f"\nTotal setups: {len(all_setups)}  Window: {win_label}")

    # ── Per-symbol ranked screen ───────────────────────────────
    by_sym = {}
    for s in all_setups:
        by_sym.setdefault(s["symbol"], []).append(s)

    rows = []
    for sym, setups in by_sym.items():
        pnls = [exit_scale_fixed(s["future"], s["entry_price"], 0.015)[0] for s in setups]
        x    = pd.Series(pnls)
        wins = (x > 0).sum()
        gw   = x[x > 0].sum()
        gl   = abs(x[x < 0].sum())
        pf_v = gw / gl if gl > 0 else float("inf")
        n_days = len(set(s["date"] for s in setups))
        rows.append(dict(
            symbol=sym, n=len(x), tpd=len(x)/n_days,
            wr=wins/len(x), pf=pf_v, ev=x.mean(),
            avg_mfe=np.mean([s["mfe"] for s in setups])*100,
            avg_mae=np.mean([s["mae"] for s in setups])*100,
        ))

    rows.sort(key=lambda r: r["pf"], reverse=True)
    print(f"\n{'='*80}")
    print(f"  SYMBOL SCREEN  (9:30-10:30, Runner@1.50% BE stop)  — ranked by PF")
    print(f"{'='*80}")
    print(f"  {'Symbol':<6}  {'n':>4}  {'TPD':>5}  {'WR':>6}  {'PF':>5}  {'EV':>9}  {'AvgMFE':>7}  {'AvgMAE':>7}")
    for r in rows:
        print(f"  {r['symbol']:<6}  {r['n']:4d}  {r['tpd']:5.2f}  {r['wr']:6.1%}  "
              f"{r['pf']:5.2f}  {r['ev']:9.4%}  {r['avg_mfe']:7.3f}%  {r['avg_mae']:7.3f}%")

    # ── Per-symbol LONG vs SHORT breakdown ─────────────────────
    print(f"\n{'='*80}")
    print(f"  PER-SYMBOL LONG vs SHORT  (Runner@1.50% BE stop)")
    print(f"{'='*80}")
    print(f"  {'Symbol':<6}  {'Side':<5}  {'n':>4}  {'WR':>6}  {'PF':>5}  {'EV':>9}  {'Total':>8}")
    dir_rows = []
    for sym, setups in by_sym.items():
        for direction in ["LONG", "SHORT"]:
            ds = [s for s in setups if s["direction"] == direction]
            if not ds:
                continue
            pnls = [exit_scale_fixed(s["future"], s["entry_price"], 0.015)[0] for s in ds]
            x = pd.Series(pnls)
            wins = (x > 0).sum()
            gw = x[x > 0].sum(); gl = abs(x[x < 0].sum())
            pf_v = gw / gl if gl > 0 else float("inf")
            dir_rows.append(dict(symbol=sym, direction=direction, n=len(x),
                                 wr=wins/len(x), pf=pf_v, ev=x.mean(), total=x.sum()))
    dir_rows.sort(key=lambda r: r["pf"], reverse=True)
    for r in dir_rows:
        flag = " ✓" if r["pf"] >= 1.20 and r["n"] >= 10 else ""
        print(f"  {r['symbol']:<6}  {r['direction']:<5}  {r['n']:4d}  {r['wr']:6.1%}  "
              f"{r['pf']:5.2f}  {r['ev']:9.4%}  {r['total']:8.2%}{flag}")
    print(f"\n  ✓ = PF >= 1.20 and n >= 10")

    pd.DataFrame(dir_rows).to_csv("boof33_direction_screen.csv", index=False)
    pd.DataFrame(rows).to_csv("boof33_screen.csv", index=False)
    print(f"\nSaved: boof33_screen.csv  boof33_direction_screen.csv")

    # ── Quality filter study (trailing stop exit) ──────────────
    def score_setups(setups):
        if not setups:
            return None
        pnls = [exit_trailing(s["future"], s["entry_price"])[0] for s in setups]
        x = pd.Series(pnls)
        wins = (x > 0).sum()
        gw = x[x > 0].sum()
        gl = abs(x[x < 0].sum())
        pf_val = gw / gl if gl > 0 else float("inf")
        return dict(n=len(x), wr=wins/len(x), pf=pf_val, ev=x.mean())

    QUALITY_FILTERS = [
        ("No filter (baseline)",          lambda s: True),
        ("RVOL > 1.5",                     lambda s: s["rvol"] > 1.5),
        ("RVOL > 2.0",                     lambda s: s["rvol"] > 2.0),
        ("Slack > 0.3%",                   lambda s: s["slack"] > 0.003),
        ("Slack > 0.5%",                   lambda s: s["slack"] > 0.005),
        ("9:30-9:45 only",                 lambda s: s["time_utc"] < "15:45"),
        ("9:45-10:30 only",                lambda s: s["time_utc"] >= "15:45"),
        ("VWAP slope < 0 (declining)",     lambda s: s["vwap_slope"] < 0),
        ("VWAP slope < -0.05%",            lambda s: s["vwap_slope"] < -0.05),
        ("RVOL>1.5 + Slack>0.3%",          lambda s: s["rvol"] > 1.5 and s["slack"] > 0.003),
        ("RVOL>1.5 + VWAP slope<0",        lambda s: s["rvol"] > 1.5 and s["vwap_slope"] < 0),
        ("RVOL>1.5 + 9:30-9:45",           lambda s: s["rvol"] > 1.5 and s["time_utc"] < "15:45"),
        ("Slack>0.3% + VWAP slope<0",      lambda s: s["slack"] > 0.003 and s["vwap_slope"] < 0),
        ("RVOL>1.5 + Slack>0.3% + slope<0",lambda s: s["rvol"] > 1.5 and s["slack"] > 0.003 and s["vwap_slope"] < 0),
    ]

    print(f"\n{'='*70}")
    print(f"  QUALITY FILTER STUDY  (Trailing Stop, {win_label})")
    print(f"{'='*70}")
    print(f"  {'Filter':<38}  {'n':>4}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    for flabel, filt in QUALITY_FILTERS:
        filtered = [s for s in all_setups if filt(s)]
        r = score_setups(filtered)
        if r is None:
            print(f"  {flabel:<38}  {'0':>4}")
            continue
        print(f"  {flabel:<38}  {r['n']:4d}  {r['wr']:6.1%}  {r['pf']:5.2f}  {r['ev']:9.4%}")

    EXIT_CONFIGS = [
        ("50%@0.50% / Runner@1.00% / BE stop",  lambda f, ep: exit_scale_fixed(f, ep, 0.010)),
        ("50%@0.50% / Runner@1.50% / BE stop",  lambda f, ep: exit_scale_fixed(f, ep, 0.015)),
        ("50%@0.50% / Trailing stop",            lambda f, ep: exit_trailing(f, ep)),
    ]

    print(f"\n{'='*70}")
    print(f"  EXIT STUDY  ({win_label}, {len(all_setups)} setups)")
    print(f"{'='*70}")
    print(f"  {'Config':<38}  {'n':>4}  {'WR':>6}  {'PF':>5}  {'EV':>9}  {'Total':>7}")

    for label, exit_fn in EXIT_CONFIGS:
        pnls = []
        for s in all_setups:
            pnl, _ = exit_fn(s["future"], s["entry_price"])
            pnls.append(pnl)
        x = pd.Series(pnls)
        wins = (x > 0).sum()
        gross_w = x[x > 0].sum()
        gross_l = abs(x[x < 0].sum())
        pf_val = gross_w / gross_l if gross_l > 0 else float("inf")
        print(f"  {label:<38}  {len(x):4d}  {wins/len(x):6.1%}  "
              f"{pf_val:5.2f}  {x.mean():9.4%}  {x.sum():7.2%}")

    # Per-symbol breakdown for best config (trailing)
    print(f"\n{'='*70}")
    print(f"  PER-SYMBOL: 50%@0.50% Trailing Stop  ({win_label})")
    print(f"{'='*70}")
    print(f"  {'Symbol':<6}  {'n':>4}  {'WR':>6}  {'PF':>5}  {'EV':>9}")
    by_sym = {}
    for s in all_setups:
        by_sym.setdefault(s["symbol"], []).append(s)
    for sym in sorted(by_sym, key=lambda s: -np.mean([exit_trailing(t["future"], t["entry_price"])[0] for t in by_sym[s]])):
        pnls = [exit_trailing(t["future"], t["entry_price"])[0] for t in by_sym[sym]]
        x = pd.Series(pnls)
        wins = (x > 0).sum()
        gw = x[x > 0].sum()
        gl = abs(x[x < 0].sum())
        pf_val = gw / gl if gl > 0 else float("inf")
        print(f"  {sym:<6}  {len(x):4d}  {wins/len(x):6.1%}  {pf_val:5.2f}  {x.mean():9.4%}")


if __name__ == "__main__":
    run()
