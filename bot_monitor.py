#!/usr/bin/env python3
"""
Live Bot Monitoring Dashboard - Real-time Setup Detection
Shows all symbols from BOOF23, BOOF30, BOOF31 with current setups and proximity to triggers
"""

import alpaca_trade_api as tradeapi
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import pytz
import json
import time
from flask import Flask, render_template_string, jsonify
import threading

app = Flask(__name__)

# Bot credentials
BOTS = {
    'BOOF23': {
        'api_key': 'PKLDR3B5YNRLB3TIL7ZLZLW7WH',
        'api_secret': 'BJkGMcbPudvadQxuvxuwVuprPquGDDE8bLwFPLuMxmiq',
        'symbols': ['TOST','HOOD','ORCL','MSFT','V','JPM','SOUN','PODD','ENTG','GE','MRNA','AI','PATH','GS','BSX','SIMO','SCHW','TEM','AMD','ABNB','NEM','GILD','MCHP','UNP','ETN','LRCX','SMTC','INCY','ITW','LLY','MAR','QRVO','MPC','BKR','TMO','CAT','NVDA','SOFI','XOM','DPZ','FCX','VRTX','S','CSCO','DE','HUM']
    },
    'BOOF30': {
        'api_key': 'PK7OQWKVUULJ7KRHMOQTUQS3QX',
        'api_secret': 'AFJBzr795JzeLwCtEMfyuHR7xE7xq1euTNCbYrD22xUd',
        'symbols': ['UPST','AFRM','PLTR','RBLX','LMND','ROOT','SOFI','HOOD','DASH','SNOW','NET','DDOG','CRWD','CFLT','SHOP','NVDA','AMD','AVGO','ARM','SMCI','MU','TSM','MRVL','ANET','COIN','MSTR','RIOT','MARA','HUT','CLSK','BTBT','BITF','IREN','RKLB','LUNR','ASTS','RDW','SPIR','SPCX','TSLA','RIVN','LCID','NIO','XPEV']
    },
    'BOOF31': {
        'api_key': 'PKY5XANXLZXX5HHRRA4PHAY2WV',
        'api_secret': 'DtYBZgpzVVRstALWcvyN9H7E827i4XPJZUsWs2sdhaC2',
        'symbols': ['AAPL','MSFT','NVDA','AMZN','META','GOOGL','TSLA','AVGO','AMD','NFLX','CRM','NOW','SNOW','PLTR','DDOG','MDB','CRWD','ZS','NET','SHOP','ADBE','INTU','PANW','TEAM','HUBS','UBER','ABNB','BKNG','RBLX','DASH','MELI','ETSY','JPM','GS','MS','AXP','SCHW','BLK','SPGI','LLY','NVO','ISRG','VRTX','REGN','MRNA','GILD','GEV','RTX','BA','CAT','DE','ETN','PH','TT','XOM','CVX','COP','SLB','HAL','OXY','EOG','MPC','TMUS','ROKU','SPOT','PINS','SNAP','RDDT','COIN','MSTR','HOOD','APP','SMCI','ARM','MU','QCOM','MRVL','TSM','ASML','AMAT','LRCX','KLAC','MCHP','ON','NXPI','SPY','QQQ','IWM','SMH','SOXX']
    }
}

# Global data storage
monitoring_data = {
    'last_update': None,
    'symbols': {},
    'bot_status': {}
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Live Bot Monitor - Real-time Setups</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #1a1a1a; color: #fff; }
        .header { text-align: center; margin-bottom: 30px; }
        .bot-section { margin-bottom: 30px; border: 1px solid #333; border-radius: 8px; padding: 15px; }
        .bot-title { font-size: 18px; font-weight: bold; color: #4CAF50; margin-bottom: 15px; }
        .symbol-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }
        .symbol-card { 
            background: #2a2a2a; 
            border: 1px solid #444; 
            border-radius: 6px; 
            padding: 10px; 
            font-size: 12px;
        }
        .symbol-name { font-weight: bold; color: #2196F3; }
        .setup-status { margin-top: 5px; }
        .setup-active { color: #4CAF50; font-weight: bold; }
        .setup-close { color: #FFC107; }
        .setup-inactive { color: #666; }
        .metrics { font-size: 10px; color: #999; margin-top: 3px; }
        .last-update { text-align: center; color: #666; margin-top: 20px; }
        .refresh-btn { 
            background: #4CAF50; 
            color: white; 
            border: none; 
            padding: 10px 20px; 
            border-radius: 4px; 
            cursor: pointer;
            margin: 10px;
        }
        .refresh-btn:hover { background: #45a049; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 Live Bot Monitor - Real-time Setups</h1>
        <button class="refresh-btn" onclick="location.reload()">🔄 Refresh Now</button>
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
                        html += `<div class="symbol-grid">`;
                        
                        for (const symbol of botData.symbols) {
                            const statusClass = symbol.setup_active ? 'setup-active' : 
                                               symbol.setup_close ? 'setup-close' : 'setup-inactive';
                            const statusText = symbol.setup_active ? '🚨 SETUP ACTIVE' :
                                              symbol.setup_close ? '⚠️ CLOSE TO SETUP' : '○ INACTIVE';
                            
                            html += `<div class="symbol-card">`;
                            html += `<div class="symbol-name">${symbol.symbol}</div>`;
                            html += `<div class="setup-status ${statusClass}">${statusText}</div>`;
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

class BotMonitor:
    def __init__(self):
        self.running = True
        
    def analyze_boof23_setup(self, symbol, api):
        """Analyze BOOF23 momentum setup"""
        try:
            bars = api.get_bars(symbol, '5Min', limit=50)
            if len(bars) < 20:
                return False, False, "Insufficient data"
            
            # Convert to DataFrame
            data = []
            for bar in bars:
                data.append([bar.t, bar.o, bar.h, bar.l, bar.c, bar.v])
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Calculate metrics
            df['sma20'] = df['close'].rolling(20).mean()
            df['volume_sma'] = df['volume'].rolling(20).mean()
            df['rsi'] = self.calculate_rsi(df['close'])
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            # BOOF23 momentum criteria
            price_above_sma = latest['close'] > latest['sma20']
            volume_surge = latest['volume'] > latest['volume_sma'] * 1.5
            rsi_ok = 30 < latest['rsi'] < 70
            momentum = (latest['close'] - prev['close']) / prev['close'] > 0.002
            
            setup_active = price_above_sma and volume_surge and rsi_ok and momentum
            setup_close = not setup_active and abs((latest['close'] - latest['sma20']) / latest['sma20']) < 0.01
            
            metrics = f"RSI: {latest['rsi']:.1f} | Vol: {latest['volume']/latest['volume_sma']:.1f}x | SMA: {((latest['close']/latest['sma20'])-1)*100:+.1f}%"
            
            return setup_active, setup_close, metrics
            
        except Exception as e:
            return False, False, f"Error: {str(e)[:30]}"
    
    def analyze_boof30_setup(self, symbol, api):
        """Analyze BOOF30 2-bar ignition setup"""
        try:
            bars = api.get_bars(symbol, '1Min', limit=30)
            if len(bars) < 25:
                return False, False, "Insufficient data"
            
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
                
                setup_active = pattern_met and score >= 3
                setup_close = not setup_active and score >= 2
                
                metrics = f"Score: {score}/4 | RVOL: {b1['rvol']:.1f} | Body1: {b1['body']*100:.2f}% | Body2: {b2['body']*100:.2f}%"
                
                return setup_active, setup_close, metrics
            
            return False, False, "Insufficient bars"
            
        except Exception as e:
            return False, False, f"Error: {str(e)[:30]}"
    
    def analyze_boof31_setup(self, symbol, api):
        """Analyze BOOF31 resistance sweep setup"""
        try:
            bars = api.get_bars(symbol, '5Min', limit=100)
            if len(bars) < 50:
                return False, False, "Insufficient data"
            
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
                    return True, False, metrics
                elif is_sweep:
                    metrics = f"Res: {resistance:.2f} | High: {current_bar['high']:.2f} | No close back"
                    return False, True, metrics
            
            # Check if near resistance
            latest = df.iloc[-1]
            resistance = df['resistance'].iloc[-2]
            near_resistance = latest['high'] > resistance * 0.998
            
            if near_resistance:
                metrics = f"Res: {resistance:.2f} | Current: {latest['high']:.2f} | Near res"
                return False, True, metrics
            
            return False, False, f"Res: {resistance:.2f} | Current: {latest['close']:.2f}"
            
        except Exception as e:
            return False, False, f"Error: {str(e)[:30]}"
    
    def calculate_rsi(self, prices, period=14):
        """Calculate RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def update_data(self):
        """Update monitoring data for all bots"""
        while self.running:
            try:
                data = {'bots': {}}
                
                for bot_name, bot_config in BOTS.items():
                    api = tradeapi.REST(bot_config['api_key'], bot_config['api_secret'], 'https://paper-api.alpaca.markets')
                    
                    symbols_data = []
                    for symbol in bot_config['symbols'][:20]:  # Limit to first 20 for performance
                        try:
                            if bot_name == 'BOOF23':
                                active, close, metrics = self.analyze_boof23_setup(symbol, api)
                            elif bot_name == 'BOOF30':
                                active, close, metrics = self.analyze_boof30_setup(symbol, api)
                            elif bot_name == 'BOOF31':
                                active, close, metrics = self.analyze_boof31_setup(symbol, api)
                            
                            symbols_data.append({
                                'symbol': symbol,
                                'setup_active': active,
                                'setup_close': close,
                                'metrics': metrics
                            })
                            
                        except Exception as e:
                            symbols_data.append({
                                'symbol': symbol,
                                'setup_active': False,
                                'setup_close': False,
                                'metrics': f"Error: {str(e)[:20]}"
                            })
                    
                    data['bots'][bot_name] = {
                        'total_symbols': len(bot_config['symbols']),
                        'symbols': symbols_data
                    }
                
                data['last_update'] = datetime.now().isoformat()
                monitoring_data.update(data)
                
            except Exception as e:
                print(f"Update error: {e}")
            
            time.sleep(30)  # Update every 30 seconds
    
    def start_monitoring(self):
        """Start the monitoring thread"""
        monitor_thread = threading.Thread(target=self.update_data, daemon=True)
        monitor_thread.start()

# Initialize and start monitoring
monitor = BotMonitor()
monitor.start_monitoring()

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/data')
def get_data():
    return jsonify(monitoring_data)

if __name__ == '__main__':
    print("🚀 Starting Bot Monitor on http://localhost:5000")
    print("📊 Monitoring all BOOF23, BOOF30, BOOF31 symbols")
    print("🔄 Auto-refresh every 30 seconds")
    app.run(host='0.0.0.0', port=5000, debug=False)
