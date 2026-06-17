"""
BOOF 28 - Short System Test
SHORT: qqq_5m <= -0.10% AND qqq_close < ema50 AND stock_5m in bucket
Entry: 9:35 | Exit: 10:15 | pnl = (entry - exit) / entry
Test buckets: -0.40/-0.60, -0.60/-0.80, -0.80/-1.00, -1.00/-1.50
Periods: 2025, 2026 YTD, Combined
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

SHORT_BUCKETS = [
    ("-0.40% to -0.60%", -0.60, -0.40),
    ("-0.60% to -0.80%", -0.80, -0.60),
    ("-0.80% to -1.00%", -1.00, -0.80),
    ("-1.00% to -1.50%", -1.50, -1.00),
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

def print_bucket_row(label, df):
    if len(df) == 0:
        print(f"  {label:22} {'0':>7}  {'---':>7}  {'---':>9}  {'---':>9}  {'---':>6}")
        return
    wins = len(df[df['pnl'] > 0])
    wr = wins / len(df) * 100
    avg = df['pnl'].mean()
    total = df['pnl'].sum()
    gp = df[df['pnl'] > 0]['pnl'].sum()
    gl = abs(df[df['pnl'] <= 0]['pnl'].sum())
    pf = gp / gl if gl > 0 else 0
    print(f"  {label:22} {len(df):>7}  {wr:>6.1f}%  {avg:>+8.3f}%  {total:>+9.2f}%  {pf:>6.2f}")

def report(trades, label):
    if not trades:
        print(f"\n{label}: NO TRADES")
        return
    df = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    wr = len(wins) / len(df) * 100
    avg = df['pnl'].mean()
    total = df['pnl'].sum()
    gp = wins['pnl'].sum()
    gl = abs(losses['pnl'].sum())
    pf = gp / gl if gl > 0 else 0
    df_s = df.sort_values('date')
    df_s['cum'] = df_s['pnl'].cumsum()
    dd = (df_s['cum'].expanding().max() - df_s['cum']).max()

    print(f"\n{'='*80}")
    print(f"{label}")
    print(f"{'='*80}")
    print(f"  Trades:        {len(df)}")
    print(f"  Win Rate:      {wr:.1f}%")
    print(f"  Avg P&L:       {avg:+.3f}%")
    print(f"  Total P&L:     {total:+.2f}%")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Max Drawdown:  -{dd:.2f}%")

    # Bucket breakdown
    print(f"\n  {'Bucket':22} {'Trades':>7}  {'WR%':>7}  {'Avg P&L':>9}  {'Total':>9}  {'PF':>6}")
    print(f"  {'-'*70}")
    for blabel, lo, hi in SHORT_BUCKETS:
        sub = df[(df['stock_5m'] >= lo) & (df['stock_5m'] < hi)]
        print_bucket_row(blabel, sub)

    # Monthly breakdown
    print(f"\n  {'Month':10} {'Trades':>8} {'Win%':>7} {'Avg P&L':>10} {'Total':>10} {'Cum P&L':>10}")
    print(f"  {'-'*60}")
    df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
    cum = 0
    for month in sorted(df['month'].unique()):
        mdf = df[df['month'] == month]
        mwr = len(mdf[mdf['pnl'] > 0]) / len(mdf) * 100
        mtot = mdf['pnl'].sum()
        cum += mtot
        print(f"  {str(month):10} {len(mdf):>8} {mwr:>6.1f}% {mdf['pnl'].mean():>+9.3f}% {mtot:>+9.2f}% {cum:>+9.2f}%")

def collect_trades(all_data, daily_ema50, start_date, end_date):
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

        qqq_5m_move = (qqq_open.iloc[-1]['close'] - qqq_open.iloc[0]['open']) / qqq_open.iloc[0]['open'] * 100

        # QQQ bearish: 5m <= -0.10%
        if qqq_5m_move > -0.10:
            continue

        # QQQ close < EMA50
        qqq_close_bar = qqq_day.between_time('16:00', '16:00')
        qqq_close = qqq_close_bar.iloc[-1]['close'] if len(qqq_close_bar) > 0 else qqq_day.iloc[-1]['close']
        ema50 = get_ema_val(daily_ema50, trade_date)
        if ema50 is None or qqq_close >= ema50:
            continue

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

            # Must be in one of the short buckets
            if not (-1.50 <= stock_5m <= -0.40):
                continue

            entry_bar = day.between_time('09:35', '09:35')
            exit_bar  = day.between_time('10:15', '10:15')
            if len(entry_bar) == 0 or len(exit_bar) == 0:
                continue

            entry_price = entry_bar.iloc[0]['close']
            exit_price  = exit_bar.iloc[0]['close']

            # Short P&L: profit when price falls
            pnl = (entry_price - exit_price) / entry_price * 100

            trades.append({
                'date':       trade_date,
                'symbol':     sym,
                'pnl':        pnl,
                'qqq_5m':     qqq_5m_move,
                'stock_5m':   stock_5m,
            })

    return trades

def main():
    print('='*80)
    print('BOOF 28 - SHORT SYSTEM TEST')
    print('qqq_5m <= -0.10% AND qqq_close < EMA50 AND stock in bucket')
    print('Entry: 9:35  |  Exit: 10:15  |  pnl = (entry - exit) / entry')
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

    print("Running 2025...")
    t2025 = collect_trades(all_data, daily_ema50, s2025_start, s2025_end)
    print("Running 2026...")
    t2026 = collect_trades(all_data, daily_ema50, s2026_start, s2026_end)

    report(t2025,          "2025 FULL YEAR — SHORT")
    report(t2026,          "2026 YTD (Jan-Jun 9) — SHORT")
    report(t2025 + t2026,  "COMBINED (2025 + 2026 YTD) — SHORT")

if __name__ == '__main__':
    main()
