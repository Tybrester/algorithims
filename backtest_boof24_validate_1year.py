"""
Boof 24.0 - 1 Year Proper Validation
Train: Jan-Jun 2024 (optimize)
Test:  Jul-Dec 2024 (validate)

This is the real test.
"""

import alpaca_trade_api as tradeapi
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import warnings
warnings.filterwarnings('ignore')

# Alpaca
ALPACA_API_KEY = os.getenv('ALPACA_API_KEY', '')
ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY', '')
ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'

SYMBOLS = ['SPY', 'QQQ', 'NVDA', 'META', 'AAPL', 'TSLA']

# LOCKED CONFIG (from optimization)
CONFIG = {
    'ATR_MULT': 0.75,        # Swing detection
    'VOL_MULT': 1.25,        # Volume threshold
    'USE_RETEST': True,      # Wait for retest
    'USE_VWAP': True,        # Trend alignment
    'TP_R': 2.0,             # 2R target
    'SL_R': 1.0,             # 1R stop
}

class Boof24Validator:
    def __init__(self):
        self.api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)
        self.results = {}
    
    def fetch_bars(self, symbol, start, end, timeframe='5Min'):
        """Fetch bars with retry"""
        try:
            bars = self.api.get_bars(
                symbol, timeframe,
                start=start.isoformat(),
                end=end.isoformat(),
                limit=10000,
                feed='iex'
            ).df
            return bars
        except Exception as e:
            print(f"    Error: {e}")
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
    
    def compute_adx(self, df, period=14):
        """ADX for regime classification"""
        high, low, close = df['high'], df['low'], df['close']
        
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        tr = pd.concat([high - low, abs(high - close.shift(1)), abs(low - close.shift(1))], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()
        
        return adx
    
    def find_swings(self, df, atr, atr_mult):
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
                swings.append({'idx': last_high['idx'], 'price': last_high['price'], 'type': 'high'})
                direction = 'down'
                last_low = {'idx': i, 'price': df['low'].iloc[i]}
            elif direction == 'down' and close - last_low['price'] > threshold:
                swings.append({'idx': last_low['idx'], 'price': last_low['price'], 'type': 'low'})
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
    
    def check_filters(self, df, atr, vwap, idx, msb_price, direction):
        """All filters in sequence"""
        # Volume
        vol_sma = df['volume'].rolling(window=20).mean()
        if df['volume'].iloc[idx] <= vol_sma.iloc[idx] * CONFIG['VOL_MULT']:
            return False, 'volume'
        
        # Retest
        if CONFIG['USE_RETEST']:
            n = len(df)
            found = False
            for i in range(max(0, n-10), n):
                if direction == 'LONG':
                    if df['low'].iloc[i] <= msb_price * 1.005 and df['close'].iloc[i] > msb_price:
                        found = True
                        break
                else:
                    if df['high'].iloc[i] >= msb_price * 0.995 and df['close'].iloc[i] < msb_price:
                        found = True
                        break
            if not found:
                return False, 'retest'
        
        # VWAP
        if CONFIG['USE_VWAP']:
            if direction == 'LONG' and df['close'].iloc[idx] < vwap.iloc[idx]:
                return False, 'vwap'
            if direction == 'SHORT' and df['close'].iloc[idx] > vwap.iloc[idx]:
                return False, 'vwap'
        
        return True, 'ok'
    
    def simulate_trade(self, df, entry_idx, direction, entry, sl, tp, max_bars=20):
        """Forward-simulate trade"""
        for i in range(entry_idx + 1, min(entry_idx + max_bars, len(df))):
            high, low = df['high'].iloc[i], df['low'].iloc[i]
            
            if direction == 'LONG':
                if low <= sl:
                    return -1.0
                if high >= tp:
                    return 2.0
            else:
                if high >= sl:
                    return -1.0
                if low <= tp:
                    return 2.0
        
        # Timeout
        exit_price = df['close'].iloc[min(entry_idx + max_bars - 1, len(df) - 1)]
        if direction == 'LONG':
            return (exit_price - entry) / (entry - sl) if (entry - sl) > 0 else 0
        else:
            return (entry - exit_price) / (sl - entry) if (sl - entry) > 0 else 0
    
    def backtest_symbol(self, symbol, start, end, period_name):
        """Backtest single symbol over period"""
        print(f"  {symbol} ({period_name}):")
        
        df = self.fetch_bars(symbol, start, end, '5Min')
        if df is None or len(df) < 100:
            return []
        
        trades = []
        atr = self.compute_atr(df)
        vwap = self.compute_vwap(df)
        adx = self.compute_adx(df)
        
        for i in range(100, len(df) - 5):
            window = df.iloc[:i+1]
            window_atr = atr.iloc[:i+1]
            
            # Swings
            swings = self.find_swings(window, window_atr, CONFIG['ATR_MULT'])
            if len(swings) < 6:
                continue
            
            # Structure
            ms = self.analyze_structure(window, swings)
            if not ms or (not ms['msb_bull'] and not ms['msb_bear']):
                continue
            
            direction = 'LONG' if ms['msb_bull'] else 'SHORT'
            
            # Filters
            passed, reason = self.check_filters(df, atr, vwap, i, ms['msb_price'], direction)
            if not passed:
                continue
            
            # Entry calc
            entry = df['close'].iloc[i]
            current_atr = window_atr.iloc[i] if pd.notna(window_atr.iloc[i]) else 0.01
            
            if direction == 'LONG':
                sl = max(ms['last_low'], entry - current_atr * 1.5)
                risk = entry - sl
                tp = entry + risk * CONFIG['TP_R']
            else:
                sl = min(ms['last_high'], entry + current_atr * 1.5)
                risk = sl - entry
                tp = entry - risk * CONFIG['TP_R']
            
            if risk <= 0 or risk / entry > 0.05:
                continue
            
            # Simulate
            r_return = self.simulate_trade(df, i, direction, entry, sl, tp)
            
            # Regime
            regime_adx = adx.iloc[i] if pd.notna(adx.iloc[i]) else 20
            if regime_adx > 25:
                regime = 'trending'
            elif regime_adx > 15:
                regime = 'normal'
            else:
                regime = 'range'
            
            trades.append({
                'symbol': symbol,
                'timestamp': df.index[i],
                'direction': direction,
                'entry': entry,
                'sl': sl,
                'tp': tp,
                'r_return': r_return,
                'regime': regime,
                'adx': regime_adx
            })
        
        return trades
    
    def run_validation(self):
        """Main validation routine"""
        print("=" * 80)
        print("BOOF 24.0 - 1 YEAR PROPER VALIDATION")
        print("=" * 80)
        print(f"\nLocked Config:")
        print(f"  ATR Multiplier: {CONFIG['ATR_MULT']}x")
        print(f"  Volume Threshold: {CONFIG['VOL_MULT']}x")
        print(f"  Retest: {'Yes' if CONFIG['USE_RETEST'] else 'No'}")
        print(f"  VWAP Filter: {'Yes' if CONFIG['USE_VWAP'] else 'No'}")
        print(f"  Risk/Reward: 1:{CONFIG['TP_R']}")
        print("=" * 80)
        
        # TRAIN PERIOD (Jan-Jun 2024)
        train_start = datetime(2024, 1, 1)
        train_end = datetime(2024, 6, 30)
        
        print(f"\n{'='*80}")
        print(f"TRAIN PERIOD: {train_start.strftime('%Y-%m-%d')} to {train_end.strftime('%Y-%m-%d')}")
        print(f"{'='*80}")
        
        train_trades = []
        for symbol in SYMBOLS:
            trades = self.backtest_symbol(symbol, train_start, train_end, 'TRAIN')
            train_trades.extend(trades)
            
            if trades:
                df = pd.DataFrame(trades)
                wins = (df['r_return'] > 0).sum()
                total = len(df)
                wr = wins / total * 100
                r_per_trade = df['r_return'].sum() / total
                print(f"    {len(trades)} trades | WR {wr:.1f}% | R/T {r_per_trade:+.3f} | Total {df['r_return'].sum():+.1f}R")
        
        # TRAIN SUMMARY
        if train_trades:
            df_train = pd.DataFrame(train_trades)
            train_wins = (df_train['r_return'] > 0).sum()
            train_total = len(df_train)
            train_wr = train_wins / train_total * 100
            train_rpt = df_train['r_return'].sum() / train_total
            train_total_r = df_train['r_return'].sum()
            
            print(f"\n  TRAIN TOTAL: {train_total} trades | {train_wr:.1f}% WR | {train_rpt:+.3f} R/T | {train_total_r:+.1f}R")
        
        # TEST PERIOD (Jul-Dec 2024) - OUT OF SAMPLE
        test_start = datetime(2024, 7, 1)
        test_end = datetime(2024, 12, 31)
        
        print(f"\n{'='*80}")
        print(f"TEST PERIOD (OUT-OF-SAMPLE): {test_start.strftime('%Y-%m-%d')} to {test_end.strftime('%Y-%m-%d')}")
        print(f"{'='*80}")
        
        test_results = {}
        
        for symbol in SYMBOLS:
            trades = self.backtest_symbol(symbol, test_start, test_end, 'TEST')
            test_results[symbol] = trades
            
            if trades:
                df = pd.DataFrame(trades)
                wins = (df['r_return'] > 0).sum()
                total = len(df)
                wr = wins / total * 100
                r_per_trade = df['r_return'].sum() / total
                total_r = df['r_return'].sum()
                
                status = "✅" if r_per_trade > 0.05 else "⚠️" if r_per_trade > 0 else "❌"
                print(f"    {status} {len(trades)} trades | WR {wr:.1f}% | R/T {r_per_trade:+.3f} | {total_r:+.1f}R")
        
        # TEST SUMMARY
        all_test_trades = []
        for trades in test_results.values():
            all_test_trades.extend(trades)
        
        if all_test_trades:
            df_test = pd.DataFrame(all_test_trades)
            test_wins = (df_test['r_return'] > 0).sum()
            test_total = len(df_test)
            test_wr = test_wins / test_total * 100
            test_rpt = df_test['r_return'].sum() / test_total
            test_total_r = df_test['r_return'].sum()
            
            print(f"\n  TEST TOTAL: {test_total} trades | {test_wr:.1f}% WR | {test_rpt:+.3f} R/T | {test_total_r:+.1f}R")
        
        # SYMBOL-BY-SYMBOL TABLE
        print(f"\n{'='*80}")
        print(f"SYMBOL-BY-SYMBOL OUT-OF-SAMPLE RESULTS")
        print(f"{'='*80}")
        print(f"\n{'Symbol':<8} {'Trades':<8} {'Win Rate':<10} {'R/T':<8} {'Total R':<10} {'Status'}")
        print("-" * 70)
        
        all_profitable = True
        for symbol in SYMBOLS:
            trades = test_results.get(symbol, [])
            if trades:
                df = pd.DataFrame(trades)
                total = len(df)
                wins = (df['r_return'] > 0).sum()
                wr = wins / total * 100
                rpt = df['r_return'].sum() / total
                total_r = df['r_return'].sum()
                
                if rpt >= 0.10:
                    status = "✅ EXCELLENT"
                elif rpt >= 0.05:
                    status = "✅ GOOD"
                elif rpt > 0:
                    status = "⚠️ MARGINAL"
                else:
                    status = "❌ FAIL"
                    all_profitable = False
                
                print(f"{symbol:<8} {total:<8} {wr:<10.1f} {rpt:<8.3f} {total_r:<+10.1f} {status}")
            else:
                print(f"{symbol:<8} {'0':<8} {'N/A':<10} {'N/A':<8} {'0.0':<10} ❌ NO TRADES")
                all_profitable = False
        
        # REGIME ANALYSIS
        print(f"\n{'='*80}")
        print(f"REGIME ANALYSIS (TEST PERIOD)")
        print(f"{'='*80}")
        
        if all_test_trades:
            df_test['regime'] = [t['regime'] for t in all_test_trades]
            
            for regime in ['trending', 'normal', 'range']:
                regime_df = df_test[df_test['regime'] == regime]
                if len(regime_df) > 0:
                    wins = (regime_df['r_return'] > 0).sum()
                    total = len(regime_df)
                    wr = wins / total * 100
                    rpt = regime_df['r_return'].sum() / total
                    total_r = regime_df['r_return'].sum()
                    
                    print(f"{regime.upper():12s}: {total:3d} trades | WR {wr:5.1f}% | R/T {rpt:+.3f} | {total_r:+.1f}R")
        
        # FINAL VALIDATION
        print(f"\n{'='*80}")
        print(f"FINAL VALIDATION RESULTS")
        print(f"{'='*80}")
        
        if all_test_trades:
            print(f"\nOut-of-Sample Performance:")
            print(f"  Trades: {test_total}")
            print(f"  Win Rate: {test_wr:.1f}%")
            print(f"  ⭐ R per Trade: {test_rpt:.3f}")
            print(f"  Total R: {test_total_r:+.1f}")
            
            print(f"\nValidation Criteria:")
            
            # R/T > 0.10
            if test_rpt >= 0.10:
                print(f"  ✅ R/T = {test_rpt:.3f} > 0.10 (EXCELLENT)")
            elif test_rpt >= 0.05:
                print(f"  ⚠️ R/T = {test_rpt:.3f} (0.05-0.10, MARGINAL)")
            else:
                print(f"  ❌ R/T = {test_rpt:.3f} < 0.05 (WEAK)")
            
            # All symbols profitable
            if all_profitable:
                print(f"  ✅ All symbols profitable")
            else:
                print(f"  ⚠️ Some symbols unprofitable")
            
            # Consistency with train
            if train_trades:
                train_rpt = df_train['r_return'].sum() / len(df_train)
                degradation = (train_rpt - test_rpt) / train_rpt * 100 if train_rpt > 0 else 0
                
                print(f"\nTrain vs Test Consistency:")
                print(f"  Train R/T: {train_rpt:.3f}")
                print(f"  Test R/T:  {test_rpt:.3f}")
                print(f"  Degradation: {degradation:.1f}%")
                
                if degradation < 30:
                    print(f"  ✅ Consistent (< 30% degradation)")
                elif degradation < 50:
                    print(f"  ⚠️ Moderate degradation (30-50%)")
                else:
                    print(f"  ❌ High degradation (> 50%) - OVERFIT")
        
        print(f"\n{'='*80}")

if __name__ == "__main__":
    validator = Boof24Validator()
    validator.run_validation()
