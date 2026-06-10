"""BOOF 24 - 2 Week Alpaca Ablation Test (Fast)"""
import alpaca_trade_api as tradeapi
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

ALPACA_API_KEY = "AKAQMRBMRXN6676IET6N5VOCTH"
ALPACA_SECRET_KEY = "AbAnxL7xjfZH5MiTYZcjFnL3YkqxnYTNnwkJpnHWGBiC"
ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'

api = tradeapi.REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)

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

def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def find_swings(df, atr, mult=0.75):
    swings = []
    last_high = {'idx': 0, 'price': df['high'].iloc[0]}
    last_low = {'idx': 0, 'price': df['low'].iloc[0]}
    
    for i in range(1, len(df)):
        high, low = df['high'].iloc[i], df['low'].iloc[i]
        
        if high > last_high['price']:
            last_high = {'idx': i, 'price': high}
        if low < last_low['price']:
            last_low = {'idx': i, 'price': low}
        
        swing_high_cond = last_high['price'] - low > mult * atr.iloc[i] if not pd.isna(atr.iloc[i]) else False
        swing_low_cond = high - last_low['price'] > mult * atr.iloc[i] if not pd.isna(atr.iloc[i]) else False
        
        if swing_high_cond:
            swings.append({'type': 'high', 'idx': last_high['idx'], 'price': last_high['price']})
            last_low = {'idx': i, 'price': low}
        elif swing_low_cond:
            swings.append({'type': 'low', 'idx': last_low['idx'], 'price': last_low['price']})
            last_high = {'idx': i, 'price': high}
    
    return swings

def analyze_structure(df, swings, idx):
    """Determine market structure at index"""
    relevant = [s for s in swings if s['idx'] <= idx]
    if len(relevant) < 2:
        return {'trend': 'neutral', 'msb_bull': False, 'msb_bear': False}
    
    highs = [s for s in relevant if s['type'] == 'high']
    lows = [s for s in relevant if s['type'] == 'low']
    
    if len(highs) < 2 or len(lows) < 2:
        return {'trend': 'neutral', 'msb_bull': False, 'msb_bear': False}
    
    # Higher highs and higher lows = uptrend
    hh = highs[-1]['price'] > highs[-2]['price']
    hl = lows[-1]['price'] > lows[-2]['price']
    
    # Lower highs and lower lows = downtrend
    lh = highs[-1]['price'] < highs[-2]['price']
    ll = lows[-1]['price'] < lows[-2]['price']
    
    trend = 'bullish' if hh and hl else 'bearish' if lh and ll else 'neutral'
    
    # Structure break detection
    current = df.iloc[idx]
    msb_bull = trend == 'bearish' and current['close'] > highs[-2]['price']
    msb_bear = trend == 'bullish' and current['close'] < lows[-2]['price']
    
    return {'trend': trend, 'msb_bull': msb_bull, 'msb_bear': msb_bear}

def check_volume(df, idx):
    vol_sma = df['volume'].rolling(window=CFG['VOL_LEN']).mean()
    return df['volume'].iloc[idx] > vol_sma.iloc[idx] * CFG['VOL_MULT']

def backtest_symbol(symbol, start, end, use_volume=True):
    """Backtest a single symbol"""
    trades_with = []
    trades_without = []
    
    try:
        df_5m = api.get_bars(
            symbol, '5Min',
            start=start.strftime('%Y-%m-%d'),
            end=end.strftime('%Y-%m-%d'),
            limit=10000, feed='iex'
        ).df
        
        if len(df_5m) < 100:
            return None, None
            
        df_5m = df_5m.reset_index()
        if 'timestamp' in df_5m.columns:
            df_5m['time'] = pd.to_datetime(df_5m['timestamp'])
        elif 'index' in df_5m.columns:
            df_5m['time'] = pd.to_datetime(df_5m['index'])
        
        atr = compute_atr(df_5m)
        swings = find_swings(df_5m, atr)
        
        for i in range(50, len(df_5m) - 10):
            structure = analyze_structure(df_5m, swings, i)
            vol_ok = check_volume(df_5m, i) if use_volume else True
            
            entry = df_5m['close'].iloc[i]
            atr_val = atr.iloc[i]
            
            if pd.isna(atr_val) or atr_val == 0:
                continue
                
            tp = entry + CFG['TP_R'] * atr_val
            sl = entry - CFG['SL_R'] * atr_val
            
            if structure['msb_bull'] and vol_ok:
                # Simulate trade
                for j in range(i+1, min(i+20, len(df_5m))):
                    high = df_5m['high'].iloc[j]
                    low = df_5m['low'].iloc[j]
                    
                    if high >= tp:
                        r_return = CFG['TP_R']
                        trades_with.append(r_return)
                        break
                    elif low <= sl:
                        r_return = -CFG['SL_R']
                        trades_with.append(r_return)
                        break
            
            # Without volume check (always True)
            if structure['msb_bull']:
                for j in range(i+1, min(i+20, len(df_5m))):
                    high = df_5m['high'].iloc[j]
                    low = df_5m['low'].iloc[j]
                    
                    if high >= tp:
                        r_return = CFG['TP_R']
                        trades_without.append(r_return)
                        break
                    elif low <= sl:
                        r_return = -CFG['SL_R']
                        trades_without.append(r_return)
                        break
        
        return trades_with, trades_without
        
    except Exception as e:
        print(f"  Error on {symbol}: {e}")
        return None, None

print("="*60)
print("BOOF 24 - 2 WEEK ABLATION TEST")
print("="*60)

end = datetime.now()
start = end - timedelta(days=14)  # 2 weeks

print(f"Period: {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}")
print(f"Symbols: {', '.join(SYMBOLS)}")
print("="*60)

all_with = []
all_without = []

for sym in SYMBOLS:
    print(f"\n{sym}...")
    trades_with, trades_without = backtest_symbol(sym, start, end, use_volume=True)
    
    if trades_with is not None:
        print(f"  WITH Volume: {len(trades_with)} trades, {sum(trades_with):.2f}R")
        print(f"  NO Volume:   {len(trades_without)} trades, {sum(trades_without):.2f}R")
        all_with.extend(trades_with)
        all_without.extend(trades_without)
    else:
        print(f"  No data")

print("\n" + "="*60)
print("OVERALL RESULTS")
print("="*60)

if all_with and all_without:
    wins_with = sum(1 for r in all_with if r > 0)
    wins_without = sum(1 for r in all_without if r > 0)
    
    print(f"\nWITH Volume Filter:")
    print(f"  Total Trades: {len(all_with)}")
    print(f"  Win Rate: {wins_with/len(all_with)*100:.1f}%")
    print(f"  Total R: {sum(all_with):.2f}")
    print(f"  Avg R/T: {sum(all_with)/len(all_with):.3f}")
    
    print(f"\nWITHOUT Volume Filter:")
    print(f"  Total Trades: {len(all_without)}")
    print(f"  Win Rate: {wins_without/len(all_without)*100:.1f}%")
    print(f"  Total R: {sum(all_without):.2f}")
    print(f"  Avg R/T: {sum(all_without)/len(all_without):.3f}")
    
    impact = sum(all_with) - sum(all_without)
    pct = impact / abs(sum(all_without)) * 100 if sum(all_without) != 0 else 0
    
    print(f"\nVolume Filter Impact: {impact:+.2f}R ({pct:+.1f}%)")
    if impact > 0:
        print("✅ Volume filter ADDS edge")
    elif impact < 0:
        print("❌ Volume filter REMOVES edge")
    else:
        print("➖ Neutral impact")
else:
    print("Not enough data")

print("="*60)
