#!/usr/bin/env python3
"""
Place pre-IPO order for SPCX on Alpaca LIVE Trading
Buy 4 shares at $136 for tomorrow's IPO
"""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# Live Alpaca credentials
LIVE_KEY = "AKHOSMJ7LAMPAWA2XFSL5W5TEL"
LIVE_SECRET = "GaHTUq3Yjh5MPp8c7yeB49gR5rAYWp9cXbvZ15GjCjxd"

def place_spacex_preipo_order():
    """Place pre-IPO limit order for SPCX at $136"""
    try:
        # Initialize live trading client
        trading_client = TradingClient(LIVE_KEY, LIVE_SECRET, paper=False)
        
        # Get account info
        account = trading_client.get_account()
        print(f"Live Account: {account.id}")
        print(f"Buying Power: ${float(account.buying_power):,.2f}")
        print(f"Cash: ${float(account.cash):,.2f}")
        
        # Pre-IPO order details
        symbol = "SPCX"  # SpaceX IPO ticker
        qty = 4
        limit_price = 136.0
        total_cost = qty * limit_price
        
        print(f"\nPlacing PRE-IPO order for tomorrow:")
        print(f"Symbol: {symbol}")
        print(f"Quantity: {qty} shares")
        print(f"Limit Price: ${limit_price}")
        print(f"Total Cost: ${total_cost:,.2f}")
        print("🚀 PRE-IPO ORDER - Will execute when SPCX starts trading")
        print("⚠️  THIS IS A LIVE ORDER - REAL MONEY WILL BE USED")
        
        # Try different time in force for pre-IPO
        time_in_force_options = [
            TimeInForce.DAY,
            TimeInForce.IOC,  # Immediate or Cancel
            TimeInForce.FOK   # Fill or Kill
        ]
        
        for tif in time_in_force_options:
            try:
                print(f"\nTrying with TimeInForce: {tif}")
                
                # Create limit order request
                limit_order_request = LimitOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=tif,
                    limit_price=limit_price
                )
                
                # Submit the order
                order = trading_client.submit_order(limit_order_request)
                
                print(f"\n✅ PRE-IPO order placed successfully!")
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
                print(f"Failed with {tif}: {e}")
                continue
        
        print("\n❌ All TimeInForce options failed")
        return None
        
    except Exception as e:
        print(f"❌ Error placing pre-IPO order: {e}")
        return None

if __name__ == "__main__":
    print("SpaceX PRE-IPO Order Placement - Alpaca LIVE Trading")
    print("=" * 60)
    print("🚀 Attempting to place pre-IPO order for SPCX")
    print("⚠️  WARNING: This will place a REAL order with REAL money!")
    print("=" * 60)
    
    order = place_spacex_preipo_order()
    
    if order:
        print(f"\n📊 PRE-IPO Order Summary:")
        print(f"- Order ID: {order.id}")
        print(f"- 4 shares of {order.symbol} at ${order.limit_price}")
        print(f"- Will execute when SPCX IPOs tomorrow")
        print(f"- Check Alpaca dashboard for order status")
        print(f"- REAL MONEY: ${float(order.limit_price) * int(order.qty):,.2f}")
    else:
        print("\n❌ PRE-IPO order failed. SPCX may not be available for pre-order.")
        print("Alternative: Place order tomorrow after IPO starts trading.")
