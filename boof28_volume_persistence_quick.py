"""
BOOF 28 - Volume Persistence Test (Quick - Top 10 Symbols)
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
import pickle
import os
import numpy as np

# Top 10 liquid symbols only for speed
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

MIN_MOVE = 0.0050
MAX_MOVE = 0.0080

def load_cached(symbol):
    cache_file = f"boof_cache/{symbol}_2025-01-01_2026-12-31.pkl"
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    return None

def calculate_time_of_day_avg_volume(all_data, symbol, time_str):
    if symbol not in all_data:
        return 1
    df = all_data[symbol].copy()
    df['date'] = df.index.date
    unique_dates = df['date'].unique()
    volumes = []
    for date in unique_dates[:100]:  # Limit to 100 days for speed
        day_df = df[df['date'] == date]
        bar = day_df.between_time(time_str, time_str)
        if len(bar) > 0:
            volumes.append(bar.iloc[0]['volume'])
    return np.mean(volumes) if volumes else 1

def get_bar_volume(df, time_str):
    bar = df.between_time(time_str, time_str)
    if len(bar) == 0:
        return 0
    return bar.iloc[0]['volume']

def build_qqq_daily_emas(qqq_df):
    """Build daily close series, EMA20 and EMA50 for QQQ"""
    qqq_daily = qqq_df.between_time('16:00', '16:00').copy()
    qqq_daily['date'] = qqq_daily.index.date
    daily_close = qqq_daily.groupby('date')['close'].last()
    daily_ema20 = daily_close.ewm(span=20, adjust=False).mean()
    daily_ema50 = daily_close.ewm(span=50, adjust=False).mean()
    return daily_ema20, daily_ema50

def summarize(trades_list, label):
    if not trades_list:
        print(f"{label}: NO TRADES")
        return
    df = pd.DataFrame(trades_list)
    wins = df[df['pnl'] > 0]
    losers = df[df['pnl'] <= 0]
    wr = len(wins) / len(df) * 100
    avg = df['pnl'].mean()
    total = df['pnl'].sum()
    gp = wins['pnl'].sum()
    gl = abs(losers['pnl'].sum())
    pf = gp / gl if gl > 0 else 0

    print(f"\n{'='*80}")
    print(f"{label}")
    print(f"{'='*80}")
    print(f"  Trades:         {len(df)}")
    print(f"  Win Rate:       {wr:.1f}%")
    print(f"  Avg P&L:        {avg:+.3f}%")
    print(f"  Total P&L:      {total:+.2f}%")
    print(f"  Profit Factor:  {pf:.2f}")

    # Persistent vs non-persistent
    p = df[df['volume_persistent'] == True]
    np_ = df[df['volume_persistent'] == False]
    p_win = len(p[p['pnl'] > 0]) / len(p) * 100 if len(p) > 0 else 0
    np_win = len(np_[np_['pnl'] > 0]) / len(np_) * 100 if len(np_) > 0 else 0

    print(f"\n  Volume Persistence:")
    print(f"  {'':3} {'Trades':8} {'Win%':8} {'Avg P&L':10}")
    print(f"  {'Persistent':12} {len(p):8} {p_win:7.1f}% {p['pnl'].mean():+9.3f}%" if len(p) > 0 else f"  Persistent: 0 trades")
    print(f"  {'Non-Persist':12} {len(np_):8} {np_win:7.1f}% {np_['pnl'].mean():+9.3f}%" if len(np_) > 0 else f"  Non-Persist: 0 trades")

    # Decay ratio winners vs losers
    w = df[df['pnl'] > 0]
    l = df[df['pnl'] <= 0]
    print(f"\n  Decay Ratio (bar3/bar1):")
    print(f"  Winners ({len(w)} trades): Avg Decay = {w['decay_ratio'].mean():.3f}")
    print(f"  Losers  ({len(l)} trades): Avg Decay = {l['decay_ratio'].mean():.3f}")
    print(f"  Correlation (decay vs pnl): {df['decay_ratio'].corr(df['pnl']):.3f}")

def run_test():
    print('='*80)
    print('BOOF 28 - VOLUME PERSISTENCE + QQQ FILTER TEST')
    print('Config: 0.50-0.80% move | 9:35 entry | 10:15 exit | 2025 full year')
    print('='*80)

    print("\nLoading data...")
    all_data = {}
    for sym in ['QQQ'] + SYMBOLS:
        df = load_cached(sym)
        if df is not None:
            all_data[sym] = df
    print(f"Loaded {len(all_data)} symbols")

    print("\nCalculating time-of-day averages...")
    time_avgs = {}
    for sym in SYMBOLS:
        if sym not in all_data:
            continue
        time_avgs[sym] = {
            '09:30': calculate_time_of_day_avg_volume(all_data, sym, '09:30'),
            '09:35': calculate_time_of_day_avg_volume(all_data, sym, '09:35'),
            '09:40': calculate_time_of_day_avg_volume(all_data, sym, '09:40')
        }

    start_date = pd.to_datetime('2025-01-01').tz_localize('UTC')
    end_date = pd.to_datetime('2025-12-31').tz_localize('UTC')

    # Build QQQ daily EMA20 and EMA50
    qqq_full = all_data['QQQ'].copy()
    qqq_full = qqq_full[(qqq_full.index >= start_date) & (qqq_full.index <= end_date)]
    daily_ema20, daily_ema50 = build_qqq_daily_emas(qqq_full)

    qqq_df = qqq_full.copy()
    qqq_df['date'] = qqq_df.index.date
    dates = sorted(qqq_df['date'].unique())

    print(f"Analyzing {len(dates)} trading days...")

    # Collect all trades with QQQ metadata
    all_trades = []

    for trade_date in dates:
        qqq_day = qqq_df[qqq_df['date'] == trade_date]
        qqq_open = qqq_day.between_time('09:30', '09:34')
        if len(qqq_open) == 0:
            continue

        qqq_move = (qqq_open.iloc[-1]['close'] - qqq_open.iloc[0]['open']) / qqq_open.iloc[0]['open']

        # QQQ daily close vs EMA20
        qqq_close_today = qqq_day.between_time('16:00', '16:00')
        if len(qqq_close_today) == 0:
            # Fallback: last bar of the day
            qqq_close_today_price = qqq_day.iloc[-1]['close']
        else:
            qqq_close_today_price = qqq_close_today.iloc[-1]['close']

        # Get EMA20 and EMA50 for today (use prior day if today not available)
        def get_ema_val(series, date):
            val = series.get(date)
            if val is None:
                prior = [d for d in series.index if d < date]
                val = series[prior[-1]] if prior else None
            return val

        ema20_val = get_ema_val(daily_ema20, trade_date)
        ema50_val = get_ema_val(daily_ema50, trade_date)

        qqq_above_ema20 = (ema20_val is not None) and (qqq_close_today_price > ema20_val)
        qqq_above_ema50 = (ema50_val is not None) and (qqq_close_today_price > ema50_val)
        ema20_above_ema50 = (ema20_val is not None) and (ema50_val is not None) and (ema20_val > ema50_val)

        for sym in SYMBOLS:
            if sym not in all_data or sym not in time_avgs:
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

            vol_930 = get_bar_volume(day, '09:30')
            vol_935 = get_bar_volume(day, '09:35')
            vol_940 = get_bar_volume(day, '09:40')

            bar1_rvol = vol_930 / time_avgs[sym]['09:30'] if time_avgs[sym]['09:30'] > 0 else 0
            bar2_rvol = vol_935 / time_avgs[sym]['09:35'] if time_avgs[sym]['09:35'] > 0 else 0
            bar3_rvol = vol_940 / time_avgs[sym]['09:40'] if time_avgs[sym]['09:40'] > 0 else 0
            decay_ratio = bar3_rvol / bar1_rvol if bar1_rvol > 0 else 0
            volume_persistent = (bar1_rvol > 2.0 and bar2_rvol > 1.5 and bar3_rvol > 1.5)

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
                'bar1_rvol': bar1_rvol,
                'bar2_rvol': bar2_rvol,
                'bar3_rvol': bar3_rvol,
                'decay_ratio': decay_ratio,
                'volume_persistent': volume_persistent,
                'qqq_move': qqq_move,
                'qqq_above_ema20': qqq_above_ema20,
                'qqq_above_ema50': qqq_above_ema50,
                'ema20_above_ema50': ema20_above_ema50
            })

    if not all_trades:
        print("No trades found")
        return

    ver_a = [t for t in all_trades if t['qqq_move'] > 0]
    ver_b = [t for t in all_trades if t['qqq_move'] > 0 and t['qqq_above_ema20']]
    ver_c = [t for t in all_trades if t['qqq_move'] > 0 and t['qqq_above_ema50']]
    ver_d = [t for t in all_trades if t['qqq_move'] > 0 and t['ema20_above_ema50']]

    summarize(ver_a, "VERSION A: QQQ 5m > 0")
    summarize(ver_b, "VERSION B: QQQ 5m > 0  AND  QQQ > Daily EMA20")
    summarize(ver_c, "VERSION C: QQQ 5m > 0  AND  QQQ > Daily EMA50")
    summarize(ver_d, "VERSION D: QQQ 5m > 0  AND  QQQ EMA20 > EMA50")

    # Summary table
    print(f"\n{'='*80}")
    print("SUMMARY COMPARISON")
    print(f"{'='*80}")
    print(f"{'Version':8} {'Filter':35} {'Trades':8} {'WR%':7} {'Avg P&L':10} {'Total':10} {'PF':6}")
    print('-'*80)
    for label, trades in [
        ('A', ver_a), ('B', ver_b), ('C', ver_c), ('D', ver_d)
    ]:
        filters = {
            'A': 'QQQ 5m > 0',
            'B': 'QQQ>0 + QQQ>EMA20',
            'C': 'QQQ>0 + QQQ>EMA50',
            'D': 'QQQ>0 + EMA20>EMA50'
        }
        if not trades:
            print(f"{label:8} {filters[label]:35} {'0':8}")
            continue
        d = pd.DataFrame(trades)
        wr = len(d[d['pnl'] > 0]) / len(d) * 100
        avg = d['pnl'].mean()
        tot = d['pnl'].sum()
        gp = d[d['pnl'] > 0]['pnl'].sum()
        gl = abs(d[d['pnl'] <= 0]['pnl'].sum())
        pf = gp / gl if gl > 0 else 0
        print(f"{label:8} {filters[label]:35} {len(d):8} {wr:6.1f}% {avg:+9.3f}% {tot:+9.2f}% {pf:6.2f}")
    print('='*80)

if __name__ == '__main__':
    run_test()
