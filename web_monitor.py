#!/usr/bin/env python3
"""
Web-based Bot Monitor for EC2 - Access via browser
Run this on EC2 and access via http://your-ec2-ip:8080
"""

import alpaca_trade_api as tradeapi
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from flask import Flask, render_template_string
import json
import threading
import time

app = Flask(__name__)

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

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Bot Monitor - Live Setups</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: 'Courier New', monospace; margin: 20px; background: #000; color: #00ff00; }
        .header { text-align: center; margin-bottom: 30px; border-bottom: 2px solid #00ff00; padding-bottom: 10px; }
        .bot-section { margin-bottom: 30px; border: 1px solid #00ff00; border-radius: 8px; padding: 15px; background: #0a0a0a; }
        .bot-title { font-size: 20px; font-weight: bold; color: #00ff00; margin-bottom: 15px; }
        .symbol-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
        .symbol-card { 
            background: #1a1a1a; 
            border: 1px solid #333; 
            border-radius: 6px; 
            padding: 10px; 
            font-size: 12px;
            font-family: 'Courier New', monospace;
        }
        .symbol-name { font-weight: bold; color: #00ffff; font-size: 14px; }
        .setup-active { color: #00ff00; font-weight: bold; }
        .setup-close { color: #ffff00; }
        .setup-inactive { color: #888888; }
        .setup-error { color: #ff0000; }
        .metrics { font-size: 10px; color: #cccccc; margin-top: 5px; }
        .last-update { text-align: center; color: #888888; margin-top: 20px; }
        .refresh-btn { 
            background: #00ff00; 
            color: black; 
            border: none; 
            padding: 10px 20px; 
            border-radius: 4px; 
            cursor: pointer;
            margin: 10px;
            font-weight: bold;
        }
        .refresh-btn:hover { background: #00cc00; }
        .summary { background: #0f0f0f; padding: 10px; margin: 10px 0; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 BOT MONITOR - LIVE SETUPS</h1>
        <button class="refresh-btn" onclick="location.reload()">🔄 REFRESH</button>
        <div id="last-update" class="last-update">Loading...</div>
    </div>

    <div id="bot-data">
        Loading bot data...
    </div>

    <script>
        function updateBotData() {
            fetch('/api/data')
                .then(response => response.json())
                .then(data => {
                    let html = '';
                    
                    for (const [botName, botData] of Object.entries(data.bots)) {
                        html += `<div class="bot-section">`;
                        html += `<div class="bot-title">📊 ${botName} - ${botData.total_symbols} symbols</div>`;
                        
                        // Summary
                        html += `<div class="summary">`;
                        html += `Active: <span style="color: #00ff00">${botData.active_setups}</span> | `;
                        html += `Close: <span style="color: #ffff00">${botData.close_setups}</span> | `;
                        html += `Inactive: <span style="color: #888888">${botData.inactive_setups}</span>`;
                        html += `</div>`;
                        
                        html += `<div class="symbol-grid">`;
                        
                        for (const symbol of botData.symbols) {
                            let statusClass = 'setup-inactive';
                            if (symbol.setup_active) statusClass = 'setup-active';
                            else if (symbol.setup_close) statusClass = 'setup-close';
                            else if (symbol.setup_error) statusClass = 'setup-error';
                            
                            const statusText = symbol.setup_active ? '🚨 SETUP ACTIVE' :
                                              symbol.setup_close ? '⚠️ CLOSE TO SETUP' :
                                              symbol.setup_error ? '❌ ERROR' : '○ INACTIVE';
                            
                            html += `<div class="symbol-card">`;
                            html += `<div class="symbol-name">${symbol.symbol}</div>`;
                            html += `<div class="${statusClass}">${statusText}</div>`;
                            html += `<div class="metrics">${symbol.metrics}</div>`;
                            html += `</div>`;
                        }
                        
                        html += `</div></div>`;
                    }
                    
                    document.getElementById('bot-data').innerHTML = html;
                    document.getElementById('last-update').innerHTML = 
                        `Last Update: ${new Date(data.last_update).toLocaleString()}`;
                })
                .catch(error => {
                    document.getElementById('bot-data').innerHTML = 'Error loading data: ' + error;
                });
        }
        
        // Auto-refresh every 30 seconds
        setInterval(updateBotData, 30000);
        updateBotData(); // Initial load
    </script>
</body>
</html>
"""

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
            return True, False, False, f"Vol: {latest['volume']/latest['volume_sma']:.1f}x | SMA: {((latest['close']/latest['sma20'])-1)*100:+.1f}%"
        elif abs((latest['close'] - latest['sma20']) / latest['sma20']) < 0.01:
            return False, True, False, f"Vol: {latest['volume']/latest['volume_sma']:.1f}x | SMA: {((latest['close']/latest['sma20'])-1)*100:+.1f}%"
        else:
            return False, False, False, f"Vol: {latest['volume']/latest['volume_sma']:.1f}x | SMA: {((latest['close']/latest['sma20'])-1)*100:+.1f}%"
        
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
            
            # Calculate score (0-7)
            score = 0
            avg_vol = df['volume'].rolling(20).mean().iloc[i]
            if not pd.isna(avg_vol) and avg_vol > 0:
                if current_bar['volume'] > avg_vol: score += 1
                upper_wick = current_bar['high'] - max(current_bar['open'], current_bar['close'])
                body = abs(current_bar['close'] - current_bar['open'])
                if body > 0 and upper_wick > body * 1.5: score += 1
                if current_bar['close'] < current_bar['open']: score += 1
                if current_bar['close'] < resistance: score += 1
                touches = int(np.sum(np.abs(df['high'].values - resistance) / resistance <= 0.002))
                if touches >= 3: score += 1
                if touches >= 4: score += 1
                score += 1  # timing point for being within window

            if is_sweep and is_close_back:
                return True, False, False, f"Res: {resistance:.2f} | Current: {current_bar['close']:.2f} | Swept: yes | Score: {score}/7"
            elif is_sweep:
                return False, True, False, f"Res: {resistance:.2f} | Current: {current_bar['close']:.2f} | Swept: partial | Score: {score}/7"

        latest = df.iloc[-1]
        resistance = df['resistance'].iloc[-2]
        pct = (latest['close'] - resistance) / resistance * 100
        near_resistance = latest['high'] > resistance * 0.998
        swept = latest['high'] > resistance * 1.002

        if near_resistance:
            return False, True, False, f"Res: {resistance:.2f} | Current: {latest['close']:.2f} | {pct:+.2f}% | Swept: {'yes' if swept else 'no'} | Score: —"

        return False, False, False, f"Res: {resistance:.2f} | Current: {latest['close']:.2f} | {pct:+.2f}% | Swept: no | Score: —"
        
    except Exception as e:
        return False, False, True, f"Error: {str(e)[:20]}"

def update_data():
    """Update monitoring data"""
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

# Start monitoring thread
monitor_thread = threading.Thread(target=update_data, daemon=True)
monitor_thread.start()

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/data')
def get_data():
    return jsonify(monitoring_data)

if __name__ == '__main__':
    print("🚀 Starting Web Bot Monitor on http://0.0.0.0:8080")
    print("📊 Access via: http://your-ec2-ip:8080")
    print("🔄 Auto-refresh every 30 seconds")
    app.run(host='0.0.0.0', port=8080, debug=False)
