"""
Fetch 3-year data (2024-2026) for all Boof 29 symbols from Alpaca.
Skips symbols already cached for the full range.
"""
import requests, pickle, os, time
import pandas as pd

API_KEY    = "AKXYPKTGTYKE2PN2GPP4U5VJHU"
API_SECRET = "6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W"
BASE_URL   = "https://data.alpaca.markets/v2/stocks/bars"
CACHE_DIR  = "boof_cache"
START      = "2024-01-01T00:00:00Z"
END        = "2026-12-31T23:59:59Z"
CACHE_KEY  = "2024-01-01_2026-12-31"

SECTORS = {
    "Semiconductors": [
        "NVDA","AMD","AVGO","TSM","ASML","MU","AMAT","KLAC","LRCX",
        "MCHP","ADI","QCOM","NXPI","ON","MPWR","MRVL","INTC","ARM",
        "TER","SWKS","QRVO","GFS","WOLF","COHR","LSCC","AEHR",
        "ACLS","FORM","CRUS","SYNA","SMTC","AMKR","RMBS","UCTT",
        "ENTG","ALAB","CEVA","ICHR","VECO","ONTO","SIMO","HIMX",
        "PI","IPGP","DIOD","POWI","MTSI","AOSL",
    ],
    "AI/Software/Cloud": [
        "PLTR","APP","SNOW","CRWD","NET","DDOG","MDB","ZS",
        "PANW","FTNT","HUBS","DUOL","CFLT","ESTC","GTLB",
        "SMAR","AI","PATH","DOCN","MNDY","ASAN","TEAM",
        "SHOP","ROKU","SPOT","AFRM","UPST","BILL","TOST",
        "PAYO","CELH","HIMS","SOUN","IONQ","TEM","RKLB",
        "S","DOCU","OKTA","TWLO","FIVN","U","DMRC",
    ],
    "Mega-cap Tech": [
        "AAPL","MSFT","META","GOOGL","AMZN","TSLA","NFLX",
        "ORCL","CRM","ADBE","NOW","INTU","IBM","CSCO",
    ],
    "Fintech": [
        "HOOD","COIN","SOFI","AFRM","UPST","SQ","FI","PYPL",
        "NU","BILL","TOST","PAYO","MA","V","AXP","SCHW",
        "MS","GS","JPM","BAC","WFC","KKR","BX","BLK",
        "SPGI","MCO","CME","ICE","AJG","PGR","TRV","MMC",
        "AMP","RJF","STT","NTRS",
    ],
    "Biotech": [
        "LLY","NVO","ISRG","REGN","VRTX","MRNA","DXCM",
        "EW","ALGN","PODD","HOLX","RMD","TECH","BIO",
        "IDXX","ZTS","HCA","UNH","ELV","CI","HUM",
        "ABBV","AMGN","GILD","TMO","DHR","ABT","MDT",
        "BSX","SYK","INCY","BMRN","EXAS","RVTY",
        "WAT","IQV","CRL","ILMN","VEEV",
    ],
    "Industrials": [
        "CAT","ETN","PH","TT","URI","DE","ROP","PWR",
        "AME","HUBB","XYL","DOV","GWW","FAST","ODFL",
        "UNP","NSC","CSX","PCAR","ROK","JCI","IR",
        "CARR","GE","RTX","LMT","NOC","GD","TDG",
        "HEI","EXPD","CHRW","ITW","EMR","HON",
    ],
    "Travel/Consumer": [
        "UBER","ABNB","BKNG","EXPE","MAR","HLT",
        "RCL","CCL","NCLH","LVS","MGM","WYNN",
        "CMG","SBUX","MCD","YUM","DPZ",
        "LULU","NKE","ULTA","TJX","ROST","MELI",
        "ETSY","DASH","CAVA","WING","SG",
    ],
    "Energy/Materials": [
        "XOM","CVX","COP","EOG","SLB","MPC","VLO",
        "PSX","OXY","DVN","FANG","APA","HAL","BKR",
        "LNG","EQT","FCX","NUE","STLD","NEM",
        "LIN","APD","SHW","MLM","VMC",
    ],
}

ALL_SYMBOLS = list(dict.fromkeys(
    ["QQQ"] + [s for syms in SECTORS.values() for s in syms]
))

def cache_file(sym):
    return f"{CACHE_DIR}/{sym}_{CACHE_KEY}.pkl"

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
            print(f"  ERROR {sym}: {r.status_code} {r.text[:80]}")
            return None
        data = r.json()
        raw  = data.get("bars", {}).get(sym, [])
        bars.extend(raw)
        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(0.15)
    if not bars:
        print(f"  NO DATA: {sym}")
        return None
    df = pd.DataFrame(bars)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    df = df.set_index("t").rename(columns={"o":"open","h":"high","l":"low","c":"close","v":"volume"})
    return df[["open","high","low","close","volume"]]

os.makedirs(CACHE_DIR, exist_ok=True)
missing = [s for s in ALL_SYMBOLS if not os.path.exists(cache_file(s))]
print(f"Total symbols: {len(ALL_SYMBOLS)}")
print(f"Already cached: {len(ALL_SYMBOLS)-len(missing)}")
print(f"Need to fetch:  {len(missing)}\n")

for i, sym in enumerate(missing):
    print(f"[{i+1}/{len(missing)}] {sym}...", end=" ", flush=True)
    df = None
    for attempt in range(4):
        try:
            df = fetch(sym)
            break
        except Exception as e:
            print(f"  retry {attempt+1} ({e.__class__.__name__})...", end=" ", flush=True)
            time.sleep(3 * (attempt + 1))
    if df is not None:
        pickle.dump(df, open(cache_file(sym), "wb"))
        print(f"OK ({len(df):,} bars)")
    time.sleep(0.4)

print("\nAll done.")
