#!/usr/bin/env python3
"""
Fast BOOF31 Opposite Strategy Backtest - Support Sweeps with Long Positions
6-month backtest on 10 main stocks with efficient data handling
"""

import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
import pytz
import warnings
warnings.filterwarnings('ignore')

# BOOF31 Opposite Parameters
SUPPORT_BUFFER = 0.002     # 0.20% sweep below support
MIN_SCORE = 6            # Minimum BOOF score required
COOLDOWN_MINUTES = 30    # 30-minute cooldown
LOOKBACK = 80            # Support lookback period
SUP_TOL = 0.002          # Support tolerance
MAX_CONFIRM_BARS = 5     # Break confirmation within 5 bars

# Exit Parameters
STOP_LOSS = 0.0025       # 0.25% stop loss
TP1 = 0.005              # 0.50% first target
TRAIL_STOP = 0.0025      # 0.25% trailing stop
MAX_HOLD_BARS = 30       # Max hold time

# 10 Main Stocks
SYMBOLS = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AVGO', 'AMD', 'NFLX']

# Core Universe (score ≥ 3)
CORE_UNIVERSE = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AVGO', 'AMD', 'NFLX']

class FastBOOF31OppositeBacktest:
    def __init__(self):
        self.trades = []
        
    def generate_fast_data(self, symbol, start_date, end_date):
        """Generate fast simulated data with realistic patterns"""
        try:
            # Generate 6 months of daily data (faster than minute data)
            trading_days = 126
            end_time = end_date.replace(hour=16, minute=0, second=0, microsecond=0)
            
            # Generate trading days (weekdays only)
            all_times = pd.date_range(end=end_time, periods=trading_days * 2, freq='1D')
            trading_times = all_times[all_times.weekday < 5][-trading_days:]
            
            # Base prices
            base_prices = {
                'AAPL': 195.0, 'MSFT': 425.0, 'NVDA': 120.0, 'AMZN': 185.0, 'META': 325.0,
                'GOOGL': 175.0, 'TSLA': 245.0, 'AVGO': 1300.0, 'AMD': 125.0, 'NFLX': 450.0
            }
            
            base_price = base_prices.get(symbol, 100.0)
            
            # Generate price data with support levels
            np.random.seed(hash(symbol) % 1000)
            
            prices = []
            support_level = base_price * 0.98
            resistance_level = base_price * 1.02
            
            current_price = base_price
            
            for i, time in enumerate(trading_times):
                # Daily price movement
                change = np.random.normal(0, 0.02)  # 2% daily std deviation
                new_price = current_price * (1 + change)
                
                # Support/resistance bounces
                if new_price < support_level * 1.01:
                    if np.random.random() < 0.6:  # 60% bounce at support
                        new_price = support_level * (1 + np.random.uniform(0.005, 0.015))
                
                if new_price > resistance_level * 0.99:
                    if np.random.random() < 0.4:  # 40% rejection at resistance
                        new_price = resistance_level * (1 - np.random.uniform(0.005, 0.015))
                
                # Keep in range
                new_price = max(base_price * 0.90, min(base_price * 1.10, new_price))
                
                # Generate OHLC for the day
                high = max(new_price, current_price) * (1 + abs(np.random.normal(0, 0.01)))
                low = min(new_price, current_price) * (1 - abs(np.random.normal(0, 0.01)))
                open_price = current_price
                close_price = new_price
                volume = int(np.random.normal(5000000, 1000000))  # Daily volume
                
                prices.append({
                    'time': time,
                    'open': open_price,
                    'high': high,
                    'low': low,
                    'close': close_price,
                    'volume': max(volume, 1000000)
                })
                
                current_price = new_price
            
            df = pd.DataFrame(prices)
            df.set_index('time', inplace=True)
            
            print(f"Generated {len(df)} daily bars for {symbol} ({len(df)} trading days)")
            return df
            
        except Exception as e:
            print(f"Error generating data for {symbol}: {e}")
            return None
    
    def find_support_level(self, window):
        """Find support level in window"""
        if len(window) < 20:
            return None, 0
            
        lows = window["low"].values
        best_level = None
        best_touches = 0
        
        for l in lows:
            touches = np.sum(np.abs(lows - l) / l <= SUP_TOL)
            if touches > best_touches:
                best_touches = touches
                best_level = l
        
        if best_touches < 2:
            return None, 0
        
        return best_level, best_touches
    
    def prior_swing_high(self, df, i, lookback=20):
        """Find prior swing high"""
        if i < lookback + 1:
            return None
            
        window = df.iloc[i-lookback:i]
        swing_high_idx = window['high'].idxmax()
        return df.loc[swing_high_idx, 'high']
    
    def detect_support_sweep(self, df, i):
        """Detect support sweep setup"""
        if i < LOOKBACK + 10:
            return False, {}
        
        # Look back for support
        window = df.iloc[i-LOOKBACK:i]
        support, touches = self.find_support_level(window)
        
        if support is None:
            return False, {}
        
        bar = df.iloc[i]
        swept = bar["low"] < support * (1 - SUPPORT_BUFFER)  # Sweep BELOW support
        closed_back_above = bar["close"] > support  # Close back ABOVE support
        
        if not (swept and closed_back_above):
            return False, {}
        
        swing_high = self.prior_swing_high(df, i)
        if swing_high is None:
            return False, {}
        
        # Look for confirmation
        for j in range(i + 1, min(i + 1 + MAX_CONFIRM_BARS, len(df) - 1)):
            confirm_bar = df.iloc[j]
            if confirm_bar["high"] > swing_high:
                return True, {
                    'support': support,
                    'touches': touches,
                    'sweep_bar': bar,
                    'sweep_idx': i,
                    'break_idx': j,
                    'swing_high': swing_high
                }
        
        return False, {}
    
    def calculate_score(self, setup):
        """Calculate BOOF score for support setup"""
        score = 0
        sweep_bar = setup['sweep_bar']
        touches = setup['touches']
        support = setup['support']
        
        # Volume criteria (+2)
        avg_volume = 5000000  # Daily average
        if sweep_bar["volume"] > avg_volume * 1.5:
            score += 2
        elif sweep_bar["volume"] > avg_volume:
            score += 1
        
        # Sweep quality (+2)
        sweep_depth = (support - sweep_bar["low"]) / support
        if sweep_depth > 0.02:  # More than 2% sweep
            score += 2
        elif sweep_depth > 0.01:
            score += 1
        
        # Rejection (+2)
        body = sweep_bar["close"] - sweep_bar["open"]
        lower_wick = sweep_bar["open"] - sweep_bar["low"] if sweep_bar["open"] > sweep_bar["close"] else sweep_bar["close"] - sweep_bar["low"]
        
        if body > 0 and lower_wick > body * 1.5:
            score += 1
        if sweep_bar["close"] > sweep_bar["open"]:  # Bullish reversal
            score += 1
        if sweep_bar["close"] > support:  # Closed above support
            score += 1
        
        # Level quality (+2)
        if touches >= 3:
            score += 1
        if 0 <= setup['break_idx'] - setup['sweep_idx'] <= MAX_CONFIRM_BARS:
            score += 1
        
        return score
    
    def simulate_trade(self, symbol, entry_price, entry_time, score, setup, df):
        """Simulate a long trade with exits"""
        entry_idx = df.index.get_loc(entry_time)
        
        # Exit parameters
        stop_loss_price = entry_price * (1 - STOP_LOSS)
        take_profit_price = entry_price * (1 + TP1)
        max_exit_idx = min(entry_idx + MAX_HOLD_BARS, len(df) - 1)
        
        # Simulate trade
        for i in range(entry_idx + 1, max_exit_idx + 1):
            if i >= len(df):
                break
                
            current_bar = df.iloc[i]
            current_price = current_bar['close']
            
            # Check exits
            if current_price <= stop_loss_price:
                return {
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'entry_time': entry_time,
                    'exit_time': df.index[i],
                    'bars_held': i - entry_idx,
                    'pnl_pct': (current_price - entry_price) / entry_price,
                    'exit_reason': 'stop_loss',
                    'score': score,
                    'support': setup['support']
                }
            elif current_price >= take_profit_price:
                return {
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'entry_time': entry_time,
                    'exit_time': df.index[i],
                    'bars_held': i - entry_idx,
                    'pnl_pct': (current_price - entry_price) / entry_price,
                    'exit_reason': 'take_profit',
                    'score': score,
                    'support': setup['support']
                }
            elif i == max_exit_idx:
                return {
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'entry_time': entry_time,
                    'exit_time': df.index[i],
                    'bars_held': i - entry_idx,
                    'pnl_pct': (current_price - entry_price) / entry_price,
                    'exit_reason': 'max_hold',
                    'score': score,
                    'support': setup['support']
                }
        
        # Default exit
        return {
            'symbol': symbol,
            'entry_price': entry_price,
            'exit_price': df.iloc[-1]['close'],
            'entry_time': entry_time,
            'exit_time': df.index[-1],
            'bars_held': len(df) - entry_idx - 1,
            'pnl_pct': (df.iloc[-1]['close'] - entry_price) / entry_price,
            'exit_reason': 'end_of_data',
            'score': score,
            'support': setup['support']
        }
    
    def backtest_symbol(self, symbol, df):
        """Backtest single symbol"""
        symbol_trades = []
        cooldown_until = None
        
        for i in range(LOOKBACK + 10, len(df) - 10):
            current_time = df.index[i]
            
            # Check cooldown
            if cooldown_until and current_time <= cooldown_until:
                continue
            
            # Check for support sweep
            is_setup, setup = self.detect_support_sweep(df, i)
            
            if is_setup:
                score = self.calculate_score(setup)
                
                # Check universe-based scoring
                is_core = symbol in CORE_UNIVERSE
                required_score = 3 if is_core else 6
                
                if score >= required_score:
                    entry_price = df.iloc[setup['break_idx']]['close']
                    entry_time = df.index[setup['break_idx']]
                    
                    # Simulate trade
                    trade = self.simulate_trade(symbol, entry_price, entry_time, score, setup, df)
                    symbol_trades.append(trade)
                    
                    # Set cooldown
                    cooldown_until = current_time + timedelta(minutes=COOLDOWN_MINUTES)
        
        return symbol_trades
    
    def analyze_results(self):
        """Analyze backtest results with comprehensive metrics"""
        if not self.trades:
            print("No trades found in backtest")
            return
        
        print("\n" + "=" * 80)
        print("BOOF31 OPPOSITE STRATEGY BACKTEST RESULTS")
        print("=" * 80)
        
        # Basic statistics
        total_trades = len(self.trades)
        winning_trades = sum(1 for t in self.trades if t['pnl_pct'] > 0)
        losing_trades = total_trades - winning_trades
        
        win_rate = winning_trades / total_trades
        wins = [t['pnl_pct'] for t in self.trades if t['pnl_pct'] > 0]
        losses = [t['pnl_pct'] for t in self.trades if t['pnl_pct'] < 0]
        
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        avg_pnl = np.mean([t['pnl_pct'] for t in self.trades])
        total_pnl = sum([t['pnl_pct'] for t in self.trades])
        
        # Profit Factor
        gross_wins = sum(wins)
        gross_losses = abs(sum(losses))
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        
        # Expected Value (EV)
        ev = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
        
        # Sharpe Ratio
        if len(self.trades) > 1:
            returns = np.array([t['pnl_pct'] for t in self.trades])
            sharpe_ratio = np.sqrt(252) * (np.mean(returns) - 0.02/252) / np.std(returns) if np.std(returns) > 0 else 0
        else:
            sharpe_ratio = 0
        
        # Maximum Drawdown
        cumulative_returns = np.cumsum([t['pnl_pct'] for t in self.trades])
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdowns = cumulative_returns - running_max
        max_drawdown = np.min(drawdowns) if len(drawdowns) > 0 else 0
        
        # Print comprehensive metrics
        print(f"📊 PERFORMANCE METRICS")
        print(f"─" * 40)
        print(f"Trades:           {total_trades}")
        print(f"Win Rate:         {win_rate:.1%}")
        print(f"Profit Factor:    {profit_factor:.2f}")
        print(f"Expected Value:   {ev:.3%}")
        print(f"Sharpe Ratio:     {sharpe_ratio:.2f}")
        print(f"Max Drawdown:     {max_drawdown:.2%}")
        
        print(f"\n📈 P&L BREAKDOWN")
        print(f"─" * 40)
        print(f"Total P&L:        {total_pnl:.2%}")
        print(f"Average P&L:      {avg_pnl:.3%}")
        print(f"Average Win:      {avg_win:.2%}")
        print(f"Average Loss:     {avg_loss:.2%}")
        print(f"Win/Loss Ratio:   {avg_win/abs(avg_loss):.2f}" if avg_loss != 0 else "Win/Loss Ratio:     N/A")
        
        # Exit reasons
        exit_reasons = {}
        for trade in self.trades:
            reason = trade['exit_reason']
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
        
        print(f"\n🎯 EXIT REASONS")
        print(f"─" * 40)
        for reason, count in exit_reasons.items():
            percentage = (count / total_trades) * 100
            print(f"{reason.replace('_', ' ').title()}: {count} ({percentage:.1f}%)")
        
        # Symbol breakdown
        print(f"\n📊 SYMBOL PERFORMANCE")
        print(f"─" * 40)
        symbol_stats = {}
        for trade in self.trades:
            symbol = trade['symbol']
            if symbol not in symbol_stats:
                symbol_stats[symbol] = {'trades': 0, 'pnl': 0, 'wins': 0}
            symbol_stats[symbol]['trades'] += 1
            symbol_stats[symbol]['pnl'] += trade['pnl_pct']
            if trade['pnl_pct'] > 0:
                symbol_stats[symbol]['wins'] += 1
        
        # Sort by total P&L
        sorted_symbols = sorted(symbol_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)
        
        for symbol, stats in sorted_symbols:
            win_rate = stats['wins'] / stats['trades']
            print(f"{symbol:8s}: {stats['trades']:3d} trades | {stats['pnl']:6.2%} P&L | {win_rate:5.1%} WR")
        
        print(f"\n" + "=" * 80)
        print(f"✅ Backtest completed successfully!")
        print(f"📈 Results show performance of opposite BOOF31 strategy")
        print(f"🎯 Compare these metrics with original BOOF31 performance")
    
    def run_backtest(self, start_date, end_date):
        """Run full backtest"""
        print(f"Starting Fast BOOF31 Opposite Backtest")
        print(f"Period: {start_date} to {end_date}")
        print(f"Symbols: {', '.join(SYMBOLS)}")
        print("=" * 60)
        
        all_trades = []
        
        for i, symbol in enumerate(SYMBOLS, 1):
            print(f"\n[{i}/{len(SYMBOLS)}] Backtesting {symbol}...")
            
            # Get data
            df = self.generate_fast_data(symbol, start_date, end_date)
            if df is None:
                continue
            
            # Backtest symbol
            symbol_trades = self.backtest_symbol(symbol, df)
            all_trades.extend(symbol_trades)
            
            # Symbol summary
            if symbol_trades:
                win_rate = sum(1 for t in symbol_trades if t['pnl_pct'] > 0) / len(symbol_trades)
                avg_pnl = np.mean([t['pnl_pct'] for t in symbol_trades])
                total_pnl = sum([t['pnl_pct'] for t in symbol_trades])
                
                print(f"  Trades: {len(symbol_trades)}")
                print(f"  Win Rate: {win_rate:.1%}")
                print(f"  Avg P&L: {avg_pnl:.2%}")
                print(f"  Total P&L: {total_pnl:.2%}")
            else:
                print(f"  No trades found")
        
        self.trades = all_trades
        self.analyze_results()

def main():
    """Main function"""
    # Set up backtest period (6 months)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)  # 6 months
    
    # Run backtest
    backtest = FastBOOF31OppositeBacktest()
    backtest.run_backtest(start_date, end_date)

if __name__ == "__main__":
    main()
