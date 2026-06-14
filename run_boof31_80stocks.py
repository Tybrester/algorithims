#!/usr/bin/env python3
"""
BOOF 31 v2 - 80 STOCKS 1-YEAR 1-MINUTE BACKTEST
Run comprehensive backtest on 80 stocks for 1 year with 1-minute data
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import logging
import time
import warnings
warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# 80 STOCK UNIVERSE
SYMBOLS = [
    # Tech Giants
    'AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AVGO', 'AMD', 'NFLX',
    # Cloud/SaaS
    'CRM', 'NOW', 'SNOW', 'PLTR', 'DDOG', 'MDB', 'CRWD', 'ZS', 'NET', 'SHOP',
    # Software
    'ADBE', 'INTU', 'PANW', 'TEAM', 'HUBS', 'UBER', 'ABNB', 'BKNG', 'RBLX', 'DASH',
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

# BOOF 31 v2 PARAMETERS
SWEEP_THRESHOLD = 0.0020  # 0.20% sweep
TP_TARGET = 0.0050        # 0.50% take profit
SL_STOP = 0.0025          # 0.25% stop loss
COOLDOWN_MINUTES = 30
MIN_SCORE = 6

def calculate_boof_score(df):
    """Calculate BOOF score for recent data"""
    if len(df) < 50:
        return 0
    
    # Calculate technical indicators
    df['sma_20'] = df['close'].rolling(window=20).mean()
    df['sma_50'] = df['close'].rolling(window=50).mean()
    df['volume_sma_20'] = df['volume'].rolling(window=20).mean()
    df['resistance_10'] = df['high'].rolling(window=10).max()
    df['price_change_5'] = df['close'].pct_change(5)
    df['volatility_10'] = df['close'].pct_change().rolling(window=10).std()
    
    # Get latest values
    latest = df.iloc[-1]
    
    score = 0
    
    # Volume expansion (score +2)
    if latest['volume'] > latest['volume_sma_20'] * 1.2:
        score += 2
    
    # Price above moving averages (score +2)
    if latest['close'] > latest['sma_20']:
        score += 1
    if latest['close'] > latest['sma_50']:
        score += 1
    
    # Near resistance (score +2)
    if latest['close'] > latest['resistance_10'] * 0.98:
        score += 2
    
    # Recent strength (score +2)
    if latest['price_change_5'] > 0.01:
        score += 2
    
    # Volatility bonus (score +1)
    if latest['volatility_10'] > latest['volatility_10'].quantile(0.7):
        score += 1
    
    return min(10, max(0, int(score)))

def check_sweep_condition(df):
    """Check if sweep condition is met"""
    if len(df) < 5:
        return False
    
    latest = df.iloc[-1]
    resistance = df['high'].rolling(window=5).max().iloc[-2]
    
    # Check if price swept above resistance
    if latest['close'] > resistance * 1.002:  # 0.2% sweep
        return True
    
    return False

def fetch_1min_data(symbol, period="1y"):
    """Fetch 1-minute data using yfinance"""
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period=period, interval="1m")
        
        if data.empty:
            return None
        
        # Standardize column names
        data.columns = [col.lower() for col in data.columns]
        data.index = pd.to_datetime(data.index)
        
        return data
    except Exception as e:
        log.warning(f"Error fetching {symbol}: {e}")
        return None

def run_backtest():
    """Run BOOF 31 v2 backtest on all symbols"""
    log.info("=" * 80)
    log.info("BOOF 31 v2 - 80 STOCKS 1-YEAR 1-MINUTE BACKTEST")
    log.info("=" * 80)
    
    all_trades = []
    symbol_results = {}
    
    for i, symbol in enumerate(SYMBOLS, 1):
        log.info(f"Processing {symbol} ({i}/{len(SYMBOLS)})...")
        
        # Fetch data
        data = fetch_1min_data(symbol)
        if data is None:
            log.warning(f"  ✗ {symbol}: No data available")
            continue
        
        if len(data) < 1000:  # Need sufficient data
            log.warning(f"  ✗ {symbol}: Insufficient data ({len(data)} bars)")
            continue
        
        # Run strategy on this symbol
        trades = run_symbol_strategy(symbol, data)
        
        if trades:
            all_trades.extend(trades)
            symbol_results[symbol] = trades
            log.info(f"  ✓ {symbol}: {len(trades)} trades")
        else:
            log.info(f"  ✓ {symbol}: No trades")
    
    # Calculate overall metrics
    if all_trades:
        calculate_overall_metrics(all_trades, symbol_results)
    else:
        log.warning("No trades generated across all symbols")

def run_symbol_strategy(symbol, data):
    """Run BOOF 31 v2 strategy on a single symbol"""
    trades = []
    position = None
    cooldown_until = None
    
    for i in range(50, len(data)):  # Start from 50 to have enough history
        current_time = data.index[i]
        current_bar = data.iloc[i]
        
        # Check cooldown
        if cooldown_until and current_time <= cooldown_until:
            continue
        
        # Check if we have an open position
        if position is None:
            # Look for entry signal
            recent_data = data.iloc[i-50:i+1]
            
            score = calculate_boof_score(recent_data)
            if score < MIN_SCORE:
                continue
            
            if not check_sweep_condition(recent_data):
                continue
            
            # Enter short position
            entry_price = current_bar['close']
            position = {
                'symbol': symbol,
                'entry_time': current_time,
                'entry_price': entry_price,
                'shares': 100,  # Standard position size
                'highest_price': entry_price  # For trailing stop
            }
            
        else:
            # Manage existing position
            current_price = current_bar['close']
            entry_price = position['entry_price']
            
            # Calculate P&L
            pnl_pct = (entry_price - current_price) / entry_price  # Short position
            
            # Check exit conditions
            exit_reason = None
            
            # Take profit
            if pnl_pct >= TP_TARGET:
                exit_reason = "take_profit"
            
            # Stop loss
            elif pnl_pct <= -SL_STOP:
                exit_reason = "stop_loss"
            
            # Time exit (end of day)
            elif current_time.time() >= pd.Timestamp("15:55:00").time():
                exit_reason = "end_of_day"
            
            if exit_reason:
                # Close position
                trade = {
                    'symbol': symbol,
                    'entry_time': position['entry_time'],
                    'exit_time': current_time,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'pnl_pct': pnl_pct,
                    'exit_reason': exit_reason
                }
                trades.append(trade)
                position = None
                
                # Set cooldown
                cooldown_until = current_time + timedelta(minutes=COOLDOWN_MINUTES)
    
    return trades

def calculate_overall_metrics(all_trades, symbol_results):
    """Calculate and display overall performance metrics"""
    log.info("=" * 80)
    log.info("BACKTEST RESULTS")
    log.info("=" * 80)
    
    # Convert to DataFrame
    df = pd.DataFrame(all_trades)
    
    # Basic stats
    total_trades = len(df)
    winning_trades = len(df[df['pnl_pct'] > 0])
    losing_trades = len(df[df['pnl_pct'] < 0])
    
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    
    # Profit factor
    gross_profit = df[df['pnl_pct'] > 0]['pnl_pct'].sum()
    gross_loss = abs(df[df['pnl_pct'] < 0]['pnl_pct'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Average metrics
    avg_win = df[df['pnl_pct'] > 0]['pnl_pct'].mean() if winning_trades > 0 else 0
    avg_loss = df[df['pnl_pct'] < 0]['pnl_pct'].mean() if losing_trades > 0 else 0
    
    # Total return
    total_return = df['pnl_pct'].sum()
    
    # Display results
    print(f"\n{'OVERALL PERFORMANCE':<40} {'VALUE':>15}")
    print("-" * 55)
    print(f"{'Total Trades':<40} {total_trades:>15}")
    print(f"{'Winning Trades':<40} {winning_trades:>15}")
    print(f"{'Losing Trades':<40} {losing_trades:>15}")
    print(f"{'Win Rate':<40} {win_rate:.1%:>15}")
    print(f"{'Profit Factor':<40} {profit_factor:.2f:>15}")
    print(f"{'Average Win':<40} {avg_win:.2%:>15}")
    print(f"{'Average Loss':<40} {avg_loss:.2%:>15}")
    print(f"{'Total Return':<40} {total_return:.2%:>15}")
    
    # Performance assessment
    print(f"\n{'PERFORMANCE ASSESSMENT':<40}")
    print("-" * 40)
    if profit_factor >= 3.0:
        print(f"✅ EXCELLENT: Profit Factor {profit_factor:.2f} (≥3.0)")
    elif profit_factor >= 2.0:
        print(f"✅ GOOD: Profit Factor {profit_factor:.2f} (≥2.0)")
    else:
        print(f"⚠️  MARGINAL: Profit Factor {profit_factor:.2f} (<2.0)")
    
    if win_rate >= 0.60:
        print(f"✅ EXCELLENT: Win Rate {win_rate:.1%} (≥60%)")
    elif win_rate >= 0.50:
        print(f"✅ GOOD: Win Rate {win_rate:.1%} (≥50%)")
    else:
        print(f"⚠️  MARGINAL: Win Rate {win_rate:.1%} (<50%)")
    
    # Symbol breakdown
    print(f"\n{'TOP 10 SYMBOLS BY TRADES':<40}")
    print("-" * 40)
    symbol_trade_counts = {symbol: len(trades) for symbol, trades in symbol_results.items()}
    top_symbols = sorted(symbol_trade_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    
    for symbol, count in top_symbols:
        symbol_trades = symbol_results[symbol]
        symbol_wins = len([t for t in symbol_trades if t['pnl_pct'] > 0])
        symbol_wr = symbol_wins / len(symbol_trades) if symbol_trades else 0
        print(f"{symbol:<8} {count:>6} trades  {symbol_wr:.1%} WR")
    
    # Save results
    with open('boof31v2_80stocks_1year_results.txt', 'w') as f:
        f.write("BOOF 31 v2 - 80 STOCKS 1-YEAR 1-MINUTE BACKTEST RESULTS\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Total Trades: {total_trades}\n")
        f.write(f"Win Rate: {win_rate:.1%}\n")
        f.write(f"Profit Factor: {profit_factor:.2f}\n")
        f.write(f"Total Return: {total_return:.2%}\n")
        f.write(f"Average Win: {avg_win:.2%}\n")
        f.write(f"Average Loss: {avg_loss:.2%}\n\n")
        
        f.write("SYMBOL BREAKDOWN:\n")
        for symbol, trades in symbol_results.items():
            symbol_wins = len([t for t in trades if t['pnl_pct'] > 0])
            symbol_wr = symbol_wins / len(trades) if trades else 0
            symbol_return = sum(t['pnl_pct'] for t in trades)
            f.write(f"{symbol}: {len(trades)} trades, {symbol_wr:.1%} WR, {symbol_return:.2%} return\n")
    
    log.info(f"Results saved to boof31v2_80stocks_1year_results.txt")

if __name__ == "__main__":
    start_time = time.time()
    run_backtest()
    end_time = time.time()
    log.info(f"Backtest completed in {(end_time - start_time)/60:.1f} minutes")
