"""
BOOF60 Volume / Universe Expansion Tests
Goal: 8-10 trades/week (240-300 per 6 months) while keeping WR>60% PF>2x
Tests:
- Expand symbol universe to 60-80 names
- Gap threshold sweep vs trade count
- SPY + QQQ regime filter combos
- Combined: best quality filter + enough volume
"""
import pickle, os, pytz, requests, time
import pandas as pd
import numpy as np
from itertools import product

ET     = pytz.timezone('America/New_York')
CACHE  = "boof_data"
SUFFIX = "_5m_6mo.parquet"
BUDGET = 750.0
PKL    = "boof60_v2_paths.pkl"

# ── Expanded universe (60 high-gap, high-vol names) ───────────────
EXPANDED = [
    # Original 30
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX',
    # Added 30 high-beta / high-gap names
    'SOFI','IONQ','RGTI','QUBT','ACHR','JOBY','LUNR','RDDT','CAVA','DUOL',
    'CELH','DKNG','MELI','SHOP','SQ','PYPL','SPOT','PINS','SNAP','LYFT',
    'RIVN','LCID','CHWY','SOUN','BBAI','AI','ASTS','RKLB','IREN','CORZ'
]

def load_sym(sym):
    path = os.path.join(CACHE, f"{sym}{SUFFIX}")
    if not os.path.exists(path): return pd.DataFrame()
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if df.index.tz is None: df.index = df.index.tz_localize('UTC')
    df.index = df.index.tz_convert(ET)
    return df

# ── Check which expanded symbols we have cached ───────────────────
new_syms = [s for s in EXPANDED if s not in [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX'
]]
missing = [s for s in new_syms if not os.path.exists(os.path.join(CACHE, f"{s}{SUFFIX}"))]
if missing:
    print(f"Fetching {len(missing)} new symbols: {missing}")
    API_KEY    = "PKKPME54QJA3KBPAJ3QZZOJXDF"
    API_SECRET = "J4GMmrbXWozxgx5FoY6kZmeNj9tCG6kmDGmyEvnXrb1Y"
    HEADERS    = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": API_SECRET}
    DATA_URL   = "https://data.alpaca.markets"
    for sym in missing:
        bars, params = [], {"timeframe":"5Min","start":"2025-12-01","end":"2026-06-16",
                            "limit":10000,"feed":"sip","adjustment":"raw"}
        url = f"{DATA_URL}/v2/stocks/{sym}/bars"
        while True:
            r = requests.get(url, headers=HEADERS, params=params, timeout=15)
            if r.status_code == 429: time.sleep(5); continue
            j = r.json(); bars.extend(j.get("bars") or []);
            token = j.get("next_page_token")
            if not token: break
            params["page_token"] = token
        if bars:
            df = pd.DataFrame(bars)
            df['t'] = pd.to_datetime(df['t'], utc=True)
            df = df.set_index('t').rename(columns={'o':'Open','h':'High','l':'Low','c':'Close','v':'Volume'})
            df[['Open','High','Low','Close','Volume']].to_parquet(os.path.join(CACHE, f"{sym}{SUFFIX}"))
            print(f"  {sym}: {len(df)} bars")
        else:
            print(f"  {sym}: NO DATA")
        time.sleep(0.3)
else:
    print(f"All {len(new_syms)} new symbols already cached")

# ── Also fetch QQQ if missing ──────────────────────────────────────
for idx_sym in ['QQQ','IWM','VXX']:
    path = os.path.join(CACHE, f"{idx_sym}{SUFFIX}")
    if not os.path.exists(path):
        print(f"Fetching {idx_sym}...")
        API_KEY    = "PKKPME54QJA3KBPAJ3QZZOJXDF"
        API_SECRET = "J4GMmrbXWozxgx5FoY6kZmeNj9tCG6kmDGmyEvnXrb1Y"
        HEADERS    = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": API_SECRET}
        DATA_URL   = "https://data.alpaca.markets"
        bars, params = [], {"timeframe":"5Min","start":"2025-12-01","end":"2026-06-16",
                            "limit":10000,"feed":"sip","adjustment":"raw"}
        url = f"{DATA_URL}/v2/stocks/{idx_sym}/bars"
        while True:
            r = requests.get(url, headers=HEADERS, params=params, timeout=15)
            if r.status_code == 429: time.sleep(5); continue
            j = r.json(); bars.extend(j.get("bars") or [])
            token = j.get("next_page_token")
            if not token: break
            params["page_token"] = token
        if bars:
            df = pd.DataFrame(bars)
            df['t'] = pd.to_datetime(df['t'], utc=True)
            df = df.set_index('t').rename(columns={'o':'Open','h':'High','l':'Low','c':'Close','v':'Volume'})
            df[['Open','High','Low','Close','Volume']].to_parquet(path)
            print(f"  {idx_sym}: {len(df)} bars")

# ── Load all data ─────────────────────────────────────────────────
print("\nLoading all symbol data...")
data = {}
for sym in EXPANDED + ['SPY','QQQ','IWM']:
    df = load_sym(sym)
    if not df.empty: data[sym] = df

print(f"Loaded: {len(data)} symbols")

# ── Build daily OHLC ──────────────────────────────────────────────
print("Building daily OHLC...")
daily = {}
for sym, df in data.items():
    rth = df.between_time('09:30','16:00')
    d   = rth.resample('1D').agg(open=('open','first'),high=('high','max'),
                                  low=('low','min'),close=('close','last')).dropna()
    daily[sym] = d

spy_daily = daily['SPY']
qqq_daily = daily.get('QQQ', pd.DataFrame())
all_dates  = sorted(spy_daily.index.date)[1:]

# ── Regime lookups ─────────────────────────────────────────────────
spy_up  = set(d for d, r in spy_daily.iterrows() if r['close'] > r['open'])
qqq_up  = set(d for d, r in qqq_daily.iterrows() if r['close'] > r['open']) if not qqq_daily.empty else set()
spy_up  = {d.date() if hasattr(d,'date') else d for d in spy_up}
qqq_up  = {d.date() if hasattr(d,'date') else d for d in qqq_up}

# ── Signal collection — expanded universe ─────────────────────────
print(f"Collecting signals across {len(EXPANDED)} symbols, {len(all_dates)} days...")
GAP_MIN  = 1.0    # collect all gaps >1%, filter in sim
MAX_POS  = 5
OPTION_MULT = 3.0
MAX_BARS = 60

raw_trades = []
for day in all_dates:
    spy_prices = []; regime = "neutral"; active_pos = {}
    spy_rth = data['SPY'][data['SPY'].index.date == day].between_time('09:30','15:55')

    for sym in EXPANDED:
        if sym not in data or sym not in daily: continue
        dh   = daily[sym]; prev = dh[dh.index.date < day]
        if len(prev) < 1: continue
        prev_close = float(prev['close'].iloc[-1])
        pdh        = float(prev['high'].iloc[-1])

        bars_5m = data[sym]
        rth = bars_5m[bars_5m.index.date == day].between_time('09:30','15:55')
        if len(rth) < 2: continue

        day_open = float(rth['open'].iloc[0])
        gap_pct  = (day_open - prev_close) / prev_close * 100
        if gap_pct < GAP_MIN: continue

        confirm = False; in_trade = None; bar_path = []

        for i, (ts, bar) in enumerate(rth.iterrows()):
            hm    = ts.strftime('%H:%M')
            price = float(bar['close'])
            high  = float(bar['high'])
            low   = float(bar['low'])

            if i < len(spy_rth):
                spy_prices.append(float(spy_rth.iloc[min(i,len(spy_rth)-1)]['close']))
                if len(spy_prices) > 5: spy_prices.pop(0)
                if len(spy_prices) >= 3:
                    if   spy_prices[-1] > spy_prices[0]*1.001: regime="bull"
                    elif spy_prices[-1] < spy_prices[0]*0.999: regime="bear"
                    else: regime="neutral"

            if in_trade:
                entry_px = in_trade['entry_price']
                stk_pct  = (price - entry_px) / entry_px * 100
                mfe_stk  = (high  - entry_px) / entry_px * 100
                mae_stk  = (low   - entry_px) / entry_px * 100
                opt_pct  = stk_pct * OPTION_MULT
                mfe_opt  = mfe_stk * OPTION_MULT
                mae_opt  = mae_stk * OPTION_MULT
                in_trade['bars_held'] += 1
                bar_path.append({'opt_pct':opt_pct,'mfe_opt':mfe_opt,'mae_opt':mae_opt,'hm':hm})
                if in_trade['bars_held'] >= MAX_BARS or hm >= '15:50':
                    raw_trades.append({'date':day,'sym':sym,'direction':'long',
                        'entry_time':in_trade['entry_time'],'regime':regime,
                        'gap_pct':gap_pct,'signal':'BOOF55','bars':bar_path,
                        'spy_up': day in spy_up, 'qqq_up': day in qqq_up})
                    in_trade=None; bar_path=[]
                    if sym in active_pos: del active_pos[sym]
                continue

            if hm > '10:30': break
            if len(active_pos) >= MAX_POS: continue

            if price > pdh and not confirm:
                confirm = True; continue
            if price > pdh and confirm and regime in ('bull','neutral'):
                in_trade = {'entry_price':price,'entry_time':hm,'bars_held':0}
                active_pos[sym] = True

        if in_trade and bar_path:
            raw_trades.append({'date':day,'sym':sym,'direction':'long',
                'entry_time':in_trade['entry_time'],'regime':regime,
                'gap_pct':gap_pct,'signal':'BOOF55','bars':bar_path,
                'spy_up': day in spy_up, 'qqq_up': day in qqq_up})

print(f"Total signals collected: {len(raw_trades)}")
trades_per_week = len(raw_trades) / (135/5)
print(f"Avg per week: {trades_per_week:.1f}\n")

# ── Simulation ────────────────────────────────────────────────────
def sim(trades, tp, sl, flat_exit=None):
    results = []
    for t in trades:
        pnl=None; exit_type='TIMEOUT'
        for j,b in enumerate(t['bars']):
            if b['mfe_opt'] >= tp:  pnl=BUDGET*tp/100;  exit_type='TP'; break
            if b['mae_opt'] <= -sl: pnl=BUDGET*(-sl)/100*-1; exit_type='SL'; break
            if flat_exit and j >= flat_exit and abs(b['opt_pct']) < 3.0:
                pnl=BUDGET*b['opt_pct']/100; exit_type='FLAT'; break
        if pnl is None: pnl=BUDGET*t['bars'][-1]['opt_pct']/100
        results.append({'pnl':pnl,'exit':exit_type})
    df = pd.DataFrame(results)
    if df.empty: return None
    wins=df[df['pnl']>0]; losses=df[df['pnl']<=0]
    wr = len(wins)/len(df)
    pf = wins['pnl'].sum()/abs(losses['pnl'].sum()) if losses['pnl'].sum()!=0 else 999
    return {'n':len(df),'wr':round(wr*100,1),'pf':round(pf,2),
            'ev':round(df['pnl'].mean(),2),'total':round(df['pnl'].sum(),2),
            'ann':round(df['pnl'].sum()/6*12,2),'tp':len(df[df['exit']=='TP'])}

def pr(r, label=""):
    if not r: print(f"  {label}: No trades"); return
    wpw = r['n']/(135/5)
    print(f"  {label:<38} n={r['n']:3d} ({wpw:.1f}/wk)  WR={r['wr']}%  PF={r['pf']}x  6mo=${r['total']}  ann=${r['ann']}/yr")

TP=20; SL=25

print("="*70)
print(f"GAP FILTER vs TRADE COUNT  (SPY up, entry ≤10:00, TP={TP}, SL=-{SL})")
print("="*70)
for gap in [1.0,1.5,2.0,2.5,3.0,3.5,4.0]:
    t = [x for x in raw_trades if x['gap_pct']>=gap and x['spy_up'] and x.get('entry_time','00:00')<='10:00']
    r = sim(t, TP, SL)
    pr(r, f"gap>{gap}%+spy_up")

print("\n" + "="*70)
print("SPY + QQQ REGIME COMBOS  (gap>2%, entry ≤10:00)")
print("="*70)
combos = [
    ("gap>2 no filter",          [x for x in raw_trades if x['gap_pct']>=2.0 and x.get('entry_time','00:00')<='10:00']),
    ("gap>2 + spy_up",           [x for x in raw_trades if x['gap_pct']>=2.0 and x['spy_up'] and x.get('entry_time','00:00')<='10:00']),
    ("gap>2 + qqq_up",           [x for x in raw_trades if x['gap_pct']>=2.0 and x['qqq_up'] and x.get('entry_time','00:00')<='10:00']),
    ("gap>2 + spy_up + qqq_up",  [x for x in raw_trades if x['gap_pct']>=2.0 and x['spy_up'] and x['qqq_up'] and x.get('entry_time','00:00')<='10:00']),
    ("gap>1.5 + spy_up",         [x for x in raw_trades if x['gap_pct']>=1.5 and x['spy_up'] and x.get('entry_time','00:00')<='10:00']),
    ("gap>1.5 + spy+qqq_up",     [x for x in raw_trades if x['gap_pct']>=1.5 and x['spy_up'] and x['qqq_up'] and x.get('entry_time','00:00')<='10:00']),
    ("gap>1.0 + spy_up",         [x for x in raw_trades if x['gap_pct']>=1.0 and x['spy_up'] and x.get('entry_time','00:00')<='10:00']),
    ("gap>1.0 + spy+qqq_up",     [x for x in raw_trades if x['gap_pct']>=1.0 and x['spy_up'] and x['qqq_up'] and x.get('entry_time','00:00')<='10:00']),
]
for label, filtered in combos:
    r = sim(filtered, TP, SL)
    pr(r, label)

print("\n" + "="*70)
print("FLAT EXIT (20 bars) + SPY UP combos")
print("="*70)
fe_combos = [
    ("gap>1.0+spy_up+flat20",    [x for x in raw_trades if x['gap_pct']>=1.0 and x['spy_up'] and x.get('entry_time','00:00')<='10:00']),
    ("gap>1.5+spy_up+flat20",    [x for x in raw_trades if x['gap_pct']>=1.5 and x['spy_up'] and x.get('entry_time','00:00')<='10:00']),
    ("gap>2.0+spy_up+flat20",    [x for x in raw_trades if x['gap_pct']>=2.0 and x['spy_up'] and x.get('entry_time','00:00')<='10:00']),
    ("gap>1.0+spy+qqq+flat20",   [x for x in raw_trades if x['gap_pct']>=1.0 and x['spy_up'] and x['qqq_up'] and x.get('entry_time','00:00')<='10:00']),
    ("gap>1.5+spy+qqq+flat20",   [x for x in raw_trades if x['gap_pct']>=1.5 and x['spy_up'] and x['qqq_up'] and x.get('entry_time','00:00')<='10:00']),
]
for label, filtered in fe_combos:
    r = sim(filtered, TP, SL, flat_exit=20)
    pr(r, label)

print("\n" + "="*70)
print("SWEET SPOT SWEEP — target 8-10/wk, maximize PF")
print("(gap>1.5+spy_up, flat exit 20 bars, various TP/SL)")
print("="*70)
target = [x for x in raw_trades if x['gap_pct']>=1.5 and x['spy_up'] and x.get('entry_time','00:00')<='10:00']
print(f"Pool: {len(target)} trades ({len(target)/(135/5):.1f}/wk)\n")
rows=[]
for tp, sl in product([10,15,20,25,35],[10,15,20,25,35]):
    r = sim(target, tp, sl, flat_exit=20)
    if r: r['tp_val']=tp; r['sl_val']=sl; rows.append(r)
df_sw = pd.DataFrame(rows).sort_values('total', ascending=False)
print(df_sw.head(20)[['tp_val','sl_val','n','wr','pf','ev','total','ann','tp']].to_string(index=False))
