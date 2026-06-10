"""Fetch missing symbols from Alpaca"""
import requests, pickle, os, time
import pandas as pd

API_KEY    = "AKXYPKTGTYKE2PN2GPP4U5VJHU"
API_SECRET = "6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W"
BASE_URL   = "https://data.alpaca.markets/v2/stocks/bars"
CACHE_DIR  = "boof_cache"
START      = "2025-01-01T00:00:00Z"
END        = "2026-12-31T23:59:59Z"

NEW_SYMBOLS = [
    # Semis
    "ENTG","LSCC","ALAB","FORM","AEHR","ACLS","SMTC","CRUS","SYNA","AMKR",
    # Biotech
    "DXCM","PODD","EW","ALGN","RMD","TECH","HOLX","INCY",
    # Fintech
    "NU","XYZ","TOST","PAYO","BILL",
    # Industrials
    "TT","AME","ROK","GWW","ODFL","UNP",
    # Travel
    "BKNG","EXPE","MAR","HLT",
]

def cache_file(sym):
    return f"{CACHE_DIR}/{sym}_2025-01-01_2026-12-31.pkl"

def fetch(sym):
    bars = []
    params = {
        "symbols": sym,
        "timeframe": "1Min",
        "start": START,
        "end": END,
        "limit": 10000,
        "adjustment": "raw",
        "feed": "iex",
    }
    headers = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": API_SECRET}
    page_token = None
    while True:
        if page_token:
            params["page_token"] = page_token
        r = requests.get(BASE_URL, params=params, headers=headers, timeout=30)
        if r.status_code != 200:
            print(f"  ERROR {sym}: {r.status_code} {r.text[:100]}")
            return None
        data = r.json()
        raw = data.get("bars", {}).get(sym, [])
        bars.extend(raw)
        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(0.2)
    if not bars:
        print(f"  NO DATA: {sym}")
        return None
    df = pd.DataFrame(bars)
    df['t'] = pd.to_datetime(df['t'], utc=True)
    df = df.set_index('t').rename(columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'})
    df = df[['open','high','low','close','volume']]
    return df

os.makedirs(CACHE_DIR, exist_ok=True)
missing = [s for s in NEW_SYMBOLS if not os.path.exists(cache_file(s))]
print(f"Need to fetch {len(missing)} symbols: {missing}\n")

for i, sym in enumerate(missing):
    print(f"[{i+1}/{len(missing)}] Fetching {sym}...", end=' ')
    df = fetch(sym)
    if df is not None:
        pickle.dump(df, open(cache_file(sym), 'wb'))
        print(f"OK ({len(df)} bars)")
    time.sleep(0.3)

print("\nDone.")
