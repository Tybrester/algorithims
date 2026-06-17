"""
Futures Cross-Reference Backtest
Watches ES, NQ, MES, MNQ for correlated/divergent moves
Uses DataBento for futures data
"""
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

# DataBento API Key
DB_API_KEY = 'db-HjUMrsa7gNvavTcwU8fUdywvQSfH7'

# Futures symbols mapping
FUTURES = {
    'ES': {'code': 'ES.c.0', 'tick_value': 12.50, 'desc': 'E-mini S&P 500'},
    'NQ': {'code': 'NQ.c.0', 'tick_value': 5.00, 'desc': 'E-mini Nasdaq'},
    'MES': {'code': 'MES.c.0', 'tick_value': 1.25, 'desc': 'Micro E-mini S&P'},
    'MNQ': {'code': 'MNQ.c.0', 'tick_value': 0.50, 'desc': 'Micro E-mini Nasdaq'},
}

# 5m timeframe config
SCHEMA = 'ohlcv-5m'
DATASET = 'GLBX'  # CME Globex

def fetch_databento(symbol_code, start, end):
    """Fetch historical data from DataBento"""
    url = 'https://hist.databento.com/v0/timeseries.get_range'
    start_ts = start.strftime('%Y-%m-%dT%H:%M:%S') + '+00:00'
    end_ts = end.strftime('%Y-%m-%dT%H:%M:%S') + '+00:00'
    
    params = {
        'dataset': DATASET,
        'schema': SCHEMA,
        'symbols': symbol_code,
        'start': start_ts,
        'end': end_ts,
        'stype_in': 'raw_symbol',
        'encoding': 'json'
    }
    
    headers = {'Authorization': f'Bearer {DB_API_KEY}'}
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=120)
        data = resp.json()
        
        if isinstance(data, list) and len(data) > 0:
            df = pd.DataFrame(data)
            df['ts_event'] = pd.to_datetime(df['ts_event'])
            df.set_index('ts_event', inplace=True)
            df.rename(columns={'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'}, inplace=True)
            return df
        return None
    except Exception as e:
        print(f'  Error fetching {symbol_code}: {e}')
        return None

def calc_atr(df, period=14):
    """Calculate ATR"""
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    atr = np.zeros(len(df))
    for i in range(1, len(df)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        atr[i] = tr if i < period else atr[i-1] * (period-1)/period + tr/period
    return atr

def calc_correlation(df1, df2, window=20):
    """Calculate rolling correlation between two price series"""
    # Align indices
    combined = pd.concat([df1['close'], df2['close']], axis=1, keys=['s1', 's2'])
    combined = combined.dropna()
    if len(combined) < window:
        return None
    return combined['s1'].rolling(window).corr(combined['s2']).iloc[-1]

def calc_zscore(series, window=20):
    """Calculate z-score of the latest value"""
    if len(series) < window:
        return 0
    mean = series.iloc[-window:].mean()
    std = series.iloc[-window:].std()
    if std == 0:
        return 0
    return (series.iloc[-1] - mean) / std

def detect_cross_signal(data_dict, i):
    """
    Detect cross-reference signals across all 4 futures
    Returns: signal dict or None
    """
    # Get current prices for all symbols at this index
    prices = {}
    for sym, info in FUTURES.items():
        df = data_dict.get(sym)
        if df is None or i >= len(df):
            return None
        prices[sym] = {
            'close': df['close'].iloc[i],
            'high': df['high'].iloc[i],
            'low': df['low'].iloc[i],
            'open': df['open'].iloc[i],
        }
    
    # Calculate returns over last N bars for each
    returns_5 = {}
    returns_10 = {}
    for sym, df in data_dict.items():
        if i >= 10:
            ret_5 = (df['close'].iloc[i] - df['close'].iloc[i-5]) / df['close'].iloc[i-5] * 100
            ret_10 = (df['close'].iloc[i] - df['close'].iloc[i-10]) / df['close'].iloc[i-10] * 100
            returns_5[sym] = ret_5
            returns_10[sym] = ret_10
    
    if len(returns_5) < 4:
        return None
    
    # STRATEGY 1: All 4 aligned (high conviction)
    all_up = all(r > 0 for r in returns_5.values())
    all_down = all(r < 0 for r in returns_5.values())
    
    # STRATEGY 2: ES leads, NQ follows (lag play)
    es_lead = returns_5['ES'] > 0.1 and returns_5['NQ'] < 0.05
    es_lead_down = returns_5['ES'] < -0.1 and returns_5['NQ'] > -0.05
    
    # STRATEGY 3: Micro divergence from full (arbitrage)
    # When MES/MNQ diverge from ES/NQ, expect convergence
    es_mes_spread = abs(returns_5['ES'] - returns_5['MES'])
    nq_mnq_spread = abs(returns_5['NQ'] - returns_5['MNQ'])
    micro_divergence = es_mes_spread > 0.15 or nq_mnq_spread > 0.15
    
    # STRATEGY 4: Relative strength - trade stronger index
    es_stronger = returns_5['ES'] > returns_5['NQ'] + 0.1
    nq_stronger = returns_5['NQ'] > returns_5['ES'] + 0.1
    
    signal = None
    
    # Priority: All aligned > Divergence > Lead/lag > Relative strength
    if all_up:
        signal = {'direction': 'LONG', 'type': 'all_aligned_up', 'strength': 3, 'returns': returns_5}
    elif all_down:
        signal = {'direction': 'SHORT', 'type': 'all_aligned_down', 'strength': 3, 'returns': returns_5}
    elif micro_divergence:
        # Trade toward the full contract direction (micros catch up)
        if returns_5['ES'] > returns_5['MES']:
            signal = {'direction': 'LONG', 'type': 'micro_catch_up_long', 'strength': 2, 'returns': returns_5}
        else:
            signal = {'direction': 'SHORT', 'type': 'micro_catch_up_short', 'strength': 2, 'returns': returns_5}
    elif es_lead:
        signal = {'direction': 'LONG', 'type': 'es_leads', 'strength': 2, 'returns': returns_5}
    elif es_lead_down:
        signal = {'direction': 'SHORT', 'type': 'es_leads_down', 'strength': 2, 'returns': returns_5}
    elif es_stronger:
        signal = {'direction': 'LONG', 'type': 'es_stronger', 'strength': 1, 'returns': returns_5, 'target': 'ES'}
    elif nq_stronger:
        signal = {'direction': 'LONG', 'type': 'nq_stronger', 'strength': 1, 'returns': returns_5, 'target': 'NQ'}
    
    return signal

def run_backtest(start_date, end_date):
    """Run the cross-reference backtest"""
    print('=' * 70)
    print('FUTURES CROSS-REFERENCE BACKTEST')
    print('Symbols: ES, NQ, MES, MNQ')
    print(f'Period: {start_date.date()} to {end_date.date()}')
    print('=' * 70)
    print()
    
    # Fetch data for all 4
    print('Fetching data...')
    data_dict = {}
    for sym, info in FUTURES.items():
        print(f'  {sym} ({info["desc"]})...', end=' ')
        df = fetch_databento(info['code'], start_date, end_date)
        if df is not None and len(df) > 100:
            # Calculate ATR
            df['atr'] = calc_atr(df)
            data_dict[sym] = df
            print(f'{len(df)} bars')
        else:
            print('FAILED')
    
    if len(data_dict) < 4:
        print('\nERROR: Could not fetch all 4 symbols')
        return
    
    # Align timestamps
    print('\nAligning data...')
    common_idx = data_dict['ES'].index
    for sym, df in data_dict.items():
        if sym != 'ES':
            common_idx = common_idx.intersection(df.index)
    
    print(f'  Common timestamps: {len(common_idx)}')
    
    # Reindex all to common timestamps
    for sym in data_dict:
        data_dict[sym] = data_dict[sym].reindex(common_idx).fillna(method='ffill')
    
    print('\nRunning backtest...')
    trades = []
    
    for i in range(50, len(common_idx) - 1):
        signal = detect_cross_signal(data_dict, i)
        
        if signal and signal['strength'] >= 2:  # Only trade strength 2+
            # Entry on ES (most liquid)
            entry = data_dict['ES']['close'].iloc[i]
            atr = data_dict['ES']['atr'].iloc[i]
            
            if atr == 0:
                continue
            
            # 2:1 R/R
            sl = entry - atr if signal['direction'] == 'LONG' else entry + atr
            tp = entry + 2 * atr if signal['direction'] == 'LONG' else entry - 2 * atr
            
            # Simulate forward
            for j in range(i + 1, min(i + 30, len(common_idx))):
                high = data_dict['ES']['high'].iloc[j]
                low = data_dict['ES']['low'].iloc[j]
                
                if signal['direction'] == 'LONG':
                    if low <= sl:
                        pnl_ticks = (sl - entry) / 0.25  # ES tick = 0.25
                        exit_price = sl
                        exit_type = 'SL'
                        break
                    if high >= tp:
                        pnl_ticks = (tp - entry) / 0.25
                        exit_price = tp
                        exit_type = 'TP'
                        break
                else:
                    if high >= sl:
                        pnl_ticks = (entry - sl) / 0.25
                        exit_price = sl
                        exit_type = 'SL'
                        break
                    if low <= tp:
                        pnl_ticks = (entry - tp) / 0.25
                        exit_price = tp
                        exit_type = 'TP'
                        break
            else:
                continue  # No exit found
            
            dollar_pnl = pnl_ticks * 12.50  # ES tick value
            
            trades.append({
                'timestamp': common_idx[i],
                'signal_type': signal['type'],
                'direction': signal['direction'],
                'strength': signal['strength'],
                'entry': entry,
                'exit': exit_price,
                'exit_type': exit_type,
                'pnl_ticks': pnl_ticks,
                'pnl_dollar': dollar_pnl,
                'atr': atr,
                'es_ret': signal['returns']['ES'],
                'nq_ret': signal['returns']['NQ'],
                'mes_ret': signal['returns']['MES'],
                'mnq_ret': signal['returns']['MNQ'],
            })
    
    # Results
    print('\n' + '=' * 70)
    print('RESULTS')
    print('=' * 70)
    
    if not trades:
        print('No trades generated')
        return
    
    pnls = np.array([t['pnl_dollar'] for t in trades])
    pos = pnls[pnls > 0]
    neg = pnls[pnls < 0]
    
    n = len(pnls)
    wr = len(pos) / n * 100
    pf = pos.sum() / abs(neg.sum()) if len(neg) > 0 else 999
    ev = pnls.mean()
    total = pnls.sum()
    
    print(f'  Total trades:     {n}')
    print(f'  Win rate:         {wr:.1f}%')
    print(f'  Profit factor:    {pf:.2f}')
    print(f'  EV/trade:         ${ev:.2f}')
    print(f'  Total P&L:        ${total:,.2f}')
    print(f'  Avg trade $:      ${np.mean(np.abs(pnls)):.2f}')
    
    # By signal type
    print('\n  By Signal Type:')
    by_type = defaultdict(list)
    for t in trades:
        by_type[t['signal_type']].append(t['pnl_dollar'])
    
    for sig_type, t_pnls in sorted(by_type.items(), key=lambda x: len(x[1]), reverse=True):
        arr = np.array(t_pnls)
        arr_pos = arr[arr > 0]
        t_wr = len(arr_pos) / len(arr) * 100 if len(arr) > 0 else 0
        print(f'    {sig_type:<25} {len(arr):>3} trades  {t_wr:>5.1f}% WR  ${arr.sum():>10,.0f}')
    
    # Recent trades sample
    print('\n  Recent Trades (last 5):')
    for t in trades[-5:]:
        print(f'    {t["timestamp"].strftime("%m/%d %H:%M")}  {t["direction"]:<6} {t["signal_type"]:<20}  PnL: ${t["pnl_dollar"]:>8,.2f}')
    
    print('\n' + '=' * 70)

if __name__ == '__main__':
    # 3 months: Mar-May 2026
    run_backtest(datetime(2026, 3, 1), datetime(2026, 5, 31))
