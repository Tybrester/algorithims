"""
BOOF60 P&L Scenarios — Stocks vs Options, multiple position sizes
Uses cached 2yr paths (boof60_final_paths.pkl)
Shows realistic annual P&L for different budgets and option multipliers
"""
import pickle, pandas as pd, numpy as np, os, pytz

FLAT_BARS=20; FLAT_THRESH=3.0; MAX_BARS=60
TP=25.0; SL=-10.0

with open('boof60_final_paths.pkl','rb') as f: raw=pickle.load(f)

ET=pytz.timezone('America/New_York')
def load_spy():
    import pyarrow.parquet as pq
    path=os.path.join('boof_data','SPY_5m_2yr.parquet')
    df=pd.read_parquet(path)
    df.columns=[c.lower() for c in df.columns]
    if df.index.tz is None: df.index=df.index.tz_localize('UTC')
    df.index=df.index.tz_convert(ET)
    rth=df.between_time('09:30','16:00')
    d=rth.resample('1D').agg(open=('open','first'),close=('close','last')).dropna()
    return sorted(d.index.date)[1:]

all_dates=load_spy()
n_weeks=len(all_dates)/5

def sim_trade(t, budget, mult, tp=TP, sl=SL):
    for j,b in enumerate(t['bars']):
        raw_pct = b['opt_pct']/3.0   # remove default 3x to get stock pct
        opt_pct = raw_pct * mult
        mfe_opt = b['mfe_opt']/3.0 * mult
        mae_opt = b['mae_opt']/3.0 * mult
        if mfe_opt >= tp:  return budget*tp/100,   'TP'
        if mae_opt <= sl:  return budget*sl/100,   'SL'
        if j>=FLAT_BARS and abs(opt_pct)<FLAT_THRESH:
            return budget*opt_pct/100, 'FLAT'
    last=t['bars'][-1]
    raw_pct=last['opt_pct']/3.0
    return budget*(raw_pct*mult)/100, 'TIMEOUT'

def run_scenario(budget, mult, label):
    res=[sim_trade(t,budget,mult) for t in raw]
    pnls=[r[0] for r in res]; exits=[r[1] for r in res]
    df=pd.DataFrame({'pnl':pnls,'exit':exits,'date':[t['date'] for t in raw]})
    w=df[df['pnl']>0]; l=df[df['pnl']<=0]
    wr=len(w)/len(df)
    pf=w['pnl'].sum()/abs(l['pnl'].sum()) if l['pnl'].sum()!=0 else 999
    total_2yr=df['pnl'].sum()
    ann=total_2yr/2
    per_week=ann/52
    per_month=ann/12
    max_risk=budget*abs(SL)/100   # max loss per trade
    df['month']=pd.to_datetime(df['date']).dt.to_period('M')
    monthly=df.groupby('month')['pnl'].sum()
    worst_month=monthly.min()
    best_month=monthly.max()
    pos_months=(monthly>0).sum()
    return {'label':label,'budget':budget,'mult':mult,'n':len(df),
            'wpw':round(len(df)/n_weeks,1),'wr':round(wr*100,1),'pf':round(pf,2),
            'ev':round(df['pnl'].mean(),2),'total_2yr':round(total_2yr,2),
            'ann':round(ann,2),'per_month':round(per_month,2),'per_week':round(per_week,2),
            'max_risk_per_trade':round(max_risk,2),'worst_month':round(worst_month,2),
            'best_month':round(best_month,2),'pos_months':f"{pos_months}/{len(monthly)}",
            'tp_n':exits.count('TP'),'sl_n':exits.count('SL')}

print("="*80)
print("BOOF60 P&L SCENARIOS — 2 Years (5,257 trades, 51.5/wk)")
print(f"TP={TP}%  SL={SL}%  Flat exit {FLAT_BARS} bars")
print("="*80)

# ── STOCKS (mult=1x) ──────────────────────────────────────────────
print(f"\n{'─'*80}")
print("STOCKS  (direct shares, no leverage)")
print(f"{'─'*80}")
print(f"  {'Setup':<30} {'$/wk':>8} {'$/mo':>9} {'$/yr':>10} {'WR':>6} {'PF':>5} {'Max loss/trade':>15} {'Worst mo':>10}")
print(f"  {'-'*30} {'-'*8} {'-'*9} {'-'*10} {'-'*6} {'-'*5} {'-'*15} {'-'*10}")
stock_scenarios=[
    (250,  1.0, "$250/trade"),
    (500,  1.0, "$500/trade"),
    (750,  1.0, "$750/trade"),
    (1000, 1.0, "$1,000/trade"),
    (1500, 1.0, "$1,500/trade"),
    (2000, 1.0, "$2,000/trade"),
    (3000, 1.0, "$3,000/trade"),
    (5000, 1.0, "$5,000/trade"),
]
for budget,mult,label in stock_scenarios:
    r=run_scenario(budget,mult,label)
    print(f"  {label:<30} ${r['per_week']:>7,.0f} ${r['per_month']:>8,.0f} ${r['ann']:>9,.0f} "
          f"{r['wr']:>5}% {r['pf']:>5}x ${r['max_risk_per_trade']:>12,.0f}  ${r['worst_month']:>9,.0f}")

# ── OPTIONS 2x mult ───────────────────────────────────────────────
print(f"\n{'─'*80}")
print("OPTIONS  2x multiplier  (slightly OTM 1DTE, slow mover stocks)")
print(f"{'─'*80}")
print(f"  {'Setup':<30} {'$/wk':>8} {'$/mo':>9} {'$/yr':>10} {'WR':>6} {'PF':>5} {'Max loss/trade':>15} {'Worst mo':>10}")
print(f"  {'-'*30} {'-'*8} {'-'*9} {'-'*10} {'-'*6} {'-'*5} {'-'*15} {'-'*10}")
for budget in [250,500,750,1000,1500,2000]:
    r=run_scenario(budget,2.0,f"${budget}/trade 2x")
    print(f"  {r['label']:<30} ${r['per_week']:>7,.0f} ${r['per_month']:>8,.0f} ${r['ann']:>9,.0f} "
          f"{r['wr']:>5}% {r['pf']:>5}x ${r['max_risk_per_trade']:>12,.0f}  ${r['worst_month']:>9,.0f}")

# ── OPTIONS 3x mult ───────────────────────────────────────────────
print(f"\n{'─'*80}")
print("OPTIONS  3x multiplier  (ATM 1DTE, moderate volatility — BASELINE)")
print(f"{'─'*80}")
print(f"  {'Setup':<30} {'$/wk':>8} {'$/mo':>9} {'$/yr':>10} {'WR':>6} {'PF':>5} {'Max loss/trade':>15} {'Worst mo':>10}")
print(f"  {'-'*30} {'-'*8} {'-'*9} {'-'*10} {'-'*6} {'-'*5} {'-'*15} {'-'*10}")
for budget in [250,500,750,1000,1500,2000,3000]:
    r=run_scenario(budget,3.0,f"${budget}/trade 3x")
    print(f"  {r['label']:<30} ${r['per_week']:>7,.0f} ${r['per_month']:>8,.0f} ${r['ann']:>9,.0f} "
          f"{r['wr']:>5}% {r['pf']:>5}x ${r['max_risk_per_trade']:>12,.0f}  ${r['worst_month']:>9,.0f}")

# ── OPTIONS 4x mult ───────────────────────────────────────────────
print(f"\n{'─'*80}")
print("OPTIONS  4x multiplier  (ATM 1DTE, high vol stocks like NVDA/TSLA/MSTR)")
print(f"{'─'*80}")
print(f"  {'Setup':<30} {'$/wk':>8} {'$/mo':>9} {'$/yr':>10} {'WR':>6} {'PF':>5} {'Max loss/trade':>15} {'Worst mo':>10}")
print(f"  {'-'*30} {'-'*8} {'-'*9} {'-'*10} {'-'*6} {'-'*5} {'-'*15} {'-'*10}")
for budget in [250,500,750,1000,1500,2000]:
    r=run_scenario(budget,4.0,f"${budget}/trade 4x")
    print(f"  {r['label']:<30} ${r['per_week']:>7,.0f} ${r['per_month']:>8,.0f} ${r['ann']:>9,.0f} "
          f"{r['wr']:>5}% {r['pf']:>5}x ${r['max_risk_per_trade']:>12,.0f}  ${r['worst_month']:>9,.0f}")

# ── OPTIONS 5x mult ───────────────────────────────────────────────
print(f"\n{'─'*80}")
print("OPTIONS  5x multiplier  (deep ITM or 2DTE on big movers)")
print(f"{'─'*80}")
print(f"  {'Setup':<30} {'$/wk':>8} {'$/mo':>9} {'$/yr':>10} {'WR':>6} {'PF':>5} {'Max loss/trade':>15} {'Worst mo':>10}")
print(f"  {'-'*30} {'-'*8} {'-'*9} {'-'*10} {'-'*6} {'-'*5} {'-'*15} {'-'*10}")
for budget in [250,500,750,1000,1500,2000]:
    r=run_scenario(budget,5.0,f"${budget}/trade 5x")
    print(f"  {r['label']:<30} ${r['per_week']:>7,.0f} ${r['per_month']:>8,.0f} ${r['ann']:>9,.0f} "
          f"{r['wr']:>5}% {r['pf']:>5}x ${r['max_risk_per_trade']:>12,.0f}  ${r['worst_month']:>9,.0f}")

# ── SUMMARY TABLE ─────────────────────────────────────────────────
print(f"\n{'─'*80}")
print("SUMMARY — $750/trade across all setups")
print(f"{'─'*80}")
print(f"  {'Setup':<35} {'$/yr':>10} {'$/mo':>9} {'WR':>6} {'PF':>5} {'Worst mo':>10} {'+ve months':>12}")
for mult,label in [(1.0,'Stock 1x'),(2.0,'Option 2x'),(3.0,'Option 3x (baseline)'),(4.0,'Option 4x'),(5.0,'Option 5x')]:
    r=run_scenario(750,mult,label)
    print(f"  {label:<35} ${r['ann']:>9,.0f} ${r['per_month']:>8,.0f} {r['wr']:>5}% {r['pf']:>5}x "
          f"${r['worst_month']:>9,.0f} {r['pos_months']:>12}")
