"""Fetch missing symbols from Alpaca"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime
import pickle, os

KEY    = 'AKXYPKTGTYKE2PN2GPP4U5VJHU'
SECRET = '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'

MISSING = ['SWKS','QRVO','GFS','COHR','WOLF','AFRM','UPST','MA','V','ITW','FAST','PWR','CARR','JCI','IR','NOC','LMT','RTX','GD','BA','HUBB','XYL','DOV','TMO','DHR','ABT','MDT','BSX','SYK','ZTS','IDXX','HCA','HUM','UNH','CI','CVS','ELV','MCK','COR','CAH','OXY','DVN','FANG','APA','HAL','BKR','KMI','WMB','LNG','EQT','COST','WMT','TGT','HD','LOW','SBUX','MCD','CMG','NKE','LULU','TJX','ROST','DG','DLTR','BBY','ULTA','YUM','KO','PEP','PM','MO','CL','PG','NCLH','MAR','HLT','WYNN','MGM','LVS','GOOG','CMCSA','DIS','T','VZ','CHTR','TMUS','ROKU','SPOT','FOXA','WBD','LIN','APD','SHW','ECL','FCX','NEM','DD','DOW','NUE','STLD','MLM','VMC','NEE','SO','DUK','AEP','XEL','EXC','SRE']

start = datetime(2025, 1, 1)
end   = datetime(2026, 6, 9)
os.makedirs('boof_cache', exist_ok=True)

for i, sym in enumerate(MISSING):
    out = f"boof_cache/{sym}_2025-01-01_2026-12-31.pkl"
    if os.path.exists(out):
        print(f"  [{i+1}/{len(MISSING)}] {sym}: already cached")
        continue
    print(f"  [{i+1}/{len(MISSING)}] Fetching {sym}...", end=' ', flush=True)
    try:
        df = fetch_alpaca_bars(sym, start, end, '1Min', KEY, SECRET)
        if df is not None and len(df) > 0:
            with open(out, 'wb') as f:
                pickle.dump(df, f)
            print(f"OK ({len(df)} bars)")
        else:
            print("NO DATA")
    except Exception as e:
        print(f"ERROR: {e}")

print("\nDone.")
