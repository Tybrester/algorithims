#!/usr/bin/env python3
# Website Trade Logger - Writes trades to website logs directory

import json
import alpaca_trade_api as tradeapi
from datetime import datetime, timedelta
import os

# All Alpaca account configurations - ALL 10 BOTS
ACCOUNTS = {
    # Instance A (13.59.123.163)
    'boof50': {
        'name': 'BOOF50',
        'key': 'PK2HCVPMLXNL7TPYECFGJOCCZK',
        'secret': '7PUiaNTfWhGYLQGfQFbMbuANWwPzzsy8nm23egqgdg4C',
        'paper': False
    },
    'boof70': {
        'name': 'BOOF70',
        'key': 'PK2HCVPMLXNL7TPYECFGJOCCZK',
        'secret': '7PUiaNTfWhGYLQGfQFbMbuANWwPzzsy8nm23egqgdg4C',
        'paper': False
    },
    'boof80': {
        'name': 'BOOF80',
        'key': 'PK2HCVPMLXNL7TPYECFGJOCCZK',
        'secret': '7PUiaNTfWhGYLQGfQFbMbuANWwPzzsy8nm23egqgdg4C',
        'paper': False
    },
    # Instance B (18.226.253.43)
    'boof90_stock': {
        'name': 'BOOF90 Stock',
        'key': 'AKLQTAXPZ3DRCU5A4TDPE5BOGU',
        'secret': '5uReJtv9vrz7wYrVo2TNwZ2qgY8PY3MHiEJmw9gyqRCk',
        'paper': False
    },
    'boof80_routed': {
        'name': 'BOOF80 Routed',
        'key': 'AKLQTAXPZ3DRCU5A4TDPE5BOGU',
        'secret': '5uReJtv9vrz7wYrVo2TNwZ2qgY8PY3MHiEJmw9gyqRCk',
        'paper': True
    },
    'boof60_stock': {
        'name': 'BOOF60 Stock',
        'key': 'AKLQTAXPZ3DRCU5A4TDPE5BOGU',
        'secret': '5uReJtv9vrz7wYrVo2TNwZ2qgY8PY3MHiEJmw9gyqRCk',
        'paper': True
    },
    # Instance C (3.15.40.190)
    'boof23_stock': {
        'name': 'BOOF23 Stock',
        'key': 'PK7J5ISZRPR7T665YI2T4LKN2N',
        'secret': 'BKMXwahnnfLj5M1bb9AgZdnqQFbtcK1zmnudL9PEGnDj',
        'paper': True
    },
    'boof23_options': {
        'name': 'BOOF23 Options',
        'key': 'PK7J5ISZRPR7T665YI2T4LKN2N',
        'secret': 'BKMXwahnnfLj5M1bb9AgZdnqQFbtcK1zmnudL9PEGnDj',
        'paper': True
    },
    'boof30_options': {
        'name': 'BOOF30 Options',
        'key': 'PK7J5ISZRPR7T665YI2T4LKN2N',
        'secret': 'BKMXwahnnfLj5M1bb9AgZdnqQFbtcK1zmnudL9PEGnDj',
        'paper': True
    },
    'boof90_options': {
        'name': 'BOOF90 Options',
        'key': 'PK7J5ISZRPR7T665YI2T4LKN2N',
        'secret': 'BKMXwahnnfLj5M1bb9AgZdnqQFbtcK1zmnudL9PEGnDj',
        'paper': True
    }
}

def get_api_client(account):
    """Get Alpaca API client for account"""
    base_url = "https://paper-api.alpaca.markets" if account['paper'] else "https://api.alpaca.markets"
    return tradeapi.REST(account['key'], account['secret'], base_url, api_version="v2")

def fetch_trades(account_id, account):
    """Fetch trades for a specific account"""
    try:
        api = get_api_client(account)
        
        # Get trades from last 24 hours
        end_date = datetime.now()
        start_date = end_date - timedelta(hours=24)
        
        # Get filled orders
        orders = api.list_orders(
            status='filled',
            limit=100,
            after=start_date,
            until=end_date,
            direction='desc'
        )
        
        trades = []
        for order in orders:
            trade_data = {
                'account': account['name'],
                'symbol': order.symbol,
                'side': order.side,
                'qty': float(order.filled_qty),
                'price': float(order.filled_avg_price) if order.filled_avg_price else 0,
                'time': order.filled_at.isoformat() if order.filled_at else '',
                'notional': float(order.notional) if order.notional else 0,
                'order_type': order.order_type,
                'limit_price': float(order.limit_price) if order.limit_price else None,
                'stop_price': float(order.stop_price) if order.stop_price else None
            }
            trades.append(trade_data)
        
        return trades
        
    except Exception as e:
        print(f"Error fetching trades for {account['name']}: {e}")
        return []

def write_trades_to_website(trades):
    """Write trades to website logs directory"""
    try:
        # Create logs directory if it doesn't exist
        logs_dir = '/home/ubuntu/website/logs'
        os.makedirs(logs_dir, exist_ok=True)
        
        # Write trades to JSON file
        trades_file = os.path.join(logs_dir, 'trades.json')
        
        # Load existing trades if file exists
        existing_trades = []
        if os.path.exists(trades_file):
            try:
                with open(trades_file, 'r') as f:
                    existing_trades = json.load(f)
            except:
                existing_trades = []
        
        # Add new trades (avoid duplicates)
        existing_times = {trade['time'] for trade in existing_trades}
        new_trades = [trade for trade in trades if trade['time'] not in existing_times]
        
        if new_trades:
            all_trades = existing_trades + new_trades
            # Sort by time (newest first)
            all_trades.sort(key=lambda x: x['time'], reverse=True)
            
            # Keep only last 1000 trades
            all_trades = all_trades[:1000]
            
            with open(trades_file, 'w') as f:
                json.dump(all_trades, f, indent=2)
            
            print(f"Added {len(new_trades)} new trades to website logs")
        
        # Write summary HTML file
        write_html_summary(trades, logs_dir)
        
    except Exception as e:
        print(f"Error writing trades to website: {e}")

def write_html_summary(trades, logs_dir):
    """Write HTML summary of recent trades"""
    html_file = os.path.join(logs_dir, 'trades.html')
    
    html_content = f'''
<!DOCTYPE html>
<html>
<head>
    <title>Boof Capital - Trade Logs</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .trade {{ border: 1px solid #ddd; margin: 10px 0; padding: 10px; }}
        .buy {{ background: #e8f5e8; }}
        .sell {{ background: #ffe8e8; }}
        .header {{ background: #f0f0f0; padding: 10px; font-weight: bold; }}
        .timestamp {{ color: #666; font-size: 0.9em; }}
        .account {{ font-weight: bold; color: #333; }}
        .symbol {{ font-weight: bold; }}
        .side-buy {{ color: green; font-weight: bold; }}
        .side-sell {{ color: red; font-weight: bold; }}
    </style>
</head>
<body>
    <h1>Boof Capital - Trade Logs</h1>
    <p>Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    
    <div class="header">Recent Trades (Last 24 Hours)</div>
'''
    
    if trades:
        for trade in trades[:50]:  # Show last 50 trades
            side_class = f"side-{trade['side']}"
            trade_class = trade['side']
            
            html_content += f'''
    <div class="trade {trade_class}">
        <div class="account">{trade['account']}</div>
        <div>
            <span class="symbol">{trade['symbol']}</span> - 
            <span class="{side_class}">{trade['side'].upper()}</span> - 
            {trade['qty']} shares @ ${trade['price']:.2f} - 
            Total: ${trade['notional']:.2f}
        </div>
        <div class="timestamp">{datetime.fromisoformat(trade['time']).strftime('%Y-%m-%d %H:%M:%S')}</div>
    </div>
'''
    else:
        html_content += '<p>No recent trades found.</p>'
    
    html_content += '''
</body>
</html>
'''
    
    with open(html_file, 'w') as f:
        f.write(html_content)

def main():
    """Main function to fetch and log trades"""
    print("Fetching trades from all accounts...")
    
    all_trades = []
    
    for account_id, account in ACCOUNTS.items():
        print(f"Fetching trades for {account['name']}...")
        trades = fetch_trades(account_id, account)
        all_trades.extend(trades)
        print(f"Found {len(trades)} trades")
    
    # Sort by time (newest first)
    all_trades.sort(key=lambda x: x['time'], reverse=True)
    
    print(f"Total trades: {len(all_trades)}")
    
    # Write to website
    write_trades_to_website(all_trades)
    
    print("Trade logging complete!")

if __name__ == '__main__':
    main()
