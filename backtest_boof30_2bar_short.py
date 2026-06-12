"""
BOOF 30 — 2-Bar Short Ignition Pattern Backtest with MFE/MAE Analysis
Bar 1: Big red candle with high volume
Bar 2: Follow-through red candle, lower close
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

SYMBOLS = ["NVDA", "TSLA", "AAPL", "MSFT", "AMZN"]  # 5 most liquid mega caps

# Parameter sweep grid - reduced for speed
BAR1_BODY_LIST = [0.004, 0.005]  # 0.40%, 0.50%
BAR1_RVOL_LIST = [2.0, 3.0]  # 2x, 3x
BAR2_RVOL_LIST = [1.5, 2.0]  # 1.5x, 2x
TP_LIST = [0.010, 0.015]  # 1.0%, 1.5%
SL_LIST = [0.003, 0.005]  # 0.30%, 0.50%

LOOKBACK_VOL = 20
MAX_HOLD_BARS = 60
START_TIME = time(9, 30)
END_TIME = time(15, 55)


def fetch_data():
    all_data = []
    end_date = datetime.now(ET)
    start_date = end_date - timedelta(days=180)
    
    print("Fetching 6 months of data...")
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


def add_vwap(df):
    """Add VWAP."""
    df = df.copy()
    df['date'] = df['datetime'].dt.date
    tp = (df['high'] + df['low'] + df['close']) / 3
    df['pv'] = tp * df['volume']
    df['cum_pv'] = df.groupby('date')['pv'].cumsum()
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['vwap'] = df['cum_pv'] / df['cum_vol']
    return df


def get_max_moves(day, entry_idx, entry_price, minutes_list=[15, 30, 60]):
    """Get max upside and downside moves for given time windows."""
    moves = {}
    
    for minutes in minutes_list:
        future_idx = entry_idx + minutes
        if future_idx < len(day):
            future_slice = day.iloc[entry_idx+1:future_idx+1]
            if len(future_slice) > 0:
                max_high = future_slice['high'].max()
                min_low = future_slice['low'].min()
                
                # For short: upside = against us (price goes up), downside = favorable (price drops)
                max_upside = (max_high - entry_price) / entry_price
                max_downside = (entry_price - min_low) / entry_price
                
                moves[f'max_upside_{minutes}m'] = max_upside
                moves[f'max_downside_{minutes}m'] = max_downside
                moves[f'mfe_{minutes}m'] = max_downside  # Max favorable excursion
                moves[f'mae_{minutes}m'] = max_upside    # Max adverse excursion
            else:
                moves[f'max_upside_{minutes}m'] = None
                moves[f'max_downside_{minutes}m'] = None
                moves[f'mfe_{minutes}m'] = None
                moves[f'mae_{minutes}m'] = None
        else:
            moves[f'max_upside_{minutes}m'] = None
            moves[f'max_downside_{minutes}m'] = None
            moves[f'mfe_{minutes}m'] = None
            moves[f'mae_{minutes}m'] = None
    
    return moves


def detect_2bar_short_ignition(df, i, bar1_body_min, bar1_rvol_min, bar2_rvol_min):
    """Detect 2-bar short ignition pattern."""
    if i < 1 or i < LOOKBACK_VOL:
        return False
    
    bar1 = df.iloc[i - 1]
    bar2 = df.iloc[i]
    
    avg_vol = df["volume"].iloc[i-LOOKBACK_VOL:i-1].mean()
    if avg_vol == 0:
        return False
    
    bar1_body_pct = abs(bar1["close"] - bar1["open"]) / bar1["open"]
    
    bar1_red = bar1["close"] < bar1["open"]
    bar2_red = bar2["close"] < bar2["open"]
    
    bar1_rvol = bar1["volume"] / avg_vol
    bar2_rvol = bar2["volume"] / avg_vol
    
    bar1_big_drop = bar1_body_pct >= bar1_body_min
    bar2_followthrough = bar2["close"] < bar1["close"]
    
    below_vwap = bar1["close"] < bar1["vwap"] and bar2["close"] < bar2["vwap"]
    no_reclaim = bar2["high"] < bar1["open"]
    
    if (
        bar1_red and bar2_red and bar1_big_drop and bar2_followthrough
        and bar1_rvol >= bar1_rvol_min and bar2_rvol >= bar2_rvol_min
        and below_vwap and no_reclaim
    ):
        return True
    
    return False


def backtest_single_params(data, bar1_body, bar1_rvol, bar2_rvol, tp_pct, sl_pct):
    """Run backtest with specific parameters, tracking MFE/MAE."""
    trades = []
    
    for symbol, df in data.groupby('symbol'):
        df = add_vwap(df)
        df['date'] = df['datetime'].dt.date
        df['time'] = df['datetime'].dt.time
        
        for date, day in df.groupby('date'):
            day = day.reset_index(drop=True)
            trade_taken = False
            
            for i in range(LOOKBACK_VOL, len(day) - MAX_HOLD_BARS):
                if trade_taken:
                    break
                
                row = day.iloc[i]
                if not (START_TIME <= row['time'] <= END_TIME):
                    continue
                
                if not detect_2bar_short_ignition(day, i, bar1_body, bar1_rvol, bar2_rvol):
                    continue
                
                entry = row['close']
                tp = entry * (1 - tp_pct)
                sl = entry * (1 + sl_pct)
                
                # Simulate trade
                future = day.iloc[i+1:i+1+MAX_HOLD_BARS]
                exit_price = future['close'].iloc[-1] if len(future) > 0 else entry
                result = 'TIME'
                
                for _, bar in future.iterrows():
                    if bar['low'] <= tp:
                        exit_price = tp
                        result = 'TP'
                        break
                    if bar['high'] >= sl:
                        exit_price = sl
                        result = 'SL'
                        break
                
                pnl_pct = (entry - exit_price) / entry
                
                # Get MFE/MAE
                moves = get_max_moves(day, i, entry)
                
                trades.append({
                    'symbol': symbol,
                    'date': date,
                    'entry_price': entry,
                    'exit_price': exit_price,
                    'pnl_pct': pnl_pct,
                    'result': result,
                    'bar1_body_pct': bar1_body,
                    'bar1_rvol_min': bar1_rvol,
                    'bar2_rvol_min': bar2_rvol,
                    'tp_pct': tp_pct,
                    'sl_pct': sl_pct,
                    **moves
                })
                trade_taken = True
    
    return trades


def analyze(trades):
    if not trades:
        return {'trades': 0, 'win_rate': 0, 'avg_win': 0, 'avg_loss': 0, 
                'avg_trade': 0, 'profit_factor': 0, 'total_pnl': 0}
    
    df = pd.DataFrame(trades)
    total = len(df)
    wins = len(df[df['pnl_pct'] > 0])
    win_rate = wins / total * 100
    
    avg_win = df[df['pnl_pct'] > 0]['pnl_pct'].mean() * 100 if wins > 0 else 0
    avg_loss = df[df['pnl_pct'] <= 0]['pnl_pct'].mean() * 100 if (total - wins) > 0 else 0
    avg_trade = df['pnl_pct'].mean() * 100
    
    gross_profit = df[df['pnl_pct'] > 0]['pnl_pct'].sum()
    gross_loss = abs(df[df['pnl_pct'] < 0]['pnl_pct'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    
    total_pnl = df['pnl_pct'].sum() * 1000
    
    # MFE/MAE Analysis (if enough signals)
    mfe_mae_stats = {}
    for period in ['15m', '30m', '60m']:
        mfe_col = f'mfe_{period}'
        mae_col = f'mae_{period}'
        if mfe_col in df.columns and df[mfe_col].notna().sum() > 0:
            mfe_vals = df[mfe_col].dropna()
            mae_vals = df[mae_col].dropna()
            if len(mfe_vals) > 0:
                mfe_mae_stats[f'avg_mfe_{period}'] = mfe_vals.mean() * 100
                mfe_mae_stats[f'median_mfe_{period}'] = mfe_vals.median() * 100
                mfe_mae_stats[f'p90_mfe_{period}'] = mfe_vals.quantile(0.90) * 100
                mfe_mae_stats[f'avg_mae_{period}'] = mae_vals.mean() * 100
                mfe_mae_stats[f'median_mae_{period}'] = mae_vals.median() * 100
    
    return {
        'trades': total,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'avg_trade': avg_trade,
        'profit_factor': profit_factor,
        'total_pnl': total_pnl,
        **mfe_mae_stats
    }


def main():
    print("="*80)
    print("BOOF 30 — 2-BAR SHORT IGNITION PATTERN with MFE/MAE")
    print("="*80)
    
    data = fetch_data()
    if data is None:
        print("No data!")
        return
    
    print(f"\nTotal: {len(data)} bars")
    
    # Run all combinations
    results = []
    all_trades = []
    total_combos = len(BAR1_BODY_LIST) * len(BAR1_RVOL_LIST) * len(BAR2_RVOL_LIST) * len(TP_LIST) * len(SL_LIST)
    combo = 0
    
    for bar1_body in BAR1_BODY_LIST:
        for bar1_rvol in BAR1_RVOL_LIST:
            for bar2_rvol in BAR2_RVOL_LIST:
                for tp in TP_LIST:
                    for sl in SL_LIST:
                        combo += 1
                        print(f"\n[{combo}/{total_combos}] B1={bar1_body*100:.1f}% RVOL{bar1_rvol:.0f}x | B2={bar2_rvol:.1f}x | TP={tp*100:.1f}% SL={sl*100:.1f}%")
                        
                        trades = backtest_single_params(data, bar1_body, bar1_rvol, bar2_rvol, tp, sl)
                        r = analyze(trades)
                        
                        results.append({
                            'bar1_body': bar1_body, 'bar1_rvol': bar1_rvol, 'bar2_rvol': bar2_rvol,
                            'tp': tp, 'sl': sl, **r
                        })
                        all_trades.extend(trades)
                        
                        print(f"  Trades: {r['trades']} | WinRate: {r['win_rate']:.1f}% | PF: {r['profit_factor']:.2f} | P&L: ${r['total_pnl']:.2f}")
                        if r['trades'] > 0 and 'avg_mfe_15m' in r:
                            print(f"  MFE 15m: Avg={r['avg_mfe_15m']:.2f}% Median={r['median_mfe_15m']:.2f}% P90={r['p90_mfe_15m']:.2f}%")
                            print(f"  MAE 15m: Avg={r['avg_mae_15m']:.2f}% Median={r['median_mae_15m']:.2f}%")
    
    # Summary table
    print("\n" + "="*80)
    print("TOP 15 CONFIGURATIONS BY PROFIT FACTOR")
    print("="*80)
    
    results_df = pd.DataFrame(results)
    top_results = results_df.sort_values('profit_factor', ascending=False).head(15)
    
    print(f"{'B1%':>5} {'B1RV':>4} {'B2RV':>5} {'TP%':>5} {'SL%':>5} {'Trades':>7} {'Win%':>6} {'PF':>5} {'EV$':>7} {'MFE15':>7}")
    print("-"*80)
    for _, r in top_results.iterrows():
        mfe_str = f"{r.get('avg_mfe_15m', 0):.1f}" if 'avg_mfe_15m' in r else "N/A"
        print(f"{r['bar1_body']*100:>5.1f} {r['bar1_rvol']:>4.0f} {r['bar2_rvol']:>5.1f} "
              f"{r['tp']*100:>5.1f} {r['sl']*100:>5.1f} {int(r['trades']):>7} "
              f"{r['win_rate']:>6.1f} {r['profit_factor']:>5.2f} {r['total_pnl']:>7.0f} {mfe_str:>7}")
    
    # Save results
    results_df.to_csv('boof30_2bar_sweep_results.csv', index=False)
    
    # Save all trades with MFE/MAE
    if all_trades:
        trades_df = pd.DataFrame(all_trades)
        trades_df.to_csv('boof30_2bar_all_trades.csv', index=False)
        
        print("\n" + "="*80)
        print(f"MFE/MAE ANALYSIS — {len(trades_df)} Total Signals")
        print("="*80)
        
        for period in ['15m', '30m', '60m']:
            mfe_col = f'mfe_{period}'
            mae_col = f'mae_{period}'
            if mfe_col in trades_df.columns:
                mfe_vals = trades_df[mfe_col].dropna()
                mae_vals = trades_df[mae_col].dropna()
                if len(mfe_vals) > 0:
                    print(f"\n{period}:")
                    print(f"  MFE — Avg: {mfe_vals.mean()*100:.2f}% | Median: {mfe_vals.median()*100:.2f}% | P90: {mfe_vals.quantile(0.90)*100:.2f}%")
                    print(f"  MAE — Avg: {mae_vals.mean()*100:.2f}% | Median: {mae_vals.median()*100:.2f}%")
    
    print("\nSaved to: boof30_2bar_sweep_results.csv and boof30_2bar_all_trades.csv")
    
    # Best config
    if len(results_df) > 0:
        best = results_df.loc[results_df['profit_factor'].idxmax()]
        print(f"\nBEST CONFIG:")
        print(f"  Bar1: {best['bar1_body']*100:.1f}% body, {best['bar1_rvol']:.0f}x RVOL")
        print(f"  Bar2: {best['bar2_rvol']:.1f}x RVOL")
        print(f"  TP: {best['tp']*100:.1f}% | SL: {best['sl']*100:.1f}%")
        print(f"  Result: {int(best['trades'])} trades | PF: {best['profit_factor']:.2f} | Win%: {best['win_rate']:.1f}")


if __name__ == "__main__":
    main()
