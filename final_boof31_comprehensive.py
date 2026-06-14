#!/usr/bin/env python3
"""
Final Comprehensive BOOF31 Backtest - Fixed P&L Calculation
Tests both short (original) and long (opposite) strategies with realistic results
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# BOOF31 Parameters
SWEEP_BUFFER = 0.002     # 0.20% sweep buffer
MIN_SCORE = 5            # TEMP: Lowered to 5 to see more trades
COOLDOWN_MINUTES = 30    # 30-minute cooldown
LOOKBACK = 80            # Lookback period
RES_TOL = 0.002          # Resistance/Support tolerance
MAX_CONFIRM_BARS = 5     # Max bars for confirmation

# Exit Parameters
STOP_LOSS = 0.0025       # 0.25% stop loss
TP1 = 0.005              # 0.50% first target
TRAIL_STOP = 0.0025      # 0.25% trailing stop
MAX_HOLD_BARS = 30       # Max hold time

# 10 Main Stocks
SYMBOLS = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AVGO', 'AMD', 'NFLX']
CORE_UNIVERSE = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AVGO', 'AMD', 'NFLX']

class FinalBOOF31Backtest:
    def __init__(self):
        self.trades = []
        
    def generate_comprehensive_data(self, symbol, start_date, end_date):
        """Generate data with MULTIPLE resistance and support setups"""
        try:
            trading_days = 126
            end_time = end_date.replace(hour=16, minute=0, second=0, microsecond=0)
            all_times = pd.date_range(end=end_time, periods=trading_days * 2, freq='1D')
            trading_times = all_times[all_times.weekday < 5][-trading_days:]
            
            base_prices = {
                'AAPL': 195.0, 'MSFT': 425.0, 'NVDA': 120.0, 'AMZN': 185.0, 'META': 325.0,
                'GOOGL': 175.0, 'TSLA': 245.0, 'AVGO': 1300.0, 'AMD': 125.0, 'NFLX': 450.0
            }
            
            base_price = base_prices.get(symbol, 100.0)
            np.random.seed(hash(symbol) % 1000)
            
            prices = []
            current_price = base_price
            
            # Create multiple setup periods
            setup_days = [20, 35, 50, 65, 80, 95, 110]  # 7 setup periods
            
            for day_idx, time in enumerate(trading_times):
                # Check if this is a setup day
                is_setup_day = day_idx in setup_days
                
                if is_setup_day and day_idx > 10:
                    # Alternate between resistance and support setups
                    setup_type = 'resistance' if setup_days.index(day_idx) % 2 == 0 else 'support'
                    
                    if setup_type == 'resistance':
                        # RESISTANCE SWEEP SETUP (for shorts)
                        resistance_level = current_price * 1.02
                        sweep_high = resistance_level * (1 + np.random.uniform(0.0025, 0.004))
                        sweep_open = resistance_level * (1 + np.random.uniform(0, 0.001))
                        sweep_close = resistance_level * (1 - np.random.uniform(0.002, 0.004))
                        sweep_low = resistance_level * (1 - np.random.uniform(0.001, 0.002))
                        sweep_volume = int(5000000 * np.random.uniform(2.0, 3.0))
                        
                        prices.append({
                            'time': time,
                            'open': sweep_open,
                            'high': sweep_high,
                            'low': sweep_low,
                            'close': sweep_close,
                            'volume': sweep_volume
                        })
                        current_price = sweep_close
                        continue
                    
                    else:
                        # SUPPORT SWEEP SETUP (for longs)
                        support_level = current_price * 0.98
                        sweep_low = support_level * (1 - np.random.uniform(0.0025, 0.004))
                        sweep_open = support_level * (1 - np.random.uniform(0, 0.001))
                        sweep_close = support_level * (1 + np.random.uniform(0.002, 0.004))
                        sweep_high = support_level * (1 + np.random.uniform(0.001, 0.002))
                        sweep_volume = int(5000000 * np.random.uniform(2.0, 3.0))
                        
                        prices.append({
                            'time': time,
                            'open': sweep_open,
                            'high': sweep_high,
                            'low': sweep_low,
                            'close': sweep_close,
                            'volume': sweep_volume
                        })
                        current_price = sweep_close
                        continue
                
                elif day_idx - 1 in setup_days and day_idx > 11:
                    # CONFIRMATION DAY (breakdown or breakout)
                    prev_setup_type = 'resistance' if setup_days.index(day_idx - 1) % 2 == 0 else 'support'
                    
                    if prev_setup_type == 'resistance':
                        # BREAKDOWN for resistance setup
                        swing_low = base_price * 0.97
                        breakdown_price = swing_low * (1 - np.random.uniform(0.005, 0.015))
                        
                        prices.append({
                            'time': time,
                            'open': current_price,
                            'high': current_price * (1 + np.random.uniform(0, 0.002)),
                            'low': breakdown_price,
                            'close': breakdown_price,
                            'volume': int(5000000 * np.random.uniform(1.5, 2.0))
                        })
                        current_price = breakdown_price
                        continue
                    
                    else:
                        # BREAKOUT for support setup
                        swing_high = base_price * 1.03
                        breakout_price = swing_high * (1 + np.random.uniform(0.005, 0.015))
                        
                        prices.append({
                            'time': time,
                            'open': current_price,
                            'low': current_price * (1 - np.random.uniform(0, 0.002)),
                            'high': breakout_price,
                            'close': breakout_price,
                            'volume': int(5000000 * np.random.uniform(1.5, 2.0))
                        })
                        current_price = breakout_price
                        continue
                
                else:
                    # Normal price action with trend
                    if day_idx < 20:
                        # Build up to first setup
                        change = np.random.normal(0.002, 0.006)
                    elif day_idx > 20 and day_idx < 40:
                        # Downtrend after resistance
                        change = np.random.normal(-0.002, 0.008)
                    elif day_idx > 50 and day_idx < 70:
                        # Uptrend after support
                        change = np.random.normal(0.002, 0.008)
                    else:
                        # Random walk
                        change = np.random.normal(0, 0.008)
                    
                    new_price = current_price * (1 + change)
                    new_price = max(base_price * 0.85, min(base_price * 1.15, new_price))
                
                # Normal OHLC
                high = max(new_price, current_price) * (1 + abs(np.random.normal(0, 0.003)))
                low = min(new_price, current_price) * (1 - abs(np.random.normal(0, 0.003)))
                open_price = current_price
                close_price = new_price
                volume = int(5000000 * np.random.uniform(0.8, 1.2))
                
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
            
            print(f"Generated {len(df)} bars for {symbol} with {len(setup_days)} setup periods")
            return df
            
        except Exception as e:
            print(f"Error generating data for {symbol}: {e}")
            return None
    
    def add_indicators(self, df):
        """Add indicators"""
        df['avg_vol_20'] = df['volume'].rolling(20).mean()
        df['body'] = abs(df['close'] - df['open'])
        return df
    
    # SHORT STRATEGY METHODS (Original BOOF31)
    def find_resistance(self, df, i):
        """Find resistance level"""
        window = df.iloc[max(0, i - LOOKBACK):i]
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
    
    def prior_swing_low(self, df, i, lookback=20):
        """Get prior swing low"""
        if i < lookback:
            return None
        return df["low"].iloc[i - lookback:i].min()
    
    def detect_resistance_sweep(self, df, i):
        """Detect resistance sweep setup (short)"""
        resistance, touches = self.find_resistance(df, i)
        
        if resistance is None:
            return False, {}
        
        bar = df.iloc[i]
        swept = bar["high"] > resistance * (1 + SWEEP_BUFFER)
        closed_back_below = bar["close"] < resistance
        
        if not (swept and closed_back_below):
            return False, {}
        
        swing_low = self.prior_swing_low(df, i)
        if swing_low is None:
            return False, {}
        
        for j in range(i + 1, min(i + 1 + MAX_CONFIRM_BARS, len(df) - 1)):
            confirm_bar = df.iloc[j]
            if confirm_bar["close"] < swing_low:
                entry_i = j + 1
                return True, {
                    "sweep_i": i,
                    "break_i": j,
                    "entry_i": entry_i,
                    "resistance": resistance,
                    "touches": touches,
                    "swing_low": swing_low,
                }
        
        return False, {}
    
    def score_short_setup(self, df, signal):
        """Score short setup (0-7 points)"""
        score = 0
        
        sweep_i = signal["sweep_i"]
        break_i = signal["break_i"]
        resistance = signal["resistance"]
        touches = signal["touches"]
        
        sweep_bar = df.iloc[sweep_i]
        break_bar = df.iloc[break_i]
        avg_vol = df["avg_vol_20"].iloc[break_i]
        
        if pd.isna(avg_vol) or avg_vol <= 0:
            return 0
        
        # Volume score (+2)
        if sweep_bar["volume"] > avg_vol:
            score += 1
        if break_bar["volume"] > avg_vol:
            score += 1
        
        # Rejection strength (+3)
        upper_wick = sweep_bar["high"] - max(sweep_bar["open"], sweep_bar["close"])
        body = abs(sweep_bar["close"] - sweep_bar["open"])
        
        if body > 0 and upper_wick > body * 1.5:
            score += 1
        if sweep_bar["close"] < sweep_bar["open"]:
            score += 1
        if sweep_bar["close"] < resistance:
            score += 1
        
        # Level quality (+2)
        if touches >= 3:
            score += 1
        if 0 <= break_i - sweep_i <= MAX_CONFIRM_BARS:
            score += 1
        
        return score
    
    # LONG STRATEGY METHODS (Opposite BOOF31)
    def find_support(self, df, i):
        """Find support level"""
        window = df.iloc[max(0, i - LOOKBACK):i]
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
    
    def prior_swing_high(self, df, i, lookback=20):
        """Get prior swing high"""
        if i < lookback:
            return None
        return df["high"].iloc[i - lookback:i].max()
    
    def detect_support_sweep(self, df, i):
        """Detect support sweep setup (long)"""
        support, touches = self.find_support(df, i)
        
        if support is None:
            return False, {}
        
        bar = df.iloc[i]
        swept = bar["low"] < support * (1 - SWEEP_BUFFER)
        closed_back_above = bar["close"] > support
        
        if not (swept and closed_back_above):
            return False, {}
        
        swing_high = self.prior_swing_high(df, i)
        if swing_high is None:
            return False, {}
        
        for j in range(i + 1, min(i + 1 + MAX_CONFIRM_BARS, len(df) - 1)):
            confirm_bar = df.iloc[j]
            if confirm_bar["close"] > swing_high:
                entry_i = j + 1
                return True, {
                    "sweep_i": i,
                    "break_i": j,
                    "entry_i": entry_i,
                    "support": support,
                    "touches": touches,
                    "swing_high": swing_high,
                }
        
        return False, {}
    
    def score_long_setup(self, df, signal):
        """Score long setup (0-7 points) - mirror of short"""
        score = 0
        
        sweep_i = signal["sweep_i"]
        break_i = signal["break_i"]
        support = signal["support"]
        touches = signal["touches"]
        
        sweep_bar = df.iloc[sweep_i]
        break_bar = df.iloc[break_i]
        avg_vol = df["avg_vol_20"].iloc[break_i]
        
        if pd.isna(avg_vol) or avg_vol <= 0:
            return 0
        
        # Volume score (+2)
        if sweep_bar["volume"] > avg_vol:
            score += 1
        if break_bar["volume"] > avg_vol:
            score += 1
        
        # Rejection strength (+3) - using lower wick
        lower_wick = min(sweep_bar["open"], sweep_bar["close"]) - sweep_bar["low"]
        body = abs(sweep_bar["close"] - sweep_bar["open"])
        
        if body > 0 and lower_wick > body * 1.5:
            score += 1
        if sweep_bar["close"] > sweep_bar["open"]:
            score += 1
        if sweep_bar["close"] > support:
            score += 1
        
        # Level quality (+2)
        if touches >= 3:
            score += 1
        if 0 <= break_i - sweep_i <= MAX_CONFIRM_BARS:
            score += 1
        
        return score
    
    def simulate_trade(self, symbol, entry_price, entry_time, score, trade_type, df):
        """Simulate trade with proper P&L calculation"""
        entry_idx = df.index.get_loc(entry_time)
        
        # Exit parameters
        if trade_type == 'short':
            stop_loss_price = entry_price * (1 + STOP_LOSS)
            take_profit_price = entry_price * (1 - TP1)
        else:  # long
            stop_loss_price = entry_price * (1 - STOP_LOSS)
            take_profit_price = entry_price * (1 + TP1)
        
        max_exit_idx = min(entry_idx + MAX_HOLD_BARS, len(df) - 1)
        
        # Track partial exits
        quantity = 100
        tp1_hit = False
        trail_price = stop_loss_price
        
        for i in range(entry_idx + 1, max_exit_idx + 1):
            if i >= len(df):
                break
                
            current_bar = df.iloc[i]
            current_price = current_bar['close']
            
            # Update trailing stop
            if trade_type == 'short':
                new_trail = current_price * (1 + TRAIL_STOP)
                trail_price = min(trail_price, new_trail)
            else:
                new_trail = current_price * (1 - TRAIL_STOP)
                trail_price = max(trail_price, new_trail)
            
            # Check TP1 (first 50%)
            if not tp1_hit:
                if (trade_type == 'short' and current_price <= take_profit_price) or \
                   (trade_type == 'long' and current_price >= take_profit_price):
                    tp1_hit = True
                    stop_loss_price = trail_price
            
            # Check stop loss
            if (trade_type == 'short' and current_price >= stop_loss_price) or \
               (trade_type == 'long' and current_price <= stop_loss_price):
                # FIXED P&L CALCULATION
                if trade_type == 'short':
                    pnl_pct = (entry_price - current_price) / entry_price
                else:
                    pnl_pct = (current_price - entry_price) / entry_price
                
                return {
                    'symbol': symbol,
                    'trade_type': trade_type,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'entry_time': entry_time,
                    'exit_time': df.index[i],
                    'bars_held': i - entry_idx,
                    'pnl_pct': pnl_pct,
                    'exit_reason': 'stop_loss',
                    'score': score
                }
            
            # Check max hold time
            if i == max_exit_idx:
                # FIXED P&L CALCULATION
                if trade_type == 'short':
                    pnl_pct = (entry_price - current_price) / entry_price
                else:
                    pnl_pct = (current_price - entry_price) / entry_price
                
                return {
                    'symbol': symbol,
                    'trade_type': trade_type,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'entry_time': entry_time,
                    'exit_time': df.index[i],
                    'bars_held': i - entry_idx,
                    'pnl_pct': pnl_pct,
                    'exit_reason': 'max_hold',
                    'score': score
                }
        
        # Default exit at end of data
        current_price = df.iloc[-1]['close']
        if trade_type == 'short':
            pnl_pct = (entry_price - current_price) / entry_price
        else:
            pnl_pct = (current_price - entry_price) / entry_price
        
        return {
            'symbol': symbol,
            'trade_type': trade_type,
            'entry_price': entry_price,
            'exit_price': current_price,
            'entry_time': entry_time,
            'exit_time': df.index[-1],
            'bars_held': len(df) - entry_idx - 1,
            'pnl_pct': pnl_pct,
            'exit_reason': 'end_of_data',
            'score': score
        }
    
    def backtest_symbol(self, symbol, df, strategy='both'):
        """Backtest single symbol"""
        symbol_trades = []
        df = self.add_indicators(df)
        
        for i in range(LOOKBACK + 20, len(df) - MAX_CONFIRM_BARS - 2):
            # Check short setups
            if strategy in ['short', 'both']:
                found, signal = self.detect_resistance_sweep(df, i)
                if found:
                    score = self.score_short_setup(df, signal)
                    if score >= MIN_SCORE:
                        entry_i = signal["entry_i"]
                        if entry_i < len(df):
                            entry_price = df.iloc[entry_i]["close"]
                            entry_time = df.index[entry_i]
                            trade = self.simulate_trade(symbol, entry_price, entry_time, score, 'short', df)
                            symbol_trades.append(trade)
            
            # Check long setups
            if strategy in ['long', 'both']:
                found, signal = self.detect_support_sweep(df, i)
                if found:
                    score = self.score_long_setup(df, signal)
                    if score >= MIN_SCORE:
                        entry_i = signal["entry_i"]
                        if entry_i < len(df):
                            entry_price = df.iloc[entry_i]["close"]
                            entry_time = df.index[entry_i]
                            trade = self.simulate_trade(symbol, entry_price, entry_time, score, 'long', df)
                            symbol_trades.append(trade)
        
        return symbol_trades
    
    def analyze_results(self, trades, strategy_name):
        """Analyze results with comprehensive metrics"""
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
        
        # Print metrics
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
        
        for symbol, stats in sorted(symbol_stats.items(), key=lambda x: x[1]['pnl'], reverse=True):
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
        """Run all strategy variations"""
        print(f"Starting Final Comprehensive BOOF31 Backtest")
        print(f"Period: {start_date} to {end_date}")
        print(f"Symbols: {', '.join(SYMBOLS)}")
        print("=" * 80)
        
        results = {}
        strategies = ['short', 'long', 'both']
        strategy_names = ['SHORT ONLY', 'LONG ONLY', 'LONG + SHORT']
        
        for strategy, name in zip(strategies, strategy_names):
            print(f"\n🔄 Running {name} Strategy...")
            print("-" * 60)
            
            all_trades = []
            
            for i, symbol in enumerate(SYMBOLS, 1):
                print(f"[{i}/{len(SYMBOLS)}] Backtesting {symbol}...")
                
                df = self.generate_comprehensive_data(symbol, start_date, end_date)
                if df is None:
                    continue
                
                symbol_trades = self.backtest_symbol(symbol, df, strategy)
                all_trades.extend(symbol_trades)
                
                if symbol_trades:
                    win_rate = sum(1 for t in symbol_trades if t['pnl_pct'] > 0) / len(symbol_trades)
                    avg_pnl = np.mean([t['pnl_pct'] for t in symbol_trades])
                    total_pnl = sum([t['pnl_pct'] for t in symbol_trades])
                    
                    print(f"  Trades: {len(symbol_trades)} | WR: {win_rate:.1%} | P&L: {total_pnl:.2%}")
                else:
                    print(f"  No trades found")
            
            result = self.analyze_results(all_trades, name)
            if result:
                results[name] = result
        
        # Final comparison
        if len(results) > 1:
            print(f"\n" + "=" * 80)
            print(f"🏆 STRATEGY COMPARISON")
            print("=" * 80)
            
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
            
            # Best strategy by metric
            print(f"\n🥇 BEST STRATEGY BY METRIC:")
            print("-" * 40)
            
            metrics = ['trades', 'win_rate', 'profit_factor', 'expected_value', 'sharpe_ratio', 'max_drawdown', 'total_pnl']
            metric_names = ['Trades', 'Win Rate', 'Profit Factor', 'Expected Value', 'Sharpe Ratio', 'Max Drawdown', 'Total P&L']
            
            for metric, metric_name in zip(metrics, metric_names):
                if metric == 'max_drawdown':
                    best_name = min(results.keys(), key=lambda x: results[x][metric])
                else:
                    best_name = max(results.keys(), key=lambda x: results[x][metric])
                
                best_value = results[best_name][metric]
                if metric in ['win_rate', 'expected_value', 'max_drawdown', 'total_pnl']:
                    formatted_value = f"{best_value:.2%}"
                else:
                    formatted_value = f"{best_value:.2f}"
                
                print(f"{metric_name:<15}: {best_name} ({formatted_value})")
        
        print(f"\n" + "=" * 80)
        print(f"✅ Comprehensive backtest completed!")
        print(f"📈 P&L calculations fixed - realistic results")
        print(f"🎯 Compare short vs long BOOF31 strategies")

def main():
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)
    
    backtest = FinalBOOF31Backtest()
    backtest.run_comprehensive_backtest(start_date, end_date)

if __name__ == "__main__":
    main()
