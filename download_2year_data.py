"""
BOOF 28 - Download 2 Years of Historical Data
For backtesting. Saves to boof_cache/ directory.
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import pickle
import os
import time

creds = {
    'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU',
    'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'
}

# All symbols to download
SYMBOLS = [
    # Semiconductors
    "NVDA", "AMD", "AVGO", "QCOM", "AMAT", "MU", "MRVL", "LRCX", "KLAC", "ASML", "TSM", "ARM", "INTC", "ON",
    "MCHP", "ADI", "NXPI", "TXN", "MPWR", "TER", "STM",
    # Hardware/Infrastructure
    "SMCI", "ANET", "DELL", "HPE",
    # Big Tech
    "MSFT", "GOOGL", "META", "AMZN", "AAPL", "TSLA", "NFLX",
    # SaaS/Cloud
    "CRM", "ADBE", "INTU", "NOW", "SHOP", "ORCL", "IBM", "CSCO",
    # Data/Analytics
    "PLTR", "SNOW", "DDOG", "MDB", "NET", "CRWD", "PANW", "ZS", "ESTC", "S",
    # AI/Automation
    "AI", "PATH", "DOCN", "FSLY", "AKAM",
    # Fintech/Payments
    "PYPL", "SQ", "HOOD", "COIN", "ADP", "FIS", "FI", "GPN", "JKHY",
    # Gig Economy
    "UBER", "ABNB", "DASH", "RBLX", "APP",
    # AdTech/Marketplace
    "TTD", "DUOL", "CELH", "CAVA",
    # Space/Defense
    "RKLB",
    # Pharma/Biotech
    "LLY", "NVO", "ABBV", "JNJ", "MRK", "AMGN", "GILD", "REGN", "VRTX", "ISRG",
    "BIIB", "BMY", "PFE", "MRNA", "NBIX",
    # Industrial
    "GE", "CAT", "ETN", "PH", "TT", "DE", "HON", "EMR", "ROP", "URI"
]

def download_symbol(symbol, start_date, end_date, cache_dir='boof_cache'):
    """Download 2 years of 5-minute data for a symbol"""
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = f"{cache_dir}/{symbol}_{start_date.date()}_{end_date.date()}.pkl"
    
    # Skip if already exists
    if os.path.exists(cache_file):
        print(f"  {symbol}: ALREADY CACHED")
        return True
    
    print(f"\n  Downloading {symbol}...", end=' ')
    
    all_data = []
    chunk_start = start_date
    chunk_size = 14  # 2-week chunks
    chunks_fetched = 0
    
    while chunk_start < end_date:
        chunk_end = min(chunk_start + timedelta(days=chunk_size), end_date)
        
        try:
            df = fetch_alpaca_bars(symbol, chunk_start, chunk_end, '5Min',
                                   creds['api_key'], creds['secret_key'])
            if df is not None and len(df) > 0:
                if 'open' not in df.columns:
                    df.columns = [c.lower() for c in df.columns]
                df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
                df = df.set_index('timestamp')
                df.index = df.index - pd.Timedelta(hours=5)  # ET
                all_data.append(df)
                chunks_fetched += 1
        except Exception as e:
            print(f"\n    Error in chunk {chunk_start.date()}: {str(e)[:60]}")
        
        chunk_start = chunk_end
        time.sleep(0.5)  # Rate limit
    
    if all_data:
        combined = pd.concat(all_data).sort_index()
        with open(cache_file, 'wb') as f:
            pickle.dump(combined, f)
        print(f"COMPLETE ({len(combined)} bars, {chunks_fetched} chunks)")
        return True
    else:
        print("FAILED - No data")
        return False

def main():
    # 2 years: Jan 1, 2025 - Dec 31, 2026
    start_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 12, 31, tzinfo=timezone.utc)
    
    print('='*100)
    print('BOOF 28 - 2 YEAR DATA DOWNLOAD')
    print('='*100)
    print(f'Period: {start_date.date()} to {end_date.date()}')
    print(f'Symbols: {len(SYMBOLS)}')
    print(f'Cache: boof_cache/')
    print(f'Bar Size: 5-minute')
    print('='*100)
    
    # Track progress
    success_count = 0
    fail_count = 0
    already_cached = 0
    
    for i, symbol in enumerate(SYMBOLS, 1):
        print(f'\n[{i}/{len(SYMBOLS)}] ', end='')
        
        # Check if already cached
        cache_file = f"boof_cache/{symbol}_{start_date.date()}_{end_date.date()}.pkl"
        if os.path.exists(cache_file):
            print(f"{symbol}: ALREADY CACHED ✓")
            already_cached += 1
            success_count += 1
            continue
        
        # Download
        if download_symbol(symbol, start_date, end_date):
            success_count += 1
        else:
            fail_count += 1
        
        # Progress summary every 10 symbols
        if i % 10 == 0:
            print(f'\n{"="*100}')
            print(f'PROGRESS: {i}/{len(SYMBOLS)} | Success: {success_count} | Failed: {fail_count} | Cached: {already_cached}')
            print(f'{"="*100}')
    
    # Final summary
    print('\n' + '='*100)
    print('DOWNLOAD COMPLETE')
    print('='*100)
    print(f'Total Symbols: {len(SYMBOLS)}')
    print(f'Successful: {success_count}')
    print(f'Failed: {fail_count}')
    print(f'Already Cached: {already_cached}')
    print(f'\nData Location: {os.path.abspath("boof_cache/")}')
    print(f'Files: boof_cache/SYMBOL_YYYY-MM-DD_YYYY-MM-DD.pkl')
    print('='*100)
    
    # List downloaded files
    print('\nDownloaded/Cached Files:')
    cache_dir = 'boof_cache'
    if os.path.exists(cache_dir):
        files = sorted([f for f in os.listdir(cache_dir) if f.endswith('.pkl')])
        for fname in files:
            size_mb = os.path.getsize(f'{cache_dir}/{fname}') / (1024*1024)
            print(f'  {fname} ({size_mb:.1f} MB)')

if __name__ == '__main__':
    main()
