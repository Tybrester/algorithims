#!/usr/bin/env python3
"""
Place SpaceX order on Alpaca LIVE Trading
Buy 4 shares at $136 for tomorrow
"""

import os
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# Live Alpaca credentials
LIVE_KEY = "AKHOSMJ7LAMPAWA2XFSL5W5TEL"
LIVE_SECRET = "GaHTUq3Yjh5MPp8c7yeB49gR5rAYWp9cXbvZ15GjCjxd"

def place_spacex_live_order():
    """Place limit order for SpaceX at $136 on live account"""
    try:
        # Initialize live trading client
        trading_client = TradingClient(LIVE_KEY, LIVE_SECRET, paper=False)
        
        # Get account info
        account = trading_client.get_account()
        print(f"Live Account: {account.id}")
        print(f"Buying Power: ${float(account.buying_power):,.2f}")
        print(f"Cash: ${float(account.cash):,.2f}")
        print(f"Portfolio Value: ${float(account.portfolio_value):,.2f}")
        
        # Order details
        symbol = "SPCE"  # SpaceX ticker
        qty = 4
        limit_price = 136.0
        total_cost = qty * limit_price
        
        print(f"\nPlacing LIVE order:")
        print(f"Symbol: {symbol}")
        print(f"Quantity: {qty} shares")
        print(f"Limit Price: ${limit_price}")
        print(f"Total Cost: ${total_cost:,.2f}")
        print("⚠️  THIS IS A LIVE ORDER - REAL MONEY WILL BE USED")
        
        # Confirm before placing
        input("\nPress Enter to confirm placing this LIVE order...")
        
        # Create limit order request
        limit_order_request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            limit_price=limit_price
        )
        
        # Submit the order
        order = trading_client.submit_order(limit_order_request)
        
        print(f"\n✅ LIVE order placed successfully!")
        print(f"Order ID: {order.id}")
        print(f"Status: {order.status}")
        print(f"Symbol: {order.symbol}")
        print(f"Quantity: {order.qty}")
        print(f"Order Type: {order.order_type}")
        print(f"Side: {order.side}")
        print(f"Limit Price: ${order.limit_price}")
        
        return order
        
    except Exception as e:
        print(f"❌ Error placing live order: {e}")
        return None

if __name__ == "__main__":
    print("SpaceX LIVE Order Placement - Alpaca LIVE Trading")
    print("=" * 60)
    print("⚠️  WARNING: This will place a REAL order with REAL money!")
    print("=" * 60)
    
    order = place_spacex_live_order()
    
    if order:
        print(f"\n📊 LIVE Order Summary:")
        print(f"- Order ID: {order.id}")
        print(f"- 4 shares of {order.symbol} at ${order.limit_price}")
        print(f"- Will execute tomorrow when price hits ${order.limit_price}")
        print(f"- Check Alpaca dashboard for order status")
        print(f"- REAL MONEY: ${float(order.limit_price) * int(order.qty):,.2f}")
    else:
        print("\n❌ LIVE order failed. Please check:")
        print("- Account balance")
        print("- Symbol ticker")
        print("- Market hours")
        print("- API credentials")
