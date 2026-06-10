"""
View first hour (9:30-10:30) of 5m bars for 200 stocks
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# 200 stocks - mix of large cap and liquid names
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
    "VZ","CMCSA","T","TMUS","CHTR","DIS","NWSA","FOXA","LUMN",
    "LIN","APD","SHW","FCX","NUE","DOW","PPG","DD","ECL",
    "PLD","AMT","CCI","SPG","PSA","WPC","O","EXR","AVB","EQR",
    "F","GM","STLA","RIVN","LCID","NIO","XPEV","LI",
    "DAL","UAL","AAL","LUV","ALK","JBLU","SAVE","ULCC",
    "COIN","HOOD","MSTR","RIOT","MARA","HUT","BITF",
    "GME","AMC","PLTR","BB","NOK","TLRY","ACB",
    "SOFI","LC","RBLX","DLO","APP","FIGS","DOCS","TOST","BROS",
    "BABA","JD","PDD","BIDU","NTES","TCOM","VIPS","TME","BILI","BEKE",
    "SPY","QQQ","IWM","XLF","XLK","XLE","XLU","XLI","XLP","XLB"
]

test_date = datetime(2026, 1, 15, tzinfo=timezone.utc)
fetch_start = test_date - timedelta(days=5)
fetch_end = test_date + timedelta(days=1)

print('='*80)
print('FIRST HOUR VIEWER - 5m bars (9:30-10:30)')
print(f'Date: {test_date.date()}')
print(f'Stocks: {len(STOCKS)}')
print('='*80)

for i, sym in enumerate(STOCKS, 1):
    try:
        df = fetch_alpaca_bars(sym, fetch_start, fetch_end, '5Min', creds['api_key'], creds['secret_key'])
        
        if df is None or len(df) == 0:
            print(f"{i:3d}. {sym:6s} - NO DATA")
            continue
        
        if 'open' not in df.columns:
            df.columns = [c.lower() for c in df.columns]
        
        df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
        
        # Filter to test date and first hour
        day_data = df[df['timestamp'].dt.date == test_date.date()].reset_index(drop=True)
        
        if len(day_data) == 0:
            print(f"{i:3d}. {sym:6s} - NO DATA FOR DATE")
            continue
        
        # First hour = first 12 bars (5m each = 60 min)
        first_hour = day_data.iloc[:12]
        
        if len(first_hour) == 0:
            print(f"{i:3d}. {sym:6s} - NO FIRST HOUR DATA")
            continue
        
        # Calculate metrics
        open_price = first_hour['open'].iloc[0]
        close_price = first_hour['close'].iloc[-1]
        high = first_hour['high'].max()
        low = first_hour['low'].min()
        total_vol = first_hour['volume'].sum()
        pct_change = (close_price - open_price) / open_price * 100
        
        print(f"{i:3d}. {sym:6s} | Bars: {len(first_hour):2d} | "
              f"Open: {open_price:8.2f} | Close: {close_price:8.2f} | "
              f"Range: {low:8.2f}-{high:8.2f} | "
              f"Change: {pct_change:+6.2f}% | Vol: {total_vol:>12,}")
        
        time.sleep(0.05)
        
    except Exception as e:
        print(f"{i:3d}. {sym:6s} - ERROR: {str(e)[:30]}")

print('='*80)
print('Done')
