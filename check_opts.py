import requests
r = requests.get(
    "https://paper-api.alpaca.markets/v2/options/contracts",
    params={"underlying_symbols": "TSLA", "type": "put", "limit": 3, "expiration_date_gte": "2026-06-16"},
    headers={"APCA-API-KEY-ID": "PKWKMWREJIGNRMBOQWORXFRMDS", "APCA-API-SECRET-KEY": "7vdjuEeeWhxSSGMUbefFQfjb4Z9rSuEzkASNDS6t74MW"}
)
print(r.status_code)
print(r.text[:500])
