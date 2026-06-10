"""
BOOF 28 - Deep Analysis Suite
Version C baseline: no KLAC/QCOM/ADI/CRM/LRCX, no mega-cap shorts
Tests: Walk-Forward, EV, Equity Curve, PF by period, Rolling DD,
       Trade Distribution, Sharpe/Sortino, Monte Carlo, Regime Breakdown
"""
import sys, os, pickle, random
OUT = open('boof28_deep_analysis.txt', 'w', encoding='utf-8')
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
import numpy as np

# ── Universe (Version C) ──────────────────────────────────────────────
SECTORS = {
    "Semiconductors": ["NVDA","AMD","AVGO","MU","MCHP","ASML","TSM","AMAT","MRVL","INTC","ON","NXPI","TXN","ARM"],
    "Fintech":        ["HOOD","COIN","SQ","SOFI","AFRM","UPST","PYPL"],
    "Industrials":    ["CAT","ETN","DE","GE","URI","ROP","TT","EMR","HON"],
    "Biotech":        ["ISRG","MRNA","VRTX","REGN","LLY","GILD","PFE","BMY","ABBV","NVO","AMGN"],
    "Mega-cap Tech":  ["MSFT","TSLA","CRM","IBM"],
    "Travel":         ["UBER","ABNB","RCL","CCL"],
}
SYM_TO_SECTOR   = {s: sec for sec, syms in SECTORS.items() for s in syms}
ALL_SYMBOLS     = list(SYM_TO_SECTOR.keys())
SHORT_BAN_SEC   = {"Mega-cap Tech"}

def load(s):
    f = f"boof_cache/{s}_2025-01-01_2026-12-31.pkl"
    return pickle.load(open(f,'rb')) if os.path.exists(f) else None

def build_ema50(qqq):
    d = qqq.between_time('16:00','16:00').copy()
    d['date'] = d.index.date
    daily = d.groupby('date')['close'].last()
    return daily.ewm(span=50, adjust=False).mean().shift(1)

def get_ema(s, date):
    ts = pd.Timestamp(date)
    v  = s.get(ts)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        prior = [d for d in s.index if pd.Timestamp(d).date() < date]
        v = s[prior[-1]] if prior else None
    return v

def collect(all_data, ema50, start, end):
    qqq = all_data['QQQ'].copy()
    qqq = qqq[(qqq.index >= start) & (qqq.index <= end)]
    qqq['date'] = qqq.index.date
    trades = []
    for d in sorted(qqq['date'].unique()):
        qday = qqq[qqq['date']==d]
        qop  = qday.between_time('09:30','09:34')
        if len(qop)==0: continue
        q5   = (qop.iloc[-1]['close'] - qop.iloc[0]['open']) / qop.iloc[0]['open']
        qob  = qday.between_time('09:30','09:30')
        if len(qob)==0: continue
        qqq_open = qob.iloc[0]['open']
        e50  = get_ema(ema50, d)
        if e50 is None: continue
        bull = qqq_open > e50 and q5 >= 0.001
        bear = qqq_open < e50 and q5 <= -0.001
        if not bull and not bear: continue
        # QQQ regime for regime breakdown
        qqq_regime = 'bull' if bull else 'bear'
        for sym in ALL_SYMBOLS:
            if sym not in all_data: continue
            df   = all_data[sym].copy()
            df   = df[(df.index >= start) & (df.index <= end)]
            day  = df[df.index.date == d]
            if len(day)==0: continue
            so   = day.between_time('09:30','09:34')
            if len(so)==0: continue
            s5   = (so.iloc[-1]['close'] - so.iloc[0]['open']) / so.iloc[0]['open']
            en   = day.between_time('09:35','09:35')
            ex   = day.between_time('10:20','10:20')
            if len(en)==0 or len(ex)==0: continue
            ep   = en.iloc[0]['open']; xp = ex.iloc[0]['open']
            sec  = SYM_TO_SECTOR.get(sym,'Other')
            direction = None
            if bull and 0.006 <= s5 <= 0.007:
                direction = 'LONG'
            elif bear and -0.015 <= s5 <= -0.008:
                if sec in SHORT_BAN_SEC: continue
                direction = 'SHORT'
            if direction is None: continue
            pnl = (xp-ep)/ep*100 if direction=='LONG' else (ep-xp)/ep*100
            trades.append({'date':d,'symbol':sym,'sector':sec,'side':direction,
                           'pnl':pnl,'qqq_5m':round(q5*100,3),'qqq_regime':qqq_regime,
                           'month': pd.Timestamp(d).to_period('M'),
                           'quarter': pd.Timestamp(d).to_period('Q')})
    return trades

def pr(*a,**k):
    print(*a,**k)
    print(*a,**k,file=OUT)

def sep(c='=', w=85): pr(c*w)
def line(w=85): pr('-'*w)

# ── Load ──────────────────────────────────────────────────────────────
pr("Loading data...")
all_data = {}
for sym in ['QQQ'] + ALL_SYMBOLS:
    df = load(sym)
    if df is not None: all_data[sym] = df
pr(f"Loaded {len(all_data)} symbols\n")

ema50 = build_ema50(all_data['QQQ'].copy())

def dt(s): return pd.to_datetime(s).tz_localize('UTC')
S25, E25 = dt('2025-01-01'), dt('2025-12-31')
S26, E26 = dt('2026-01-01'), dt('2026-06-09')
SH1, EH1 = dt('2025-01-01'), dt('2025-06-30')
SH2, EH2 = dt('2025-07-01'), dt('2025-12-31')
SH3, EH3 = dt('2026-01-01'), dt('2026-06-09')

pr("Collecting trades...")
t_full  = collect(all_data, ema50, S25, E26)
t_25    = collect(all_data, ema50, S25, E25)
t_26    = collect(all_data, ema50, S26, E26)
t_h1    = collect(all_data, ema50, SH1, EH1)
t_h2    = collect(all_data, ema50, SH2, EH2)
t_h3    = collect(all_data, ema50, SH3, EH3)
pr(f"Full: {len(t_full)} trades | 2025: {len(t_25)} | 2026: {len(t_26)}\n")

df_full = pd.DataFrame(t_full)

# ═══════════════════════════════════════════════════════════════════════
# HELPER STATS
# ═══════════════════════════════════════════════════════════════════════
def base_stats(trades):
    if isinstance(trades, pd.DataFrame):
        df = trades
    else:
        if not trades: return {}
        df = pd.DataFrame(trades)
    if len(df) == 0: return {}
    n  = len(df)
    wins = df[df['pnl']>0]; loss = df[df['pnl']<=0]
    wr   = len(wins)/n
    aw   = wins['pnl'].mean() if len(wins) else 0
    al   = abs(loss['pnl'].mean()) if len(loss) else 0
    ev   = wr*aw - (1-wr)*al
    gp   = wins['pnl'].sum(); gl = abs(loss['pnl'].sum())
    pf   = gp/gl if gl>0 else 0
    tot  = df['pnl'].sum(); avg = df['pnl'].mean()
    cum  = df['pnl'].cumsum()
    dd   = (cum.expanding().max()-cum).max()
    return dict(n=n,wr=wr,aw=aw,al=al,ev=ev,pf=pf,tot=tot,avg=avg,dd=dd,
                wins=wins,loss=loss,df=df)

# ═══════════════════════════════════════════════════════════════════════
# 1. WALK-FORWARD TEST
# ═══════════════════════════════════════════════════════════════════════
sep()
pr("  TEST 1: WALK-FORWARD")
sep()
pr(f"  Strategy parameters are FIXED (Version C). No re-fitting.")
pr(f"  We only check if performance holds on unseen periods.\n")

wf_sets = [
    ("TRAIN: 2025 Full",          t_25),
    ("TEST:  2026 YTD (unseen)",   t_26),
    ("TRAIN: H1 2025 (Jan-Jun)",   t_h1),
    ("TEST:  H2 2025 (Jul-Dec)",   t_h2),
    ("TEST:  H3 2026 (Jan-Jun)",   t_h3),
]

pr(f"  {'Period':<35} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9} {'MaxDD':>8}")
line()
for label, t in wf_sets:
    if not t:
        pr(f"  {label:<35} {'NO TRADES':>7}"); continue
    s = base_stats(t)
    marker = " <-- TRAIN" if "TRAIN" in label else " <-- TEST (out-of-sample)"
    pr(f"  {label:<35} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}% -{s['dd']:>6.2f}%{marker}")
sep()

# ═══════════════════════════════════════════════════════════════════════
# 2. EXPECTANCY (EV)
# ═══════════════════════════════════════════════════════════════════════
sep()
pr("  TEST 2: EXPECTANCY (EV)")
sep()
s = base_stats(df_full)
pr(f"  Win Rate:          {s['wr']*100:.1f}%")
pr(f"  Avg Winner:        +{s['aw']:.3f}%")
pr(f"  Avg Loser:         -{s['al']:.3f}%")
pr(f"  EV per trade:      {s['ev']:+.4f}%")
pr(f"  EV formula:  ({s['wr']*100:.1f}% x +{s['aw']:.3f}%) - ({(1-s['wr'])*100:.1f}% x {s['al']:.3f}%) = {s['ev']:+.4f}%\n")

# By side
for side in ['LONG','SHORT']:
    sub = df_full[df_full['side']==side]
    if len(sub)==0: continue
    ss = base_stats(sub)
    pr(f"  {side:6}  WR {ss['wr']*100:.1f}%  AvgW +{ss['aw']:.3f}%  AvgL -{ss['al']:.3f}%  EV {ss['ev']:+.4f}%  PF {ss['pf']:.2f}")
sep()

# ═══════════════════════════════════════════════════════════════════════
# 3. EQUITY CURVE (text-based)
# ═══════════════════════════════════════════════════════════════════════
sep()
pr("  TEST 3: EQUITY CURVE (cumulative P&L by trade)")
sep()
cum = df_full['pnl'].cumsum().values
n   = len(cum)
# Print sparkline at 10 checkpoints
checkpoints = [int(i*(n-1)/(9)) for i in range(10)]
pr(f"  {'Trade#':>8} {'Cum PnL':>10} {'Bar':}")
line()
bar_max = 40
scale   = max(abs(cum)) / bar_max if max(abs(cum)) > 0 else 1
for i in checkpoints:
    v    = cum[i]
    bars = int(abs(v) / scale)
    bar  = ('+' if v>=0 else '-') * bars
    pr(f"  {i+1:>8} {v:>+9.2f}%  |{bar}")
pr(f"\n  Final: {cum[-1]:+.2f}%  |  Peak: {max(cum):+.2f}%  |  Trough: {min(cum):+.2f}%")
sep()

# ═══════════════════════════════════════════════════════════════════════
# 4. PROFIT FACTOR BY YEAR / QUARTER
# ═══════════════════════════════════════════════════════════════════════
sep()
pr("  TEST 4: PROFIT FACTOR BY YEAR / QUARTER")
sep()
pr(f"  {'Period':<12} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Total':>9}  Status")
line()
for yr, t in [('2025', t_25), ('2026 YTD', t_26)]:
    if not t: continue
    s = base_stats(t)
    status = "PASS" if s['pf'] >= 1.2 else "WARN"
    pr(f"  {yr:<12} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['tot']:>+8.2f}%  {status}")

line()
pr(f"  BY QUARTER:")
line()
for q in sorted(df_full['quarter'].unique()):
    sub = df_full[df_full['quarter']==q]
    s   = base_stats(sub)
    status = "PASS" if s['pf'] >= 1.2 else ("WARN" if s['pf'] >= 0.9 else "FAIL")
    pr(f"  {str(q):<12} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['tot']:>+8.2f}%  {status}")
sep()

# ═══════════════════════════════════════════════════════════════════════
# 5. ROLLING DRAWDOWN + RECOVERY
# ═══════════════════════════════════════════════════════════════════════
sep()
pr("  TEST 5: ROLLING DRAWDOWN & RECOVERY TIME")
sep()
cum_s  = df_full['pnl'].cumsum()
peak_s = cum_s.expanding().max()
dd_s   = cum_s - peak_s
max_dd = dd_s.min()
max_dd_idx = dd_s.idxmin()

# Find when DD started and recovered
dd_start = None
for i in range(max_dd_idx, -1, -1):
    if dd_s.iloc[i] == 0:
        dd_start = i
        break

recovered_at = None
for i in range(max_dd_idx, len(dd_s)):
    if dd_s.iloc[i] >= -0.01:
        recovered_at = i
        break

recovery_trades = (recovered_at - max_dd_idx) if recovered_at else None
if dd_start is not None:
    drawdown_trades = max_dd_idx - dd_start
else:
    drawdown_trades = max_dd_idx

pr(f"  Max Drawdown:         {max_dd:+.2f}%")
pr(f"  DD occurred at trade: #{max_dd_idx+1}")
if dd_start is not None:
    pr(f"  DD started at trade:  #{dd_start+1} ({drawdown_trades} trades to reach bottom)")
if recovery_trades:
    pr(f"  Recovery took:        {recovery_trades} trades after trough")
    # Dates
    dd_date   = df_full.iloc[max_dd_idx]['date']
    rec_date  = df_full.iloc[recovered_at]['date']
    pr(f"  DD bottom date:       {dd_date}")
    pr(f"  Recovery date:        {rec_date}")
else:
    pr(f"  Recovery:             Not fully recovered by end of period")

# Monthly DD view
pr(f"\n  Monthly cumulative P&L:")
line()
pr(f"  {'Month':>10} {'Total':>9} {'Cum':>9} {'DD from peak':>14}")
cum_so_far = 0.0
peak_so_far = 0.0
for m in sorted(df_full['month'].unique()):
    mdf = df_full[df_full['month']==m]
    mt  = mdf['pnl'].sum()
    cum_so_far += mt
    peak_so_far = max(peak_so_far, cum_so_far)
    dd_now = cum_so_far - peak_so_far
    pr(f"  {str(m):>10} {mt:>+8.2f}% {cum_so_far:>+8.2f}% {dd_now:>+13.2f}%")
sep()

# ═══════════════════════════════════════════════════════════════════════
# 6. TRADE DISTRIBUTION
# ═══════════════════════════════════════════════════════════════════════
sep()
pr("  TEST 6: TRADE DISTRIBUTION")
sep()
wins_all = df_full[df_full['pnl']>0]['pnl']
loss_all = df_full[df_full['pnl']<=0]['pnl']

pr(f"  WINNERS ({len(wins_all)} trades):")
pr(f"    Avg:      +{wins_all.mean():.3f}%")
pr(f"    Median:   +{wins_all.median():.3f}%")
pr(f"    Largest:  +{wins_all.max():.3f}%")
pr(f"    Std Dev:   {wins_all.std():.3f}%")
pr(f"    >1%:       {(wins_all>1).sum()} trades  ({(wins_all>1).mean()*100:.0f}%)")
pr(f"    >2%:       {(wins_all>2).sum()} trades  ({(wins_all>2).mean()*100:.0f}%)")

pr(f"\n  LOSERS ({len(loss_all)} trades):")
pr(f"    Avg:      {loss_all.mean():.3f}%")
pr(f"    Median:   {loss_all.median():.3f}%")
pr(f"    Largest:  {loss_all.min():.3f}%")
pr(f"    Std Dev:   {loss_all.std():.3f}%")
pr(f"    <-1%:      {(loss_all<-1).sum()} trades  ({(loss_all<-1).mean()*100:.0f}%)")
pr(f"    <-2%:      {(loss_all<-2).sum()} trades  ({(loss_all<-2).mean()*100:.0f}%)")

# PF from outliers vs core
top5_wins = wins_all.nlargest(5).sum()
rest_wins  = wins_all.sum() - top5_wins
pr(f"\n  PF concentration check:")
pr(f"    Top 5 winners contribute: +{top5_wins:.2f}% of +{wins_all.sum():.2f}% gross profit ({top5_wins/wins_all.sum()*100:.0f}%)")
pr(f"    Remaining {len(wins_all)-5} winners:     +{rest_wins:.2f}%")
sep()

# ═══════════════════════════════════════════════════════════════════════
# 7. SHARPE / SORTINO
# ═══════════════════════════════════════════════════════════════════════
sep()
pr("  TEST 7: SHARPE / SORTINO RATIO")
sep()
# Daily returns
daily_pnl = df_full.groupby('date')['pnl'].sum()
mu  = daily_pnl.mean()
std = daily_pnl.std()
# Annualize (252 trading days)
sharpe = (mu / std) * np.sqrt(252) if std > 0 else 0
# Sortino: only downside deviation
downside = daily_pnl[daily_pnl < 0]
sortino_std = downside.std() if len(downside) > 0 else std
sortino = (mu / sortino_std) * np.sqrt(252) if sortino_std > 0 else 0

pr(f"  Based on {len(daily_pnl)} active trading days")
pr(f"  Avg daily P&L:     {mu:+.4f}%")
pr(f"  Daily Std Dev:      {std:.4f}%")
pr(f"  Sharpe Ratio:      {sharpe:.2f}  (>1.0 good, >2.0 excellent)")
pr(f"  Sortino Ratio:     {sortino:.2f}  (penalizes only downside vol)")
sep()

# ═══════════════════════════════════════════════════════════════════════
# 8. MONTE CARLO (1000 simulations)
# ═══════════════════════════════════════════════════════════════════════
sep()
pr("  TEST 8: MONTE CARLO (1000 simulations, randomized trade order)")
sep()
pnl_list = df_full['pnl'].tolist()
N_SIM    = 1000
final_returns = []
max_dds       = []
random.seed(42)

for _ in range(N_SIM):
    shuffled = random.sample(pnl_list, len(pnl_list))
    cum = np.cumsum(shuffled)
    final_returns.append(cum[-1])
    peak = np.maximum.accumulate(cum)
    dd   = (cum - peak).min()
    max_dds.append(dd)

final_returns = np.array(final_returns)
max_dds       = np.array(max_dds)

pr(f"  Total trades simulated per run: {len(pnl_list)}")
pr(f"\n  FINAL RETURN distribution:")
pr(f"    Best case  (95th pct):  {np.percentile(final_returns,95):+.2f}%")
pr(f"    Expected   (median):    {np.median(final_returns):+.2f}%")
pr(f"    Worst case (5th pct):   {np.percentile(final_returns,5):+.2f}%")
pr(f"    % of sims profitable:   {(final_returns>0).mean()*100:.1f}%")

pr(f"\n  MAX DRAWDOWN distribution:")
pr(f"    Best case  (5th pct):   {np.percentile(max_dds,5):+.2f}%")
pr(f"    Expected   (median):    {np.median(max_dds):+.2f}%")
pr(f"    Worst case (95th pct):  {np.percentile(max_dds,95):+.2f}%")
pr(f"    DD > -30%:              {(max_dds<-30).mean()*100:.1f}% of simulations")
pr(f"    DD > -50%:              {(max_dds<-50).mean()*100:.1f}% of simulations")
sep()

# ═══════════════════════════════════════════════════════════════════════
# 9. REGIME BREAKDOWN
# ═══════════════════════════════════════════════════════════════════════
sep()
pr("  TEST 9: REGIME BREAKDOWN")
sep()
# Bull = QQQ open > EMA50 + 5m move up  (long trades day)
# Bear = QQQ open < EMA50 + 5m move down (short trades day)
# Use qqq_regime field from trades + QQQ price trend context

pr(f"  {'Regime':<10} {'Trades':>7} {'WR%':>6} {'PF':>6} {'EV':>8} {'Total':>9}")
line()
for regime in ['bull','bear']:
    sub = df_full[df_full['qqq_regime']==regime]
    if len(sub)==0: continue
    s = base_stats(sub)
    pr(f"  {regime.upper():<10} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}%")

# Further split bull regime by QQQ strength
line()
pr(f"  BULL days by QQQ 5m strength:")
line()
bull_trades = df_full[df_full['qqq_regime']=='bull'].copy()
buckets = [(0.1, 0.15,'0.10-0.15%'), (0.15,0.25,'0.15-0.25%'), (0.25,0.40,'0.25-0.40%'), (0.40,99,'> 0.40%')]
for lo, hi, lbl in buckets:
    sub = bull_trades[(bull_trades['qqq_5m']>=lo) & (bull_trades['qqq_5m']<hi)]
    if len(sub)==0: continue
    s = base_stats(sub)
    pr(f"  QQQ {lbl:<14} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}%")

line()
pr(f"  BEAR days by QQQ 5m strength:")
line()
bear_trades = df_full[df_full['qqq_regime']=='bear'].copy()
buckets_b = [(-0.15,-0.10,'0.10-0.15%'), (-0.25,-0.15,'0.15-0.25%'), (-0.40,-0.25,'0.25-0.40%'), (-99,-0.40,'> 0.40%')]
for lo, hi, lbl in buckets_b:
    sub = bear_trades[(bear_trades['qqq_5m']>=lo) & (bear_trades['qqq_5m']<hi)]
    if len(sub)==0: continue
    s = base_stats(sub)
    pr(f"  QQQ -{lbl:<14} {s['n']:>7} {s['wr']*100:>5.1f}% {s['pf']:>6.2f} {s['ev']:>+7.3f}% {s['tot']:>+8.2f}%")
sep()

OUT.flush(); OUT.close()
pr("\nDone. Full results in boof28_deep_analysis.txt")
