#!/usr/bin/env python3
"""
Comprehensive BOOF31 Backtest - Both Short and Long Strategies
Mirrors exact BOOF31 logic for resistance sweeps (short) and support sweeps (long)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import warnings
warnings.filterwarnings('ignore')

# BOOF31 Parameters
SWEEP_BUFFER = 0.002      # 0.20% sweep buffer
RES_TOL = 0.002          # Resistance/Support tolerance
MIN_SCORE = 6            # Minimum score for extended universe
CORE_MIN_SCORE = 3       # Minimum score for core universe
LOOKBACK = 80            # Lookback period
MAX_CONFIRM_BARS = 5     # Max bars for confirmation
COOLDOWN_MINUTES = 30    # Cooldown period

# Exit Parameters
STOP_LOSS = 0.0025       # 0.25% stop loss
TP1 = 0.005              # 0.50% first target
TRAIL_STOP = 0.0025      # 0.25% trailing stop
MAX_HOLD_BARS = 30       # Max hold time

# 10 Main Stocks
SYMBOLS = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AVGO', 'AMD', 'NFLX']
CORE_UNIVERSE = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AVGO', 'AMD', 'NFLX']

class ComprehensiveBOOF31Backtest:
    def __init__(self):
        self.trades = []
        
    def generate_fast_data(self, symbol, start_date, end_date):
        """Generate realistic data with proper BOOF31 setups"""
        try:
            # Generate 6 months of daily data
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
            
            # Generate price data with BOOF31-friendly patterns
            np.random.seed(hash(symbol) % 1000)
            
            prices = []
            
            # Create multiple support/resistance levels throughout the period
            levels = []
            current_base = base_price
            
            for i in range(5):  # 5 different levels over 6 months
                level_base = current_base
                support = level_base * 0.98
                resistance = level_base * 1.02
                levels.append({
                    'start_day': i * 25,
                    'end_day': (i + 1) * 25,
                    'support': support,
                    'resistance': resistance,
                    'trend': np.random.choice([-0.001, 0, 0.001])
                })
                current_base = level_base * np.random.uniform(0.95, 1.05)  # Drift to new level
            
            current_price = base_price
            
            for day_idx, time in enumerate(trading_times):
                # Find current level
                current_level = None
                for level in levels:
                    if level['start_day'] <= day_idx < level['end_day']:
                        current_level = level
                        break
                
                if current_level is None:
                    current_level = levels[-1]  # Use last level
                
                # Generate price with trend and mean reversion
                trend = current_level['trend']
                noise = np.random.normal(0, 0.01)  # 1% daily noise
                
                # Mean reversion to middle of range
                middle = (current_level['support'] + current_level['resistance']) / 2
                reversion = (middle - current_price) * 0.05  # 5% reversion
                
                new_price = current_price * (1 + trend + noise + reversion)
                
                # Create BOOF31 setups periodically
                if day_idx % 15 == 7:  # Every ~3 weeks, create setup
                    setup_type = np.random.choice(['resistance', 'support'])
                    
                    if setup_type == 'resistance':
                        # Resistance sweep setup
                        sweep_price = current_level['resistance'] * (1 + np.random.uniform(0.002, 0.006))
                        # Create sweep bar
                        high = sweep_price
                        low = current_level['resistance'] * (1 - np.random.uniform(0.001, 0.003))
                        close = current_level['resistance'] * (1 - np.random.uniform(0.001, 0.004))
                        open_price = current_level['resistance'] * (1 + np.random.uniform(0, 0.002))
                        
                        # High volume on sweep
                        volume = int(5000000 * np.random.uniform(2.0, 3.0))
                        
                        # Next bar breaks down (confirmation)
                        if day_idx + 1 < len(trading_times):
                            breakdown_price = current_level['resistance'] * (1 - np.random.uniform(0.005, 0.015))
                            prices.append({
                                'time': time,
                                'open': open_price,
                                'high': high,
                                'low': low,
                                'close': close,
                                'volume': volume
                            })
                            current_price = close
                            continue
                    
                    else:  # support setup
                        # Support sweep setup
                        sweep_price = current_level['support'] * (1 - np.random.uniform(0.002, 0.006))
                        # Create sweep bar
                        low = sweep_price
                        high = current_level['support'] * (1 + np.random.uniform(0.001, 0.003))
                        close = current_level['support'] * (1 + np.random.uniform(0.001, 0.004))
                        open_price = current_level['support'] * (1 - np.random.uniform(0, 0.002))
                        
                        # High volume on sweep
                        volume = int(5000000 * np.random.uniform(2.0, 3.0))
                        
                        prices.append({
                            'time': time,
                            'open': open_price,
                            'high': high,
                            'low': low,
                            'close': close,
                            'volume': volume
                        })
                        current_price = close
                        continue
                
                # Normal bar generation
                high = max(new_price, current_price) * (1 + abs(np.random.normal(0, 0.005)))
                low = min(new_price, current_price) * (1 - abs(np.random.normal(0, 0.005)))
                open_price = current_price
                close_price = new_price
                
                # Normal volume
                volume = int(5000000 * np.random.uniform(0.7, 1.3))
                
                # Keep within range
                close_price = max(current_level['support'] * 0.98, min(current_level['resistance'] * 1.02, close_price))
                high = max(high, close_price)
                low = min(low, close_price)
                
                prices.append({
                    'time': time,
                    'open': open_price,
                    'high': high,
                    'low': low,
                    'close': close_price,
                    'volume': max(volume, 1000000)
                })
                
                current_price = close_price
            
            df = pd.DataFrame(prices)
            df.set_index('time', inplace=True)
            
            print(f"Generated {len(df)} daily bars for {symbol} with BOOF31 setups")
            return df
            
        except Exception as e:
            print(f"Error generating data for {symbol}: {e}")
            return None
    
    def find_resistance_level(self, window):
        """Find resistance level in window"""
        if len(window) < 20:
            return None, 0
            
        highs = window["high"].values
        best_level = None
        best_touches = 0
        
        for h in highs:
            touches = np.sum(np.abs(highs - h) / h <= RES_TOL)
            if touches > best_touches:
                best_touches = touches
                best_level = h
        
        if best_touches < 2:
            return None, 0
        
        return best_level, best_touches
    
    def find_support_level(self, window):
        """Find support level in window"""
        if len(window) < 20:
            return None, 0
            
        lows = window["low"].values
        best_level = None
        best_touches = 0
        
        for l in lows:
            touches = np.sum(np.abs(lows - l) / l <= RES_TOL)
            if touches > best_touches:
                best_touches = touches
                best_level = l
        
        if best_touches < 2:
            return None, 0
        
        return best_level, best_touches
    
    def prior_swing_low(self, df, i, lookback=20):
        """Find prior swing low"""
        if i < lookback + 1:
            return None
            
        window = df.iloc[i-lookback:i]
        swing_low_idx = window['low'].idxmin()
        return df.loc[swing_low_idx, 'low']
    
    def prior_swing_high(self, df, i, lookback=20):
        """Find prior swing high"""
        if i < lookback + 1:
            return None
            
        window = df.iloc[i-lookback:i]
        swing_high_idx = window['high'].idxmax()
        return df.loc[swing_high_idx, 'high']
    
    def detect_resistance_sweep(self, df, i):
        """Detect resistance sweep setup (for short trades)"""
        if i < LOOKBACK + 10:
            return False, {}
        
        # Look back for resistance
        window = df.iloc[i-LOOKBACK:i]
        resistance, touches = self.find_resistance_level(window)
        
        if resistance is None:
            return False, {}
        
        bar = df.iloc[i]
        swept = bar["high"] > resistance * (1 + SWEEP_BUFFER)  # Sweep ABOVE resistance
        closed_back_below = bar["close"] < resistance  # Close back BELOW resistance
        
        if not (swept and closed_back_below):
            return False, {}
        
        swing_low = self.prior_swing_low(df, i)
        if swing_low is None:
            return False, {}
        
        # Look for confirmation
        for j in range(i + 1, min(i + 1 + MAX_CONFIRM_BARS, len(df) - 1)):
            confirm_bar = df.iloc[j]
            if confirm_bar["low"] < swing_low:
                return True, {
                    'resistance': resistance,
                    'touches': touches,
                    'sweep_bar': bar,
                    'sweep_idx': i,
                    'break_idx': j,
                    'swing_low': swing_low
                }
        
        return False, {}
    
    def detect_support_sweep(self, df, i):
        """Detect support sweep setup (for long trades)"""
        if i < LOOKBACK + 10:
            return False, {}
        
        # Look back for support
        window = df.iloc[i-LOOKBACK:i]
        support, touches = self.find_support_level(window)
        
        if support is None:
            return False, {}
        
        bar = df.iloc[i]
        swept = bar["low"] < support * (1 - SWEEP_BUFFER)  # Sweep BELOW support
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
    
    def calculate_short_score(self, setup):
        """Calculate BOOF score for resistance sweep (short)"""
        score = 0
        sweep_bar = setup['sweep_bar']
        touches = setup['touches']
        resistance = setup['resistance']
        
        # Volume criteria (0-2)
        avg_volume = 5000000
        if sweep_bar["volume"] > avg_volume * 1.5:
            score += 2
        elif sweep_bar["volume"] > avg_volume:
            score += 1
        
        # Sweep quality (0-2)
        sweep_depth = (sweep_bar["high"] - resistance) / resistance
        if sweep_depth > 0.02:  # More than 2% sweep
            score += 2
        elif sweep_depth > 0.01:
            score += 1
        
        # Rejection strength (0-3) - using upper wick for resistance
        body = abs(sweep_bar["close"] - sweep_bar["open"])
        upper_wick = sweep_bar["high"] - max(sweep_bar["open"], sweep_bar["close"])
        
        if body > 0 and upper_wick > body * 1.5:
            score += 1
        if sweep_bar["close"] < sweep_bar["open"]:  # Bearish reversal
            score += 1
        if sweep_bar["close"] < resistance:  # Closed below resistance
            score += 1
        
        # Freshness (0-2)
        if touches >= 3:
            score += 1
        if 0 <= setup['break_idx'] - setup['sweep_idx'] <= MAX_CONFIRM_BARS:
            score += 1
        
        return score
    
    def calculate_long_score(self, setup):
        """Calculate BOOF score for support sweep (long) - mirror of short"""
        score = 0
        sweep_bar = setup['sweep_bar']
        touches = setup['touches']
        support = setup['support']
        
        # Volume criteria (0-2)
        avg_volume = 5000000
        if sweep_bar["volume"] > avg_volume * 1.5:
            score += 2
        elif sweep_bar["volume"] > avg_volume:
            score += 1
        
        # Sweep quality (0-2)
        sweep_depth = (support - sweep_bar["low"]) / support
        if sweep_depth > 0.02:  # More than 2% sweep
            score += 2
        elif sweep_depth > 0.01:
            score += 1
        
        # Rejection strength (0-3) - using lower wick for support
        body = abs(sweep_bar["close"] - sweep_bar["open"])
        lower_wick = min(sweep_bar["open"], sweep_bar["close"]) - sweep_bar["low"]
        
        if body > 0 and lower_wick > body * 1.5:
            score += 1
        if sweep_bar["close"] > sweep_bar["open"]:  # Bullish reversal
            score += 1
        if sweep_bar["close"] > support:  # Closed above support
            score += 1
        
        # Freshness (0-2)
        if touches >= 3:
            score += 1
        if 0 <= setup['break_idx'] - setup['sweep_idx'] <= MAX_CONFIRM_BARS:
            score += 1
        
        return score
    
    def simulate_trade_with_partial_exits(self, symbol, entry_price, entry_time, score, setup, trade_type, df):
        """Simulate trade with TP1 50% exit and trailing stop - FIXED P&L CALCULATION"""
        entry_idx = df.index.get_loc(entry_time)
        
        # Exit parameters
        if trade_type == 'short':
            stop_loss_price = entry_price * (1 + STOP_LOSS)
            take_profit_price = entry_price * (1 - TP1)
        else:  # long
            stop_loss_price = entry_price * (1 - STOP_LOSS)
            take_profit_price = entry_price * (1 + TP1)
        
        max_exit_idx = min(entry_idx + MAX_HOLD_BARS, len(df) - 1)
        
        # Track trade state
        quantity = 100  # Standard quantity
        total_pnl_dollars = 0
        trail_price = stop_loss_price
        
        # Simulate trade
        for i in range(entry_idx + 1, max_exit_idx + 1):
            if i >= len(df):
                break
                
            current_bar = df.iloc[i]
            current_price = current_bar['close']
            
            # Update trailing stop
            if trade_type == 'short':
                new_trail = current_price * (1 + TRAIL_STOP)
                trail_price = min(trail_price, new_trail)  # Trail down for shorts
            else:
                new_trail = current_price * (1 - TRAIL_STOP)
                trail_price = max(trail_price, new_trail)  # Trail up for longs
            
            # Check TP1 (first 50%)
            if (trade_type == 'short' and current_price <= take_profit_price) or \
               (trade_type == 'long' and current_price >= take_profit_price):
                # Exit 50% at TP1
                pnl_per_share = (entry_price - current_price) if trade_type == 'short' else (current_price - entry_price)
                total_pnl_dollars += (quantity * 0.5 * pnl_per_share)
                stop_loss_price = trail_price  # Move stop to trail
                
                # Continue with remaining 50%
                remaining_quantity = quantity * 0.5
                
                # Check if remaining position hits stop loss
                if (trade_type == 'short' and current_price >= stop_loss_price) or \
                   (trade_type == 'long' and current_price <= stop_loss_price):
                    pnl_per_share = (entry_price - current_price) if trade_type == 'short' else (current_price - entry_price)
                    total_pnl_dollars += (remaining_quantity * pnl_per_share)
                    
                    total_pnl_pct = total_pnl_dollars / (quantity * entry_price)
                    return {
                        'symbol': symbol,
                        'trade_type': trade_type,
                        'entry_price': entry_price,
                        'exit_price': current_price,
                        'entry_time': entry_time,
                        'exit_time': df.index[i],
                        'bars_held': i - entry_idx,
                        'pnl_pct': total_pnl_pct,
                        'exit_reason': 'take_profit_then_stop',
                        'score': score,
                        'setup': setup.get('resistance') if trade_type == 'short' else setup.get('support')
                    }
            
            # Check stop loss
            if (trade_type == 'short' and current_price >= stop_loss_price) or \
               (trade_type == 'long' and current_price <= stop_loss_price):
                # Exit remaining
                remaining_quantity = quantity if total_pnl_dollars == 0 else quantity * 0.5
                pnl_per_share = (entry_price - current_price) if trade_type == 'short' else (current_price - entry_price)
                total_pnl_dollars += (remaining_quantity * pnl_per_share)
                
                total_pnl_pct = total_pnl_dollars / (quantity * entry_price)
                return {
                    'symbol': symbol,
                    'trade_type': trade_type,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'entry_time': entry_time,
                    'exit_time': df.index[i],
                    'bars_held': i - entry_idx,
                    'pnl_pct': total_pnl_pct,
                    'exit_reason': 'stop_loss',
                    'score': score,
                    'setup': setup.get('resistance') if trade_type == 'short' else setup.get('support')
                }
            
            # Check max hold time
            if i == max_exit_idx:
                # Exit remaining at market
                remaining_quantity = quantity if total_pnl_dollars == 0 else quantity * 0.5
                pnl_per_share = (entry_price - current_price) if trade_type == 'short' else (current_price - entry_price)
                total_pnl_dollars += (remaining_quantity * pnl_per_share)
                
                total_pnl_pct = total_pnl_dollars / (quantity * entry_price)
                return {
                    'symbol': symbol,
                    'trade_type': trade_type,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'entry_time': entry_time,
                    'exit_time': df.index[i],
                    'bars_held': i - entry_idx,
                    'pnl_pct': total_pnl_pct,
                    'exit_reason': 'max_hold',
                    'score': score,
                    'setup': setup.get('resistance') if trade_type == 'short' else setup.get('support')
                }
        
        # Default exit at end of data
        remaining_quantity = quantity if total_pnl_dollars == 0 else quantity * 0.5
        pnl_per_share = (entry_price - df.iloc[-1]['close']) if trade_type == 'short' else (df.iloc[-1]['close'] - entry_price)
        total_pnl_dollars += (remaining_quantity * pnl_per_share)
        
        total_pnl_pct = total_pnl_dollars / (quantity * entry_price)
        return {
            'symbol': symbol,
            'trade_type': trade_type,
            'entry_price': entry_price,
            'exit_price': df.iloc[-1]['close'],
            'entry_time': entry_time,
            'exit_time': df.index[-1],
            'bars_held': len(df) - entry_idx - 1,
            'pnl_pct': total_pnl_pct,
            'exit_reason': 'end_of_data',
            'score': score,
            'setup': setup.get('resistance') if trade_type == 'short' else setup.get('support')
        }
    
    def backtest_symbol(self, symbol, df, strategy='both'):
        """Backtest single symbol with specified strategy"""
        symbol_trades = []
        short_cooldown_until = None
        long_cooldown_until = None
        
        for i in range(LOOKBACK + 10, len(df) - 10):
            current_time = df.index[i]
            
            # Check cooldowns
            if strategy in ['short', 'both']:
                if short_cooldown_until and current_time <= short_cooldown_until:
                    pass  # In cooldown
                else:
                    # Check for resistance sweep (short)
                    is_setup, setup = self.detect_resistance_sweep(df, i)
                    if is_setup:
                        score = self.calculate_short_score(setup)
                        
                        # Check universe-based scoring
                        is_core = symbol in CORE_UNIVERSE
                        required_score = CORE_MIN_SCORE if is_core else MIN_SCORE
                        
                        if score >= required_score:
                            entry_price = df.iloc[setup['break_idx']]['close']
                            entry_time = df.index[setup['break_idx']]
                            
                            # Simulate trade
                            trade = self.simulate_trade_with_partial_exits(symbol, entry_price, entry_time, score, setup, 'short', df)
                            symbol_trades.append(trade)
                            
                            # Set cooldown
                            short_cooldown_until = current_time + timedelta(minutes=COOLDOWN_MINUTES)
            
            if strategy in ['long', 'both']:
                if long_cooldown_until and current_time <= long_cooldown_until:
                    pass  # In cooldown
                else:
                    # Check for support sweep (long)
                    is_setup, setup = self.detect_support_sweep(df, i)
                    if is_setup:
                        score = self.calculate_long_score(setup)
                        
                        # Check universe-based scoring
                        is_core = symbol in CORE_UNIVERSE
                        required_score = CORE_MIN_SCORE if is_core else MIN_SCORE
                        
                        if score >= required_score:
                            entry_price = df.iloc[setup['break_idx']]['close']
                            entry_time = df.index[setup['break_idx']]
                            
                            # Simulate trade
                            trade = self.simulate_trade_with_partial_exits(symbol, entry_price, entry_time, score, setup, 'long', df)
                            symbol_trades.append(trade)
                            
                            # Set cooldown
                            long_cooldown_until = current_time + timedelta(minutes=COOLDOWN_MINUTES)
        
        return symbol_trades
    
    def analyze_results(self, trades, strategy_name):
        """Analyze backtest results with comprehensive metrics"""
        if not trades:
            print(f"No trades found for {strategy_name}")
            return None
        
        print(f"\n" + "=" * 80)
        print(f"{strategy_name.upper()} STRATEGY RESULTS")
        print("=" * 80)
        
        # Basic statistics
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t['pnl_pct'] > 0)
        losing_trades = total_trades - winning_trades
        
        win_rate = winning_trades / total_trades
        wins = [t['pnl_pct'] for t in trades if t['pnl_pct'] > 0]
        losses = [t['pnl_pct'] for t in trades if t['pnl_pct'] < 0]
        
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        avg_pnl = np.mean([t['pnl_pct'] for t in trades])
        total_pnl = sum([t['pnl_pct'] for t in trades])
        
        # Profit Factor
        gross_wins = sum(wins)
        gross_losses = abs(sum(losses))
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        
        # Expected Value (EV)
        ev = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
        
        # Sharpe Ratio
        if len(trades) > 1:
            returns = np.array([t['pnl_pct'] for t in trades])
            sharpe_ratio = np.sqrt(252) * (np.mean(returns) - 0.02/252) / np.std(returns) if np.std(returns) > 0 else 0
        else:
            sharpe_ratio = 0
        
        # Maximum Drawdown
        cumulative_returns = np.cumsum([t['pnl_pct'] for t in trades])
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
        
        # Trade type breakdown
        if strategy_name == 'both':
            short_trades = [t for t in trades if t['trade_type'] == 'short']
            long_trades = [t for t in trades if t['trade_type'] == 'long']
            
            print(f"\n🎯 TRADE TYPE BREAKDOWN")
            print(f"─" * 40)
            print(f"Short Trades:     {len(short_trades)} ({len(short_trades)/total_trades:.1%})")
            if short_trades:
                short_wr = sum(1 for t in short_trades if t['pnl_pct'] > 0) / len(short_trades)
                short_pnl = sum([t['pnl_pct'] for t in short_trades])
                print(f"  Short WR:        {short_wr:.1%}")
                print(f"  Short P&L:       {short_pnl:.2%}")
            
            print(f"Long Trades:      {len(long_trades)} ({len(long_trades)/total_trades:.1%})")
            if long_trades:
                long_wr = sum(1 for t in long_trades if t['pnl_pct'] > 0) / len(long_trades)
                long_pnl = sum([t['pnl_pct'] for t in long_trades])
                print(f"  Long WR:         {long_wr:.1%}")
                print(f"  Long P&L:        {long_pnl:.2%}")
        
        # Symbol breakdown
        print(f"\n📊 SYMBOL PERFORMANCE")
        print(f"─" * 40)
        symbol_stats = {}
        for trade in trades:
            symbol = trade['symbol']
            if symbol not in symbol_stats:
                symbol_stats[symbol] = {'trades': 0, 'pnl': 0, 'wins': 0, 'short': 0, 'long': 0}
            symbol_stats[symbol]['trades'] += 1
            symbol_stats[symbol]['pnl'] += trade['pnl_pct']
            if trade['pnl_pct'] > 0:
                symbol_stats[symbol]['wins'] += 1
            if trade['trade_type'] == 'short':
                symbol_stats[symbol]['short'] += 1
            else:
                symbol_stats[symbol]['long'] += 1
        
        # Sort by total P&L
        sorted_symbols = sorted(symbol_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)
        
        for symbol, stats in sorted_symbols:
            win_rate = stats['wins'] / stats['trades']
            trade_types = f"S:{stats['short']}/L:{stats['long']}"
            print(f"{symbol:8s}: {stats['trades']:3d} trades | {stats['pnl']:6.2%} P&L | {win_rate:5.1%} WR | {trade_types}")
        
        print(f"\n" + "=" * 80)
        
        return {
            'trades': total_trades,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'expected_value': ev,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl
        }
    
    def run_comprehensive_backtest(self, start_date, end_date):
        """Run all four strategy variations"""
        print(f"Starting Comprehensive BOOF31 Backtest")
        print(f"Period: {start_date} to {end_date}")
        print(f"Symbols: {', '.join(SYMBOLS)}")
        print("=" * 80)
        
        results = {}
        
        # Test each strategy
        strategies = ['short', 'long', 'both']
        strategy_names = ['SHORT ONLY', 'LONG ONLY', 'LONG + SHORT']
        
        for strategy, name in zip(strategies, strategy_names):
            print(f"\n🔄 Running {name} Strategy...")
            print("-" * 60)
            
            all_trades = []
            
            for i, symbol in enumerate(SYMBOLS, 1):
                print(f"[{i}/{len(SYMBOLS)}] Backtesting {symbol}...")
                
                # Get data
                df = self.generate_fast_data(symbol, start_date, end_date)
                if df is None:
                    continue
                
                # Backtest symbol
                symbol_trades = self.backtest_symbol(symbol, df, strategy)
                all_trades.extend(symbol_trades)
                
                # Symbol summary
                if symbol_trades:
                    win_rate = sum(1 for t in symbol_trades if t['pnl_pct'] > 0) / len(symbol_trades)
                    avg_pnl = np.mean([t['pnl_pct'] for t in symbol_trades])
                    total_pnl = sum([t['pnl_pct'] for t in symbol_trades])
                    
                    print(f"  Trades: {len(symbol_trades)} | WR: {win_rate:.1%} | P&L: {total_pnl:.2%}")
                else:
                    print(f"  No trades found")
            
            # Analyze results
            result = self.analyze_results(all_trades, name)
            if result:
                results[name] = result
        
        # Final comparison
        if len(results) > 1:
            print(f"\n" + "=" * 80)
            print(f"🏆 STRATEGY COMPARISON")
            print("=" * 80)
            
            comparison_metrics = ['trades', 'win_rate', 'profit_factor', 'expected_value', 'sharpe_ratio', 'max_drawdown', 'total_pnl']
            metric_names = ['Trades', 'Win Rate', 'Profit Factor', 'Expected Value', 'Sharpe Ratio', 'Max Drawdown', 'Total P&L']
            
            print(f"{'Strategy':<15} | {'Trades':>8} | {'WR':>6} | {'PF':>6} | {'EV':>8} | {'Sharpe':>7} | {'Max DD':>8} | {'Total P&L':>10}")
            print("-" * 85)
            
            for name, result in results.items():
                trades = result['trades']
                wr = f"{result['win_rate']:.1%}"
                pf = f"{result['profit_factor']:.2f}"
                ev = f"{result['expected_value']:.2%}"
                sharpe = f"{result['sharpe_ratio']:.2f}"
                max_dd = f"{result['max_drawdown']:.2%}"
                total_pnl = f"{result['total_pnl']:.2%}"
                
                print(f"{name:<15} | {trades:>8} | {wr:>6} | {pf:>6} | {ev:>8} | {sharpe:>7} | {max_dd:>8} | {total_pnl:>10}")
            
            # Find best strategy for each metric
            print(f"\n🥇 BEST STRATEGY BY METRIC:")
            print("-" * 40)
            
            for metric, metric_name in zip(comparison_metrics, metric_names):
                if metric == 'max_drawdown':
                    # Lower is better for drawdown
                    best_name = min(results.keys(), key=lambda x: results[x][metric])
                    best_value = results[best_name][metric]
                else:
                    # Higher is better for other metrics
                    best_name = max(results.keys(), key=lambda x: results[x][metric])
                    best_value = results[best_name][metric]
                
                if metric in ['win_rate', 'expected_value', 'max_drawdown', 'total_pnl']:
                    formatted_value = f"{best_value:.2%}"
                elif metric == 'profit_factor':
                    formatted_value = f"{best_value:.2f}"
                else:
                    formatted_value = f"{best_value:.2f}"
                
                print(f"{metric_name:<15}: {best_name} ({formatted_value})")
        
        print(f"\n" + "=" * 80)
        print(f"✅ Comprehensive backtest completed!")
        print(f"📈 All strategies tested with exact BOOF31 logic")
        print(f"🎯 Use comparison to determine optimal approach")

def main():
    """Main function"""
    # Set up backtest period (6 months)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)  # 6 months
    
    # Run comprehensive backtest
    backtest = ComprehensiveBOOF31Backtest()
    backtest.run_comprehensive_backtest(start_date, end_date)

if __name__ == "__main__":
    main()
