"""
BOOF 28 - Long/Short Regime System
if qqq_close > ema50: run_long_strategy()
else:                  run_short_strategy()

LONG:  qqq_5m >= +0.10% | stock_5m 0.60-0.70% | entry 9:35 | exit 10:15
SHORT: qqq_5m <= -0.10% | stock_5m -0.80 to -1.50% | entry 9:35 | exit 10:15
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
import pickle
import os
import numpy as np

SYMBOLS = [
    "NVDA", "AMD", "AVGO", "QCOM", "AMAT", "MU", "MRVL", "LRCX", "KLAC", "ASML", "TSM", "ARM", "INTC", "ON",
    "MCHP", "ADI", "NXPI", "TXN", "MPWR", "TER", "SMCI", "ANET", "DELL", "HPE", "STM",
    "MSFT", "GOOGL", "META", "AMZN", "AAPL", "TSLA", "NFLX",
    "CRM", "ADBE", "INTU", "NOW", "SHOP", "ORCL", "IBM", "CSCO",
    "PLTR", "SNOW", "DDOG", "MDB", "NET", "CRWD", "PANW", "ZS", "ESTC", "S",
    "AI", "PATH", "DOCN", "FSLY", "AKAM",
    "PYPL", "SQ", "HOOD", "COIN", "ADP", "FIS", "FI", "GPN", "JKHY",
    "UBER", "ABNB", "DASH", "RBLX", "APP",
    "TTD", "DUOL", "CELH", "CAVA", "RKLB",
    "LLY", "NVO", "ABBV", "JNJ", "MRK", "AMGN", "GILD", "REGN", "VRTX", "ISRG",
    "BIIB", "BMY", "PFE", "MRNA", "NBIX",
    "GE", "CAT", "ETN", "PH", "TT", "DE", "HON", "EMR", "ROP", "URI"
]

def load_cached(symbol):
    cache_file = f"boof_cache/{symbol}_2025-01-01_2026-12-31.pkl"
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    return None

def build_daily_ema50(qqq_df):
    daily = qqq_df.between_time('16:00', '16:00').copy()
    daily['date'] = daily.index.date
    daily_close = daily.groupby('date')['close'].last()
    return daily_close.ewm(span=50, adjust=False).mean()

def get_ema_val(series, date):
    val = series.get(date)
    if val is None:
        prior = [d for d in series.index if d < date]
        val = series[prior[-1]] if prior else None
    return val

def report(trades, label):
    if not trades:
        print(f"\n{label}: NO TRADES")
        return
    df = pd.DataFrame(trades)
    longs  = df[df['side'] == 'LONG']
    shorts = df[df['side'] == 'SHORT']

    def stats(d):
        if len(d) == 0:
            return 0, 0, 0, 0, 0
        wr  = len(d[d['pnl'] > 0]) / len(d) * 100
        avg = d['pnl'].mean()
        tot = d['pnl'].sum()
        gp  = d[d['pnl'] > 0]['pnl'].sum()
        gl  = abs(d[d['pnl'] <= 0]['pnl'].sum())
        pf  = gp / gl if gl > 0 else 0
        return wr, avg, tot, pf, len(d)

    l_wr, l_avg, l_tot, l_pf, l_n = stats(longs)
    s_wr, s_avg, s_tot, s_pf, s_n = stats(shorts)
    t_wr, t_avg, t_tot, t_pf, t_n = stats(df)

    df_s = df.sort_values('date')
    df_s['cum'] = df_s['pnl'].cumsum()
    dd = (df_s['cum'].expanding().max() - df_s['cum']).max()

    print(f"\n{'='*80}")
    print(f"{label}")
    print(f"{'='*80}")
    print(f"  {'':10} {'Trades':>8} {'Win%':>7} {'Avg P&L':>10} {'Total':>10} {'PF':>6}")
    print(f"  {'-'*55}")
    print(f"  {'LONG':10} {l_n:>8} {l_wr:>6.1f}% {l_avg:>+9.3f}% {l_tot:>+9.2f}% {l_pf:>6.2f}")
    print(f"  {'SHORT':10} {s_n:>8} {s_wr:>6.1f}% {s_avg:>+9.3f}% {s_tot:>+9.2f}% {s_pf:>6.2f}")
    print(f"  {'-'*55}")
    print(f"  {'COMBINED':10} {t_n:>8} {t_wr:>6.1f}% {t_avg:>+9.3f}% {t_tot:>+9.2f}% {t_pf:>6.2f}")
    print(f"  Max Drawdown: -{dd:.2f}%")

    # Monthly
    print(f"\n  {'Month':10} {'Side':6} {'Trades':>7} {'Win%':>7} {'Total':>10} {'Cum':>10}")
    print(f"  {'-'*55}")
    df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
    cum = 0
    for month in sorted(df['month'].unique()):
        mdf = df[df['month'] == month]
        mtot = mdf['pnl'].sum()
        cum += mtot
        mwr  = len(mdf[mdf['pnl'] > 0]) / len(mdf) * 100
        ml   = len(mdf[mdf['side'] == 'LONG'])
        ms   = len(mdf[mdf['side'] == 'SHORT'])
        sides = f"L={ml}/S={ms}"
        print(f"  {str(month):10} {sides:8} {len(mdf):>7} {mwr:>6.1f}% {mtot:>+9.2f}% {cum:>+9.2f}%")

def collect_trades(all_data, daily_ema50, start_date, end_date, use_qqq_5m_filter=False):
    qqq_df = all_data['QQQ'].copy()
    qqq_df = qqq_df[(qqq_df.index >= start_date) & (qqq_df.index <= end_date)]
    qqq_df['date'] = qqq_df.index.date
    dates = sorted(qqq_df['date'].unique())

    trades = []

    for trade_date in dates:
        qqq_day = qqq_df[qqq_df['date'] == trade_date]
        qqq_open = qqq_day.between_time('09:30', '09:34')
        if len(qqq_open) == 0:
            continue

        qqq_5m = (qqq_open.iloc[-1]['close'] - qqq_open.iloc[0]['open']) / qqq_open.iloc[0]['open'] * 100

        # QQQ daily close vs EMA50
        qqq_close_bar = qqq_day.between_time('16:00', '16:00')
        qqq_close = qqq_close_bar.iloc[-1]['close'] if len(qqq_close_bar) > 0 else qqq_day.iloc[-1]['close']
        ema50 = get_ema_val(daily_ema50, trade_date)
        if ema50 is None:
            continue

        bull_regime = qqq_close > ema50
        bear_regime = qqq_close < ema50

        for sym in SYMBOLS:
            if sym not in all_data:
                continue

            df = all_data[sym].copy()
            df = df[(df.index >= start_date) & (df.index <= end_date)]
            day = df[df.index.date == trade_date]
            if len(day) == 0:
                continue

            stock_open = day.between_time('09:30', '09:34')
            if len(stock_open) == 0:
                continue

            open_p  = stock_open.iloc[0]['open']
            close_p = stock_open.iloc[-1]['close']
            stock_5m = (close_p - open_p) / open_p * 100

            entry_bar = day.between_time('09:35', '09:35')
            exit_bar  = day.between_time('10:15', '10:15')
            if len(entry_bar) == 0 or len(exit_bar) == 0:
                continue

            entry_price = entry_bar.iloc[0]['close']
            exit_price  = exit_bar.iloc[0]['close']

            # ── LONG ──────────────────────────────────────────────
            long_ok = bull_regime and (0.60 <= stock_5m < 0.70)
            if use_qqq_5m_filter:
                long_ok = long_ok and qqq_5m >= 0.10

            if long_ok:
                pnl = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    'date': trade_date, 'symbol': sym,
                    'pnl': pnl, 'side': 'LONG',
                    'qqq_5m': qqq_5m, 'stock_5m': stock_5m
                })

            # ── SHORT ─────────────────────────────────────────────
            short_ok = bear_regime and (-1.50 <= stock_5m <= -0.80)
            if use_qqq_5m_filter:
                short_ok = short_ok and qqq_5m <= -0.10

            if short_ok:
                pnl = (entry_price - exit_price) / entry_price * 100
                trades.append({
                    'date': trade_date, 'symbol': sym,
                    'pnl': pnl, 'side': 'SHORT',
                    'qqq_5m': qqq_5m, 'stock_5m': stock_5m
                })

    return trades

def main():
    print('='*80)
    print('BOOF 28 - LONG/SHORT REGIME SYSTEM')
    print('if qqq_close > ema50: LONG  (qqq_5m>=0.10%, stock 0.60-0.70%)')
    print('else:                  SHORT (qqq_5m<=-0.10%, stock -0.80 to -1.50%)')
    print('Entry: 9:35  |  Exit: 10:15')
    print('='*80)

    print("\nLoading data...")
    all_data = {}
    for sym in ['QQQ'] + SYMBOLS:
        df = load_cached(sym)
        if df is not None:
            all_data[sym] = df
    print(f"Loaded {len(all_data)} symbols")

    qqq_full = all_data['QQQ'].copy()
    daily_ema50 = build_daily_ema50(qqq_full)

    s2025_start = pd.to_datetime('2025-01-01').tz_localize('UTC')
    s2025_end   = pd.to_datetime('2025-12-31').tz_localize('UTC')
    s2026_start = pd.to_datetime('2026-01-01').tz_localize('UTC')
    s2026_end   = pd.to_datetime('2026-06-09').tz_localize('UTC')

    for ver, use_filter in [
        ("VERSION 1 — EMA50 regime only (no QQQ 5m filter)", False),
        ("VERSION 2 — EMA50 regime + QQQ 5m filter (>=+0.10% / <=-0.10%)", True),
    ]:
        print(f"\n\n{'#'*80}")
        print(f"# {ver}")
        print(f"{'#'*80}")

        print("  Running 2025...")
        t2025 = collect_trades(all_data, daily_ema50, s2025_start, s2025_end, use_filter)
        print("  Running 2026...")
        t2026 = collect_trades(all_data, daily_ema50, s2026_start, s2026_end, use_filter)

        report(t2025,         f"2025 FULL YEAR  [{ver}]")
        report(t2026,         f"2026 YTD        [{ver}]")
        report(t2025 + t2026, f"COMBINED        [{ver}]")

if __name__ == '__main__':
    main()
