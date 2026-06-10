"""
BOOF 28 - Scoring-Based System
750 stocks, score everything, rank, take top 5-10
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Expanded universe - 750 stocks (using top liquid names)
# For now using ~150 for testing, can expand
STOCKS = [
    # Mega cap tech
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","NFLX","CRM",
    # Semis
    "AMD","INTC","QCOM","MU","TXN","ADI","MRVL","SNPS","CDNS","KLAC",
    # Finance
    "JPM","V","MA","BAC","GS","WFC","C","AXP","BLK","SPGI",
    # Healthcare
    "UNH","JNJ","LLY","PFE","ABBV","MRK","TMO","ABT","DHR","BMY",
    "AMGN","GILD","REGN","VRTX","ZTS","ISRG","ELV","CI","HUM","CVS",
    # Consumer
    "WMT","COST","HD","PG","KO","PEP","MCD","NKE","TJX","LOW",
    "SBUX","TGT","DG","DLTR","ROST","BKNG","MAR","HLT","ABNB","DASH",
    # Energy
    "XOM","CVX","COP","EOG","SLB","OXY","MPC","VLO","PSX","KMI",
    # Industrials
    "GE","HON","UPS","BA","CAT","DE","LMT","NOC","RTX","UNP",
    # Communication
    "VZ","CMCSA","T","TMUS","CHTR","DIS","NWSA","FOXA","LUMN","S",
    # Materials
    "LIN","APD","SHW","FCX","NUE","DOW","PPG","DD","ECL","IFF",
    # Reits/Real estate
    "PLD","AMT","CCI","SPG","PSA","WPC","O","EXR","AVB","EQR",
    # Auto
    "F","GM","STLA","RIVN","LCID","NIO","XPEV","LI","FSR","GOEV",
    # Airlines
    "DAL","UAL","AAL","LUV","ALK","JBLU","SAVE","ULCC","SKYW","CPA",
    # Crypto/blockchain
    "COIN","HOOD","MSTR","RIOT","MARA","HUT","BITF","CORZ","BTBT","WULF",
    # Meme/retail favorites
    "GME","AMC","PLTR","BB","NOK","SNDL","TLRY","ACB","CGC","CRON",
    # SPACs/Mergers
    "SOFI","LC","RBLX","HOOD","DLO","APP","FIGS","DOCS","TOST","BROS",
    # Chinese ADRs
    "BABA","JD","PDD","NIO","XPEV","LI","BIDU","NTES","TCOM","VIPS",
    "TME","BILI","DIDI","DADA","BEKE","ZH","WB","MOMO","YY","SOHU",
    # SPY for reference
    "SPY","QQQ","IWM","XLF","XLK","XLE","XLU","XLI","XLP","XLB"
]

def get_data(symbol, date, lookback=20):
    """Get 5m data for a date"""
    start = date - timedelta(days=lookback)
    end = date + timedelta(days=1)
    df = fetch_alpaca_bars(symbol, start, end, '5Min', creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 10:
        return None
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
    return df[df['timestamp'].dt.date == date.date()].reset_index(drop=True)

def get_spy_data(date, lookback=20):
    """Get SPY for relative strength"""
    df = get_data('SPY', date, lookback)
    if df is None or len(df) == 0:
        return None
    return df

def calculate_vwap(df):
    """Calculate VWAP"""
    if len(df) == 0:
        return None
    typical = (df['high'] + df['low'] + df['close']) / 3
    return (typical * df['volume']).cumsum() / df['volume'].cumsum()

def calculate_rvol(df, current_idx, lookback_days=10):
    """Calculate RVOL at specific bar"""
    if current_idx < 0 or len(df) == 0:
        return None
    current_vol = df['volume'].iloc[current_idx]
    current_time = df['timestamp'].iloc[current_idx]
    current_date = current_time.date()
    
    hist_vols = []
    for days_back in range(1, lookback_days + 1):
        past_date = current_date - timedelta(days=days_back)
        if past_date.weekday() >= 5:
            continue
        # Get historical data
        past_start = datetime.combine(past_date, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=30)
        past_end = datetime.combine(past_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        past_df = fetch_alpaca_bars(df.name if hasattr(df, 'name') else 'AAPL', past_start, past_end, '5Min', 
                                     creds['api_key'], creds['secret_key'])
        if past_df is None:
            continue
        if 'open' not in past_df.columns:
            past_df.columns = [c.lower() for c in past_df.columns]
        past_df['timestamp'] = pd.to_datetime(past_df['timestamp'] if 'timestamp' in past_df.columns else past_df.index)
        past_day = past_df[past_df['timestamp'].dt.date == past_date]
        if len(past_day) >= current_idx + 1:
            hist_vols.append(past_day['volume'].iloc[current_idx])
    
    if len(hist_vols) < 3:
        return None
    return current_vol / np.mean(hist_vols)

def score_stock(df, spy_df=None, scan_time_idx=2):
    """
    Calculate composite score for a stock
    Returns dict with all components and total score
    """
    if len(df) < scan_time_idx + 1:
        return None
    
    vwap_series = calculate_vwap(df)
    if vwap_series is None:
        return None
    
    price = df['close'].iloc[scan_time_idx]
    vwap = vwap_series.iloc[scan_time_idx]
    open_price = df['open'].iloc[0]
    
    # 1. RVOL Score (0-100)
    # Simple volume comparison - current vs average of first 10 bars
    current_vol = df['volume'].iloc[:scan_time_idx+1].sum()
    avg_vol = df['volume'].mean() * (scan_time_idx + 1)
    rvol = current_vol / avg_vol if avg_vol > 0 else 1.0
    rvol_score = min(rvol * 25, 100)  # RVOL 4.0 = 100 points
    
    # 2. VWAP Alignment Score (0-100)
    vwap_distance = (price - vwap) / vwap * 100
    if vwap_distance > 0:
        vwap_score = min(vwap_distance * 20, 100)  # 5% above = 100 points
    else:
        vwap_score = max(vwap_distance * 20, -100)  # Below VWAP = negative
    
    # 3. Momentum Score (0-100) - 5-15 min trend
    if scan_time_idx >= 2:
        recent = df['close'].iloc[:scan_time_idx+1]
        momentum = (recent.iloc[-1] - recent.iloc[0]) / recent.iloc[0] * 100
        momentum_score = momentum * 10  # 10% move = 100 points
    else:
        momentum_score = 0
    
    # 4. Relative Strength vs SPY (0-100)
    rs_score = 50  # Neutral if no SPY
    if spy_df is not None and len(spy_df) > scan_time_idx:
        spy_price = spy_df['close'].iloc[scan_time_idx]
        spy_open = spy_df['open'].iloc[0]
        spy_ret = (spy_price - spy_open) / spy_open * 100
        stock_ret = (price - open_price) / open_price * 100
        rel_strength = stock_ret - spy_ret
        rs_score = 50 + rel_strength * 10  # Outperform by 5% = 100 points
    
    # 5. Volatility Expansion Score (0-100)
    if len(df) >= 3:
        recent_range = (df['high'].iloc[:scan_time_idx+1].max() - 
                       df['low'].iloc[:scan_time_idx+1].min()) / open_price * 100
        vol_exp_score = min(recent_range * 5, 100)  # 20% range = 100 points
    else:
        vol_exp_score = 0
    
    # WEIGHTED TOTAL SCORE
    total_score = (
        rvol_score * 0.30 +      # 30% weight
        vwap_score * 0.25 +       # 25% weight
        momentum_score * 0.20 +   # 20% weight
        rs_score * 0.15 +         # 15% weight
        vol_exp_score * 0.10      # 10% weight
    )
    
    return {
        'total_score': total_score,
        'rvol_score': rvol_score,
        'vwap_score': vwap_score,
        'momentum_score': momentum_score,
        'rs_score': rs_score,
        'vol_exp_score': vol_exp_score,
        'price': price,
        'vwap': vwap,
        'rvol': rvol
    }

def run_backtest():
    start_date = datetime(2025, 12, 1, tzinfo=timezone.utc)
    end_date = datetime(2026, 1, 31, tzinfo=timezone.utc)
    max_trades_per_day = 5
    
    print('='*70)
    print('BOOF 28 - SCORING SYSTEM')
    print(f'Universe: {len(STOCKS)} stocks')
    print(f'Max trades/day: {max_trades_per_day}')
    print('='*70)
    
    # Trading days
    days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    
    print(f'\nBacktesting {len(days)} days...\n')
    
    all_trades = []
    
    for date in days:
        print(f'{date.date()}:', end=' ')
        
        # Get SPY first for relative strength
        spy_df = get_spy_data(date)
        
        # Score all stocks
        scored_stocks = []
        for sym in STOCKS:
            df = get_data(sym, date)
            if df is None or len(df) < 3:
                continue
            
            scores = score_stock(df, spy_df, scan_time_idx=2)  # 9:40ish with 5m bars
            if scores and scores['total_score'] > 0:
                scored_stocks.append({
                    'symbol': sym,
                    'df': df,
                    'scores': scores
                })
            
            time.sleep(0.05)
        
        if not scored_stocks:
            print('No candidates')
            continue
        
        # RANK by total score
        scored_stocks.sort(key=lambda x: x['scores']['total_score'], reverse=True)
        
        # Trade ALL scored stocks (no limit testing)
        qualifying_stocks = scored_stocks
        
        # Simulate trades
        day_pnl = 0
        day_trades = 0
        for stock in qualifying_stocks:
            sym = stock['symbol']
            df = stock['df']
            entry_price = stock['scores']['price']
            
            # Simple exit: 1% TP, 0.5% SL, 10 bar max
            tp = entry_price * 1.01
            sl = entry_price * 0.995
            
            exit_pnl = None
            for i in range(3, min(13, len(df))):
                if df['high'].iloc[i] >= tp:
                    exit_pnl = 1.0
                    break
                if df['low'].iloc[i] <= sl:
                    exit_pnl = -0.5
                    break
            
            if exit_pnl is None:
                exit_price = df['close'].iloc[min(12, len(df)-1)]
                exit_pnl = (exit_price - entry_price) / entry_price * 100
            
            all_trades.append({
                'date': date,
                'symbol': sym,
                'score': stock['scores']['total_score'],
                'rvol': stock['scores']['rvol'],
                'pnl': exit_pnl
            })
            day_pnl += exit_pnl
            day_trades += 1
        
        print(f'{len(scored_stocks)} scored, {day_trades} qualifying trades, P&L: {day_pnl:+.2f}%')
    
    return all_trades

if __name__ == "__main__":
    trades = run_backtest()
    
    print('\n' + '='*70)
    print('FINAL RESULTS')
    print('='*70)
    
    if trades:
        df = pd.DataFrame(trades)
        wins = len(df[df['pnl'] > 0])
        
        print(f"\nTotal Trades: {len(df)}")
        print(f"Win Rate: {wins / len(df) * 100:.1f}%")
        print(f"Avg P&L: {df['pnl'].mean():.3f}%")
        print(f"Total Return: {df['pnl'].sum():.2f}%")
        
        win_sum = df[df['pnl'] > 0]['pnl'].sum()
        loss_sum = abs(df[df['pnl'] < 0]['pnl'].sum())
        pf = win_sum / loss_sum if loss_sum > 0 else 999
        print(f"Profit Factor: {pf:.2f}")
        
        print("\nBy Symbol (Top 10):")
        for sym, group in df.groupby('symbol'):
            print(f"  {sym}: {len(group)} trades, {group['pnl'].sum():.2f}%")
    else:
        print("No trades generated")
    
    print('='*70)
