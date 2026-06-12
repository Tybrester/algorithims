#!/usr/bin/env python3
"""Check Boof 30 status and trades"""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest, GetPositionsRequest
from alpaca.trading.enums import QueryOrderStatus
from datetime import datetime, timedelta

API_KEY = 'PK2O2N4OQ4PEATNTDN57MNSIB7'
API_SECRET = '894T7WQpHVjfLXitiv1cG1ZkGeQsegtWhA2jLocVfCnc'

client = TradingClient(API_KEY, API_SECRET, paper=True)

print("="*60)
print("BOOF 30 STATUS CHECK")
print("="*60)

# Check account
account = client.get_account()
print(f"\nAccount: {account.account_number}")
print(f"Equity: ${account.equity}")
print(f"Buying Power: ${account.buying_power}")

# Check positions
positions = client.get_all_positions()
print(f"\nOpen Positions: {len(positions)}")
for p in positions:
    print(f"  {p.symbol}: {p.qty} @ ${p.avg_entry_price} (Current: ${p.current_price}, P&L: ${p.unrealized_pl})")

# Check orders
print("\n--- Last 7 Days ---")
orders = client.get_orders(filter=GetOrdersRequest(
    status=QueryOrderStatus.ALL,
    after=datetime.now() - timedelta(days=7)
))

print(f"Total Orders: {len(orders)}")
for o in orders[:10]:
    print(f"  {o.symbol} {o.side.value} | Qty: {o.filled_qty}/{o.qty} | Status: {o.status.value} | Price: ${o.filled_avg_price}")

print("\n" + "="*60)
