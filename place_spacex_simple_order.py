#!/usr/bin/env python3
"""
Simple SpaceX order - place and let it sit until SPCX becomes active
"""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# Live Alpaca credentials
LIVE_KEY = "AKHOSMJ7LAMPAWA2XFSL5W5TEL"
LIVE_SECRET = "GaHTUq3Yjh5MPp8c7yeB49gR5rAYWp9cXbvZ15GjCjxd"

def place_spacex_simple():
    """Just place the damn order"""
    try:
        trading_client = TradingClient(LIVE_KEY, LIVE_SECRET, paper=False)
        
        # Simple order
        order_request = LimitOrderRequest(
            symbol="SPCX",
            qty=4,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,  # Good til cancelled
            limit_price=136.0
        )
        
        order = trading_client.submit_order(order_request)
        print(f"✅ Order placed: {order.id}")
        return order
        
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    place_spacex_simple()
