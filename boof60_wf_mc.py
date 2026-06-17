"""
BOOF60 Walk-Forward + Monte Carlo + 2-Year Full Backtest
Strategy : Gap-up >1.5% + SPY up day + PDH break + entry ≤10:00
           + flat exit after 20 bars (100 min) if no move
TP=25%, SL=-10%, 3x option multiplier, $750/trade
"""
import os, pytz, pickle
import pandas as pd
import numpy as np
from datetime import date

ET     = pytz.timezone('America/New_York')
CACHE  = "boof_data"
SUFFIX = "_5m_2yr.parquet"
BUDGET = 750.0
TP     = 25.0
SL     = -10.0
MULT   = 3.0
GAP_MIN    = 1.5
MAX_BARS   = 60
FLAT_BARS  = 20
FLAT_THRESH= 3.0   # % — exit if still within ±3% after 20 bars
MAX_POS    = 5

SYMBOLS = [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX',
    'SOFI','IONQ','RGTI','QUBT','ACHR','JOBY','LUNR','RDDT','CAVA','DUOL',
    'CELH','DKNG','MELI','SHOP','PYPL','SPOT','PINS','SNAP','LYFT','RIVN',
    'LCID','CHWY','SOUN','BBAI','AI','ASTS','RKLB','IREN','CORZ',
]

# ── Load data ──────────────────────────────────────────────────────
def load_sym(sym):
    path = os.path.join(CACHE, f"{sym}{SUFFIX}")
    if not os.path.exists(path): return pd.DataFrame()
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if df.index.tz is None: df.index = df.index.tz_localize('UTC')
    df.index = df.index.tz_convert(ET)
    return df

print("Loading 2yr data...")
data = {}
for sym in SYMBOLS + ['SPY','QQQ']:
    df = load_sym(sym)
    if not df.empty: data[sym] = df
print(f"  Loaded {len(data)} symbols")

print("Building daily OHLC...")
daily = {}
for sym, df in data.items():
    rth = df.between_time('09:30','16:00')
    d   = rth.resample('1D').agg(open=('open','first'),high=('high','max'),
                                  low=('low','min'),close=('close','last')).dropna()
    daily[sym] = d

spy_daily = daily['SPY']
all_dates  = sorted(spy_daily.index.date)[1:]
spy_up_set = {d.date() if hasattr(d,'date') else d
              for d,r in spy_daily.iterrows() if r['close'] > r['open']}
print(f"  {len(all_dates)} trading days ({all_dates[0]} → {all_dates[-1]})\n")

# ── Signal collection ──────────────────────────────────────────────
PKL = "boof60_2yr_paths.pkl"
if os.path.exists(PKL):
    print(f"Loading cached 2yr paths from {PKL}...")
    with open(PKL,'rb') as f: raw_trades = pickle.load(f)
    print(f"  {len(raw_trades)} trade paths\n")
else:
    print("Collecting signals (2yr pass)...")
    raw_trades = []
    for di, day in enumerate(all_dates):
        if di % 50 == 0: print(f"  Day {di}/{len(all_dates)} — {day}  trades so far: {len(raw_trades)}")
        spy_prices = []; regime = "neutral"; active_pos = {}
        spy_rth = data['SPY'][data['SPY'].index.date == day].between_time('09:30','15:55')

        for sym in SYMBOLS:
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
                    ep  = in_trade['entry_price']
                    stk = (price-ep)/ep*100; mfe=(high-ep)/ep*100; mae=(low-ep)/ep*100
                    in_trade['bars_held'] += 1
                    bar_path.append({'opt_pct':stk*MULT,'mfe_opt':mfe*MULT,'mae_opt':mae*MULT,'hm':hm})
                    if in_trade['bars_held'] >= MAX_BARS or hm >= '15:50':
                        raw_trades.append({'date':day,'sym':sym,'entry_time':in_trade['entry_time'],
                            'regime':regime,'gap_pct':gap_pct,'spy_up':day in spy_up_set,'bars':bar_path})
                        in_trade=None; bar_path=[]
                        if sym in active_pos: del active_pos[sym]
                    continue
                if hm > '10:00': break
                if len(active_pos) >= MAX_POS: continue
                if price > pdh and not confirm: confirm=True; continue
                if price > pdh and confirm and regime in ('bull','neutral') and day in spy_up_set:
                    in_trade = {'entry_price':price,'entry_time':hm,'bars_held':0}
                    active_pos[sym] = True
            if in_trade and bar_path:
                raw_trades.append({'date':day,'sym':sym,'entry_time':in_trade['entry_time'],
                    'regime':regime,'gap_pct':gap_pct,'spy_up':day in spy_up_set,'bars':bar_path})

    with open(PKL,'wb') as f: pickle.dump(raw_trades,f)
    print(f"\n  {len(raw_trades)} paths cached to {PKL}\n")

# ── Core sim function ──────────────────────────────────────────────
def sim_trade(t, tp=TP, sl=SL, flat_bars=FLAT_BARS):
    for j, b in enumerate(t['bars']):
        if b['mfe_opt'] >= tp:      return BUDGET*tp/100,    'TP'
        if b['mae_opt'] <= sl:      return BUDGET*sl/100,    'SL'
        if j >= flat_bars and abs(b['opt_pct']) < FLAT_THRESH:
            return BUDGET*b['opt_pct']/100, 'FLAT'
    last = t['bars'][-1]
    return BUDGET*last['opt_pct']/100, 'TIMEOUT'

def run_backtest(trades, tp=TP, sl=SL, flat_bars=FLAT_BARS, label=""):
    results = [sim_trade(t, tp, sl, flat_bars) for t in trades]
    pnls    = [r[0] for r in results]
    exits   = [r[1] for r in results]
    df = pd.DataFrame({'pnl':pnls,'exit':exits,'date':[t['date'] for t in trades]})
    if df.empty: return None
    wins = df[df['pnl']>0]; losses = df[df['pnl']<=0]
    wr   = len(wins)/len(df)
    pf   = wins['pnl'].sum()/abs(losses['pnl'].sum()) if losses['pnl'].sum()!=0 else 999
    ev   = df['pnl'].mean()
    months = (df['date'].max() - df['date'].min()).days / 30.44
    return {
        'label':label, 'n':len(df), 'wr':round(wr*100,1), 'pf':round(pf,2),
        'ev':round(ev,2), 'total':round(df['pnl'].sum(),2),
        'ann':round(df['pnl'].sum()/max(months,1)*12,2),
        'tp_n':exits.count('TP'), 'sl_n':exits.count('SL'),
        'flat_n':exits.count('FLAT'), 'df':df
    }

# ═══════════════════════════════════════════════════════════════════
# 1. FULL 2-YEAR BACKTEST
# ═══════════════════════════════════════════════════════════════════
print("="*65)
print("1. FULL 2-YEAR BACKTEST")
print("="*65)
full = run_backtest(raw_trades, label="2yr_full")
print(f"  Period:      {all_dates[0]} → {all_dates[-1]}")
print(f"  Trades:      {full['n']}  ({full['n']/len(all_dates)*5:.1f}/week)")
print(f"  Win Rate:    {full['wr']}%")
print(f"  Prof Factor: {full['pf']}x")
print(f"  EV/trade:    ${full['ev']}")
print(f"  Total P&L:   ${full['total']}")
print(f"  Annualized:  ${full['ann']}/yr")
print(f"  Exits → TP:{full['tp_n']}  SL:{full['sl_n']}  FLAT:{full['flat_n']}  TIMEOUT:{full['n']-full['tp_n']-full['sl_n']-full['flat_n']}")

print("\n  Monthly breakdown:")
full['df']['month'] = pd.to_datetime(full['df']['date']).dt.to_period('M')
mb = full['df'].groupby('month').agg(
    n=('pnl','count'), pnl=('pnl','sum'),
    wr=('pnl', lambda x: f"{(x>0).mean()*100:.0f}%"),
    avg=('pnl','mean')).round(2)
print(mb.to_string())

# ═══════════════════════════════════════════════════════════════════
# 2. WALK-FORWARD TEST (6 rolling windows)
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*65}")
print("2. WALK-FORWARD TEST")
print("   Train 6 months → Test 2 months (rolling, 6 windows)")
print(f"{'='*65}")

wf_results = []
TRAIN_DAYS = 126   # ~6 months trading days
TEST_DAYS  = 42    # ~2 months trading days

for i in range(6):
    train_start = i * TEST_DAYS
    train_end   = train_start + TRAIN_DAYS
    test_start  = train_end
    test_end    = test_start + TEST_DAYS
    if test_end > len(all_dates): break

    train_dates = set(all_dates[train_start:train_end])
    test_dates  = set(all_dates[test_start:test_end])

    train_t = [t for t in raw_trades if t['date'] in train_dates]
    test_t  = [t for t in raw_trades if t['date'] in test_dates]

    if not train_t or not test_t: continue

    tr = run_backtest(train_t, label=f"train_{i+1}")
    te = run_backtest(test_t,  label=f"test_{i+1}")

    wf_results.append({
        'window': i+1,
        'train_period': f"{all_dates[train_start]} → {all_dates[train_end-1]}",
        'test_period':  f"{all_dates[test_start]} → {all_dates[test_end-1]}",
        'train_n': tr['n'], 'train_wr': tr['wr'], 'train_pf': tr['pf'], 'train_pnl': tr['total'],
        'test_n':  te['n'], 'test_wr':  te['wr'], 'test_pf':  te['pf'], 'test_pnl':  te['total'],
        'test_ann': te['ann'],
    })
    print(f"\n  Window {i+1}:")
    print(f"    TRAIN {all_dates[train_start]}→{all_dates[train_end-1]}  n={tr['n']}  WR={tr['wr']}%  PF={tr['pf']}x  P&L=${tr['total']}")
    print(f"    TEST  {all_dates[test_start]}→{all_dates[test_end-1]}   n={te['n']}  WR={te['wr']}%  PF={te['pf']}x  P&L=${te['total']}  ann=${te['ann']}")

wf_df = pd.DataFrame(wf_results)
print(f"\n  Walk-Forward Summary:")
print(f"  Avg test WR:  {wf_df['test_wr'].mean():.1f}%")
print(f"  Avg test PF:  {wf_df['test_pf'].mean():.2f}x")
print(f"  Avg test P&L: ${wf_df['test_pnl'].mean():.2f} / 2mo")
print(f"  Profitable windows: {(wf_df['test_pnl']>0).sum()}/{len(wf_df)}")
print(f"  WF Efficiency: {wf_df['test_pnl'].mean()/(wf_df['train_pnl'].mean()/3)*100:.0f}%  (test P&L vs 1/3 train)")

# ═══════════════════════════════════════════════════════════════════
# 3. MONTE CARLO (10,000 simulations)
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*65}")
print("3. MONTE CARLO SIMULATION  (10,000 runs)")
print(f"{'='*65}")

pnls = np.array([sim_trade(t)[0] for t in raw_trades])
n    = len(pnls)
RUNS = 10000

np.random.seed(42)
mc_totals   = []
mc_maxdd    = []
mc_wr       = []

for _ in range(RUNS):
    sample  = np.random.choice(pnls, size=n, replace=True)
    mc_totals.append(sample.sum())
    mc_wr.append((sample > 0).mean())
    # max drawdown on this run
    equity = np.cumsum(sample)
    peak   = np.maximum.accumulate(equity)
    dd     = equity - peak
    mc_maxdd.append(dd.min())

mc_totals = np.array(mc_totals)
mc_maxdd  = np.array(mc_maxdd)
mc_wr     = np.array(mc_wr)

print(f"\n  Inputs: {n} trades, actual total ${pnls.sum():.2f}")
print(f"\n  TOTAL P&L distribution (2yr):")
print(f"    5th  pct:  ${np.percentile(mc_totals,5):>10.2f}  (worst likely)")
print(f"    25th pct:  ${np.percentile(mc_totals,25):>10.2f}")
print(f"    50th pct:  ${np.percentile(mc_totals,50):>10.2f}  (median)")
print(f"    75th pct:  ${np.percentile(mc_totals,75):>10.2f}")
print(f"    95th pct:  ${np.percentile(mc_totals,95):>10.2f}  (best likely)")
print(f"    Prob > $0: {(mc_totals>0).mean()*100:.1f}%")
print(f"    Prob > $5k/yr: {(mc_totals>10000).mean()*100:.1f}%")
print(f"    Prob > $10k/yr:{(mc_totals>20000).mean()*100:.1f}%")

print(f"\n  MAX DRAWDOWN distribution:")
print(f"    Median max DD:    ${np.percentile(mc_maxdd,50):>10.2f}")
print(f"    95th pct max DD:  ${np.percentile(mc_maxdd,95):>10.2f}  (worst 5% of runs)")
print(f"    Worst seen:       ${mc_maxdd.min():>10.2f}")

print(f"\n  WIN RATE distribution:")
print(f"    5th pct WR:   {np.percentile(mc_wr,5)*100:.1f}%")
print(f"    Median WR:    {np.percentile(mc_wr,50)*100:.1f}%")
print(f"    95th pct WR:  {np.percentile(mc_wr,95)*100:.1f}%")

# Sharpe-like ratio (annual P&L / std of monthly P&L)
full['df']['month'] = pd.to_datetime(full['df']['date']).dt.to_period('M')
monthly_pnl = full['df'].groupby('month')['pnl'].sum()
sharpe = monthly_pnl.mean() / monthly_pnl.std() * np.sqrt(12) if monthly_pnl.std() > 0 else 0
print(f"\n  Monthly Sharpe (annualized): {sharpe:.2f}")
print(f"  Monthly P&L std:  ${monthly_pnl.std():.2f}")
print(f"  Monthly P&L mean: ${monthly_pnl.mean():.2f}")
print(f"  Worst month:      ${monthly_pnl.min():.2f}")
print(f"  Best month:       ${monthly_pnl.max():.2f}")
print(f"  Positive months:  {(monthly_pnl>0).sum()}/{len(monthly_pnl)}")

# ═══════════════════════════════════════════════════════════════════
# 4. ROBUSTNESS — sensitivity to params
# ═══════════════════════════════════════════════════════════════════
print(f"\n{'='*65}")
print("4. PARAMETER SENSITIVITY (does small change break it?)")
print(f"{'='*65}")
sens = [
    ("BASE  TP=25 SL=-10 flat=20",  25, -10, 20),
    ("TP=20 SL=-10 flat=20",        20, -10, 20),
    ("TP=30 SL=-10 flat=20",        30, -10, 20),
    ("TP=25 SL=-8  flat=20",        25,  -8, 20),
    ("TP=25 SL=-12 flat=20",        25, -12, 20),
    ("TP=25 SL=-10 flat=15",        25, -10, 15),
    ("TP=25 SL=-10 flat=25",        25, -10, 25),
    ("TP=25 SL=-10 no_flat",        25, -10, 999),
]
print(f"  {'Config':<35} {'n':>5}  {'WR':>6}  {'PF':>5}  {'Total':>9}  {'Ann':>10}")
print(f"  {'-'*35} {'-'*5}  {'-'*6}  {'-'*5}  {'-'*9}  {'-'*10}")
for label, tp, sl, fb in sens:
    r = run_backtest(raw_trades, tp=tp, sl=sl, flat_bars=fb)
    if r:
        print(f"  {label:<35} {r['n']:>5}  {r['wr']:>5}%  {r['pf']:>5}x  ${r['total']:>8.0f}  ${r['ann']:>9.0f}/yr")

print(f"\n{'='*65}")
print("VERDICT")
print(f"{'='*65}")
wf_pass  = (wf_df['test_pnl']>0).sum() >= 4  if len(wf_df)>0 else False
mc_pass  = (mc_totals>0).mean() >= 0.75
wr_pass  = full['wr'] >= 60.0
pf_pass  = full['pf'] >= 2.0
freq_pass= full['n']/len(all_dates)*5 >= 8.0

checks = [
    ("WR ≥ 60%",           wr_pass,   f"{full['wr']}%"),
    ("PF ≥ 2.0x",          pf_pass,   f"{full['pf']}x"),
    ("8+ trades/week",     freq_pass, f"{full['n']/len(all_dates)*5:.1f}/wk"),
    ("MC prob>0 ≥ 75%",    mc_pass,   f"{(mc_totals>0).mean()*100:.1f}%"),
    ("WF 4/6 profitable",  wf_pass,   f"{(wf_df['test_pnl']>0).sum()}/6 windows" if len(wf_df)>0 else "N/A"),
]
all_pass = all(c[1] for c in checks)
for name, passed, val in checks:
    print(f"  {'✓' if passed else '✗'}  {name:<25} {val}")
print(f"\n  {'DEPLOY READY ✓' if all_pass else 'NOT READY — fix failing checks'}")
