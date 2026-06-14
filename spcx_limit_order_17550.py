#!/usr/bin/env python3
"""
Place SPCX limit order at $175.50 on Alpaca LIVE Trading
SpaceX IPO - Buy limit order
"""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# Live Alpaca credentials
LIVE_KEY = "AKHOSMJ7LAMPAWA2XFSL5W5TEL"
LIVE_SECRET = "GaHTUq3Yjh5MPp8c7yeB49gR5rAYWp9cXbvZ15GjCjxd"

def place_spcx_limit_order():
    """Place SPCX limit order at $175.50"""
    try:
        # Initialize live trading client
        trading_client = TradingClient(LIVE_KEY, LIVE_SECRET, paper=False)
        
        # Get account info
        account = trading_client.get_account()
        print(f"Live Account: {account.id}")
        print(f"Buying Power: ${float(account.buying_power):,.2f}")
        print(f"Cash: ${float(account.cash):,.2f}")
        
        # Order details
        symbol = "SPCX"  # SpaceX IPO ticker
        qty = 4  # shares
        limit_price = 175.50
        total_cost = qty * limit_price
        
        print(f"\nPlacing SPCX limit order:")
        print(f"Symbol: {symbol} (SpaceX)")
        print(f"Quantity: {qty} shares")
        print(f"Limit Price: ${limit_price}")
        print(f"Total Cost: ${total_cost:,.2f}")
        print("🚀 SPACE X IPO ORDER")
        print("⚠️  THIS IS A LIVE ORDER - REAL MONEY WILL BE USED")
        
        # Create limit order request
        limit_order_request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,  # Good for the day
            limit_price=limit_price
        )
        
        # Submit the order
        order = trading_client.submit_order(limit_order_request)
        
        print(f"\n✅ SPCX order placed successfully!")
        print(f"Order ID: {order.id}")
        print(f"Status: {order.status}")
        print(f"Symbol: {order.symbol}")
        print(f"Quantity: {order.qty}")
        print(f"Order Type: {order.order_type}")
        print(f"Side: {order.side}")
        print(f"Limit Price: ${order.limit_price}")
        print(f"Time in Force: {order.time_in_force}")
        
        return order
        
    except Exception as e:
        print(f"❌ Error placing SPCX order: {e}")
        return None

if __name__ == "__main__":
    print("SPCX SpaceX IPO - Limit Order Placement")
    print("=" * 50)
    print("Placing buy limit order for 4 shares at $175.50")
    print("=" * 50)
    
    order = place_spcx_limit_order()
    
    if order:
        print(f"\n📊 ORDER CONFIRMATION:")
        print(f"- Order ID: {order.id}")
        print(f"- 4 shares of SPCX (SpaceX) at ${175.50}")
        print(f"- Total: ${702.00}")
        print(f"- Status: {order.status}")
        print(f"- Check Alpaca dashboard for order updates")
    else:
        print("\n❌ Order failed. SPCX may not be available yet.")
