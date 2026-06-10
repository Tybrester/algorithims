"""
BOOF 28 - QQQ Move Bucket + Stock Move Sub-Bucket Analysis
QQQ buckets: 0-0.10%, 0.10-0.25%, 0.25-0.50%, >0.50%
Stock move sub-buckets: 0.50-0.60%, 0.60-0.70%, 0.70-0.80%
Filter: QQQ > EMA50 (best filter found)
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

# Wide stock move range to capture all sub-buckets
MIN_MOVE = 0.0050
MAX_MOVE = 0.0080

def load_cached(symbol):
    cache_file = f"boof_cache/{symbol}_2025-01-01_2026-12-31.pkl"
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    return None

def build_qqq_daily_emas(qqq_df):
    qqq_daily = qqq_df.between_time('16:00', '16:00').copy()
    qqq_daily['date'] = qqq_daily.index.date
    daily_close = qqq_daily.groupby('date')['close'].last()
    ema20 = daily_close.ewm(span=20, adjust=False).mean()
    ema50 = daily_close.ewm(span=50, adjust=False).mean()
    return ema20, ema50

def get_ema_val(series, date):
    val = series.get(date)
    if val is None:
        prior = [d for d in series.index if d < date]
        val = series[prior[-1]] if prior else None
    return val

def print_bucket(label, df):
    if len(df) == 0:
        print(f"  {label:20} {'0':>6}  {'---':>7}  {'---':>9}  {'---':>9}  {'---':>6}")
        return
    wins = len(df[df['pnl'] > 0])
    wr = wins / len(df) * 100
    avg = df['pnl'].mean()
    total = df['pnl'].sum()
    gp = df[df['pnl'] > 0]['pnl'].sum()
    gl = abs(df[df['pnl'] <= 0]['pnl'].sum())
    pf = gp / gl if gl > 0 else 0
    print(f"  {label:20} {len(df):>6}  {wr:>6.1f}%  {avg:>+8.3f}%  {total:>+8.2f}%  {pf:>6.2f}")

def run_test():
    print('='*90)
    print('BOOF 28 - QQQ MOVE BUCKETS + STOCK MOVE SUB-BUCKETS')
    print('Filter: QQQ 5m > 0 AND QQQ > Daily EMA50 | Entry 9:35 | Exit 10:15 | 2025')
    print('='*90)

    print("\nLoading data...")
    all_data = {}
    for sym in ['QQQ'] + SYMBOLS:
        df = load_cached(sym)
        if df is not None:
            all_data[sym] = df
    print(f"Loaded {len(all_data)} symbols")

    start_date = pd.to_datetime('2025-01-01').tz_localize('UTC')
    end_date = pd.to_datetime('2025-12-31').tz_localize('UTC')

    qqq_full = all_data['QQQ'].copy()
    qqq_full = qqq_full[(qqq_full.index >= start_date) & (qqq_full.index <= end_date)]
    daily_ema20, daily_ema50 = build_qqq_daily_emas(qqq_full)

    qqq_df = qqq_full.copy()
    qqq_df['date'] = qqq_df.index.date
    dates = sorted(qqq_df['date'].unique())

    print(f"Analyzing {len(dates)} trading days...\n")

    all_trades = []

    for trade_date in dates:
        qqq_day = qqq_df[qqq_df['date'] == trade_date]
        qqq_open = qqq_day.between_time('09:30', '09:34')
        if len(qqq_open) == 0:
            continue

        qqq_move = (qqq_open.iloc[-1]['close'] - qqq_open.iloc[0]['open']) / qqq_open.iloc[0]['open']
        if qqq_move <= 0:
            continue

        # EMA50 filter
        qqq_close_today = qqq_day.between_time('16:00', '16:00')
        qqq_price = qqq_close_today.iloc[-1]['close'] if len(qqq_close_today) > 0 else qqq_day.iloc[-1]['close']
        ema50_val = get_ema_val(daily_ema50, trade_date)
        if ema50_val is None or qqq_price <= ema50_val:
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

            open_p = stock_open.iloc[0]['open']
            close_p = stock_open.iloc[-1]['close']
            stock_move = (close_p - open_p) / open_p

            if not (MIN_MOVE <= stock_move <= MAX_MOVE):
                continue

            entry_data = day.between_time('09:35', '09:35')
            exit_data = day.between_time('10:15', '10:15')
            if len(entry_data) == 0 or len(exit_data) == 0:
                continue

            entry_price = entry_data.iloc[0]['close']
            exit_price = exit_data.iloc[0]['close']
            pnl = (exit_price - entry_price) / entry_price * 100

            all_trades.append({
                'symbol': sym,
                'pnl': pnl,
                'qqq_move': qqq_move * 100,       # in %
                'stock_move': stock_move * 100     # in %
            })

    if not all_trades:
        print("No trades found")
        return

    df = pd.DataFrame(all_trades)
    print(f"Total trades (QQQ>0 + QQQ>EMA50): {len(df)}\n")

    hdr = f"  {'Bucket':20} {'Trades':>6}  {'WR%':>7}  {'Avg P&L':>9}  {'Total':>9}  {'PF':>6}"
    sep = '  ' + '-'*86

    # ── QQQ 5m Move Buckets ──────────────────────────────────────────
    print('='*90)
    print('QQQ 5m MOVE BUCKETS')
    print('='*90)
    print(hdr)
    print(sep)

    qqq_buckets = [
        ('QQQ 0.00-0.10%',  (0.00, 0.10)),
        ('QQQ 0.10-0.25%',  (0.10, 0.25)),
        ('QQQ 0.25-0.50%',  (0.25, 0.50)),
        ('QQQ > 0.50%',     (0.50, 99.0)),
    ]
    for label, (lo, hi) in qqq_buckets:
        sub = df[(df['qqq_move'] > lo) & (df['qqq_move'] <= hi)]
        print_bucket(label, sub)

    # ── Stock Move Sub-Buckets (0.50-0.80%) ─────────────────────────
    print()
    print('='*90)
    print('STOCK MOVE SUB-BUCKETS (within 0.50-0.80%)')
    print('='*90)
    print(hdr)
    print(sep)

    stock_buckets = [
        ('Stock 0.50-0.60%', (0.50, 0.60)),
        ('Stock 0.60-0.70%', (0.60, 0.70)),
        ('Stock 0.70-0.80%', (0.70, 0.80)),
    ]
    for label, (lo, hi) in stock_buckets:
        sub = df[(df['stock_move'] > lo) & (df['stock_move'] <= hi)]
        print_bucket(label, sub)

    # ── Cross-tab: QQQ bucket × Stock sub-bucket ────────────────────
    print()
    print('='*90)
    print('CROSS-TAB: QQQ BUCKET x STOCK SUB-BUCKET')
    print('='*90)
    print(f"  {'':20}", end='')
    for slabel, _ in stock_buckets:
        print(f"  {slabel:>18}", end='')
    print()
    print('  ' + '-'*86)

    for qlabel, (qlo, qhi) in qqq_buckets:
        qsub = df[(df['qqq_move'] > qlo) & (df['qqq_move'] <= qhi)]
        print(f"  {qlabel:20}", end='')
        for slabel, (slo, shi) in stock_buckets:
            cell = qsub[(qsub['stock_move'] > slo) & (qsub['stock_move'] <= shi)]
            if len(cell) == 0:
                print(f"  {'  --/--':>18}", end='')
            else:
                wr = len(cell[cell['pnl'] > 0]) / len(cell) * 100
                avg = cell['pnl'].mean()
                print(f"  {f'n={len(cell)} WR={wr:.0f}% avg={avg:+.2f}%':>18}", end='')
        print()

    print('='*90)

if __name__ == '__main__':
    run_test()
