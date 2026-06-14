#!/usr/bin/env python3
"""
Simple Bot Monitor - Live Setup Detection
Shows all symbols and their current setup status
"""

import alpaca_trade_api as tradeapi
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import pytz
import time
import json

# Bot credentials
BOTS = {
    'BOOF23': {
        'api_key': 'PKLDR3B5YNRLB3TIL7ZLZLW7WH',
        'api_secret': 'BJkGMcbPudvadQxuvxuwVuprPquGDDE8bLwFPLuMxmiq',
        'symbols': ['FCX','NVDA','SCHW','V','JPM','AMD','BSX','ENTG','PODD','MRNA','SOFI','GS','ETN','XOM','PATH','GILD','HUM','CAT']
    },
    'BOOF30': {
        'api_key': 'PK7OQWKVUULJ7KRHMOQTUQS3QX',
        'api_secret': 'AFJBzr795JzeLwCtEMfyuHR7xE7xq1euTNCbYrD22xUd',
        'symbols': ['HUT','BITF','BTBT','COIN','MSTR','SOFI','HOOD','PLTR','RBLX','NVDA','AMD','TSLA','SPCE','APP','SMCI']
    },
    'BOOF31': {
        'api_key': 'PKY5XANXLZXX5HHRRA4PHAY2WV',
        'api_secret': 'DtYBZgpzVVRstALWcvyN9H7E827i4XPJZUsWs2sdhaC2',
        'symbols': ['HUT','BITF','BTBT','COIN','MSTR','HOOD','RBLX','AMD','APP','SMCI','SPCE','NVDA','TSLA','PLTR','SOFI']
    }
}

def analyze_boof23_setup(symbol, api):
    """Analyze BOOF23 momentum setup"""
    try:
        bars = api.get_bars(symbol, '5Min', limit=50)
        if len(bars) < 20:
            return "○ INACTIVE", "Insufficient data"
        
        # Convert to DataFrame
        data = []
        for bar in bars:
            data.append([bar.t, bar.o, bar.h, bar.l, bar.c, bar.v])
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Calculate metrics
        df['sma20'] = df['close'].rolling(20).mean()
        df['volume_sma'] = df['volume'].rolling(20).mean()
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # BOOF23 momentum criteria
        price_above_sma = latest['close'] > latest['sma20']
        volume_surge = latest['volume'] > latest['volume_sma'] * 1.5
        momentum = (latest['close'] - prev['close']) / prev['close'] > 0.002
        
        if price_above_sma and volume_surge and momentum:
            status = "🚨 SETUP ACTIVE"
        elif abs((latest['close'] - latest['sma20']) / latest['sma20']) < 0.01:
            status = "⚠️ CLOSE TO SETUP"
        else:
            status = "○ INACTIVE"
        
        metrics = f"RSI: N/A | Vol: {latest['volume']/latest['volume_sma']:.1f}x | SMA: {((latest['close']/latest['sma20'])-1)*100:+.1f}%"
        
        return status, metrics
        
    except Exception as e:
        return "❌ ERROR", f"Error: {str(e)[:20]}"

def analyze_boof30_setup(symbol, api):
    """Analyze BOOF30 2-bar ignition setup"""
    try:
        bars = api.get_bars(symbol, '1Min', limit=30)
        if len(bars) < 25:
            return "○ INACTIVE", "Insufficient data"
        
        # Convert to DataFrame
        data = []
        for bar in bars:
            data.append([bar.t, bar.o, bar.h, bar.l, bar.c, bar.v])
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Calculate metrics
        df['vwap'] = ((df['high'] + df['low'] + df['close']) / 3 * df['volume']).cumsum() / df['volume'].cumsum()
        df['avg_vol'] = df['volume'].rolling(20, min_periods=20).mean()
        df['rvol'] = df['volume'] / df['avg_vol']
        df['body'] = abs(df['close'] - df['open']) / df['open']
        df['vwap_slope'] = df['vwap'].diff(10) / df['vwap'].shift(10) * 100
        
        # Check last 2 complete bars
        if len(df) >= 3:
            b1 = df.iloc[-3]  # 2 bars ago
            b2 = df.iloc[-2]  # 1 bar ago
            
            # BOOF30 criteria (with corrected parameters)
            rvol_ok = b1['rvol'] > 3
            body1_ok = b1['body'] * 100 > 0.5
            body2_ok = b2['body'] * 100 > 0.3
            vwap_ok = b1['vwap_slope'] > 0.25
            
            pattern_met = (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                          b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high'])
            
            score = (1 if rvol_ok else 0) + (1 if body1_ok else 0) + (1 if vwap_ok else 0) + (1 if body2_ok else 0)
            
            if pattern_met and score >= 3:
                status = "🚨 SETUP ACTIVE"
            elif score >= 2:
                status = "⚠️ CLOSE TO SETUP"
            else:
                status = "○ INACTIVE"
            
            metrics = f"Score: {score}/4 | RVOL: {b1['rvol']:.1f} | Body1: {b1['body']*100:.2f}% | Body2: {b2['body']*100:.2f}%"
            
            return status, metrics
        
        return "○ INACTIVE", "Insufficient bars"
        
    except Exception as e:
        return "❌ ERROR", f"Error: {str(e)[:20]}"

def analyze_boof31_setup(symbol, api):
    """Analyze BOOF31 resistance sweep setup"""
    try:
        bars = api.get_bars(symbol, '5Min', limit=100)
        if len(bars) < 50:
            return "○ INACTIVE", "Insufficient data"
        
        # Convert to DataFrame
        data = []
        for bar in bars:
            data.append([bar.t, bar.o, bar.h, bar.l, bar.c, bar.v])
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Calculate rolling resistance
        df['resistance'] = df['high'].rolling(20).max()
        
        # Check recent bars for sweep pattern
        for i in range(20, min(len(df) - 1, 30)):  # Check last 10 bars
            current_bar = df.iloc[i]
            resistance = df['resistance'].iloc[i - 1]
            
            # BOOF31 sweep criteria
            sweep_threshold = resistance * (1 + 0.002)  # 0.20% buffer
            is_sweep = current_bar['high'] > sweep_threshold
            is_close_back = current_bar['close'] < resistance
            
            if is_sweep and is_close_back:
                metrics = f"Res: {resistance:.2f} | High: {current_bar['high']:.2f} | Close: {current_bar['close']:.2f}"
                return "🚨 SETUP ACTIVE", metrics
            elif is_sweep:
                metrics = f"Res: {resistance:.2f} | High: {current_bar['high']:.2f} | No close back"
                return "⚠️ CLOSE TO SETUP", metrics
        
        # Check if near resistance
        latest = df.iloc[-1]
        resistance = df['resistance'].iloc[-2]
        near_resistance = latest['high'] > resistance * 0.998
        
        if near_resistance:
            metrics = f"Res: {resistance:.2f} | Current: {latest['high']:.2f} | Near res"
            return "⚠️ CLOSE TO SETUP", metrics
        
        metrics = f"Res: {resistance:.2f} | Current: {latest['close']:.2f}"
        return "○ INACTIVE", metrics
        
    except Exception as e:
        return "❌ ERROR", f"Error: {str(e)[:20]}"

def main():
    """Main monitoring loop"""
    print("🤖 Live Bot Monitor - Real-time Setups")
    print("=" * 60)
    print("Press Ctrl+C to stop")
    print()
    
    while True:
        try:
            print(f"\n🕐 Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("-" * 60)
            
            for bot_name, bot_config in BOTS.items():
                print(f"\n📊 {bot_name} - {len(bot_config['symbols'])} symbols")
                print("-" * 40)
                
                api = tradeapi.REST(bot_config['api_key'], bot_config['api_secret'], 'https://paper-api.alpaca.markets')
                
                active_setups = 0
                close_setups = 0
                
                for symbol in bot_config['symbols']:
                    try:
                        if bot_name == 'BOOF23':
                            status, metrics = analyze_boof23_setup(symbol, api)
                        elif bot_name == 'BOOF30':
                            status, metrics = analyze_boof30_setup(symbol, api)
                        elif bot_name == 'BOOF31':
                            status, metrics = analyze_boof31_setup(symbol, api)
                        
                        if "🚨" in status:
                            active_setups += 1
                            print(f"  {symbol:<6} | {status:<15} | {metrics}")
                        elif "⚠️" in status:
                            close_setups += 1
                            print(f"  {symbol:<6} | {status:<15} | {metrics}")
                        
                    except Exception as e:
                        continue
                
                if active_setups == 0 and close_setups == 0:
                    print(f"  No active setups detected")
                else:
                    print(f"  Summary: {active_setups} active, {close_setups} close to setup")
            
            print(f"\n⏰ Next update in 30 seconds...")
            time.sleep(30)
            
        except KeyboardInterrupt:
            print("\n\n🛑 Monitor stopped by user")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            time.sleep(10)

if __name__ == '__main__':
    main()
