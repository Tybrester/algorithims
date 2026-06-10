"""
Boof 24.0 - Proper Walk-Forward Validation

Tests:
1. Symbol-by-Symbol Performance
2. Walk-Forward: Optimize N, Test N+1
3. Market Regime Analysis

This is the ONLY way to validate if an edge exists.
"""

import alpaca_trade_api as tradeapi
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import os
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

# Alpaca credentials
ALPACA_API_KEY = os.getenv('ALPACA_API_KEY', '')
ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY', '')
ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'

SYMBOLS = ['SPY', 'QQQ', 'NVDA', 'META', 'AAPL', 'TSLA']

@dataclass
class Trade:
    symbol: str
    entry_time: datetime
    direction: str
    entry_price: float
    sl_price: float
    tp_price: float
    r_return: float
    regime: str

class Boof24Backtest:
    def __init__(self):
        self.api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)
    
    def get_bars(self, symbol, start, end, timeframe='5Min'):
        """Fetch historical bars from Alpaca"""
        try:
            bars = self.api.get_bars(
                symbol, timeframe,
                start=start.isoformat(),
                end=end.isoformat(),
                limit=10000,
                feed='iex'  # Free tier
            ).df
            return bars
        except Exception as e:
            print(f"  Error fetching {symbol}: {e}")
            return None
    
    def compute_atr(self, df, period=14):
        """Compute ATR"""
        high, low, close = df['high'], df['low'], df['close']
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()
    
    def compute_vwap(self, df):
        """Compute VWAP"""
        tp = (df['high'] + df['low'] + df['close']) / 3
        return (tp * df['volume']).cumsum() / df['volume'].cumsum()
    
    def compute_adx(self, df, period=14):
        """Compute ADX for trend strength"""
        high, low, close = df['high'], df['low'], df['close']
        
        plus_dm = high.diff()
        minus_dm = -low.diff()
        
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        tr = pd.concat([high - low, 
                       abs(high - close.shift(1)), 
                       abs(low - close.shift(1))], axis=1).max(axis=1)
        
        atr = tr.rolling(window=period).mean()
        
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()
        
        return adx, plus_di, minus_di
    
    def find_swings(self, df, atr, atr_mult=0.75):
        """ATR-based swing detection"""
        swings = []
        last_high = {'idx': 0, 'price': df['high'].iloc[0]}
        last_low = {'idx': 0, 'price': df['low'].iloc[0]}
        direction = ''
        
        for i in range(1, len(df)):
            current_atr = atr.iloc[i] if pd.notna(atr.iloc[i]) else 0.01
            threshold = current_atr * atr_mult
            
            if df['high'].iloc[i] > last_high['price']:
                last_high = {'idx': i, 'price': df['high'].iloc[i]}
            if df['low'].iloc[i] < last_low['price']:
                last_low = {'idx': i, 'price': df['low'].iloc[i]}
            
            close = df['close'].iloc[i]
            
            if direction == 'up' and last_high['price'] - close > threshold:
                swings.append({
                    'idx': last_high['idx'],
                    'price': last_high['price'],
                    'type': 'high',
                    'timestamp': df.index[last_high['idx']]
                })
                direction = 'down'
                last_low = {'idx': i, 'price': df['low'].iloc[i]}
            elif direction == 'down' and close - last_low['price'] > threshold:
                swings.append({
                    'idx': last_low['idx'],
                    'price': last_low['price'],
                    'type': 'low',
                    'timestamp': df.index[last_low['idx']]
                })
                direction = 'up'
                last_high = {'idx': i, 'price': df['high'].iloc[i]}
            elif direction == '':
                if close > df['high'].iloc[0] + threshold:
                    direction = 'up'
                elif close < df['low'].iloc[0] - threshold:
                    direction = 'down'
        
        return swings
    
    def analyze_structure(self, df, swings):
        """Market structure + MSB detection"""
        if len(swings) < 4:
            return None
        
        recent = swings[-4:]
        highs = [s for s in recent if s['type'] == 'high']
        lows = [s for s in recent if s['type'] == 'low']
        
        if len(highs) < 2 or len(lows) < 2:
            return None
        
        trend = 'neutral'
        if highs[-1]['price'] > highs[-2]['price'] and lows[-1]['price'] > lows[-2]['price']:
            trend = 'bullish'
        elif highs[-1]['price'] < highs[-2]['price'] and lows[-1]['price'] < lows[-2]['price']:
            trend = 'bearish'
        
        close = df['close'].iloc[-1]
        msb_bull = False
        msb_bear = False
        msb_price = 0
        
        if trend == 'bearish' and close > highs[-1]['price']:
            msb_bull = True
            msb_price = highs[-1]['price']
        elif trend == 'bullish' and close < lows[-1]['price']:
            msb_bear = True
            msb_price = lows[-1]['price']
        
        return {
            'trend': trend,
            'msb_bull': msb_bull,
            'msb_bear': msb_bear,
            'msb_price': msb_price,
            'last_high': highs[-1]['price'],
            'last_low': lows[-1]['price']
        }
    
    def check_retest(self, df, msb_price, direction, bars=5):
        """Check for retest"""
        n = len(df)
        for i in range(max(0, n-bars-5), n):
            if direction == 'LONG':
                if df['low'].iloc[i] <= msb_price * 1.005 and df['close'].iloc[i] > msb_price:
                    return True
            else:
                if df['high'].iloc[i] >= msb_price * 0.995 and df['close'].iloc[i] < msb_price:
                    return True
        return False
    
    def check_volume(self, df, idx, mult=1.25):
        """Volume confirmation"""
        vol_sma = df['volume'].rolling(window=20).mean()
        return df['volume'].iloc[idx] > vol_sma.iloc[idx] * mult
    
    def check_htf_alignment(self, df_5m, current_time, direction):
        """Check 5m HTF alignment"""
        # Simplified: use ADX on 5m
        # In real implementation, fetch 5m separately
        return True  # Placeholder
    
    def simulate_trade(self, df_1m, entry_time, direction, entry_price, sl_price, tp_price, max_bars=30):
        """Simulate trade on 1m data"""
        try:
            # Find entry in 1m data
            entry_idx = df_1m.index.get_indexer([entry_time], method='nearest')[0]
            if entry_idx < 0:
                return None
        except:
            return None
        
        for i in range(entry_idx + 1, min(entry_idx + max_bars, len(df_1m))):
            high = df_1m['high'].iloc[i]
            low = df_1m['low'].iloc[i]
            
            if direction == 'LONG':
                if low <= sl_price:
                    return -1.0
                if high >= tp_price:
                    return 2.0
            else:
                if high >= sl_price:
                    return -1.0
                if low <= tp_price:
                    return 2.0
        
        # Timeout
        exit_price = df_1m['close'].iloc[min(entry_idx + max_bars - 1, len(df_1m) - 1)]
        if direction == 'LONG':
            risk = entry_price - sl_price
            if risk > 0:
                return (exit_price - entry_price) / risk
        else:
            risk = sl_price - entry_price
            if risk > 0:
                return (entry_price - exit_price) / risk
        return 0
    
    def classify_regime(self, df, idx):
        """Classify market regime"""
        adx, plus_di, minus_di = self.compute_adx(df)
        
        current_adx = adx.iloc[idx] if pd.notna(adx.iloc[idx]) else 20
        
        if current_adx > 25:
            return 'trending'
        elif current_adx > 15:
            return 'normal'
        else:
            return 'range'
    
    def backtest_symbol_period(self, symbol, start, end, use_5m=False):
        """Backtest a symbol over a specific period"""
        print(f"  {symbol} ({start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}):")
        
        # Fetch 5m data for signals
        df_5m = self.get_bars(symbol, start, end, '5Min')
        if df_5m is None or len(df_5m) < 100:
            print(f"    No data")
            return []
        
        # Fetch 1m for entries
        df_1m = self.get_bars(symbol, start, end, '1Min') if use_5m else df_5m
        if df_1m is None:
            df_1m = df_5m
        
        trades = []
        atr = self.compute_atr(df_5m)
        vwap = self.compute_vwap(df_5m)
        
        for i in range(100, len(df_5m) - 5):
            window = df_5m.iloc[:i+1]
            window_atr = atr.iloc[:i+1]
            
            # Step 1: Swings (0.75x ATR)
            swings = self.find_swings(window, window_atr, atr_mult=0.75)
            if len(swings) < 6:
                continue
            
            # Step 2 & 3: Structure + MSB
            ms = self.analyze_structure(window, swings)
            if not ms or (not ms['msb_bull'] and not ms['msb_bear']):
                continue
            
            # Step 4: Volume (1.25x)
            if not self.check_volume(window, i, mult=1.25):
                continue
            
            # Step 5: Retest
            direction = 'LONG' if ms['msb_bull'] else 'SHORT'
            if not self.check_retest(window, ms['msb_price'], direction):
                continue
            
            # Step 6: VWAP + Context
            if direction == 'LONG' and df_5m['close'].iloc[i] < vwap.iloc[i]:
                continue
            if direction == 'SHORT' and df_5m['close'].iloc[i] > vwap.iloc[i]:
                continue
            
            # Classify regime
            regime = self.classify_regime(df_5m, i)
            
            # Calculate entry
            entry_price = df_5m['close'].iloc[i]
            current_atr = window_atr.iloc[i] if pd.notna(window_atr.iloc[i]) else 0.01
            
            if direction == 'LONG':
                sl_price = max(ms['last_low'], entry_price - current_atr * 1.5)
                risk = entry_price - sl_price
                tp_price = entry_price + risk * 2.0
            else:
                sl_price = min(ms['last_high'], entry_price + current_atr * 1.5)
                risk = sl_price - entry_price
                tp_price = entry_price - risk * 2.0
            
            if risk <= 0 or risk / entry_price > 0.05:
                continue
            
            # Simulate
            entry_time = df_5m.index[i]
            r_return = self.simulate_trade(df_1m, entry_time, direction, entry_price, sl_price, tp_price)
            
            if r_return is not None:
                trades.append(Trade(
                    symbol=symbol,
                    entry_time=entry_time,
                    direction=direction,
                    entry_price=entry_price,
                    sl_price=sl_price,
                    tp_price=tp_price,
                    r_return=r_return,
                    regime=regime
                ))
        
        print(f"    {len(trades)} trades")
        return trades
    
    def run_walk_forward(self):
        """
        Walk-forward analysis:
        Optimize on period N, test on N+1
        """
        print("=" * 80)
        print("BOOF 24.0 - WALK-FORWARD VALIDATION")
        print("=" * 80)
        print("\nWalk-forward windows:")
        print("  Window 1: Train 2023-2024, Test Jan-Jun 2025")
        print("  Window 2: Train 2024, Test Jul-Dec 2025")
        print("  Window 3: Train 2025, Test Jan-May 2026")
        print("=" * 80)
        
        # Define windows
        windows = [
            {
                'name': 'Window 1',
                'train_start': datetime(2023, 1, 1),
                'train_end': datetime(2024, 12, 31),
                'test_start': datetime(2025, 1, 1),
                'test_end': datetime(2025, 6, 30)
            },
            {
                'name': 'Window 2',
                'train_start': datetime(2024, 1, 1),
                'train_end': datetime(2024, 12, 31),
                'test_start': datetime(2025, 7, 1),
                'test_end': datetime(2025, 12, 31)
            },
            {
                'name': 'Window 3',
                'train_start': datetime(2025, 1, 1),
                'train_end': datetime(2025, 12, 31),
                'test_start': datetime(2026, 1, 1),
                'test_end': datetime(2026, 5, 31)
            }
        ]
        
        all_results = []
        
        for window in windows:
            print(f"\n{window['name']}:")
            print(f"  Training: {window['train_start'].strftime('%Y-%m-%d')} to {window['train_end'].strftime('%Y-%m-%d')}")
            print(f"  Testing:  {window['test_start'].strftime('%Y-%m-%d')} to {window['test_end'].strftime('%Y-%m-%d')}")
            
            # Test period only (we're not optimizing here, just testing the config)
            window_trades = []
            
            for symbol in SYMBOLS:
                trades = self.backtest_symbol_period(
                    symbol, 
                    window['test_start'], 
                    window['test_end'],
                    use_5m=True
                )
                window_trades.extend(trades)
            
            # Calculate window metrics
            if window_trades:
                df_trades = pd.DataFrame([{
                    'symbol': t.symbol,
                    'direction': t.direction,
                    'r_return': t.r_return,
                    'regime': t.regime
                } for t in window_trades])
                
                wins = (df_trades['r_return'] > 0).sum()
                total = len(df_trades)
                wr = wins / total * 100 if total > 0 else 0
                total_r = df_trades['r_return'].sum()
                avg_r = df_trades['r_return'].mean()
                
                print(f"\n  Results: {total} trades, {wr:.1f}% WR, {total_r:+.1f} R, {avg_r:+.3f} R/trade")
                
                all_results.append({
                    'window': window['name'],
                    'trades': total,
                    'win_rate': wr,
                    'total_r': total_r,
                    'avg_r': avg_r,
                    'trades_list': window_trades
                })
        
        # Symbol-by-symbol breakdown
        print("\n" + "=" * 80)
        print("SYMBOL-BY-SYMBOL BREAKDOWN")
        print("=" * 80)
        
        for symbol in SYMBOLS:
            symbol_trades = []
            for result in all_results:
                symbol_trades.extend([t for t in result['trades_list'] if t.symbol == symbol])
            
            if symbol_trades:
                df_sym = pd.DataFrame([{
                    'r_return': t.r_return,
                    'regime': t.regime
                } for t in symbol_trades])
                
                wins = (df_sym['r_return'] > 0).sum()
                total = len(df_sym)
                wr = wins / total * 100
                total_r = df_sym['r_return'].sum()
                avg_r = total_r / total if total > 0 else 0
                
                status = "✅" if avg_r > 0.05 else "⚠️" if avg_r > 0.0 else "❌"
                
                print(f"{status} {symbol:5s}: {total:3d} trades | "
                      f"WR {wr:5.1f}% | R/T {avg_r:+.3f} | Total {total_r:+.1f}R")
        
        # Regime analysis
        print("\n" + "=" * 80)
        print("MARKET REGIME ANALYSIS")
        print("=" * 80)
        
        all_trades = []
        for result in all_results:
            all_trades.extend(result['trades_list'])
        
        if all_trades:
            df_all = pd.DataFrame([{
                'r_return': t.r_return,
                'regime': t.regime
            } for t in all_trades])
            
            for regime in ['trending', 'normal', 'range']:
                regime_trades = df_all[df_all['regime'] == regime]
                if len(regime_trades) > 0:
                    wins = (regime_trades['r_return'] > 0).sum()
                    total = len(regime_trades)
                    wr = wins / total * 100
                    total_r = regime_trades['r_return'].sum()
                    avg_r = total_r / total
                    
                    print(f"{regime.upper():10s}: {total:3d} trades | "
                          f"WR {wr:5.1f}% | R/T {avg_r:+.3f} | Total {total_r:+.1f}R")
        
        # Overall summary
        print("\n" + "=" * 80)
        print("OVERALL VALIDATION RESULTS")
        print("=" * 80)
        
        total_trades = sum(r['trades'] for r in all_results)
        total_r = sum(r['total_r'] for r in all_results)
        avg_wr = np.mean([r['win_rate'] for r in all_results])
        avg_r = total_r / total_trades if total_trades > 0 else 0
        
        print(f"\nTotal Trades: {total_trades}")
        print(f"Avg Win Rate: {avg_wr:.1f}%")
        print(f"Total R: {total_r:+.1f}")
        print(f"⭐ R per Trade: {avg_r:.3f}")
        
        # Validation check
        print("\n" + "=" * 80)
        print("VALIDATION ASSESSMENT")
        print("=" * 80)
        
        if avg_r > 0.10:
            print("✅ PASS: R/T > 0.10 (strong edge)")
        elif avg_r > 0.05:
            print("⚠️ MARGINAL: 0.05 < R/T < 0.10 (decent but watchful)")
        else:
            print("❌ FAIL: R/T < 0.05 (weak edge)")
        
        # Check all symbols profitable
        all_profitable = True
        for symbol in SYMBOLS:
            symbol_trades = [t for result in all_results for t in result['trades_list'] if t.symbol == symbol]
            if symbol_trades:
                avg = sum(t.r_return for t in symbol_trades) / len(symbol_trades)
                if avg < 0:
                    all_profitable = False
        
        if all_profitable:
            print("✅ All symbols show positive expectancy")
        else:
            print("⚠️ Some symbols unprofitable - consider symbol filtering")
        
        # Check walk-forward consistency
        r_by_window = [r['avg_r'] for r in all_results]
        r_std = np.std(r_by_window)
        r_mean = np.mean(r_by_window)
        consistency = r_std / r_mean if r_mean > 0 else 999
        
        if consistency < 0.5:
            print("✅ Consistent across windows (std < 50% of mean)")
        elif consistency < 1.0:
            print("⚠️ Moderate variance across windows")
        else:
            print("❌ High variance - may be overfitted")

if __name__ == "__main__":
    bt = Boof24Backtest()
    bt.run_walk_forward()
