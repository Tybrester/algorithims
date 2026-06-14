#!/usr/bin/env python3
"""
Cancel SPCE order on Alpaca LIVE Trading
"""

from alpaca.trading.client import TradingClient

# Live Alpaca credentials
LIVE_KEY = "AKHOSMJ7LAMPAWA2XFSL5W5TEL"
LIVE_SECRET = "GaHTUq3Yjh5MPp8c7yeB49gR5rAYWp9cXbvZ15GjCjxd"

def cancel_spce_order():
    """Cancel the SPCE live order"""
    try:
        trading_client = TradingClient(LIVE_KEY, LIVE_SECRET, paper=False)
        
        # Get all open orders to find the SPCE order
        orders = trading_client.get_orders()
        spce_order = None
        
        for order in orders:
            if order.symbol == "SPCE":
                spce_order = order
                break
        
        if spce_order:
            trading_client.cancel_order_by_id(spce_order.id)
            print(f"✅ Cancelled SPCE order: {spce_order.id}")
            return True
        else:
            print("No open SPCE order found")
            return False
            
    except Exception as e:
        print(f"❌ Error cancelling SPCE order: {e}")
        return False

if __name__ == "__main__":
    print("Cancelling SPCE order - LIVE Trading")
    cancel_spce_order()
