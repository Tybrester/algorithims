#!/usr/bin/env python3
"""
Sync ALL Alpaca trades (live + paper) to JSON for website display
Run this on EC2 every minute via cron or manually
"""

import json
import os
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

# PAPER ACCOUNT 1 - Boof 23 & Boof 30
PAPER1_KEY = 'PK2O2N4OQ4PEATNTDN57MNSIB7'
PAPER1_SECRET = '894T7WQpHVjfLXitiv1cG1ZkGeQsegtWhA2jLocVfCnc'

# PAPER ACCOUNT 2 - Boof 29
PAPER2_KEY = 'PKU37C3QZHELGN2IDQLNYAEFJR'
PAPER2_SECRET = 'CTcQtRqgC5SkKxo9q7sAn8iwTZt5CWWtvueiPjvbC22w'

def fetch_trades(api_key, api_secret, account_type, days=2):
    """Fetch closed trades from Alpaca"""
    try:
        client = TradingClient(api_key, api_secret, paper=(account_type=='paper'))
        
        # Get orders from last N days
        after_date = datetime.now() - timedelta(days=days)
        
        orders = client.get_orders(
            filter=GetOrdersRequest(
                status=QueryOrderStatus.CLOSED,
                after=after_date
            )
        )
        
        trades = []
        for order in orders:
            if order.filled_qty and float(order.filled_qty) > 0:
                # Calculate P&L for closed positions
                pnl = 0
                if order.realized_pl:
                    pnl = float(order.realized_pl)
                
                trades.append({
                    'symbol': order.symbol,
                    'side': order.side.value,
                    'qty': float(order.filled_qty),
                    'entry_price': float(order.filled_avg_price),
                    'status': 'filled',
                    'submitted_at': str(order.submitted_at),
                    'filled_at': str(order.filled_at),
                    'pnl': pnl,
                    'account': account_type,
                    'source': 'bot' if account_type == 'paper' else 'manual'
                })
        
        return trades
    except Exception as e:
        print(f"Error fetching {account_type} trades: {e}")
        return []

def main():
    print(f"Fetching trades at {datetime.now()}...")
    
    all_trades = []
    
    # Fetch PAPER 2 trades (Boof 29)
    paper2_trades = fetch_trades(PAPER2_KEY, PAPER2_SECRET, 'paper2')
    all_trades.extend(paper2_trades)
    print(f"  Paper 2 (Boof 29) trades: {len(paper2_trades)}")
    
    # Fetch PAPER 1 trades (Boof 23 & 30)
    paper1_trades = fetch_trades(PAPER1_KEY, PAPER1_SECRET, 'paper1')
    all_trades.extend(paper1_trades)
    print(f"  Paper 1 (Boof 23/30) trades: {len(paper1_trades)}")
    
    # Sort by filled time
    all_trades.sort(key=lambda x: x['filled_at'], reverse=True)
    
    # Save to JSON
    output = {
        'last_updated': str(datetime.now()),
        'total_trades': len(all_trades),
        'paper1_count': len(paper1_trades),
        'paper2_count': len(paper2_trades),
        'trades': all_trades
    }
    
    output_path = os.path.expanduser('~/boof_bots/all_trades.json')
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"Saved to {output_path}")
    print(f"Total: {len(all_trades)} trades")

if __name__ == '__main__':
    main()
