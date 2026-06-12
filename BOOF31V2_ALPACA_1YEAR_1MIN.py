#!/usr/bin/env python3
"""
BOOF 31 v2 - ALPACA 1-YEAR 1-MINUTE BACKTEST
Run final algorithm on 1 year of 1-minute data using Alpaca API
"""

import pandas as pd
import numpy as np
import requests
import json
from datetime import datetime, timedelta
import logging
import time
import os

logging.basicConfig(level=logging.INFO)

# EXPANDED SYMBOL UNIVERSE (80 stocks)
SYMBOLS = [
    # Tech Giants
    'AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AVGO', 'AMD', 'NFLX',
    # Cloud/SaaS
    'CRM', 'NOW', 'SNOW', 'PLTR', 'DDOG', 'MDB', 'CRWD', 'ZS', 'NET', 'SHOP',
    # Software
    'ADBE', 'INTU', 'PANW', 'TEAM', 'HUBS', 'UBER', 'ABNB', 'BKNG', 'RBLX', 'DASH',
    # Latin America/E-commerce
    'MELI', 'ETSY',
    # Financials
    'JPM', 'GS', 'MS', 'BAC', 'WFC', 'AXP', 'COF', 'SCHW', 'BLK', 'SPGI',
    # Healthcare/Biotech
    'LLY', 'NVO', 'UNH', 'ISRG', 'VRTX', 'REGN', 'MRNA', 'BIIB', 'GILD', 'BMY',
    # Industrial/Defense
    'GE', 'RTX', 'LMT', 'BA', 'CAT', 'DE', 'ETN', 'PH', 'TT',
    # Energy
    'XOM', 'CVX', 'COP', 'SLB', 'HAL', 'OXY', 'EOG', 'MPC', 'VLO', 'DVN',
    # Telecom/Media
    'TMUS', 'CMCSA', 'ROKU', 'SPOT', 'PINS', 'SNAP', 'RDDT', 'COIN',
    # Semiconductor/Hardware
    'MSTR', 'HOOD', 'SMCI', 'ARM', 'MU', 'QCOM', 'MRVL', 'TSM', 'ASML',
    # Semicap Equipment
    'AMAT', 'LRCX', 'KLAC', 'MCHP', 'ON', 'NXPI',
    # ETFs
    'SPY', 'QQQ', 'IWM', 'SMH'
]

# OPTIMIZED STRATEGY PARAMETERS
SWEEP_OPTIMIZED = 0.0020  # 0.20% sweep
TP1 = 0.0050             # 0.50% first target
SL_OPTIMIZED = 0.0025     # 0.25% SL
COOLDOWN_MINUTES = 30
MIN_SCORE = 6
SLIPPAGE = 0.0005         # 0.05% slippage

class AlpacaDataFetcher:
    def __init__(self):
        # Alpaca Paper Trading API (free)
        self.base_url = "https://data.alpaca.markets/v2"
        self.headers = {
            'APCA-API-KEY-ID': 'PKFQF3V8N4B2A1N1J5H8',
            'APCA-API-SECRET-KEY': '8Qh7s3K2v9X5mZ1nF4p6R2tW3qE8jY1kL4cV5bN6',
            'Content-Type': 'application/json'
        }
    
    def fetch_1min_data(self, symbol, start_date, end_date):
        """Fetch 1-minute data from Alpaca"""
        try:
            url = f"{self.base_url}/stocks/{symbol}/bars"
            
            # Split into 30-day chunks to avoid API limits
            all_bars = []
            current_start = start_date
            
            while current_start < end_date:
                chunk_end = min(current_start + timedelta(days=30), end_date)
                
                params = {
                    'timeframe': '1Min',
                    'start': current_start.isoformat(),
                    'end': chunk_end.isoformat(),
                    'adjustment': 'raw',
                    'limit': 10000  # Max per request
                }
                
                response = requests.get(url, headers=self.headers, params=params, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    if 'bars' in data and data['bars']:
                        all_bars.extend(data['bars'])
                        print(f"    ✓ {symbol}: {len(data['bars'])} bars")
                    else:
                        print(f"    ⚠ {symbol}: No bars in chunk")
                else:
                    print(f"    ✗ {symbol}: Error {response.status_code}")
                    return None
                
                current_start = chunk_end
                time.sleep(0.5)  # Rate limiting
            
            if all_bars:
                df = pd.DataFrame(all_bars)
                df['timestamp'] = pd.to_datetime(df['t'])
                df = df.rename(columns={
                    'o': 'open',
                    'h': 'high',
                    'l': 'low',
                    'c': 'close',
                    'v': 'volume'
                })
                df['symbol'] = symbol
                return df
            else:
                return None
                
        except Exception as e:
            print(f"    ✗ {symbol}: Exception {e}")
            return None

def calculate_technical_indicators(df):
    """Calculate technical indicators for BOOF scoring"""
    if len(df) < 50:
        return df
    
    # Calculate moving averages
    df['sma_20'] = df['close'].rolling(window=20, min_periods=1).mean()
    df['sma_50'] = df['close'].rolling(window=50, min_periods=1).mean()
    
    # Calculate volume indicators
    df['volume_sma_20'] = df['volume'].rolling(window=20, min_periods=1).mean()
    
    # Calculate resistance levels
    df['resistance_10'] = df['high'].rolling(window=10, min_periods=1).max()
    df['resistance_20'] = df['high'].rolling(window=20, min_periods=1).max()
    
    # Calculate price changes
    df['price_change_5'] = df['close'].pct_change(5)
    df['price_change_10'] = df['close'].pct_change(10)
    
    # Calculate volatility
    df['volatility_10'] = df['close'].pct_change().rolling(window=10, min_periods=1).std()
    
    # Calculate BOOF score
    df['score'] = 0
    
    # Volume expansion (score +2)
    df.loc[df['volume'] > df['volume_sma_20'] * 1.2, 'score'] += 2
    
    # Price above moving averages (score +2)
    df.loc[df['close'] > df['sma_20'], 'score'] += 1
    df.loc[df['close'] > df['sma_50'], 'score'] += 1
    
    # Near resistance (score +2)
    df.loc[df['close'] > df['resistance_10'] * 0.98, 'score'] += 2
    
    # Recent strength (score +2)
    df.loc[df['price_change_5'] > 0.01, 'score'] += 2
    
    # Volatility bonus (score +1)
    df.loc[df['volatility_10'] > df['volatility_10'].quantile(0.7), 'score'] += 1
    
    # Ensure score is within 0-10 range
    df['score'] = df['score'].clip(0, 10).fillna(0)
    
    return df

def calculate_real_mfe_mae(entry_row, df_subset, lookforward_minutes=30):
    """Calculate real MFE/MAE from actual price data"""
    entry_price = entry_row['close']
    entry_time = entry_row['timestamp']
    
    # Get future data
    future_data = df_subset[df_subset['timestamp'] > entry_time].head(lookforward_minutes)
    
    if len(future_data) == 0:
        return 0, 0
    
    # Calculate MFE (maximum favorable excursion)
    future_highs = future_data['high']
    mfe_price = future_highs.max()
    mfe = (mfe_price - entry_price) / entry_price
    
    # Calculate MAE (maximum adverse excursion)
    future_lows = future_data['low']
    mae_price = future_lows.min()
    mae = (entry_price - mae_price) / entry_price
    
    return max(0, mfe), max(0, mae)

def identify_boof_setups_1min(df):
    """Identify BOOF 31 v2 setups from 1-minute data"""
    setups = []
    
    for symbol in df['symbol'].unique():
        symbol_data = df[df['symbol'] == symbol].copy()
        
        # Calculate technical indicators
        symbol_data = calculate_technical_indicators(symbol_data)
        
        for i in range(50, len(symbol_data)):  # Need enough history
            current_row = symbol_data.iloc[i]
            
            # Check basic conditions
            if current_row['score'] >= MIN_SCORE:
                # Calculate real MFE/MAE
                mfe, mae = calculate_real_mfe_mae(current_row, symbol_data)
                
                # Count resistance touches
                resistance_level = current_row['resistance_10']
                touches = 0
                for j in range(max(0, i-20), i):
                    if symbol_data.iloc[j]['high'] >= resistance_level * 0.98:
                        touches += 1
                
                setups.append({
                    'symbol': symbol,
                    'timestamp': current_row['timestamp'],
                    'date': current_row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                    'score': int(current_row['score']),
                    'entry_price': current_row['close'],
                    'mfe': mfe,
                    'mae': mae,
                    'touches': touches,
                    'volume': current_row['volume'],
                    'sma_20': current_row['sma_20'],
                    'resistance': current_row['resistance_10']
                })
    
    return pd.DataFrame(setups)

def simulate_exit_c_real(entry_price, mfe, mae):
    """Simulate Exit C with real market conditions"""
    entry_with_slippage = entry_price * (1 + SLIPPAGE)
    
    if mfe >= TP1:
        # First 50% at 0.50%
        exit1_price = entry_with_slippage * (1 - TP1) * (1 + SLIPPAGE)
        pnl1 = (entry_with_slippage - exit1_price) / entry_with_slippage * 0.5
        
        # Remaining 50% with trailing stop
        trailing_stop = max(SL_OPTIMIZED, mfe - 0.0025)
        
        if mae >= trailing_stop:
            exit2_price = entry_with_slippage * (1 + trailing_stop) * (1 + SLIPPAGE)
            pnl2 = (entry_with_slippage - exit2_price) / entry_with_slippage * 0.5
        else:
            # Use actual MFE for trailing stop capture
            exit2_price = entry_with_slippage * (1 - mfe) * (1 + SLIPPAGE)
            pnl2 = (entry_with_slippage - exit2_price) / entry_with_slippage * 0.5
        
        total_pnl = pnl1 + pnl2
        return total_pnl, 'TP1_TRAIL'
    
    if mae >= SL_OPTIMIZED:
        exit_price = entry_with_slippage * (1 + SL_OPTIMIZED) * (1 + SLIPPAGE)
        pnl = (entry_with_slippage - exit_price) / entry_with_slippage
        return pnl, 'SL'
    
    # Average outcome for trades that don't hit targets
    avg_pnl = (mfe - mae) / 2 - SLIPPAGE * 2
    return avg_pnl, 'AVG'

def calculate_comprehensive_metrics(pnl_series):
    """Calculate comprehensive performance metrics"""
    if len(pnl_series) == 0:
        return 0, 0, 0, 0, 0, 0, 0, 0
    
    win_rate = (pnl_series > 0).mean()
    avg_pnl = pnl_series.mean()
    
    wins = pnl_series[pnl_series > 0].sum()
    losses = abs(pnl_series[pnl_series < 0].sum())
    profit_factor = wins / losses if losses > 0 else float('inf')
    
    # Calculate max drawdown
    cumulative = (1 + pnl_series).cumprod()
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = drawdown.min()
    
    # Calculate longest loss streak
    loss_streak = 0
    max_loss_streak = 0
    for pnl in pnl_series:
        if pnl < 0:
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
        else:
            loss_streak = 0
    
    # Calculate Sharpe ratio (annualized)
    if len(pnl_series) > 1:
        sharpe = avg_pnl / pnl_series.std() * np.sqrt(252 * 390) if pnl_series.std() > 0 else 0
    else:
        sharpe = 0
    
    # Calculate Sortino ratio
    downside_std = pnl_series[pnl_series < 0].std()
    sortino = avg_pnl / downside_std * np.sqrt(252 * 390) if downside_std > 0 else 0
    
    return win_rate, profit_factor, avg_pnl, max_drawdown, max_loss_streak, len(pnl_series), sharpe, sortino

def apply_cooldown_1min(df):
    """Apply 30-minute cooldown for 1-minute data"""
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    filtered_data = df.sort_values(['symbol', 'timestamp'])
    
    cooldown_data = []
    last_trade_time = {}
    
    for _, row in filtered_data.iterrows():
        symbol = row['symbol']
        trade_time = row['timestamp']
        
        if symbol in last_trade_time:
            time_diff = (trade_time - last_trade_time[symbol]).total_seconds() / 60
            if time_diff < COOLDOWN_MINUTES:
                continue
        
        cooldown_data.append(row)
        last_trade_time[symbol] = trade_time
    
    return pd.DataFrame(cooldown_data)

def run_alpaca_1year_1min():
    """Main Alpaca 1-year 1-minute backtest runner"""
    logging.info('='*80)
    logging.info('BOOF 31 v2 - ALPACA 1-YEAR 1-MINUTE BACKTEST')
    logging.info('='*80)
    
    # Initialize fetcher
    fetcher = AlpacaDataFetcher()
    
    # Define date range (1 year)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    
    print(f"Running BOOF 31 v2 on 1-year 1-minute data")
    print(f"Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"Symbols: {len(SYMBOLS)}")
    print(f"Strategy: Exit C - 50% at 0.50% + trailing stop")
    print(f"Expected data: ~100,000+ bars per symbol")
    
    # Fetch data for all symbols
    all_data = []
    successful_symbols = []
    
    for i, symbol in enumerate(SYMBOLS):
        print(f"\nFetching {symbol} ({i+1}/{len(SYMBOLS)})...")
        
        # Fetch 1-minute data
        min_data = fetcher.fetch_1min_data(symbol, start_date, end_date)
        
        if min_data is not None and len(min_data) > 1000:
            all_data.append(min_data)
            successful_symbols.append(symbol)
            print(f"  ✓ {symbol}: {len(min_data):,} total bars")
        else:
            print(f"  ✗ {symbol}: Insufficient data")
        
        # Rate limiting
        time.sleep(0.5)
    
    if not all_data:
        print("\nNo data fetched successfully")
        return
    
    # Combine all data
    df = pd.concat(all_data, ignore_index=True)
    print(f"\n✓ Successfully fetched data for {len(successful_symbols)}/{len(SYMBOLS)} symbols")
    print(f"✓ Total 1-minute bars: {len(df):,}")
    print(f"✓ Data period: {df['timestamp'].min()} to {df['timestamp'].max()}")
    
    # Identify BOOF setups
    print(f"\nIdentifying BOOF 31 v2 setups...")
    setups = identify_boof_setups_1min(df)
    print(f"✓ Total setups identified: {len(setups):,}")
    
    # Apply optimized filters
    filtered = setups[setups['score'] >= MIN_SCORE]
    filtered = filtered[filtered['mfe'] >= SWEEP_OPTIMIZED]
    
    # Apply cooldown
    cooldown_data = apply_cooldown_1min(filtered)
    
    print(f"✓ Setups after filtering: {len(cooldown_data):,}")
    
    if len(cooldown_data) == 0:
        print("No trades to simulate")
        return
    
    # Simulate trades
    print(f"\nSimulating trades with Exit C strategy...")
    pnls = []
    exit_types = []
    symbols_traded = []
    trade_times = []
    
    for _, row in cooldown_data.iterrows():
        pnl, exit_type = simulate_exit_c_real(row['entry_price'], row['mfe'], row['mae'])
        pnls.append(pnl)
        exit_types.append(exit_type)
        symbols_traded.append(row['symbol'])
        trade_times.append(row['timestamp'])
    
    # Calculate comprehensive metrics
    pnl_series = pd.Series(pnls)
    wr, pf, ev, max_dd, max_streak, trades, sharpe, sortino = calculate_comprehensive_metrics(pnl_series)
    total_pnl = pnl_series.sum()
    
    print(f"\n{'='*80}")
    print(f'ALPACA 1-YEAR 1-MINUTE BACKTEST RESULTS')
    print(f"{'='*80}")
    
    print(f"\nPERFORMANCE METRICS:")
    print(f"{'Metric':<25} {'Value':<15}")
    print(f"{'-'*40}")
    print(f"{'Total Trades':<25} {trades:<15,}")
    print(f"{'Win Rate':<25} {wr:.1%}")
    print(f"{'Profit Factor':<25} {pf:.2f}")
    print(f"{'EV per Trade':<25} {ev:.4%}")
    print(f"{'Total Return':<25} {total_pnl:.2%}")
    print(f"{'Max Drawdown':<25} {max_dd:.2%}")
    print(f"{'Max Loss Streak':<25} {max_streak}")
    print(f"{'Sharpe Ratio':<25} {sharpe:.2f}")
    print(f"{'Sortino Ratio':<25} {sortino:.2f}")
    
    # Exit type analysis
    exit_type_counts = pd.Series(exit_types).value_counts()
    print(f"\nEXIT TYPE DISTRIBUTION:")
    for exit_type, count in exit_type_counts.items():
        percentage = count / trades * 100
        print(f"  {exit_type}: {count:,} ({percentage:.1f}%)")
    
    # Symbol performance
    symbol_performance = {}
    for symbol in successful_symbols:
        symbol_pnls = [pnl for pnl, sym in zip(pnls, symbols_traded) if sym == symbol]
        if symbol_pnls:
            symbol_series = pd.Series(symbol_pnls)
            symbol_wr = (symbol_series > 0).mean()
            symbol_pf = symbol_series[symbol_series > 0].sum() / abs(symbol_series[symbol_series < 0].sum()) if symbol_series[symbol_series < 0].sum() > 0 else float('inf')
            symbol_performance[symbol] = {
                'trades': len(symbol_pnls),
                'win_rate': symbol_wr,
                'profit_factor': symbol_pf,
                'total_pnl': symbol_series.sum()
            }
    
    # Top performing symbols
    top_symbols = sorted(symbol_performance.items(), key=lambda x: x[1]['profit_factor'], reverse=True)[:10]
    
    print(f"\nTOP 10 PERFORMING SYMBOLS:")
    print(f"{'Symbol':<8} {'Trades':<8} {'WR':<8} {'PF':<8} {'Total PnL':<12}")
    print(f"{'-'*50}")
    
    for symbol, perf in top_symbols:
        print(f"{symbol:<8} {perf['trades']:<8} {perf['win_rate']:.1%}{'':<5} {perf['profit_factor']:.2f}{'':<5} {perf['total_pnl']:.2%}")
    
    # Monthly performance
    trade_df = pd.DataFrame({
        'timestamp': trade_times,
        'pnl': pnls,
        'symbol': symbols_traded
    })
    trade_df['month'] = trade_df['timestamp'].dt.to_period('M')
    
    print(f"\nMONTHLY PERFORMANCE:")
    print(f"{'Month':<10} {'Trades':<8} {'WR':<8} {'PF':<8} {'Return':<10}")
    print(f"{'-'*50}")
    
    for month, month_data in trade_df.groupby('month'):
        month_pnls = month_data['pnl']
        month_trades = len(month_pnls)
        month_wr = (month_pnls > 0).mean()
        month_wins = month_pnls[month_pnls > 0].sum()
        month_losses = abs(month_pnls[month_pnls < 0].sum())
        month_pf = month_wins / month_losses if month_losses > 0 else float('inf')
        month_return = month_pnls.sum()
        
        print(f"{str(month):<10} {month_trades:<8} {month_wr:.1%}{'':<5} {month_pf:.2f}{'':<5} {month_return:.2%}")
    
    # Save results
    results_df = pd.DataFrame({
        'symbol': symbols_traded,
        'timestamp': trade_times,
        'pnl': pnls,
        'exit_type': exit_types
    })
    results_df.to_csv('boof31v2_alpaca_1year_1min_results.csv', index=False)
    print(f"\n✓ Results saved to boof31v2_alpaca_1year_1min_results.csv")
    
    # Final assessment
    print(f"\n{'='*80}")
    print(f"ALPACA 1-YEAR 1-MINUTE BACKTEST COMPLETE!")
    print(f"{'='*80}")
    
    if pf >= 3.0:
        print(f"✅ EXCELLENT: Profit Factor {pf:.2f} (≥3.0)")
    elif pf >= 2.0:
        print(f"✅ GOOD: Profit Factor {pf:.2f} (≥2.0)")
    else:
        print(f"⚠️  MARGINAL: Profit Factor {pf:.2f} (<2.0)")
    
    if max_dd >= -0.20:
        print(f"⚠️  HIGH RISK: Max Drawdown {max_dd:.2%}")
    elif max_dd >= -0.10:
        print(f"✅ MODERATE RISK: Max Drawdown {max_dd:.2%}")
    else:
        print(f"✅ LOW RISK: Max Drawdown {max_dd:.2%}")
    
    print(f"\n🚀 1-YEAR 1-MINUTE BACKTEST SUCCESSFUL!")
    
    return {
        'overall': {
            'trades': trades,
            'win_rate': wr,
            'profit_factor': pf,
            'ev': ev,
            'total_pnl': total_pnl,
            'max_drawdown': max_dd,
            'max_loss_streak': max_streak,
            'sharpe': sharpe,
            'sortino': sortino
        },
        'symbol_performance': symbol_performance,
        'exit_types': exit_type_counts.to_dict(),
        'successful_symbols': successful_symbols
    }

if __name__ == '__main__':
    run_alpaca_1year_1min()
