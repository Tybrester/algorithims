#!/usr/bin/env python3
"""
Cancel SpaceX order on Alpaca Paper Trading
"""

import os
from alpaca.trading.client import TradingClient

# Paper trading credentials
PAPER_KEY = os.environ.get("ALPACA_PAPER_KEY", "PKU37C3QZHELGN2IDQLNYAEFJR")
PAPER_SECRET = os.environ.get("ALPACA_PAPER_SECRET", "CTcQtRqgC5SkKxo9q7sAn8iwTZt5CWWtvueiPjvbC22w")

def cancel_spacex_order():
    """Cancel the SpaceX order"""
    try:
        # Initialize trading client
        trading_client = TradingClient(PAPER_KEY, PAPER_SECRET, paper=True)
        
        # Cancel the order
        order_id = "7c47314a-f86b-4061-99b1-6dd5d60e7056"
        trading_client.cancel_order_by_id(order_id)
        
        print(f"✅ Order {order_id} cancelled successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error cancelling order: {e}")
        return False

if __name__ == "__main__":
    print("Cancelling SpaceX Order - Paper Trading")
    print("=" * 50)
    
    success = cancel_spacex_order()
    
    if success:
        print("Paper trading order cancelled. Ready for live account order.")
    else:
        print("Failed to cancel. Order may already be filled or cancelled.")
