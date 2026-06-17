"""Fetch 2 years of 5m bars (Jun 2024 - Jun 2026) for all 60 BOOF60 symbols."""
import requests, pandas as pd, time, os

API_KEY    = "PKKPME54QJA3KBPAJ3QZZOJXDF"
API_SECRET = "J4GMmrbXWozxgx5FoY6kZmeNj9tCG6kmDGmyEvnXrb1Y"
HEADERS    = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": API_SECRET}
DATA_URL   = "https://data.alpaca.markets"
OUT_DIR    = "boof_data"
START      = "2024-06-01"
END        = "2026-06-16"
SUFFIX     = "_5m_2yr.parquet"

SYMBOLS = [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX',
    'SOFI','IONQ','RGTI','QUBT','ACHR','JOBY','LUNR','RDDT','CAVA','DUOL',
    'CELH','DKNG','MELI','SHOP','PYPL','SPOT','PINS','SNAP','LYFT','RIVN',
    'LCID','CHWY','SOUN','BBAI','AI','ASTS','RKLB','IREN','CORZ',
    'SPY','QQQ'
]

def fetch_bars(sym):
    bars, params = [], {
        "timeframe": "5Min", "start": START, "end": END,
        "limit": 10000, "feed": "sip", "adjustment": "raw",
    }
    url = f"{DATA_URL}/v2/stocks/{sym}/bars"
    while True:
        r = requests.get(url, headers=HEADERS, params=params, timeout=20)
        if r.status_code == 429: time.sleep(5); continue
        if r.status_code != 200: return pd.DataFrame()
        j = r.json()
        bars.extend(j.get("bars") or [])
        token = j.get("next_page_token")
        if not token: break
        params["page_token"] = token
    if not bars: return pd.DataFrame()
    df = pd.DataFrame(bars)
    df['t'] = pd.to_datetime(df['t'], utc=True)
    df = df.set_index('t').rename(columns={'o':'Open','h':'High','l':'Low','c':'Close','v':'Volume'})
    return df[['Open','High','Low','Close','Volume']]

os.makedirs(OUT_DIR, exist_ok=True)
already = [s for s in SYMBOLS if os.path.exists(os.path.join(OUT_DIR, f"{s}{SUFFIX}"))]
needed  = [s for s in SYMBOLS if s not in already]
print(f"Already cached: {len(already)} | Fetching: {len(needed)}\n")

for sym in needed:
    path = os.path.join(OUT_DIR, f"{sym}{SUFFIX}")
    print(f"  {sym}...", end="", flush=True)
    df = fetch_bars(sym)
    if df.empty: print(" NO DATA"); continue
    df.to_parquet(path)
    print(f" {len(df)} bars")
    time.sleep(0.3)

print("\nDone.")
