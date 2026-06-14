#!/usr/bin/env python3
"""
SPCX IPO Order Script - Run tomorrow when SPCX starts trading
Buy 4 shares at $136 limit order
"""

import time
from datetime import datetime
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# Live Alpaca credentials
LIVE_KEY = "AKHOSMJ7LAMPAWA2XFSL5W5TEL"
LIVE_SECRET = "GaHTUq3Yjh5MPp8c7yeB49gR5rAYWp9cXbvZ15GjCjxd"

def check_spcx_available():
    """Check if SPCX is available for trading"""
    try:
        trading_client = TradingClient(LIVE_KEY, LIVE_SECRET, paper=False)
        
        # Try to get SPCX asset info
        from alpaca.trading.requests import GetAssetRequest
        try:
            asset = trading_client.get_asset(GetAssetRequest(symbol="SPCX"))
            return asset.status.value == "active"
        except:
            return False
            
    except Exception as e:
        print(f"Error checking SPCX: {e}")
        return False

def place_spcx_order():
    """Place SPCX limit order at $136"""
    try:
        trading_client = TradingClient(LIVE_KEY, LIVE_SECRET, paper=False)
        
        # Get account info
        account = trading_client.get_account()
        print(f"Account: {account.id}")
        print(f"Buying Power: ${float(account.buying_power):,.2f}")
        
        # Place limit order
        order_request = LimitOrderRequest(
            symbol="SPCX",
            qty=4,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            limit_price=136.0
        )
        
        order = trading_client.submit_order(order_request)
        
        print(f"\n✅ SPCX IPO order placed!")
        print(f"Order ID: {order.id}")
        print(f"Symbol: {order.symbol}")
        print(f"Quantity: {order.qty}")
        print(f"Limit Price: ${order.limit_price}")
        print(f"Status: {order.status}")
        
        return order
        
    except Exception as e:
        print(f"❌ Error placing SPCX order: {e}")
        return None

def monitor_and_place_order():
    """Monitor for SPCX availability and place order"""
    print("🚀 SPCX IPO Order Monitor")
    print("=" * 40)
    print("Waiting for SPCX to become available...")
    
    attempts = 0
    max_attempts = 120  # Check for 2 hours max
    
    while attempts < max_attempts:
        attempts += 1
        print(f"Attempt {attempts}/{max_attempts} - {datetime.now().strftime('%H:%M:%S')}")
        
        if check_spcx_available():
            print("✅ SPCX is now available! Placing order...")
            order = place_spcx_order()
            if order:
                print(f"\n🎉 SPCX IPO order successful!")
                print(f"Order ID: {order.id}")
                print(f"4 shares at $136 = ${544.00}")
                break
        else:
            print("SPCX not available yet, waiting 1 minute...")
            time.sleep(60)
    
    if attempts >= max_attempts:
        print("⏰ Timeout: SPCX didn't become available within 2 hours")
        print("Try placing the order manually")

if __name__ == "__main__":
    print("SPCX IPO Order Script")
    print("Run this tomorrow morning when market opens")
    print("Will automatically place order when SPCX becomes available")
    print("\nTo run: python spcx_ipo_tomorrow.py")
    print("Or run now to start monitoring...")
    
    # Uncomment the line below to start monitoring immediately
    # monitor_and_place_order()
