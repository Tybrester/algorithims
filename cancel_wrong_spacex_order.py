#!/usr/bin/env python3
"""
Cancel wrong SpaceX order (SPCE) on Alpaca LIVE Trading
"""

from alpaca.trading.client import TradingClient

# Live Alpaca credentials
LIVE_KEY = "AKHOSMJ7LAMPAWA2XFSL5W5TEL"
LIVE_SECRET = "GaHTUq3Yjh5MPp8c7yeB49gR5rAYWp9cXbvZ15GjCjxd"

def cancel_wrong_order():
    """Cancel the wrong SPCE order"""
    try:
        # Initialize live trading client
        trading_client = TradingClient(LIVE_KEY, LIVE_SECRET, paper=False)
        
        # Cancel the wrong order
        order_id = "92593c40-ef46-4f11-a9fa-ae6a18436ce1"
        trading_client.cancel_order_by_id(order_id)
        
        print(f"✅ Wrong order {order_id} (SPCE) cancelled successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error cancelling wrong order: {e}")
        return False

if __name__ == "__main__":
    print("Cancelling Wrong SpaceX Order - LIVE Trading")
    print("=" * 50)
    
    success = cancel_wrong_order()
    
    if success:
        print("Wrong SPCE order cancelled. Ready to place correct SPCX order.")
    else:
        print("Failed to cancel. Order may already be filled or cancelled.")
