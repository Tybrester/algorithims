#!/usr/bin/env python3
"""
Place SpaceX order on Alpaca
Buy 4 shares at $136 for tomorrow
"""

import os
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

# Alpaca credentials
PAPER_KEY = os.environ.get("ALPACA_PAPER_KEY", "PKU37C3QZHELGN2IDQLNYAEFJR")
PAPER_SECRET = os.environ.get("ALPACA_PAPER_SECRET", "CTcQtRqgC5SkKxo9q7sAn8iwTZt5CWWtvueiPjvbC22w")

def place_spacex_order():
    """Place limit order for SpaceX at $136"""
    try:
        # Initialize trading client
        trading_client = TradingClient(PAPER_KEY, PAPER_SECRET, paper=True)
        
        # Get account info
        account = trading_client.get_account()
        print(f"Account: {account.id}")
        print(f"Buying Power: ${float(account.buying_power):,.2f}")
        print(f"Cash: ${float(account.cash):,.2f}")
        
        # Order details
        symbol = "SPCE"  # SpaceX ticker (assuming SPCE)
        qty = 4
        limit_price = 136.0
        total_cost = qty * limit_price
        
        print(f"\nPlacing order:")
        print(f"Symbol: {symbol}")
        print(f"Quantity: {qty} shares")
        print(f"Limit Price: ${limit_price}")
        print(f"Total Cost: ${total_cost:,.2f}")
        
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
        
        print(f"\n✅ Order placed successfully!")
        print(f"Order ID: {order.id}")
        print(f"Status: {order.status}")
        print(f"Symbol: {order.symbol}")
        print(f"Quantity: {order.qty}")
        print(f"Order Type: {order.order_type}")
        print(f"Side: {order.side}")
        print(f"Limit Price: ${order.limit_price}")
        
        return order
        
    except Exception as e:
        print(f"❌ Error placing order: {e}")
        return None

if __name__ == "__main__":
    print("SpaceX Order Placement - Alpaca Paper Trading")
    print("=" * 50)
    
    order = place_spacex_order()
    
    if order:
        print(f"\n📊 Order Summary:")
        print(f"- Order ID: {order.id}")
        print(f"- 4 shares of {order.symbol} at ${order.limit_price}")
        print(f"- Will execute tomorrow when price hits ${order.limit_price}")
        print(f"- Check Alpaca dashboard for order status")
    else:
        print("\n❌ Order failed. Please check:")
        print("- Account balance")
        print("- Symbol ticker (SpaceX might be different)")
        print("- Market hours")
