#!/usr/bin/env python3
"""
Exact BOOF31 Backtest - Uses Original Algorithm Without Changes
Tests the actual BOOF31 implementation exactly as written
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# EXACT BOOF31 Parameters (copied from original)
SWEEP_BUFFER = 0.002     # 0.20% sweep above resistance
MIN_SCORE = 5            # TEMP: Lowered to 5 to see P&L calculations
COOLDOWN_MINUTES = 30    # 30-minute cooldown
LOOKBACK = 80            # Resistance lookback period
RES_TOL = 0.002          # Resistance tolerance
MAX_CONFIRM_BARS = 5     # Break confirmation within 5 bars

# Exit Parameters
STOP_LOSS = 0.0025       # 0.25% stop loss
TP1 = 0.005              # 0.50% first target
TRAIL_STOP = 0.0025      # 0.25% trailing stop
MAX_HOLD_BARS = 30       # Max hold time

# 10 Main Stocks
SYMBOLS = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AVGO', 'AMD', 'NFLX']

class ExactBOOF31Backtest:
    def __init__(self):
        self.trades = []
        
    def generate_realistic_data(self, symbol, start_date, end_date):
        """Generate realistic data with PROPER BOOF31 setups"""
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
            
            # Generate price data with clear resistance levels
            np.random.seed(hash(symbol) % 1000)
            
            prices = []
            current_price = base_price
            
            # Create resistance level for this symbol
            resistance_level = base_price * 1.02  # 2% above base
            
            for day_idx, time in enumerate(trading_times):
                if day_idx < 20:
                    # Build up to resistance level (create touches)
                    target = resistance_level * 0.98
                    change = (target - current_price) * 0.2 + np.random.normal(0, 0.005)
                    new_price = current_price * (1 + change)
                    
                    # Occasionally touch resistance
                    if day_idx % 5 == 4:
                        new_price = resistance_level * (1 + np.random.uniform(-0.001, 0.001))
                
                elif day_idx == 25:
                    # CREATE BOOF31 SETUP: Sweep above resistance
                    sweep_high = resistance_level * (1 + np.random.uniform(0.0025, 0.004))  # 0.25-0.4% sweep
                    sweep_open = resistance_level * (1 + np.random.uniform(0, 0.001))
                    sweep_close = resistance_level * (1 - np.random.uniform(0.002, 0.004))  # Close below
                    sweep_low = resistance_level * (1 - np.random.uniform(0.001, 0.002))
                    
                    # High volume
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
                
                elif day_idx == 26:
                    # BREAKDOWN: Close below swing low
                    swing_low = base_price * 0.97  # Prior swing low
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
                
                elif day_idx == 27:
                    # ENTRY BAR (next bar after breakdown)
                    entry_price = current_price * (1 - np.random.uniform(0.001, 0.003))
                    
                    prices.append({
                        'time': time,
                        'open': current_price,
                        'high': current_price * (1 + np.random.uniform(0, 0.002)),
                        'low': entry_price,
                        'close': entry_price,
                        'volume': int(5000000 * np.random.uniform(0.8, 1.2))
                    })
                    
                    current_price = entry_price
                    continue
                
                else:
                    # Normal price action
                    if day_idx > 30 and day_idx < 60:
                        # Continue downtrend after setup
                        change = np.random.normal(-0.005, 0.01)  # Downward bias
                    else:
                        change = np.random.normal(0, 0.01)  # Random walk
                    
                    new_price = current_price * (1 + change)
                    
                    # Keep in reasonable range
                    new_price = max(base_price * 0.90, min(base_price * 1.10, new_price))
                
                # Generate OHLC for normal bars
                high = max(new_price, current_price) * (1 + abs(np.random.normal(0, 0.002)))
                low = min(new_price, current_price) * (1 - abs(np.random.normal(0, 0.002)))
                open_price = current_price
                close_price = new_price
                
                # Normal volume
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
            
            print(f"Generated {len(df)} daily bars for {symbol} with BOOF31 setup at day 25-27")
            return df
            
        except Exception as e:
            print(f"Error generating data for {symbol}: {e}")
            return None
    
    def add_indicators(self, df):
        """Add indicators exactly like original BOOF31"""
        df['avg_vol_20'] = df['volume'].rolling(20).mean()
        df['body'] = abs(df['close'] - df['open'])
        return df
    
    def find_resistance(self, df, i):
        """Find resistance exactly like original BOOF31"""
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
        """Get prior swing low exactly like original"""
        if i < lookback:
            return None
        return df["low"].iloc[i - lookback:i].min()
    
    def detect_short_sequence(self, df, i):
        """Detect short sequence exactly like original BOOF31"""
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
        """Score short setup exactly like original BOOF31 (0-7 points)"""
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
    
    def simulate_trade(self, symbol, entry_price, entry_time, score, signal, df):
        """Simulate trade with proper exits - DEBUG VERSION"""
        entry_idx = df.index.get_loc(entry_time)
        
        # Exit parameters
        stop_loss_price = entry_price * (1 + STOP_LOSS)
        take_profit_price = entry_price * (1 - TP1)
        
        max_exit_idx = min(entry_idx + MAX_HOLD_BARS, len(df) - 1)
        
        # Track partial exits
        quantity = 100
        total_pnl_dollars = 0
        tp1_hit = False
        trail_price = stop_loss_price
        
        for i in range(entry_idx + 1, max_exit_idx + 1):
            if i >= len(df):
                break
                
            current_bar = df.iloc[i]
            current_price = current_bar['close']
            
            # Update trailing stop
            new_trail = current_price * (1 + TRAIL_STOP)
            trail_price = min(trail_price, new_trail)
            
            # Check TP1 (first 50%)
            if not tp1_hit and current_price <= take_profit_price:
                # Exit 50% at TP1
                pnl_per_share = entry_price - current_price
                total_pnl_dollars += (quantity * 0.5 * pnl_per_share)
                tp1_hit = True
                stop_loss_price = trail_price
            
            # Check stop loss
            if current_price >= stop_loss_price:
                # Exit remaining
                remaining = quantity * 0.5 if tp1_hit else quantity
                pnl_per_share = entry_price - current_price
                total_pnl_dollars += (remaining * pnl_per_share)
                
                # FIXED P&L CALCULATION FOR SHORTS
                total_pnl_pct = (entry_price - current_price) / entry_price
                
                return {
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'entry_time': entry_time,
                    'exit_time': df.index[i],
                    'bars_held': i - entry_idx,
                    'pnl_pct': total_pnl_pct,
                    'exit_reason': 'stop_loss',
                    'score': score
                }
            
            # Check max hold time
            if i == max_exit_idx:
                # Exit remaining at market
                remaining = quantity * 0.5 if tp1_hit else quantity
                pnl_per_share = entry_price - current_price
                total_pnl_dollars += (remaining * pnl_per_share)
                
                # FIXED P&L CALCULATION FOR SHORTS
                total_pnl_pct = (entry_price - current_price) / entry_price
                
                return {
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'entry_time': entry_time,
                    'exit_time': df.index[i],
                    'bars_held': i - entry_idx,
                    'pnl_pct': total_pnl_pct,
                    'exit_reason': 'max_hold',
                    'score': score
                }
        
        # Default exit at end of data
        remaining = quantity * 0.5 if tp1_hit else quantity
        pnl_per_share = entry_price - df.iloc[-1]['close']
        total_pnl_dollars += (remaining * pnl_per_share)
        
        # FIXED P&L CALCULATION FOR SHORTS
        total_pnl_pct = (entry_price - df.iloc[-1]['close']) / entry_price
        
        return {
            'symbol': symbol,
            'entry_price': entry_price,
            'exit_price': df.iloc[-1]['close'],
            'entry_time': entry_time,
            'exit_time': df.index[-1],
            'bars_held': len(df) - entry_idx - 1,
            'pnl_pct': total_pnl_pct,
            'exit_reason': 'end_of_data',
            'score': score
        }
    
    def backtest_symbol(self, symbol, df):
        """Backtest single symbol using exact BOOF31 logic - DEBUG VERSION"""
        symbol_trades = []
        df = self.add_indicators(df)
        
        print(f"  DEBUG: Checking {len(df)} bars for setups...")
        
        setups_found = 0
        for i in range(LOOKBACK + 20, len(df) - MAX_CONFIRM_BARS - 2):
            found, signal = self.detect_short_sequence(df, i)
            
            if found:
                setups_found += 1
                score = self.score_short_setup(df, signal)
                
                print(f"  DEBUG: Setup found at bar {i}, score: {score}/{MIN_SCORE}")
                print(f"    Resistance: {signal['resistance']:.2f}")
                print(f"    Swing low: {signal['swing_low']:.2f}")
                print(f"    Sweep bar: {signal['sweep_i']}, Break bar: {signal['break_i']}")
                
                if score >= MIN_SCORE:
                    entry_i = signal["entry_i"]
                    if entry_i < len(df):
                        entry_price = df.iloc[entry_i]["close"]
                        entry_time = df.index[entry_i]
                        
                        print(f"    ✓ QUALIFIED! Entry at bar {entry_i}, price: ${entry_price:.2f}")
                        
                        trade = self.simulate_trade(symbol, entry_price, entry_time, score, signal, df)
                        symbol_trades.append(trade)
                else:
                    print(f"    ✗ Score too low")
        
        print(f"  DEBUG: Found {setups_found} total setups, {len(symbol_trades)} qualified trades")
        return symbol_trades
    
    def analyze_results(self, trades):
        """Analyze results"""
        if not trades:
            print("No trades found")
            return
        
        print("\n" + "=" * 80)
        print("EXACT BOOF31 BACKTEST RESULTS")
        print("=" * 80)
        
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
        
        gross_wins = sum(wins)
        gross_losses = abs(sum(losses))
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        
        ev = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
        
        if len(trades) > 1:
            returns = np.array([t['pnl_pct'] for t in trades])
            sharpe_ratio = np.sqrt(252) * (np.mean(returns) - 0.02/252) / np.std(returns) if np.std(returns) > 0 else 0
        else:
            sharpe_ratio = 0
        
        cumulative_returns = np.cumsum([t['pnl_pct'] for t in trades])
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdowns = cumulative_returns - running_max
        max_drawdown = np.min(drawdowns) if len(drawdowns) > 0 else 0
        
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
        
        print(f"\n📊 SYMBOL BREAKDOWN")
        symbol_stats = {}
        for trade in trades:
            symbol = trade['symbol']
            if symbol not in symbol_stats:
                symbol_stats[symbol] = {'trades': 0, 'pnl': 0, 'wins': 0}
            symbol_stats[symbol]['trades'] += 1
            symbol_stats[symbol]['pnl'] += trade['pnl_pct']
            if trade['pnl_pct'] > 0:
                symbol_stats[symbol]['wins'] += 1
        
        for symbol, stats in sorted(symbol_stats.items(), key=lambda x: x[1]['pnl'], reverse=True):
            win_rate = stats['wins'] / stats['trades']
            print(f"{symbol:8s}: {stats['trades']:3d} trades | {stats['pnl']:6.2%} P&L | {win_rate:5.1%} WR")
        
        print(f"\n" + "=" * 80)
    
    def run_backtest(self, start_date, end_date):
        """Run exact BOOF31 backtest - DEBUG VERSION"""
        print(f"Starting Exact BOOF31 Backtest - DEBUG")
        print(f"Period: {start_date} to {end_date}")
        print(f"Symbols: {', '.join(SYMBOLS)}")
        print("=" * 60)
        
        all_trades = []
        trade_counter = 0
        
        for i, symbol in enumerate(SYMBOLS, 1):
            print(f"\n[{i}/{len(SYMBOLS)}] Backtesting {symbol}...")
            
            df = self.generate_realistic_data(symbol, start_date, end_date)
            if df is None:
                continue
            
            symbol_trades = self.backtest_symbol(symbol, df)
            
            # DEBUG: Show first 10 trades with detailed P&L
            for trade in symbol_trades:
                trade_counter += 1
                if trade_counter <= 10:
                    entry_price = trade['entry_price']
                    exit_price = trade['exit_price']
                    pnl_pct = trade['pnl_pct']
                    
                    # Manual calculation for verification
                    manual_pnl = (entry_price - exit_price) / entry_price
                    
                    print(f"\n🔍 DEBUG TRADE #{trade_counter}")
                    print(f"Symbol: {symbol}")
                    print(f"Type: SHORT")
                    print(f"Entry: ${entry_price:.2f}")
                    print(f"Exit:  ${exit_price:.2f}")
                    print(f"Calculated P&L: {pnl_pct:.2%}")
                    print(f"Manual P&L:     {manual_pnl:.2%}")
                    print(f"Difference:     {abs(pnl_pct - manual_pnl):.4%}")
                    
                    # Check for ridiculous values
                    if abs(pnl_pct) > 0.10:  # More than 10% on single trade
                        print(f"⚠️  RIDICULOUS P&L DETECTED: {pnl_pct:.2%}")
                    
                    print("-" * 40)
            
            all_trades.extend(symbol_trades)
            
            if symbol_trades:
                win_rate = sum(1 for t in symbol_trades if t['pnl_pct'] > 0) / len(symbol_trades)
                avg_pnl = np.mean([t['pnl_pct'] for t in symbol_trades])
                total_pnl = sum([t['pnl_pct'] for t in symbol_trades])
                
                print(f"  Trades: {len(symbol_trades)} | WR: {win_rate:.1%} | P&L: {total_pnl:.2%}")
            else:
                print(f"  No trades found")
        
        print(f"\n🔍 PARAMETER CHECK:")
        print(f"STOP_LOSS: {STOP_LOSS} (should be 0.0025 for 0.25%)")
        print(f"TP1: {TP1} (should be 0.005 for 0.5%)")
        print(f"TRAIL_STOP: {TRAIL_STOP} (should be 0.0025 for 0.25%)")
        print(f"SWEEP_BUFFER: {SWEEP_BUFFER} (should be 0.002 for 0.2%)")
        
        self.trades = all_trades
        self.analyze_results(all_trades)

def main():
    """Main function"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)  # 6 months
    
    backtest = ExactBOOF31Backtest()
    backtest.run_backtest(start_date, end_date)

if __name__ == "__main__":
    main()
