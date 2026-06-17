"""
Download 6 months of 5m data for 500 stocks - save locally for fast backtesting
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time
import os

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Create data directory
DATA_DIR = 'c:/Users/tybre/Desktop/aivibe/boof_data'
os.makedirs(DATA_DIR, exist_ok=True)

# 500 stocks - S&P 500 core
STOCKS = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","NFLX","CRM",
    "AMD","INTC","QCOM","MU","TXN","ADI","MRVL","SNPS","CDNS","KLAC",
    "JPM","V","MA","BAC","GS","WFC","C","AXP","BLK","SPGI",
    "UNH","JNJ","LLY","PFE","ABBV","MRK","TMO","ABT","DHR","BMY",
    "AMGN","GILD","REGN","VRTX","ZTS","ISRG","ELV","CI","HUM","CVS",
    "WMT","COST","HD","PG","KO","PEP","MCD","NKE","TJX","LOW",
    "SBUX","TGT","DG","ROST","BKNG","MAR","HLT","ABNB","DASH","UBER",
    "XOM","CVX","COP","EOG","SLB","OXY","MPC","VLO","PSX","KMI",
    "GE","HON","UPS","BA","CAT","DE","LMT","NOC","RTX","UNP",
    "VZ","CMCSA","T","TMUS","CHTR","DIS","NWSA","FOXA","LUMN","S",
    "LIN","APD","SHW","FCX","NUE","DOW","PPG","DD","ECL","IFF",
    "PLD","AMT","CCI","SPG","PSA","WPC","O","EXR","AVB","EQR",
    "F","GM","STLA","RIVN","LCID","NIO","XPEV","LI",
    "DAL","UAL","AAL","LUV","ALK","JBLU","SAVE","ULCC","SKYW","CPA",
    "COIN","HOOD","MSTR","RIOT","MARA","HUT","BITF","CORZ","BTBT","WULF",
    "GME","AMC","PLTR","BB","NOK","SNDL","TLRY","ACB","CGC","CRON",
    "SOFI","LC","RBLX","HOOD","DLO","APP","FIGS","DOCS","TOST","BROS",
    "BABA","JD","PDD","NIO","XPEV","LI","BIDU","NTES","TCOM","VIPS",
    "TME","BILI","DIDI","DADA","BEKE","ZH","WB","MOMO","YY","SOHU",
    "SPY","QQQ","IWM","XLF","XLK","XLE","XLU","XLI","XLP","XLB"
]

def download_stock(symbol, start_date, end_date):
    """Download and save 5m data for one stock"""
    filename = f"{DATA_DIR}/{symbol}_5m_{start_date.date()}_to_{end_date.date()}.parquet"
    
    # Skip if already exists
    if os.path.exists(filename):
        print(f"  {symbol}: Already downloaded")
        return True
    
    try:
        df = fetch_alpaca_bars(symbol, start_date, end_date, '5Min', 
                               creds['api_key'], creds['secret_key'])
        
        if df is None or len(df) == 0:
            print(f"  {symbol}: No data")
            return False
        
        if 'open' not in df.columns:
            df.columns = [c.lower() for c in df.columns]
        
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        df['symbol'] = symbol
        
        # Save as parquet (fast + compressed)
        df.to_parquet(filename)
        print(f"  {symbol}: {len(df)} bars saved")
        return True
        
    except Exception as e:
        print(f"  {symbol}: ERROR - {str(e)[:50]}")
        return False

def main():
    # 6 months: Dec 2025 - May 2026
    start_date = datetime(2025, 12, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)
    
    print('='*80)
    print('DOWNLOADING 6 MONTHS OF 5M DATA')
    print(f'Period: {start_date.date()} to {end_date.date()}')
    print(f'Stocks: {len(STOCKS)}')
    print(f'Save location: {DATA_DIR}')
    print('='*80)
    
    success = 0
    failed = 0
    
    for i, sym in enumerate(STOCKS, 1):
        print(f"\n{i}/{len(STOCKS)}. {sym}...")
        
        if download_stock(sym, start_date, end_date):
            success += 1
        else:
            failed += 1
        
        time.sleep(0.1)  # Rate limit
    
    print('\n' + '='*80)
    print(f'DOWNLOAD COMPLETE:')
    print(f'Success: {success}/{len(STOCKS)}')
    print(f'Failed: {failed}/{len(STOCKS)}')
    print(f'Files saved to: {DATA_DIR}')
    print('='*80)

if __name__ == '__main__':
    main()
