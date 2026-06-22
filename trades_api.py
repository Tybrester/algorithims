#!/usr/bin/env python3
# Simple API to serve trades data to web interface

import json
import os
from datetime import datetime
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

@app.route('/api/trades')
def get_trades():
    """API endpoint to get trades data"""
    try:
        trades_file = '/home/ubuntu/website/logs/trades.json'
        
        if os.path.exists(trades_file):
            with open(trades_file, 'r') as f:
                trades = json.load(f)
        else:
            trades = []
        
        return jsonify({
            'trades': trades,
            'total_trades': len(trades),
            'last_update': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'trades': [],
            'total_trades': 0,
            'last_update': datetime.now().isoformat(),
            'error': str(e)
        })

if __name__ == '__main__':
    print("Starting Trades API on port 5001...")
    app.run(host='0.0.0.0', port=5001, debug=False)
