"""
BOOF 30 Quick Test — Key Parameters Only
Focus on TP levels and win rate
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

API_KEY    = os.getenv("ALPACA_API_KEY", "PKAJ7LELQVQMPJPEJTGZDRT3XP")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "53BHpMNadsdZ6gUx4DmU7wHD7eGu1SNwnHKPqFHhqwhZ")

ET = ZoneInfo("America/New_York")
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

SYMBOLS = ["NVDA", "TSLA", "META", "AVGO", "AMZN", "MSFT", "AAPL", "GOOGL", "AMD", "COIN"]

# Key parameters only
CONFIRM_BARS = 5
RVOL_MIN = 2.0
TP_LEVELS = [0.0075, 0.010, 0.015]  # 0.75%, 1.0%, 1.5%
SL_PCT = 0.004  # Fixed at 0.4%

LOOKBACK_VOL = 20
MAX_HOLD_BARS = 60
START_TIME = time(9, 30)
END_TIME = time(10, 30)


def fetch_data():
    all_data = []
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=180)
    
    print("Fetching data...")
    for symbol in SYMBOLS:
        try:
            req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start_date, end=end_date)
            df = data_client.get_stock_bars(req).df
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(symbol)
            df = df.reset_index()
            if 't' in df.columns:
                df = df.rename(columns={'t': 'timestamp'})
            df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})
            df['datetime'] = pd.to_datetime(df['timestamp'])
            df['symbol'] = symbol
            all_data.append(df[['datetime', 'symbol', 'open', 'high', 'low', 'close', 'volume']])
            print(f"  {symbol}: {len(df)} bars")
        except Exception as e:
            print(f"  {symbol}: ERROR - {e}")
    
    return pd.concat(all_data, ignore_index=True) if all_data else None


def calculate_score(row, confirm):
    """Calculate entry score (0-5 scale)."""
    score = 0
    # RVOL component (0-2 points)
    if row['rvol'] >= 5:
        score += 2
    elif row['rvol'] >= 3:
        score += 1
    # VWAP distance component (0-2 points)
    vwap_dist = abs(confirm['close'] - confirm['vwap']) / confirm['vwap']
    if vwap_dist > 0.005:
        score += 2
    elif vwap_dist > 0.002:
        score += 1
    # Candle body component (0-1 point)
    body_pct = abs(row['close'] - row['open']) / row['open']
    if body_pct > 0.005:
        score += 1
    return score


def backtest_tp_level(data, tp_pct, version='A'):
    """Test a single TP level."""
    trades = []
    
    for symbol, df in data.groupby('symbol'):
        df = df.copy()
        df['date'] = df['datetime'].dt.date
        df['time'] = df['datetime'].dt.time
        
        # Add VWAP
        tp = (df['high'] + df['low'] + df['close']) / 3
        df['pv'] = tp * df['volume']
        df['cum_pv'] = df.groupby('date')['pv'].cumsum()
        df['cum_vol'] = df.groupby('date')['volume'].cumsum()
        df['vwap'] = df['cum_pv'] / df['cum_vol']
        
        # RVOL
        df['avg_vol'] = df.groupby('date')['volume'].rolling(LOOKBACK_VOL).mean().reset_index(level=0, drop=True)
        df['rvol'] = df['volume'] / df['avg_vol']
        
        for date, day in df.groupby('date'):
            day = day.reset_index(drop=True)
            trade_taken = False
            
            for i in range(LOOKBACK_VOL, len(day) - CONFIRM_BARS - MAX_HOLD_BARS):
                if trade_taken:
                    break
                
                row = day.iloc[i]
                if not (START_TIME <= row['time'] <= END_TIME):
                    continue
                if pd.isna(row['rvol']) or row['rvol'] < RVOL_MIN:
                    continue
                
                spike_dir = 'long' if row['close'] > row['open'] else 'short'
                confirm = day.iloc[i + CONFIRM_BARS]
                
                # Version B & C: VWAP check
                if version in ['B', 'C']:
                    if spike_dir == 'long' and confirm['close'] <= confirm['vwap']:
                        continue
                    if spike_dir == 'short' and confirm['close'] >= confirm['vwap']:
                        continue
                
                # Version C: Score check
                if version == 'C':
                    score = calculate_score(row, confirm)
                    if score < 3:
                        continue
                
                entry = confirm['close']
                if spike_dir == 'long':
                    tp = entry * (1 + tp_pct)
                    sl = entry * (1 - SL_PCT)
                else:
                    tp = entry * (1 - tp_pct)
                    sl = entry * (1 + SL_PCT)
                
                # Simulate
                future_start = i + CONFIRM_BARS + 1
                future_end = min(future_start + MAX_HOLD_BARS, len(day))
                future = day.iloc[future_start:future_end]
                
                exit_price = future['close'].iloc[-1] if len(future) > 0 else entry
                result = 'TIME'
                
                for _, bar in future.iterrows():
                    if spike_dir == 'long':
                        if bar['high'] >= tp:
                            exit_price = tp
                            result = 'TP'
                            break
                        if bar['low'] <= sl:
                            exit_price = sl
                            result = 'SL'
                            break
                    else:
                        if bar['low'] <= tp:
                            exit_price = tp
                            result = 'TP'
                            break
                        if bar['high'] >= sl:
                            exit_price = sl
                            result = 'SL'
                            break
                
                pnl_pct = (exit_price - entry) / entry if spike_dir == 'long' else (entry - exit_price) / entry
                
                trades.append({
                    'symbol': symbol, 'date': date, 'direction': spike_dir,
                    'entry': entry, 'exit': exit_price, 'pnl_pct': pnl_pct,
                    'result': result, 'rvol': row['rvol'], 'version': version,
                    'tp_pct': tp_pct
                })
                trade_taken = True
    
    return trades


def analyze(trades):
    if not trades:
        return None
    df = pd.DataFrame(trades)
    total = len(df)
    wins = len(df[df['pnl_pct'] > 0])
    win_rate = wins / total * 100 if total > 0 else 0
    avg_win = df[df['pnl_pct'] > 0]['pnl_pct'].mean() * 100 if wins > 0 else 0
    avg_loss = df[df['pnl_pct'] <= 0]['pnl_pct'].mean() * 100 if (total - wins) > 0 else 0
    avg_trade = df['pnl_pct'].mean() * 100
    
    gross_profit = df[df['pnl_pct'] > 0]['pnl_pct'].sum()
    gross_loss = abs(df[df['pnl_pct'] < 0]['pnl_pct'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    
    return {
        'trades': total, 'win_rate': win_rate, 'avg_win': avg_win,
        'avg_loss': avg_loss, 'avg_trade': avg_trade, 'profit_factor': profit_factor,
        'tp_hits': (df['result'] == 'TP').sum(), 'sl_hits': (df['result'] == 'SL').sum(),
        'time_exits': (df['result'] == 'TIME').sum()
    }


def main():
    print("="*80)
    print("BOOF 30 QUICK TEST — TP Levels Focus")
    print("="*80)
    
    data = fetch_data()
    if data is None:
        print("No data!")
        return
    
    print(f"\nTotal: {len(data)} bars across {len(SYMBOLS)} symbols")
    print(f"\nTesting: CB={CONFIRM_BARS} | RVOL>{RVOL_MIN} | SL={SL_PCT*100:.2f}%")
    print(f"Versions: A (RVOL) | B (RVOL+VWAP) | C (RVOL+VWAP+Score>=3)")
    print("="*80)
    
    all_results = []
    
    for tp in TP_LEVELS:
        print(f"\n{'='*80}")
        print(f"TP = {tp*100:.2f}%")
        print(f"{'='*80}")
        
        trades_a = backtest_tp_level(data, tp, 'A')
        trades_b = backtest_tp_level(data, tp, 'B')
        trades_c = backtest_tp_level(data, tp, 'C')
        
        r_a = analyze(trades_a)
        r_b = analyze(trades_b)
        r_c = analyze(trades_c)
        
        print(f"\n{'Metric':<20} {'Ver A':<12} {'Ver B':<12} {'Ver C':<12}")
        print("-"*60)
        print(f"{'Trades':<20} {r_a['trades']:<12} {r_b['trades']:<12} {r_c['trades']:<12}")
        print(f"{'Win Rate %':<20} {r_a['win_rate']:<12.1f} {r_b['win_rate']:<12.1f} {r_c['win_rate']:<12.1f}")
        print(f"{'Avg Win %':<20} {r_a['avg_win']:<12.2f} {r_b['avg_win']:<12.2f} {r_c['avg_win']:<12.2f}")
        print(f"{'Avg Loss %':<20} {r_a['avg_loss']:<12.2f} {r_b['avg_loss']:<12.2f} {r_c['avg_loss']:<12.2f}")
        print(f"{'Avg Trade %':<20} {r_a['avg_trade']:<12.3f} {r_b['avg_trade']:<12.3f} {r_c['avg_trade']:<12.3f}")
        print(f"{'Profit Factor':<20} {r_a['profit_factor']:<12.2f} {r_b['profit_factor']:<12.2f} {r_c['profit_factor']:<12.2f}")
        print(f"{'TP Hits':<20} {r_a['tp_hits']:<12} {r_b['tp_hits']:<12} {r_c['tp_hits']:<12}")
        print(f"{'SL Hits':<20} {r_a['sl_hits']:<12} {r_b['sl_hits']:<12} {r_c['sl_hits']:<12}")
        print(f"{'Time Exits':<20} {r_a['time_exits']:<12} {r_b['time_exits']:<12} {r_c['time_exits']:<12}")
        
        all_results.append({'tp': tp, 'version': 'A', **r_a})
        all_results.append({'tp': tp, 'version': 'B', **r_b})
        all_results.append({'tp': tp, 'version': 'C', **r_c})
    
    print("\n" + "="*80)
    print("SUMMARY TABLE")
    print("="*80)
    print(f"{'TP%':<8} {'Ver':<5} {'Trades':<8} {'Win%':<7} {'PF':<6} {'AvgWin':<8} {'AvgLoss':<9}")
    print("-"*70)
    for r in all_results:
        print(f"{r['tp']*100:<8.2f} {r['version']:<5} {r['trades']:<8} {r['win_rate']:<7.1f} "
              f"{r['profit_factor']:<6.2f} {r['avg_win']:<8.2f} {r['avg_loss']:<9.2f}")
    
    # Best by PF
    best = max(all_results, key=lambda x: x['profit_factor'])
    print(f"\nBEST: TP={best['tp']*100:.2f}% | Ver={best['version']} | PF={best['profit_factor']:.2f} | WinRate={best['win_rate']:.1f}%")


if __name__ == "__main__":
    main()
