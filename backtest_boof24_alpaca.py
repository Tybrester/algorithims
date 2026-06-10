"""
Boof 24.0 - Alpaca Backtest
5m signals + 1m entries
Ablation: With vs Without Volume Filter
"""

import alpaca_trade_api as tradeapi
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import warnings
warnings.filterwarnings('ignore')

# Alpaca credentials - get from environment or prompt
ALPACA_API_KEY = os.getenv('APCA_API_KEY_ID', '')
ALPACA_SECRET_KEY = os.getenv('APCA_API_SECRET_KEY', '')
ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'

# If not set via env vars, use hardcoded from your Supabase (for quick test)
# Replace these with your actual keys:
if not ALPACA_API_KEY:
    ALPACA_API_KEY = input("Enter Alpaca API Key ID: ")
if not ALPACA_SECRET_KEY:
    ALPACA_SECRET_KEY = input("Enter Alpaca API Secret Key: ")

SYMBOLS = ['SPY', 'QQQ', 'NVDA', 'META', 'AAPL', 'TSLA']

CFG = {
    'ATR_LEN': 14,
    'VOL_LEN': 20,
    'ATR_REV_MULT': 1.0,
    'VOL_MULT': 1.25,
    'ATR_PERCENTILE_MIN': 40,
    'RETEST_BARS': 5,
    'TP_R': 2.0,
    'SL_R': 1.0,
}

class Boof24Backtest:
    def __init__(self):
        self.api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)
    
    def get_bars(self, symbol, timeframe, start, end):
        """Fetch bars from Alpaca"""
        try:
            # Format dates properly for Alpaca API
            start_str = start.strftime('%Y-%m-%dT%H:%M:%SZ') if hasattr(start, 'strftime') else str(start)
            end_str = end.strftime('%Y-%m-%dT%H:%M:%SZ') if hasattr(end, 'strftime') else str(end)
            bars = self.api.get_bars(
                symbol,
                timeframe,
                start=start_str,
                end=end_str,
                limit=10000
            ).df
            return bars
        except Exception as e:
            print(f"  Error fetching {symbol}: {e}")
            return None
    
    def compute_atr(self, df, period=14):
        high, low, close = df['high'], df['low'], df['close']
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()
    
    def compute_vwap(self, df):
        tp = (df['high'] + df['low'] + df['close']) / 3
        return (tp * df['volume']).cumsum() / df['volume'].cumsum()
    
    def find_swings(self, df, atr):
        """ATR-based swing detection"""
        swings = []
        last_high = {'idx': 0, 'price': df['high'].iloc[0]}
        last_low = {'idx': 0, 'price': df['low'].iloc[0]}
        direction = ''
        
        for i in range(1, len(df)):
            current_atr = atr.iloc[i] if pd.notna(atr.iloc[i]) else 0.01
            threshold = current_atr * CFG['ATR_REV_MULT']
            
            if df['high'].iloc[i] > last_high['price']:
                last_high = {'idx': i, 'price': df['high'].iloc[i]}
            if df['low'].iloc[i] < last_low['price']:
                last_low = {'idx': i, 'price': df['low'].iloc[i]}
            
            close = df['close'].iloc[i]
            
            if direction == 'up' and last_high['price'] - close > threshold:
                swings.append({'idx': last_high['idx'], 'price': last_high['price'], 'type': 'high', 'timestamp': df.index[last_high['idx']]})
                direction = 'down'
                last_low = {'idx': i, 'price': df['low'].iloc[i]}
            elif direction == 'down' and close - last_low['price'] > threshold:
                swings.append({'idx': last_low['idx'], 'price': last_low['price'], 'type': 'low', 'timestamp': df.index[last_low['idx']]})
                direction = 'up'
                last_high = {'idx': i, 'price': df['high'].iloc[i]}
            elif direction == '':
                if close > df['high'].iloc[0] + threshold:
                    direction = 'up'
                elif close < df['low'].iloc[0] - threshold:
                    direction = 'down'
        
        return swings
    
    def analyze_structure(self, df, swings):
        """Market structure + MSB"""
        if len(swings) < 4:
            return None
        
        recent = swings[-4:]
        highs = [s for s in recent if s['type'] == 'high']
        lows = [s for s in recent if s['type'] == 'low']
        
        if len(highs) < 2 or len(lows) < 2:
            return None
        
        trend = 'neutral'
        hh = highs[-1]['price'] > highs[-2]['price']
        hl = lows[-1]['price'] > lows[-2]['price']
        lh = highs[-1]['price'] < highs[-2]['price']
        ll = lows[-1]['price'] < lows[-2]['price']
        
        if hh and hl:
            trend = 'bullish'
        elif lh and ll:
            trend = 'bearish'
        
        close = df['close'].iloc[-1]
        msb_bull = False
        msb_bear = False
        msb_price = 0
        
        if trend == 'bearish' and highs:
            if close > highs[-1]['price']:
                msb_bull = True
                msb_price = highs[-1]['price']
        elif trend == 'bullish' and lows:
            if close < lows[-1]['price']:
                msb_bear = True
                msb_price = lows[-1]['price']
        
        return {
            'trend': trend,
            'msb_bull': msb_bull,
            'msb_bear': msb_bear,
            'msb_price': msb_price,
            'last_high': highs[-1]['price'] if highs else df['high'].iloc[-1],
            'last_low': lows[-1]['price'] if lows else df['low'].iloc[-1]
        }
    
    def check_volume(self, df, idx):
        """Volume confirmation"""
        vol_sma = df['volume'].rolling(window=CFG['VOL_LEN']).mean()
        return df['volume'].iloc[idx] > vol_sma.iloc[idx] * CFG['VOL_MULT']
    
    def check_retest(self, df, msb_price, direction):
        """Retest check"""
        n = len(df)
        for i in range(max(0, n-CFG['RETEST_BARS']-5), n):
            if direction == 'LONG':
                if df['low'].iloc[i] <= msb_price * 1.005 and df['close'].iloc[i] > msb_price:
                    return True
            else:
                if df['high'].iloc[i] >= msb_price * 0.995 and df['close'].iloc[i] < msb_price:
                    return True
        return False
    
    def check_context(self, df, atr, vwap, direction, idx):
        """Context filters"""
        atr_pct = atr.rolling(window=50).apply(lambda x: (x < x.iloc[-1]).sum() / len(x) * 100 if len(x) > 0 else 0, raw=False)
        if pd.isna(atr_pct.iloc[idx]) or atr_pct.iloc[idx] < CFG['ATR_PERCENTILE_MIN']:
            return False
        
        close = df['close'].iloc[idx]
        if direction == 'LONG' and close < vwap.iloc[idx]:
            return False
        if direction == 'SHORT' and close > vwap.iloc[idx]:
            return False
        return True
    
    def simulate_trade(self, df_1m, entry_time, direction, entry_price, sl_price, tp_price, max_bars=30):
        """Simulate trade on 1m data"""
        try:
            entry_idx = df_1m.index.get_loc(entry_time)
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
    
    def backtest_symbol(self, symbol, use_volume=True):
        """Backtest single symbol"""
        print(f"\n{symbol}:")
        
        # Fetch 5m data (last 30 days max for free tier)
        end = datetime.now()
        start = end - timedelta(days=30)
        
        df_5m = self.get_bars(symbol, '5Min', start, end)
        if df_5m is None or len(df_5m) < 100:
            print("  No 5m data")
            return None
        
        # Fetch 1m data for entries
        df_1m = self.get_bars(symbol, '1Min', start, end)
        if df_1m is None:
            print("  No 1m data")
            return None
        
        print(f"  5m bars: {len(df_5m)}, 1m bars: {len(df_1m)}")
        
        trades = []
        atr = self.compute_atr(df_5m)
        vwap = self.compute_vwap(df_5m)
        
        for i in range(100, len(df_5m) - 5):
            window = df_5m.iloc[:i+1]
            window_atr = atr.iloc[:i+1]
            window_vwap = vwap.iloc[:i+1]
            
            # Step 1: Swings
            swings = self.find_swings(window, window_atr)
            if len(swings) < 6:
                continue
            
            # Step 2 & 3: Structure + MSB
            ms = self.analyze_structure(window, swings)
            if not ms or (not ms['msb_bull'] and not ms['msb_bear']):
                continue
            
            # Step 4: Volume (ablation)
            if use_volume and not self.check_volume(window, i):
                continue
            
            # Step 5: Retest
            direction = 'LONG' if ms['msb_bull'] else 'SHORT'
            if not self.check_retest(window, ms['msb_price'], direction):
                continue
            
            # Step 6: Context
            if not self.check_context(window, window_atr, window_vwap, direction, i):
                continue
            
            # Calculate entry
            entry_price = df_5m['close'].iloc[i]
            current_atr = window_atr.iloc[i] if pd.notna(window_atr.iloc[i]) else 0.01
            
            if direction == 'LONG':
                sl_price = max(ms['last_low'], entry_price - current_atr * 1.5)
                risk = entry_price - sl_price
                tp_price = entry_price + risk * CFG['TP_R']
            else:
                sl_price = min(ms['last_high'], entry_price + current_atr * 1.5)
                risk = sl_price - entry_price
                tp_price = entry_price - risk * CFG['TP_R']
            
            if risk <= 0 or risk / entry_price > 0.05:  # Max 5% risk
                continue
            
            # Simulate on 1m
            entry_time = df_5m.index[i]
            r_return = self.simulate_trade(df_1m, entry_time, direction, entry_price, sl_price, tp_price)
            
            if r_return is not None:
                trades.append({
                    'timestamp': entry_time,
                    'direction': direction,
                    'entry': entry_price,
                    'sl': sl_price,
                    'tp': tp_price,
                    'r_return': r_return,
                    'pnl_pct': (r_return * risk / entry_price) * 100
                })
        
        return trades
    
    def run(self):
        """Run ablation test"""
        print("=" * 70)
        print("BOOF 24.0 - ALPACA ABLATION TEST")
        print("5m Signals + 1m Entries")
        print("=" * 70)
        
        results = {}
        
        for symbol in SYMBOLS:
            # Test with volume
            print(f"\n[WITH Volume] ", end="")
            trades_with = self.backtest_symbol(symbol, use_volume=True)
            
            # Test without volume  
            print(f"\n[NO Volume] ", end="")
            trades_without = self.backtest_symbol(symbol, use_volume=False)
            
            results[symbol] = {
                'with': trades_with,
                'without': trades_without
            }
        
        # Print summary
        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)
        
        total_with = []
        total_without = []
        
        for symbol, res in results.items():
            print(f"\n{symbol}:")
            
            for test_name, trades in [('WITH Vol', res['with']), ('NO Vol', res['without'])]:
                if not trades:
                    print(f"  {test_name}: No trades")
                    continue
                
                df = pd.DataFrame(trades)
                wins = (df['r_return'] > 0).sum()
                wr = wins / len(df) * 100
                avg_r = df['r_return'].mean()
                total_r = df['r_return'].sum()
                
                print(f"  {test_name}: {len(df)} trades, WR {wr:.1f}%, Avg R {avg_r:.2f}, Total R {total_r:.2f}")
                
                if test_name == 'WITH Vol':
                    total_with.extend(trades)
                else:
                    total_without.extend(trades)
        
        # Overall
        print("\n" + "=" * 70)
        print("OVERALL ABLATION TEST")
        print("=" * 70)
        
        if total_with and total_without:
            df_with = pd.DataFrame(total_with)
            df_without = pd.DataFrame(total_without)
            
            wins_with = (df_with['r_return'] > 0).sum()
            wins_without = (df_without['r_return'] > 0).sum()
            
            print(f"\nWITH Volume Filter:")
            print(f"  Trades: {len(df_with)}")
            print(f"  Win Rate: {wins_with/len(df_with)*100:.1f}%")
            print(f"  Total R: {df_with['r_return'].sum():.2f}")
            print(f"  Avg R per trade: {df_with['r_return'].mean():.3f}")
            
            print(f"\nWITHOUT Volume Filter:")
            print(f"  Trades: {len(df_without)}")
            print(f"  Win Rate: {wins_without/len(df_without)*100:.1f}%")
            print(f"  Total R: {df_without['r_return'].sum():.2f}")
            print(f"  Avg R per trade: {df_without['r_return'].mean():.3f}")
            
            impact = df_with['r_return'].sum() - df_without['r_return'].sum()
            pct_impact = impact / abs(df_without['r_return'].sum()) * 100 if df_without['r_return'].sum() != 0 else 0
            
            print(f"\nVolume Filter Impact: {impact:+.2f} R ({pct_impact:+.1f}%)")
            
            if impact > 0:
                print("✅ Volume filter ADDED edge")
            elif impact < 0:
                print("❌ Volume filter REMOVED edge")
            else:
                print("➖ No significant impact")
        else:
            print("\nNot enough data for comparison")

if __name__ == "__main__":
    bt = Boof24Backtest()
    bt.run()
