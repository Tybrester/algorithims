"""
test_options_order.py
Fires a real paper limit buy order for the nearest available put on TSLA
for each bot's paper account. Cancels immediately after placing.
"""
import requests, time

BOTS = {
    "BOOF23": ("PK22C5W5QQLOX2NLK3LDFVKCHW", "F8TBURaRyCVY3ekXEhJ7RkF3QXJbohRxDBxPg5LiS9nX"),
    "BOOF50": ("PKUE2IRNMB5ZUCK3ISPE3RIUX4", "Cb3rxrN6SNSYkpYEbVn96i7FjM5KCBcpR8bLq7hKRciB"),
    "BOOF51": ("PKWKMWREJIGNRMBOQWORXFRMDS",  "7vdjuEeeWhxSSGMUbefFQfjb4Z9rSuEzkASNDS6t74MW"),
}
BASE = "https://paper-api.alpaca.markets/v2"

def get_headers(key, secret):
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

def find_nearest_put(sym, headers):
    r = requests.get(f"{BASE}/options/contracts",
        params={"underlying_symbols": sym, "type": "put",
                "expiration_date_gte": "2026-06-16", "limit": 10},
        headers=headers)
    contracts = r.json().get("option_contracts", [])
    if not contracts:
        return None
    # pick smallest expiry, closest ATM strike
    contracts.sort(key=lambda c: (c["expiration_date"], abs(float(c["strike_price"]) - 409)))
    return contracts[0]

def place_and_cancel(bot, key, secret):
    hdrs = get_headers(key, secret)
    contract = find_nearest_put("TSLA", hdrs)
    if not contract:
        print(f"  {bot}: no contracts found")
        return
    sym    = contract["symbol"]
    expiry = contract["expiration_date"]
    strike = contract["strike_price"]
    print(f"  {bot}: placing BUY 1 {sym} (exp={expiry} strike={strike}) @ limit $0.01 ...")
    r = requests.post(f"{BASE}/orders", headers=hdrs, json={
        "symbol": sym, "qty": "1", "side": "buy",
        "type": "limit", "time_in_force": "day", "limit_price": "0.01"
    })
    order = r.json()
    if "id" not in order:
        print(f"  {bot}: ORDER FAILED — {order}")
        return
    oid = order["id"]
    print(f"  {bot}: order placed id={oid} status={order.get('status')} ✅")
    time.sleep(1)
    rc = requests.delete(f"{BASE}/orders/{oid}", headers=hdrs)
    print(f"  {bot}: cancel status={rc.status_code} {'✅' if rc.status_code in (200,204) else '❌'}")

print("=" * 55)
print("Options order test — paper accounts")
print("=" * 55)
for bot, (key, secret) in BOTS.items():
    print(f"\n{bot}:")
    place_and_cancel(bot, key, secret)

print("\nDone.")
