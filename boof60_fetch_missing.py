"""Fetch missing BOOF60 symbols and save as 5m parquets matching existing cache format."""
import requests, pandas as pd, time, os

API_KEY    = "PKKPME54QJA3KBPAJ3QZZOJXDF"
API_SECRET = "J4GMmrbXWozxgx5FoY6kZmeNj9tCG6kmDGmyEvnXrb1Y"
HEADERS    = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": API_SECRET}
DATA_URL   = "https://data.alpaca.markets"
OUT_DIR    = "boof_data"
START      = "2025-12-01"
END        = "2026-06-16"

MISSING = [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX','SPY'
]

def fetch_bars(sym):
    bars, params = [], {
        "timeframe": "5Min", "start": START, "end": END,
        "limit": 10000, "feed": "sip", "adjustment": "raw",
    }
    url = f"{DATA_URL}/v2/stocks/{sym}/bars"
    while True:
        r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        if r.status_code == 429: time.sleep(5); continue
        j = r.json()
        bars.extend(j.get("bars", []))
        token = j.get("next_page_token")
        if not token: break
        params["page_token"] = token
    if not bars: return pd.DataFrame()
    df = pd.DataFrame(bars)
    df['t'] = pd.to_datetime(df['t'], utc=True)
    df = df.set_index('t').rename(columns={'o':'Open','h':'High','l':'Low','c':'Close','v':'Volume'})
    return df[['Open','High','Low','Close','Volume']]

os.makedirs(OUT_DIR, exist_ok=True)
for sym in MISSING:
    path = f"{OUT_DIR}/{sym}_5m_6mo.parquet"
    print(f"  {sym}...", end="", flush=True)
    df = fetch_bars(sym)
    if df.empty:
        print(" NO DATA")
        continue
    df.to_parquet(path)
    print(f" {len(df)} bars → {path}")
    time.sleep(0.3)

print("\nDone.")
