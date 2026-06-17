"""
BOOF 28 - MASTER BACKTEST (190 symbols, 2 years)
Entry: 9:35 open | Exit: 10:20 open
LONG:  QQQ>EMA50, QQQ_5m>=+0.10%, stock_5m 0.60-0.70%
SHORT: QQQ<EMA50, QQQ_5m<=-0.10%, stock_5m -0.80% to -1.50%
"""
import sys
OUT = open('boof28_master_results.txt', 'w', encoding='utf-8')
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import pandas as pd
import pickle
import os
import numpy as np

# ── Universe ──────────────────────────────────────────────────────────
SECTORS = {
    "Semiconductors": ["NVDA","AMD","AVGO","MU","AMAT","ASML","TSM","QCOM","TXN","ADI","NXPI","MCHP","ON","MPWR","LRCX","KLAC","MRVL","INTC","ARM","TER","SWKS","QRVO","GFS","COHR","WOLF"],
    "Mega-cap Tech":  ["MSFT","AAPL","META","GOOGL","GOOG","AMZN","TSLA","NFLX","ORCL","IBM","ADBE","CRM","NOW","INTU","PANW","SNOW"],
    "Fintech":        ["HOOD","COIN","SQ","FI","PYPL","SOFI","AFRM","UPST","MA","V","JPM","GS","MS","SCHW","BLK"],
    "Industrials":    ["CAT","ETN","PH","TT","DE","URI","GE","EMR","HON","ROP","ITW","FAST","PWR","CARR","JCI","IR","NOC","LMT","RTX","GD","BA","HUBB","XYL","DOV"],
    "Biotech":        ["LLY","NVO","ISRG","REGN","VRTX","ABBV","AMGN","GILD","MRNA","BMY","PFE","TMO","DHR","ABT","MDT","BSX","SYK","ZTS","IDXX","HCA","HUM","UNH","CI","CVS","ELV","MCK","COR","CAH"],
    "Energy":         ["XOM","CVX","COP","EOG","SLB","MPC","VLO","PSX","OXY","DVN","FANG","APA","HAL","BKR","KMI","WMB","LNG","EQT"],
    "Consumer":       ["COST","WMT","TGT","HD","LOW","SBUX","MCD","CMG","NKE","LULU","TJX","ROST","DG","DLTR","BBY","ULTA","YUM","KO","PEP","PM","MO","CL","PG"],
    "Travel":         ["UBER","ABNB","BKNG","EXPE","RCL","CCL","NCLH","MAR","HLT","WYNN","MGM","LVS"],
    "Communications": ["CMCSA","DIS","T","VZ","CHTR","TMUS","ROKU","SPOT","FOXA","WBD"],
    "Materials":      ["LIN","APD","SHW","ECL","FCX","NEM","DD","DOW","NUE","STLD","MLM","VMC"],
    "Utilities":      ["NEE","SO","DUK","AEP","XEL","EXC","SRE"],
}

SYM_TO_SECTOR = {s: sec for sec, syms in SECTORS.items() for s in syms}
ALL_SYMBOLS   = list(SYM_TO_SECTOR.keys())

# ── Helpers ───────────────────────────────────────────────────────────
def load_cached(s):
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

# ── Collect trades ────────────────────────────────────────────────────
def collect(all_data, ema50, start, end):
    qqq = all_data['QQQ'].copy()
    qqq = qqq[(qqq.index >= start) & (qqq.index <= end)]
    qqq['date'] = qqq.index.date
    trades = []
    trading_days = set()

    for d in sorted(qqq['date'].unique()):
        qday = qqq[qqq['date'] == d]
        qop  = qday.between_time('09:30','09:34')
        if len(qop) == 0: continue
        q5 = (qop.iloc[-1]['close'] - qop.iloc[0]['open']) / qop.iloc[0]['open']

        qopen_bar = qday.between_time('09:30','09:30')
        if len(qopen_bar) == 0: continue
        qqq_open_price = qopen_bar.iloc[0]['open']
        e50 = get_ema(ema50, d)
        if e50 is None: continue

        bull = qqq_open_price > e50 and q5 >= 0.001
        bear = qqq_open_price < e50 and q5 <= -0.001
        if not bull and not bear: continue

        trading_days.add(d)

        for sym in ALL_SYMBOLS:
            if sym not in all_data: continue
            df  = all_data[sym].copy()
            df  = df[(df.index >= start) & (df.index <= end)]
            day = df[df.index.date == d]
            if len(day) == 0: continue

            so = day.between_time('09:30','09:34')
            if len(so) == 0: continue
            s5 = (so.iloc[-1]['close'] - so.iloc[0]['open']) / so.iloc[0]['open']

            en = day.between_time('09:35','09:35')
            ex = day.between_time('10:20','10:20')
            if len(en) == 0 or len(ex) == 0: continue
            ep = en.iloc[0]['open']
            xp = ex.iloc[0]['open']

            direction = None
            if bull and 0.006 <= s5 <= 0.007:
                direction = 'LONG'
            elif bear and -0.015 <= s5 <= -0.008:
                direction = 'SHORT'
            if direction is None: continue

            if direction == 'LONG':
                pnl = (xp - ep) / ep * 100
            else:
                pnl = (ep - xp) / ep * 100

            trades.append({
                'date':     d,
                'symbol':   sym,
                'sector':   SYM_TO_SECTOR.get(sym, 'Other'),
                'side':     direction,
                'pnl':      pnl,
                'qqq_5m':   round(q5 * 100, 3),
                'stock_5m': round(s5 * 100, 3),
                'entry':    ep,
                'exit':     xp,
            })

    return trades, trading_days

# ── Report ────────────────────────────────────────────────────────────
def report(trades, trading_days, label):
    if not trades:
        print(f"\n{label}: NO TRADES"); return
    df = pd.DataFrame(trades)
    n  = len(df)
    W  = 90

    def pf(d):
        gp = d[d['pnl']>0]['pnl'].sum()
        gl = abs(d[d['pnl']<=0]['pnl'].sum())
        return gp/gl if gl>0 else 0

    def maxdd(d):
        c = d['pnl'].cumsum()
        return (c.expanding().max() - c).max()

    def wr(d): return len(d[d['pnl']>0]) / len(d) * 100

    wins = df[df['pnl']>0]; loss = df[df['pnl']<=0]
    gp   = wins['pnl'].sum(); gl = abs(loss['pnl'].sum())
    _pf  = gp/gl if gl>0 else 0
    _dd  = maxdd(df)
    _wr  = wr(df)
    _avg = df['pnl'].mean()
    _tot = df['pnl'].sum()
    tdays = len(trading_days)
    tpd   = n / tdays if tdays > 0 else 0

    ldf = df[df['side']=='LONG']
    sdf = df[df['side']=='SHORT']

    def pr(*a, **k): print(*a, **k); print(*a, **k, file=OUT)
    print("\n" + "="*W); OUT.write("\n" + "="*W + "\n")
    pr(f"  BOOF 28 -- MASTER BACKTEST  |  {label}")
    pr("="*W)
    pr(f"  {'Trades:':<22} {n}")
    pr(f"  {'Win Rate:':<22} {_wr:.1f}%")
    pr(f"  {'Avg Trade:':<22} {_avg:+.3f}%")
    pr(f"  {'Profit Factor:':<22} {_pf:.2f}")
    pr(f"  {'Max Drawdown:':<22} -{_dd:.2f}%")
    pr(f"  {'Total Return:':<22} {_tot:+.2f}%")
    pr(f"  {'Trading Days:':<22} {tdays}")
    pr(f"  {'Total Trades:':<22} {n}")
    pr(f"  {'Trades/Day:':<22} {tpd:.2f}")

    pr(f"\n  {'-'*W}")
    pr(f"  {'':8} {'Trades':>8} {'WR%':>7} {'PF':>6} {'Avg':>10} {'Total':>10}")
    pr(f"  {'-'*W}")
    for side, d in [('LONG', ldf), ('SHORT', sdf)]:
        if len(d)==0: continue
        pr(f"  {side:8} {len(d):>8} {wr(d):>6.1f}% {pf(d):>6.2f} {d['pnl'].mean():>+9.3f}% {d['pnl'].sum():>+9.2f}%")

    sector_order = ["Semiconductors","Mega-cap Tech","Fintech","Industrials","Biotech","Energy","Consumer","Travel","Communications","Materials","Utilities"]
    pr(f"\n  {'-'*W}")
    pr(f"  SECTOR BREAKDOWN")
    pr(f"  {'-'*W}")
    pr(f"  {'Sector':18} {'Trades':>8} {'WR%':>7} {'PF':>6} {'Avg':>10} {'Total':>10} {'Best Sym':>10}")
    pr(f"  {'-'*W}")
    for sec in sector_order:
        sub = df[df['sector']==sec]
        if len(sub)==0: continue
        best = sub.groupby('symbol')['pnl'].sum().idxmax()
        pr(f"  {sec:18} {len(sub):>8} {wr(sub):>6.1f}% {pf(sub):>6.2f} {sub['pnl'].mean():>+9.3f}% {sub['pnl'].sum():>+9.2f}% {best:>10}")

    # ── Top 75 symbols
    sym_stats = []
    for sym, grp in df.groupby('symbol'):
        sym_stats.append({
            'sym': sym, 'n': len(grp),
            'wr': wr(grp), 'pf': pf(grp),
            'avg': grp['pnl'].mean(), 'total': grp['pnl'].sum(),
            'sector': grp.iloc[0]['sector']
        })
    sym_df = pd.DataFrame(sym_stats).sort_values('total', ascending=False)

    pr(f"\n  {'-'*W}")
    pr(f"  TOP 75 SYMBOLS")
    pr(f"  {'-'*W}")
    pr(f"  {'#':>4} {'Symbol':>8} {'Sector':>16} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Avg':>9} {'Total':>9}")
    pr(f"  {'-'*W}")
    for i, (_, r) in enumerate(sym_df.head(75).iterrows(), 1):
        pr(f"  {i:>4} {r['sym']:>8} {r['sector']:>16} {r['n']:>7} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['avg']:>+8.3f}% {r['total']:>+8.2f}%")

    pr(f"\n  {'-'*W}")
    pr(f"  BOTTOM 20 SYMBOLS")
    pr(f"  {'-'*W}")
    pr(f"  {'#':>4} {'Symbol':>8} {'Sector':>16} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Avg':>9} {'Total':>9}")
    pr(f"  {'-'*W}")
    for i, (_, r) in enumerate(sym_df.tail(20).iloc[::-1].iterrows(), 1):
        pr(f"  {i:>4} {r['sym']:>8} {r['sector']:>16} {r['n']:>7} {r['wr']:>5.1f}% {r['pf']:>6.2f} {r['avg']:>+8.3f}% {r['total']:>+8.2f}%")

    df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
    pr(f"\n  {'-'*W}")
    pr(f"  MONTHLY BREAKDOWN")
    pr(f"  {'-'*W}")
    pr(f"  {'Month':>10} {'Trades':>8} {'L':>5} {'S':>5} {'WR%':>7} {'Total':>10} {'Cum':>10}")
    pr(f"  {'-'*W}")
    cum = 0.0
    for m in sorted(df['month'].unique()):
        mdf = df[df['month']==m]
        ml  = len(mdf[mdf['side']=='LONG'])
        ms  = len(mdf[mdf['side']=='SHORT'])
        mt  = mdf['pnl'].sum()
        cum += mt
        pr(f"  {str(m):>10} {len(mdf):>8} {ml:>5} {ms:>5} {wr(mdf):>6.1f}% {mt:>+9.2f}% {cum:>+9.2f}%")

    top50 = df.nlargest(50, 'pnl')[['date','symbol','side','pnl','qqq_5m','stock_5m']]
    pr(f"\n  {'-'*W}")
    pr(f"  TOP 50 TRADES")
    pr(f"  {'-'*W}")
    pr(f"  {'#':>4} {'Date':>12} {'Symbol':>8} {'Side':>6} {'P&L':>9} {'QQQ 5m':>8} {'Stock 5m':>9}")
    pr(f"  {'-'*W}")
    for i, (_, r) in enumerate(top50.iterrows(), 1):
        pr(f"  {i:>4} {str(r['date']):>12} {r['symbol']:>8} {r['side']:>6} {r['pnl']:>+8.2f}% {r['qqq_5m']:>+7.3f}% {r['stock_5m']:>+8.3f}%")

    bot20 = df.nsmallest(20, 'pnl')[['date','symbol','side','pnl','qqq_5m','stock_5m']]
    pr(f"\n  {'-'*W}")
    pr(f"  WORST 20 TRADES")
    pr(f"  {'-'*W}")
    pr(f"  {'#':>4} {'Date':>12} {'Symbol':>8} {'Side':>6} {'P&L':>9} {'QQQ 5m':>8} {'Stock 5m':>9}")
    pr(f"  {'-'*W}")
    for i, (_, r) in enumerate(bot20.iterrows(), 1):
        pr(f"  {i:>4} {str(r['date']):>12} {r['symbol']:>8} {r['side']:>6} {r['pnl']:>+8.2f}% {r['qqq_5m']:>+7.3f}% {r['stock_5m']:>+8.3f}%")

    pr("\n" + "="*W)
    OUT.flush()

# ── Main ─────────────────────────────────────────────────────────────
print("Loading data...")
all_data = {}
missing  = []
for sym in ['QQQ'] + ALL_SYMBOLS:
    df = load_cached(sym)
    if df is not None:
        all_data[sym] = df
    else:
        missing.append(sym)

print(f"Loaded {len(all_data)} symbols")
if missing:
    print(f"Missing (skipped): {missing}")

ema50 = build_ema50(all_data['QQQ'].copy())

s25s = pd.to_datetime('2025-01-01').tz_localize('UTC')
s25e = pd.to_datetime('2025-12-31').tz_localize('UTC')
s26s = pd.to_datetime('2026-01-01').tz_localize('UTC')
s26e = pd.to_datetime('2026-06-09').tz_localize('UTC')

print("\nRunning 2025...")
t25, d25 = collect(all_data, ema50, s25s, s25e)
print(f"  {len(t25)} trades on {len(d25)} days")

print("Running 2026...")
t26, d26 = collect(all_data, ema50, s26s, s26e)
print(f"  {len(t26)} trades on {len(d26)} days")

report(t25,         d25,       "2025 FULL YEAR")
report(t26,         d26,       "2026 YTD (Jan–Jun 9)")
report(t25 + t26,   d25 | d26, "COMBINED (2025 + 2026 YTD)")
