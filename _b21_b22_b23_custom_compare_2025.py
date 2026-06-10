"""
Unified Comparison Script for 2025:
- B21 on full Boof ETF list (11 symbols: NVDA, AAPL, MSFT, AMZN, GOOGL, AVGO, META, TSLA, LLY, QQQ, SPY)
- B22 on Boof 5 with ETF (7 symbols: NVDA, AAPL, MSFT, AMZN, GOOGL, QQQ, SPY)
- B23 on Boof 5 with ETF (7 symbols: NVDA, AAPL, MSFT, AMZN, GOOGL, QQQ, SPY)

Optimized to download each symbol's data only once per month.
"""
import sys, numpy as np, pandas as pd, requests
from collections import defaultdict

sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_signals import get_alpaca_credentials
from backtest_boof21 import backtest as b21_backtest

from backtest_boof22 import (compute_atr as b22_atr, build_cluster_array,
                              nearest_sr_distance, DEFAULT_PARAMS as B22_DEF,
                              ATR_LEN as B22_ATR_LEN, VOL_LEN as B22_VOL_LEN,
                              FRACTAL_BARS as B22_FRAC)
import backtest_boof23 as b23mod
from backtest_boof23 import (compute_atr as b23_atr, build_cluster_array as b23_clusters,
                              nearest_sr_distance as b23_sr, _build_zigzag,
                              DEFAULT_PARAMS as B23_DEF,
                              ATR_LEN as B23_ATR_LEN, VOL_LEN as B23_VOL_LEN,
                              FRACTAL_BARS as B23_FRAC, MAX_HOLD as B23_MAX_H)
b23mod.CLUSTER_COMPLETION = False
b23mod.LOW_VOL_FILTER     = False

# All symbols involved in any of the tests
all_syms = ['NVDA','AAPL','MSFT','AMZN','GOOGL','AVGO','META','TSLA','QQQ','SPY','LLY']

b21_syms = ['NVDA','AAPL','MSFT','AMZN','GOOGL','AVGO','META','TSLA','QQQ','SPY','LLY']
b22_b23_syms = ['NVDA','AAPL','MSFT','AMZN','GOOGL','QQQ','SPY']

# Parameters
TP_PCT = 0.35
SL_PCT = 0.15
TP_ATR = 0.70
SL_ATR = 0.30

B21_SIZE = 250
B22_CORE = 600; B22_EXP = 200
B23_CORE = 500; B23_EXP = 200

MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MDAYS  = [ 23,   20,   21,   22,   21,   21,   23,   21,   21,   23,   19,   23]
TOTAL_DAYS = sum(MDAYS)

MONTH_DATES = {
    'Jan': ('2025-01-02','2025-01-31'), 'Feb': ('2025-02-03','2025-02-28'),
    'Mar': ('2025-03-03','2025-03-31'), 'Apr': ('2025-04-01','2025-04-30'),
    'May': ('2025-05-01','2025-05-30'), 'Jun': ('2025-06-02','2025-06-30'),
    'Jul': ('2025-07-01','2025-07-31'), 'Aug': ('2025-08-01','2025-08-29'),
    'Sep': ('2025-09-02','2025-09-30'), 'Oct': ('2025-10-01','2025-10-31'),
    'Nov': ('2025-11-03','2025-11-28'), 'Dec': ('2025-12-01','2025-12-31')
}

def fetch_bars(symbol, start_str, end_str, api_key, secret_key):
    all_bars = []
    url = f'https://data.alpaca.markets/v2/stocks/{symbol}/bars'
    params = {'timeframe':'1Min','start':start_str+'T09:30:00Z',
              'end':end_str+'T20:00:00Z','adjustment':'raw',
              'feed':'sip','limit':10000}
    headers = {'APCA-API-KEY-ID':api_key,'APCA-API-SECRET-KEY':secret_key}
    while True:
        r = requests.get(url, params=params, headers=headers)
        if r.status_code != 200: break
        d = r.json()
        all_bars.extend(d.get('bars', []))
        token = d.get('next_page_token')
        if not token: break
        params['page_token'] = token
    if not all_bars: return None
    df = pd.DataFrame(all_bars)
    df['time'] = pd.to_datetime(df['t'])
    df = df.rename(columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'})
    return df[['time','open','high','low','close','volume']].set_index('time')

def run_b21(df, sym):
    raw = b21_backtest(df, sym)
    trades = []
    for t in raw:
        et = t['exit_type']
        if et == 'tp':        pnl = TP_PCT * B21_SIZE
        elif et == 'stop':    pnl = -SL_PCT * B21_SIZE
        else:
            pnl = float(t['pnl']) * B21_SIZE * 2.0
            pnl = max(-SL_PCT * B21_SIZE, min(TP_PCT * B21_SIZE, pnl))
        trades.append(pnl)
    return trades

def run_b22(df):
    if df is None or len(df) < 200: return []
    params   = B22_DEF
    atr_mult = params['atr_mult']; vol_mult = params['vol_mult']; sr_dist = params['sr_dist']
    df2 = df.copy().reset_index(drop=True)
    atr_s = b22_atr(df2)
    df2['atr']    = atr_s
    df2['vol_sma']= df2['volume'].rolling(B22_VOL_LEN).mean()
    df2['rvol']   = (df2['volume'] / df2['vol_sma'] * 100).fillna(0)
    df2['hi_vol'] = df2['volume'] > df2['vol_sma'] * vol_mult
    cluster_prices, _ = build_cluster_array(df2, atr_s, vol_mult)
    opens=df2['open'].values; highs=df2['high'].values
    lows=df2['low'].values; closes=df2['close'].values; atrs=df2['atr'].values
    F=B22_FRAC; MAX_H=30; warmup=B22_VOL_LEN+B22_ATR_LEN+F
    in_trade=False; trade_end=0; trades=[]
    for i in range(warmup, len(df2)-F-MAX_H-3):
        if in_trade and i<=trade_end: continue
        atr=atrs[i]
        if np.isnan(atr) or atr==0: continue
        if df2.iloc[i]['rvol']<80: continue
        if not df2.iloc[i]['hi_vol']: continue
        if nearest_sr_distance(closes[i], cluster_prices, atr) > sr_dist: continue
        lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
        ll=lows[i-F:i];  rl=lows[i+1:i+F+1]
        fp=(highs[i]>lh.max()) and (highs[i]>rh.max())
        ft=(lows[i]<ll.min())  and (lows[i]<rl.min())
        ps=(highs[i]-closes[i])/atr; ts=(closes[i]-lows[i])/atr
        ar=closes[i]<highs[i]-atr*atr_mult; ab=closes[i]>lows[i]+atr*atr_mult
        direction=None; slack=0.0
        if fp and ar: direction='short'; slack=ps
        elif ft and ab: direction='long'; slack=ts
        if direction is None: continue
        ep=float(opens[min(i+1,len(df2)-1)])
        tp_p=ep+atr*TP_ATR if direction=='long' else ep-atr*TP_ATR
        sl_p=ep-atr*SL_ATR if direction=='long' else ep+atr*SL_ATR
        et='time'; exit_bar=min(i+1+MAX_H, len(df2)-1)
        for j in range(i+2, min(i+MAX_H+2, len(df2))):
            h=highs[j]; l=lows[j]
            if direction=='long':
                if h>=tp_p: et='tp'; exit_bar=j; break
                if l<=sl_p: et='sl'; exit_bar=j; break
            else:
                if l<=tp_p: et='tp'; exit_bar=j; break
                if h>=sl_p: et='sl'; exit_bar=j; break
        in_trade=True; trade_end=exit_bar
        size=B22_CORE if slack>=1.4 else B22_EXP
        pnl=TP_PCT*size if et=='tp' else -SL_PCT*size if et=='sl' else 0.05*size
        trades.append(pnl)
    return trades

def run_b23(df):
    if df is None or len(df) < 200: return []
    params   = B23_DEF
    atr_mult = params['atr_mult']; vol_mult = params['vol_mult']; sr_dist = params['sr_dist']
    df2 = df.copy().reset_index(drop=True)
    atr_s = b23_atr(df2)
    df2['atr']    = atr_s
    df2['vol_sma']= df2['volume'].rolling(B23_VOL_LEN).mean()
    df2['rvol']   = (df2['volume'] / df2['vol_sma'] * 100).fillna(0)
    df2['hi_vol'] = df2['volume'] > df2['vol_sma'] * vol_mult
    cluster_prices, _ = b23_clusters(df2, atr_s, vol_mult)
    opens=df2['open'].values; highs=df2['high'].values
    lows=df2['low'].values; closes=df2['close'].values; atrs=df2['atr'].values
    zz_trend, zz_high, zz_high_bar, zz_low, zz_low_bar = _build_zigzag(highs, lows, opens, closes)
    F=B23_FRAC; MAX_H=B23_MAX_H; warmup=B23_VOL_LEN+B23_ATR_LEN+F
    ZZ_PROX=30; in_trade=False; trade_end=0; trades=[]
    for i in range(warmup, len(df2)-F-MAX_H-3):
        if in_trade and i<=trade_end: continue
        atr=atrs[i]
        if np.isnan(atr) or atr==0: continue
        if df2.iloc[i]['rvol']<80: continue
        if not df2.iloc[i]['hi_vol']: continue
        if b23_sr(closes[i], cluster_prices, atr) > sr_dist: continue
        lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
        ll=lows[i-F:i];  rl=lows[i+1:i+F+1]
        fp=(highs[i]>lh.max()) and (highs[i]>rh.max())
        ft=(lows[i]<ll.min())  and (lows[i]<rl.min())
        ps=(highs[i]-closes[i])/atr; ts=(closes[i]-lows[i])/atr
        ar=closes[i]<highs[i]-atr*atr_mult; ab=closes[i]>lows[i]+atr*atr_mult
        zzt=zz_trend[i]
        direction=None; slack=0.0
        if fp and ar and zzt=='up'   and abs(i-int(zz_high_bar[i]))<=ZZ_PROX: direction='short'; slack=ps
        elif ft and ab and zzt=='down' and abs(i-int(zz_low_bar[i]))<=ZZ_PROX: direction='long';  slack=ts
        if direction is None: continue
        ep=float(opens[min(i+1,len(df2)-1)])
        tp_p=ep+atr*TP_ATR if direction=='long' else ep-atr*TP_ATR
        sl_p=ep-atr*SL_ATR if direction=='long' else ep+atr*SL_ATR
        et='time'; exit_bar=min(i+1+MAX_H, len(df2)-1)
        for j in range(i+2, min(i+MAX_H+2, len(df2))):
            h=highs[j]; l=lows[j]
            if direction=='long':
                if h>=tp_p: et='tp'; exit_bar=j; break
                if l<=sl_p: et='sl'; exit_bar=j; break
            else:
                if l<=tp_p: et='tp'; exit_bar=j; break
                if h>=sl_p: et='sl'; exit_bar=j; break
        in_trade=True; trade_end=exit_bar
        size=B23_CORE if slack>=1.4 else B23_EXP
        pnl=TP_PCT*size if et=='tp' else -SL_PCT*size if et=='sl' else 0.05*size
        trades.append(pnl)
    return trades

creds = get_alpaca_credentials()

# Storage
results = {
    'b21': {mo: 0.0 for mo in MONTHS},
    'b22': {mo: 0.0 for mo in MONTHS},
    'b23': {mo: 0.0 for mo in MONTHS}
}
trades_count = {
    'b21': {mo: 0 for mo in MONTHS},
    'b22': {mo: 0 for mo in MONTHS},
    'b23': {mo: 0 for mo in MONTHS}
}

print("Starting custom multi-strategy 2025 backtest...")

for m in MONTHS:
    start_d, end_d = MONTH_DATES[m]
    print(f"\n--- {m} 2025 ({start_d} to {end_d}) ---")
    
    # Process symbol by symbol (FETCH ONCE)
    for sym in all_syms:
        print(f"  {sym}...", end=' ', flush=True)
        try:
            df = fetch_bars(sym, start_d, end_d, api_key=creds['api_key'], secret_key=creds['secret_key'])
        except Exception as e:
            print(f"ERR: {e}")
            continue
            
        if df is None or len(df) < 200:
            print("no data")
            continue
            
        # Run B21 if symbol is in B21's list
        if sym in b21_syms:
            t21 = run_b21(df, sym)
            results['b21'][m] += sum(t21)
            trades_count['b21'][m] += len(t21)
            
        # Run B22 and B23 if symbol is in B22/B23's list
        if sym in b22_b23_syms:
            t22 = run_b22(df)
            t23 = run_b23(df)
            results['b22'][m] += sum(t22)
            results['b23'][m] += sum(t23)
            trades_count['b22'][m] += len(t22)
            trades_count['b23'][m] += len(t23)
            
        print("done")

print("\n==========================================================")
print("             2025 CUSTOM COMPARISON RESULTS               ")
print("==========================================================")
print("             B21 (Boof ETF)     B22 (Boof 5 + ETF)  B23 (Boof 5 + ETF)")
print("Month        P&L      (Trades)   P&L      (Trades)   P&L      (Trades)")
print("----------------------------------------------------------")
for m in MONTHS:
    p21, t21 = results['b21'][m], trades_count['b21'][m]
    p22, t22 = results['b22'][m], trades_count['b22'][m]
    p23, t23 = results['b23'][m], trades_count['b23'][m]
    print(f"{m:<6}  ${p21:9,.0f} ({t21:4d})    ${p22:9,.0f} ({t22:4d})    ${p23:9,.0f} ({t23:4d})")
print("==========================================================")
total_b21 = sum(results['b21'].values())
total_b22 = sum(results['b22'].values())
total_b23 = sum(results['b23'].values())
trades_b21 = sum(trades_count['b21'].values())
trades_b22 = sum(trades_count['b22'].values())
trades_b23 = sum(trades_count['b23'].values())

print(f"TOTAL   ${total_b21:9,.0f} ({trades_b21:4d})    ${total_b22:9,.0f} ({trades_b22:4d})    ${total_b23:9,.0f} ({trades_b23:4d})")
print(f"DAILY   ${total_b21/TOTAL_DAYS:9,.1f}/day         ${total_b22/TOTAL_DAYS:9,.1f}/day         ${total_b23/TOTAL_DAYS:9,.1f}/day")
print("==========================================================")
