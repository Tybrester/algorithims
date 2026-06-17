import requests

headers = {
    'APCA-API-KEY-ID': 'PKTAPRDPBBOKTQYZGNBDZJ6XJZ',
    'APCA-API-SECRET-KEY': '6tzye8uezFRCV13EwhUqft4BNV6cg47kC77WgRVVZrpi'
}

r = requests.get('https://paper-api.alpaca.markets/v2/account', headers=headers)
a = r.json()
print(f"Status:          {a.get('status')}")
print(f"Options level:   {a.get('options_approved_level')}")
print(f"Options trading: {a.get('options_trading_level')}")
print(f"Buying power:    ${float(a.get('buying_power',0)):,.2f}")
print(f"Equity:          ${float(a.get('equity',0)):,.2f}")
print(f"Pattern day trader: {a.get('pattern_day_trader')}")
