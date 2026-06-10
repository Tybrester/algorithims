"""
Boof 22 final summary with atr_mult=0.6
Full 2025 + 2026 (Dec25-May26), $200/trade, 4xATR TP, 2xATR SL
Reports: WR, EV, P&L, trades/day, monthly breakdown
"""
import pickle, sys, numpy as np, pandas as pd
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
from backtest_boof22 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              FRACTAL_BARS, ATR_LEN, VOL_LEN, SR_DIST_MAX)

TRADE=200; TM=0.08; MAX_HOLD=30; ATR_SL=2.0; ATR_TP=4.0; ATR_MULT=0.6; F=FRACTAL_BARS
SYMS=['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']

print('Loading caches...')
cache25 = pickle.load(open('_boof22_cache.pkl','rb'))    # Jan-Dec 2025 (keys: (sym, 'Jan') etc)
cache26 = pickle.load(open('_boof_2026_cache.pkl','rb')) # 2026 months

MONTHS = [
    ('Jan 25', 'Jan', 23, cache25),
    ('Feb 25', 'Feb', 20, cache25),
    ('Mar 25', 'Mar', 21, cache25),
    ('Apr 25', 'Apr', 22, cache25),
    ('May 25', 'May', 21, cache25),
    ('Jun 25', 'Jun', 21, cache25),
    ('Jul 25', 'Jul', 23, cache25),
    ('Aug 25', 'Aug', 21, cache25),
    ('Sep 25', 'Sep', 21, cache25),
    ('Oct 25', 'Oct', 23, cache25),
    ('Nov 25', 'Nov', 20, cache25),
    ('Dec 25', 'Dec', 23, cache25),
    ('Jan 26', 'Jan 26', 22, cache26),
    ('Feb 26', 'Feb 26', 20, cache26),
    ('Mar 26', 'Mar 26', 21, cache26),
    ('Apr 26', 'Apr 26', 22, cache26),
    ('May 26', 'May 26', 18, cache26),
]

def run_month(mo_key, trading_days, cache):
    trades = []
    for sym in SYMS:
        df = cache.get((sym, mo_key))
        if df is None or len(df) < 100: continue
        df = df.copy().reset_index(drop=True)
        atr_s = compute_atr(df); df['atr'] = atr_s
        df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
        df['rvol'] = (df['volume'] / df['vol_sma'] * 100).fillna(0)
        df['hi_vol'] = df['volume'] > df['vol_sma'] * 1.3
        cp, _ = build_cluster_array(df, atr_s, 1.3)
        highs = df['high'].values; lows = df['low'].values; closes = df['close'].values

        for i in range(VOL_LEN + ATR_LEN + F, len(df) - F - MAX_HOLD - 3):
            row = df.iloc[i]
            if row['rvol'] < 80: continue
            atr = row['atr']
            if pd.isna(atr) or atr == 0 or not row['hi_vol']: continue
            if nearest_sr_distance(row['close'], cp, atr) > SR_DIST_MAX: continue
            lh=highs[i-F:i]; rh=highs[i+1:i+F+1]
            ll=lows[i-F:i];  rl=lows[i+1:i+F+1]
            fp=(highs[i]>lh.max())and(highs[i]>rh.max())
            ft=(lows[i]<ll.min()) and(lows[i]<rl.min())
            arp=closes[i]<highs[i]-atr*ATR_MULT
            arb=closes[i]>lows[i]+atr*ATR_MULT
            if fp and arp: d='short'
            elif ft and arb: d='long'
            else: continue
            if i+1 >= len(df)-MAX_HOLD-2: continue
            ep = float(df.iloc[i+1]['open'])
            tp_p=ep+atr*ATR_TP if d=='long' else ep-atr*ATR_TP
            sl_p=ep-atr*ATR_SL if d=='long' else ep+atr*ATR_SL
            et='time'
            for j in range(i+2, min(i+2+MAX_HOLD, len(df))):
                h=df['high'].iloc[j]; l=df['low'].iloc[j]
                if d=='long':
                    if h>=tp_p: et='tp'; break
                    if l<=sl_p: et='sl'; break
                else:
                    if l<=tp_p: et='tp'; break
                    if h>=sl_p: et='sl'; break
            pnl=(TRADE*(atr*ATR_TP/ep) if et=='tp'
                 else -TRADE*(atr*ATR_SL/ep) if et=='sl'
                 else TRADE*TM)
            trades.append({'pnl': pnl, 'et': et, 'sym': sym})
    return trades, trading_days

# ── Run all months ─────────────────────────────────────────────────
print('Running backtest...')
all_trades = []
monthly = []

for label, mo_key, tdays, cache in MONTHS:
    trades, td = run_month(mo_key, tdays, cache)
    pnls = np.array([t['pnl'] for t in trades])
    n = len(pnls)
    if n == 0:
        monthly.append((label, 0, 0, 0, 0, 0, td))
        continue
    w=pnls[pnls>0]; l=pnls[pnls<0]
    wr=round(len(w)/n*100,1)
    pf=round(float(sum(w)/max(abs(sum(l)),0.01)),2)
    ev=round(float(np.mean(pnls)),2)
    tot=round(float(sum(pnls)),2)
    tpd=round(n/td,1)
    monthly.append((label, n, wr, pf, ev, tot, td, tpd))
    all_trades.extend(trades)
    print(f'  {label}: {n} trades  {tpd}/day  WR={wr}%  EV=${ev}  P&L=${tot:,.0f}')

# ── Aggregate stats ────────────────────────────────────────────────
all_pnls = np.array([t['pnl'] for t in all_trades])
n_total = len(all_pnls)
wins = all_pnls[all_pnls>0]; losses = all_pnls[all_pnls<0]
wr_all = round(len(wins)/n_total*100,1)
pf_all = round(float(sum(wins)/max(abs(sum(losses)),0.01)),2)
ev_all = round(float(np.mean(all_pnls)),2)
total_pnl = round(float(sum(all_pnls)),2)
cum = np.cumsum(all_pnls)
dd = round(float((np.maximum.accumulate(cum)-cum).max()),2)
sharpe = round((np.mean(all_pnls)/np.std(all_pnls,ddof=1))*np.sqrt(n_total),2)
total_days = sum(m[6] for m in monthly)
avg_tpd = round(n_total/total_days,1)

# Exit type breakdown
tp_n=sum(1 for t in all_trades if t['et']=='tp')
sl_n=sum(1 for t in all_trades if t['et']=='sl')
tm_n=sum(1 for t in all_trades if t['et']=='time')

print(f'\n{"═"*72}')
print(f' BOOF 22.0 — FINAL SUMMARY | atr_mult=0.6 | $200/trade')
print(f' 4× ATR TP  |  2× ATR SL  |  30-bar max hold')
print(f'{"═"*72}')
print(f'\n  {"Month":<10}{"Trades":>8}{"T/day":>7}{"WR%":>7}{"PF":>7}{"EV$":>8}{"P&L":>12}')
print(f'  {"-"*62}')

yr25=[m for m in monthly if '25' in m[0]]
yr26=[m for m in monthly if '26' in m[0]]

print(f'  ── 2025 ──')
for m in yr25:
    if len(m)==8:
        print(f'  {m[0]:<10}{m[1]:>8}{m[7]:>7}{m[2]:>7}{m[3]:>7}{m[4]:>8}  ${m[5]:>9,.0f}')
pnl25=sum(m[5] for m in yr25 if len(m)==8)
n25=sum(m[1] for m in yr25 if len(m)==8)
print(f'  {"2025 TOTAL":<10}{n25:>8}{"":>7}{"":>7}{"":>7}{"":>8}  ${pnl25:>9,.0f}')

print(f'  ── 2026 ──')
for m in yr26:
    if len(m)==8:
        print(f'  {m[0]:<10}{m[1]:>8}{m[7]:>7}{m[2]:>7}{m[3]:>7}{m[4]:>8}  ${m[5]:>9,.0f}')
pnl26=sum(m[5] for m in yr26 if len(m)==8)
n26=sum(m[1] for m in yr26 if len(m)==8)
print(f'  {"2026 TOTAL":<10}{n26:>8}{"":>7}{"":>7}{"":>7}{"":>8}  ${pnl26:>9,.0f}')

print(f'\n{"═"*72}')
print(f'  OVERALL ({len(MONTHS)} months | {total_days} trading days)')
print(f'{"═"*72}')
print(f'  Total trades:      {n_total:,}')
print(f'  Trades/day:        {avg_tpd}  ({round(avg_tpd/9,1)} per symbol avg)')
print(f'  Win Rate:          {wr_all}%')
print(f'  Profit Factor:     {pf_all}')
print(f'  EV per trade:      ${ev_all}')
print(f'  Total P&L:         ${total_pnl:,.2f}')
print(f'  Max Drawdown:      ${dd:,.2f}')
print(f'  Sharpe:            {sharpe}')
print(f'  Exit breakdown:    TP={round(tp_n/n_total*100,1)}%  SL={round(sl_n/n_total*100,1)}%  Time={round(tm_n/n_total*100,1)}%')
print(f'  Avg monthly P&L:   ${round(total_pnl/len(MONTHS)):,}')
print(f'{"═"*72}')
