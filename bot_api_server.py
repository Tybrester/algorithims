#!/usr/bin/env python3
"""
Bot API Server - Provides real-time data for the Logs page
Integrates with existing bot monitoring and serves data via REST API
"""

import alpaca_trade_api as tradeapi
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from flask import Flask, jsonify, render_template
import json
import threading
import time
import warnings
warnings.filterwarnings('ignore')

app = Flask(__name__)

# Enable CORS for all routes
from flask import Flask, jsonify, render_template
from flask_cors import CORS
CORS(app)

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

# Global data storage
monitoring_data = {'last_update': None, 'bots': {}}

def analyze_boof23_setup(symbol, api):
    """Analyze BOOF23 momentum setup"""
    try:
        bars = api.get_bars(symbol, '5Min', limit=50)
        if len(bars) < 20:
            return False, False, False, "Insufficient data"
        
        data = []
        for bar in bars:
            data.append([bar.t, bar.o, bar.h, bar.l, bar.c, bar.v])
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['sma20'] = df['close'].rolling(20).mean()
        df['volume_sma'] = df['volume'].rolling(20).mean()
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        price_above_sma = latest['close'] > latest['sma20']
        volume_surge = latest['volume'] > latest['volume_sma'] * 1.5
        momentum = (latest['close'] - prev['close']) / prev['close'] > 0.002
        
        if price_above_sma and volume_surge and momentum:
            return True, False, False, f"RSI: N/A | Vol: {latest['volume']/latest['volume_sma']:.1f}x | SMA: {((latest['close']/latest['sma20'])-1)*100:+.1f}%"
        elif abs((latest['close'] - latest['sma20']) / latest['sma20']) < 0.01:
            return False, True, False, f"RSI: N/A | Vol: {latest['volume']/latest['volume_sma']:.1f}x | SMA: {((latest['close']/latest['sma20'])-1)*100:+.1f}%"
        else:
            return False, False, False, f"RSI: N/A | Vol: {latest['volume']/latest['volume_sma']:.1f}x | SMA: {((latest['close']/latest['sma20'])-1)*100:+.1f}%"
        
    except Exception as e:
        return False, False, True, f"Error: {str(e)[:20]}"

def analyze_boof30_setup(symbol, api):
    """Analyze BOOF30 2-bar ignition setup"""
    try:
        bars = api.get_bars(symbol, '1Min', limit=30)
        if len(bars) < 25:
            return False, False, False, "Insufficient data"
        
        data = []
        for bar in bars:
            data.append([bar.t, bar.o, bar.h, bar.l, bar.c, bar.v])
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['vwap'] = ((df['high'] + df['low'] + df['close']) / 3 * df['volume']).cumsum() / df['volume'].cumsum()
        df['avg_vol'] = df['volume'].rolling(20, min_periods=20).mean()
        df['rvol'] = df['volume'] / df['avg_vol']
        df['body'] = abs(df['close'] - df['open']) / df['open']
        df['vwap_slope'] = df['vwap'].diff(10) / df['vwap'].shift(10) * 100
        
        if len(df) >= 3:
            b1 = df.iloc[-3]
            b2 = df.iloc[-2]
            
            rvol_ok = b1['rvol'] > 3
            body1_ok = b1['body'] * 100 > 0.5
            body2_ok = b2['body'] * 100 > 0.3
            vwap_ok = b1['vwap_slope'] > 0.25
            
            pattern_met = (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                          b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high'])
            
            score = (1 if rvol_ok else 0) + (1 if body1_ok else 0) + (1 if vwap_ok else 0) + (1 if body2_ok else 0)
            
            if pattern_met and score >= 3:
                return True, False, False, f"Score: {score}/4 | RVOL: {b1['rvol']:.1f} | Body1: {b1['body']*100:.2f}%"
            elif score >= 2:
                return False, True, False, f"Score: {score}/4 | RVOL: {b1['rvol']:.1f} | Body1: {b1['body']*100:.2f}%"
            else:
                return False, False, False, f"Score: {score}/4 | RVOL: {b1['rvol']:.1f} | Body1: {b1['body']*100:.2f}%"
        
        return False, False, False, "Insufficient bars"
        
    except Exception as e:
        return False, False, True, f"Error: {str(e)[:20]}"

def analyze_boof31_setup(symbol, api):
    """Analyze BOOF31 resistance sweep setup"""
    try:
        bars = api.get_bars(symbol, '5Min', limit=100)
        if len(bars) < 50:
            return False, False, False, "Insufficient data"
        
        data = []
        for bar in bars:
            data.append([bar.t, bar.o, bar.h, bar.l, bar.c, bar.v])
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['resistance'] = df['high'].rolling(20).max()
        
        for i in range(20, min(len(df) - 1, 30)):
            current_bar = df.iloc[i]
            resistance = df['resistance'].iloc[i - 1]
            
            sweep_threshold = resistance * (1 + 0.002)
            is_sweep = current_bar['high'] > sweep_threshold
            is_close_back = current_bar['close'] < resistance
            
            if is_sweep and is_close_back:
                return True, False, False, f"Res: {resistance:.2f} | High: {current_bar['high']:.2f} | Close: {current_bar['close']:.2f}"
            elif is_sweep:
                return False, True, False, f"Res: {resistance:.2f} | High: {current_bar['high']:.2f} | No close back"
        
        latest = df.iloc[-1]
        resistance = df['resistance'].iloc[-2]
        near_resistance = latest['high'] > resistance * 0.998
        
        if near_resistance:
            return False, True, False, f"Res: {resistance:.2f} | Current: {latest['high']:.2f} | Near res"
        
        return False, False, False, f"Res: {resistance:.2f} | Current: {latest['close']:.2f}"
        
    except Exception as e:
        return False, False, True, f"Error: {str(e)[:20]}"

def update_data():
    """Update monitoring data continuously"""
    while True:
        try:
            data = {'bots': {}}
            
            for bot_name, bot_config in BOTS.items():
                api = tradeapi.REST(bot_config['api_key'], bot_config['api_secret'], 'https://paper-api.alpaca.markets')
                
                symbols_data = []
                active_setups = 0
                close_setups = 0
                inactive_setups = 0
                
                for symbol in bot_config['symbols']:
                    try:
                        if bot_name == 'BOOF23':
                            active, close, error, metrics = analyze_boof23_setup(symbol, api)
                        elif bot_name == 'BOOF30':
                            active, close, error, metrics = analyze_boof30_setup(symbol, api)
                        elif bot_name == 'BOOF31':
                            active, close, error, metrics = analyze_boof31_setup(symbol, api)
                        
                        if active:
                            active_setups += 1
                        elif close:
                            close_setups += 1
                        else:
                            inactive_setups += 1
                        
                        symbols_data.append({
                            'symbol': symbol,
                            'setup_active': active,
                            'setup_close': close,
                            'setup_error': error,
                            'metrics': metrics
                        })
                        
                    except Exception as e:
                        symbols_data.append({
                            'symbol': symbol,
                            'setup_active': False,
                            'setup_close': False,
                            'setup_error': True,
                            'metrics': f"Error: {str(e)[:20]}"
                        })
                
                data['bots'][bot_name] = {
                    'total_symbols': len(bot_config['symbols']),
                    'active_setups': active_setups,
                    'close_setups': close_setups,
                    'inactive_setups': inactive_setups,
                    'symbols': symbols_data
                }
            
            data['last_update'] = datetime.now().isoformat()
            monitoring_data.update(data)
            
        except Exception as e:
            print(f"Update error: {e}")
        
        time.sleep(30)

@app.route('/api/bot-data')
def get_bot_data():
    """API endpoint for bot monitoring data"""
    return jsonify(monitoring_data)

@app.route('/logs')
def logs_page():
    """Serve the logs page"""
    return render_template('logs.html')

def start_monitoring():
    """Start the background monitoring thread"""
    monitor_thread = threading.Thread(target=update_data, daemon=True)
    monitor_thread.start()
    print("🤖 Bot monitoring started")

if __name__ == '__main__':
    print("🚀 Starting Bot API Server on http://localhost:5000")
    print("📊 Logs page: http://localhost:5000/logs")
    print("🔄 API endpoint: http://localhost:5000/api/bot-data")
    
    start_monitoring()
    app.run(host='0.0.0.0', port=5000, debug=False)
