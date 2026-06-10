"""
BOOF 28 - Opening Drive Strategy
6-Month Backtest: Dec 2025 - May 2026
S&P 500 Universe
"""
import sys
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import fetch_alpaca_bars
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import time

creds = {'api_key': 'AKXYPKTGTYKE2PN2GPP4U5VJHU', 'secret_key': '6eseko36Ww3RNPE419HMULS9JHjikonFwQurSoXYcV6W'}

# Full S&P 500 (as of 2024)
SP500 = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","BRK.B","LLY","AVGO","TSLA",
    "UNH","JPM","V","XOM","MA","HD","PG","COST","ABBV","JNJ",
    "WMT","KO","BAC","TRV","PEP","LIN","MRK","TMO","ACN","ABT",
    "MCD","ADBE","CSCO","WFC","TXN","VZ","CRM","NEE","PM","NKE",
    "CMCSA","RTX","BMY","ORCL","AMGN","SPGI","HON","UPS","LOW","INTC",
    "IBM","UNP","QCOM","SBUX","MDT","GE","GS","CAT","DE","ELV",
    "LMT","GILD","CVS","BLK","AXP","PLD","CI","AMAT","TJX","INTU",
    "ADP","ISRG","VRTX","ZTS","MDLZ","TMUS","CB","PYPL","REGN","SYK",
    "BKNG","C","BSX","ADI","SCHW","SO","MMC","HCA","ETN","DUK",
    "MU","PNC","AON","ITW","SHW","CSX","NOC","CL","EOG","APD",
    "BDX","TGT","FDX","ECL","HUM","FCX","SLB","WM","F","NSC",
    "HES","PXD","OXY","EMR","MPC","VLO","PSX","KMI","OKE","WMB",
    "COP","DVN","CTRA","MRO","APA","FTNT","PANW","CRWD","ZS","SNOW",
    "DDOG","NET","OKTA","PLTR","RBLX","UBER","LYFT","DASH","ABNB","SQ",
    "SHOP","SPOT","ZM","DOCU","TWLO","DDOG","FSLY","NET","CRWD","OKTA",
    "ZS","PANW","FTNT","CYBR","SPLK","NOW","VEEV","WDAY","TEAM","ATLASSIAN",
    "MDB","MONGO","DATA","SNOW","PLTR","RBLX","U","EA","TTWO","ATVI",
    "TTD","TRIP","BKNG","EXPE","MAR","HLT","CCL","RCL","NCLH","DAL",
    "UAL","AAL","LUV","JBLU","ALK","SAVE","HA","ULCC","CPA","AZUL",
    "GOL","LTM","SKYW","ENVA","GLAD","MAIN","ARCC","PSEC","TSLX","NMFC",
    "BXSL","OXSQ","TCPC","GAIN","CSWC","NEWT","KCAP","MCC","NGVC","FDUS",
    "TCPC","PFLT","GLAD","MAIN","ARCC","GBDC","ORCC","TPVG","HRZN","HCAP",
    "CMFN","MRCC","PNNT","TICC","MCI","MCG","PFDR","FSIC","CCT","CCAP",
    "OHAI","KIO","SLRC","SUNS","BBDC","NMS","OCSL","OCSI","PFLT","TCRD",
    "MRCC","FSK","FSKR","XAN","CPTA","CPTAG","CPTAL","SBIC","SIEB","NMZ",
    "DSU","VCF","VGI","MAV","MHI","HYI","AFT","AWF","BGH","EFT",
    "EFF","EHT","ETB","ETG","ETY","EVG","EVT","EFR","EVF","EVG",
    "EVT","EVV","EXD","EXG","FFA","FCT","FDEU","FIF","FLC","FMY",
    "FPL","GBAB","GDO","GF","GGZ","GGM","GHY","GIM","GLU","GPM",
    "GXG","HCI","HDP","HIO","HIX","HYT","HYB","ICB","IIM","INSI",
    "INU","IAD","JFR","JRO","JSD","KIO","LDP","LEO","MCI","MEN",
    "MFT","MGF","MIN","MMT","MXE","MXF","MYN","NAZ","NDP","NEA",
    "NEV","NHA","NHI","NIE","NKG","NKX","NMZ","NMT","NMS","NMZ",
    "NUO","NVG","NAD","NCV","NCZ","NFJ","NZF","PMF","PML","PMX",
    "PCN","PFN","PFL","PGP","PHK","PKO","PPR","PTY","RCS","RGT",
    "RHI","RIVR","RMT","ROIC","RQI","RQI","RQP","RY","SAF","SBI",
    "SCM","SEF","SEMG","SFDC","SFE","SFT","SIG","SLRC","SMM","SOR",
    "SPE","SPPP","SPY","SRF","STK","SBI","SYM","TCC","TCRD","TDF",
    "TEI","TGF","TICC","TLI","TLT","TPVG","TPZ","TWN","TY","USA",
    "UTG","VBF","VCV","VGI","VGM","VKQ","VLT","VMM","VMO","VRA",
    "VTA","VTN","VVR","WEA","WIA","WIT","WMC","WRI","WSR","XFLT",
    "XHR","YLD","ZTR","SPY"
]

def get_data(sym, start, end, tf='5Min'):
    df = fetch_alpaca_bars(sym, start, end, tf, creds['api_key'], creds['secret_key'])
    if df is None or len(df) < 10:
        return None
    if 'open' not in df.columns:
        df.columns = [c.lower() for c in df.columns]
    df['timestamp'] = pd.to_datetime(df['timestamp'] if 'timestamp' in df.columns else df.index)
    return df.sort_values('timestamp')

def calculate_vwap(df):
    typical = (df['high'] + df['low'] + df['close']) / 3
    pv = (typical * df['volume']).cumsum()
    vol = df['volume'].cumsum()
    return pv / vol

def calculate_rvol(df, current_idx, lookback_days=20):
    """RVOL at current bar vs historical average at same time"""
    if current_idx < 1:
        return None
    
    current_volume = df['volume'].iloc[current_idx]
    current_time = df['timestamp'].iloc[current_idx]
    current_date = current_time.date()
    current_hour, current_minute = current_time.hour, current_time.minute
    
    # Get historical volumes at same time
    historical = []
    for days_back in range(1, lookback_days + 1):
        past_date = current_date - timedelta(days=days_back)
        if past_date.weekday() >= 5:
            continue
        past_day = df[df['timestamp'].dt.date == past_date]
        if len(past_day) > 0:
            # Find closest time
            past_day['time_diff'] = abs(past_day['timestamp'].dt.hour - current_hour) * 60 + \
                                     abs(past_day['timestamp'].dt.minute - current_minute)
            closest = past_day.loc[past_day['time_diff'].idxmin()]
            if closest['time_diff'] <= 5:
                historical.append(closest['volume'])
    
    if len(historical) < 5:
        return None
    
    avg_volume = np.mean(historical)
    return current_volume / avg_volume if avg_volume > 0 else 0

def simulate_trade(entry_price, direction, df, entry_idx, atr, sl_r=1.0, tp_r=2.0, max_bars=24):
    """Simulate trade with 1R SL, 2R TP, time exit"""
    if entry_idx >= len(df) - 1:
        return None, None
    
    if direction == 'LONG':
        sl = entry_price - atr * sl_r
        tp = entry_price + atr * tp_r
    else:
        sl = entry_price + atr * sl_r
        tp = entry_price - atr * tp_r
    
    max_idx = min(entry_idx + max_bars, len(df) - 1)
    
    for j in range(entry_idx + 1, max_idx + 1):
        bar = df.iloc[j]
        if direction == 'LONG':
            if bar['low'] <= sl:
                return (sl - entry_price) / entry_price * 100, 'SL'
            if bar['high'] >= tp:
                return (tp - entry_price) / entry_price * 100, 'TP'
        else:
            if bar['high'] >= sl:
                return (entry_price - sl) / entry_price * 100, 'SL'
            if bar['low'] <= tp:
                return (entry_price - tp) / entry_price * 100, 'TP'
    
    # Time exit
    exit_price = df.iloc[max_idx]['close']
    if direction == 'LONG':
        return (exit_price - entry_price) / entry_price * 100, 'TIME'
    else:
        return (entry_price - exit_price) / entry_price * 100, 'TIME'

def run_scan_day(date, data_cache, spy_data):
    """Run 9:35 AM scan for one day"""
    trades = []
    target_time = datetime.combine(date, datetime.strptime('09:35', '%H:%M').time(), tzinfo=timezone.utc)
    end_time = datetime.combine(date, datetime.strptime('11:30', '%H:%M').time(), tzinfo=timezone.utc)
    
    for sym, df in data_cache.items():
        if sym == 'SPY':
            continue
        
        # Get day data
        day_data = df[df['timestamp'].dt.date == date].reset_index(drop=True)
        if len(day_data) < 10:
            continue
        
        # Get 9:35 bar (with 5m data, this is bar at or after 9:35)
        bars_935 = day_data[day_data['timestamp'] <= target_time]
        if len(bars_935) < 2:  # Need at least opening range (first 2 bars = 10 min)
            continue
        
        idx_935 = bars_935.index[-1]
        
        # Calculate metrics
        current_price = bars_935['close'].iloc[-1]
        open_price = day_data['open'].iloc[0]
        
        # VWAP
        vwap_series = calculate_vwap(bars_935)
        vwap = vwap_series.iloc[-1]
        
        # Gap %
        prev_day = df[df['timestamp'].dt.date == date - timedelta(days=1)]
        if len(prev_day) == 0:
            continue
        prev_close = prev_day['close'].iloc[-1]
        gap_pct = (open_price - prev_close) / prev_close * 100
        
        # RVOL
        full_idx = df[df['timestamp'] <= bars_935['timestamp'].iloc[-1]].index[-1]
        rvol = calculate_rvol(df, full_idx)
        if rvol is None:
            continue
        
        # Relative Strength vs SPY
        spy_day = spy_data[spy_data['timestamp'].dt.date == date]
        if len(spy_day) < 5:
            rel_strength = 0
        else:
            spy_open = spy_day['open'].iloc[0]
            spy_935 = spy_day[spy_day['timestamp'] <= target_time]['close'].iloc[-1] if len(spy_day[spy_day['timestamp'] <= target_time]) > 0 else spy_open
            spy_move = (spy_935 - spy_open) / spy_open * 100
            stock_move = (current_price - open_price) / open_price * 100
            rel_strength = stock_move - spy_move
        
        # Opening Range (first 2 bars = 10 minutes with 5m data)
        opening = day_data.iloc[:2]
        or_high = opening['high'].max()
        or_low = opening['low'].min()
        
        # Filters
        vwap_bonus = 1 if current_price > vwap else 0
        above_or = current_price > or_high
        
        # Score
        score = min(rvol, 10) * 0.4 + rel_strength * 0.3 + abs(gap_pct) * 0.2 + vwap_bonus * 0.1
        
        # Entry criteria: RVOL > 2, RS > 1%, above VWAP, above opening range
        if rvol > 2 and rel_strength > 1 and current_price > vwap and above_or:
            # Calculate ATR
            if idx_935 >= 14:
                atr_window = df.iloc[idx_935-14:idx_935]
                trs = []
                for i in range(1, len(atr_window)):
                    h, l, c = atr_window['high'].iloc[i], atr_window['low'].iloc[i], atr_window['close'].iloc[i-1]
                    trs.append(max(h-l, abs(h-c), abs(l-c)))
                atr = np.mean(trs) if trs else current_price * 0.001
            else:
                atr = current_price * 0.001
            
            # Check if we can complete trade by 11:30 AM
            entry_time = bars_935['timestamp'].iloc[-1]
            if entry_time + timedelta(minutes=100) > end_time:
                continue  # Not enough time to complete trade
            
            # Simulate trade
            pnl, exit_type = simulate_trade(current_price, 'LONG', day_data, len(bars_935)-1, atr)
            if pnl is not None:
                trades.append({
                    'date': date,
                    'sym': sym,
                    'score': score,
                    'rvol': rvol,
                    'gap': gap_pct,
                    'rs': rel_strength,
                    'pnl': pnl,
                    'exit': exit_type
                })
    
    return trades

# MAIN
print('='*70)
print('BOOF 28 - 6 MONTH BACKTEST (Dec 2025 - May 2026)')
print('='*70)

start_date = datetime(2025, 12, 1, tzinfo=timezone.utc)
end_date = datetime(2026, 5, 31, tzinfo=timezone.utc)

# Fetch all data (3-month lookback for RVOL)
fetch_start = start_date - timedelta(days=30)
fetch_end = end_date + timedelta(days=1)

print(f'\nFetching data for {len(SP500)} symbols...')
print(f'Period: {fetch_start.date()} to {fetch_end.date()}')

data_cache = {}
for sym in SP500:
    df = get_data(sym, fetch_start, fetch_end, '1Min')
    if df is not None:
        data_cache[sym] = df
        print(f'  {sym}: {len(df)} bars')
    time.sleep(0.2)

print(f'\nLoaded {len(data_cache)} symbols')

if 'SPY' not in data_cache:
    print('ERROR: SPY required')
    sys.exit(1)

spy_data = data_cache['SPY']

# Generate trading days
trading_days = []
current = start_date
while current <= end_date:
    if current.weekday() < 5:  # Mon-Fri
        trading_days.append(current.date())
    current += timedelta(days=1)

print(f'\nRunning backtest on {len(trading_days)} trading days...')
print('='*70)

all_trades = []
for i, date in enumerate(trading_days):
    if i % 10 == 0:
        print(f'  Day {i+1}/{len(trading_days)}: {date}')
    
    trades = run_scan_day(date, data_cache, spy_data)
    all_trades.extend(trades)

print('\n' + '='*70)
print('RESULTS')
print('='*70)

if all_trades:
    df_trades = pd.DataFrame(all_trades)
    
    print(f"\nTotal Trades: {len(df_trades)}")
    print(f"Win Rate: {len(df_trades[df_trades['pnl'] > 0]) / len(df_trades) * 100:.1f}%")
    print(f"Avg P&L: {df_trades['pnl'].mean():.3f}%")
    print(f"Total Return: {df_trades['pnl'].sum():.2f}%")
    print(f"Profit Factor: {df_trades[df_trades['pnl'] > 0]['pnl'].sum() / abs(df_trades[df_trades['pnl'] < 0]['pnl'].sum()):.2f}")
    
    print("\nBy Exit Type:")
    for et, group in df_trades.groupby('exit'):
        print(f"  {et}: {len(group)} trades, {group['pnl'].sum():.2f}% total")
    
    print("\nTop 10 Trades by Score:")
    top = df_trades.nlargest(10, 'score')[['date', 'sym', 'score', 'rvol', 'pnl']]
    for _, row in top.iterrows():
        print(f"  {row['date']} {row['sym']}: Score {row['score']:.1f}, RVOL {row['rvol']:.1f}x, P&L {row['pnl']:.2f}%")
    
    print("\nBy Symbol (Top 10):")
    by_sym = df_trades.groupby('sym')['pnl'].sum().sort_values(ascending=False).head(10)
    for sym, pnl in by_sym.items():
        print(f"  {sym}: ${pnl:.2f}%")
else:
    print("No trades generated")

print('='*70)
