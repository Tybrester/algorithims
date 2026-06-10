"""Test Databento API key"""
import requests

KEY = 'db-TevcgBq8wHEDTSh9QpQMjnXMayfqQ'
url = 'https://hist.databento.com/v0/timeseries.get_range'
headers = {'Authorization': KEY}
params = {
    'dataset': 'GLBX.MDP3',
    'symbols': 'ES.c.0',
    'schema': 'ohlcv-1m',
    'start': '2026-05-20T00:00:00',
    'end': '2026-05-21T23:59:59',
    'stype_in': 'raw_symbol'
}

print("Testing Databento API key...")
print(f"Key: {KEY[:10]}...{KEY[-5:]}")

r = requests.get(url, headers=headers, params=params, timeout=30)
print(f"\nStatus: {r.status_code}")

if r.status_code == 200:
    data = r.json()
    bars = data.get('data', [])
    print(f"✅ Success! Got {len(bars)} bars")
    if bars:
        print(f"First bar: {bars[0]}")
else:
    print(f"❌ Error: {r.text[:200]}")
