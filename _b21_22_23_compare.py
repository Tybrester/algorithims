"""
Boof 21 vs 22 vs 23 — Head-to-Head Comparison
===============================================
B21: Boof ETF list (QQQ, SPY) — $250/trade — cache: _boof21_cache.pkl
B22: Boof No-ETF list (AAPL, NVDA, META, GOOGL, AMD) — $200 exp / $600 core
B23: Boof No-ETF list (NVDA, AAPL, MSFT, AMZN, GOOGL, AVGO, META, TSLA, BRK.B, LLY)
                       — $200 exp / $500 core (capped)

Shared period: Jan-Dec 2025 (12 months, ~252 trading days)
Metrics: rolling monthly P&L, trades/day, WR, PF, EV/trade
"""
import pickle, sys, numpy as np, pandas as pd
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
import backtest_boof21 as bt21
from backtest_boof22 import (compute_atr as b22_atr, build_cluster_array as b22_bca,
                              nearest_sr_distance as b22_nsd,
                              SYMBOL_PARAMS as B22_SP, DEFAULT_PARAMS as B22_DP,
                              ATR_LEN as B22_ATR_LEN, VOL_LEN as B22_VOL_LEN,
                              FRACTAL_BARS as B22_FB)
from backtest_boof23 import (compute_atr, build_cluster_array, nearest_sr_distance,
                              _build_zigzag, SYMBOL_PARAMS, DEFAULT_PARAMS,
                              ATR_LEN, VOL_LEN, ATR_TP, ATR_SL, ATR_MULT,
                              FRACTAL_BARS, TIME_EXIT_PCT, MAX_HOLD)

# ── Symbol lists ──────────────────────────────────────────────────
B21_SYMS   = ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOGL']
B22_SYMS   = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']
B23_SYMS   = ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'AVGO', 'META', 'TSLA', 'LLY']

# ── Sizing ────────────────────────────────────────────────────────
B21_SIZE    = 250
B21_TP      = 0.35   # fixed +35% options TP
B21_SL      = -0.10  # fixed -10% options SL
B21_TM      = 0.08   # time exit estimate
B22_EXP     = 200; B22_CORE = 600
B23_EXP     = 200; B23_CORE = 500   # capped

# ── Month calendar ────────────────────────────────────────────────
MONTHS_21 = ['Jan 25','Feb 25','Mar 25','Apr 25','May 25','Jun 25',
             'Jul 25','Aug 25','Sep 25','Oct 25','Nov 25','Dec 25']
MONTHS_22 = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MONTH_DAYS = [23,20,21,22,21,21,23,21,22,23,20,23]   # trading days per month 2025
MONTH_LABELS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
TOTAL_DAYS = sum(MONTH_DAYS)
PROX = 30

print('Loading caches...')
cache21 = pickle.load(open('_boof21_cache.pkl',  'rb'))
cache22 = pickle.load(open('_boof22_cache.pkl',  'rb'))
print('  Caches loaded.\n')

# ══════════════════════════════════════════════════════════════════
# B21 — run via backtest_boof21.backtest()
# pnl is underlying fraction → multiply by entry price to get $
# Then scale to $250 notional: dollar_pnl = pnl_frac * B21_SIZE
# ══════════════════════════════════════════════════════════════════
print('Running Boof 21...')
b21_monthly = {}
for mo21, mo_label in zip(MONTHS_21, MONTH_LABELS):
    trades = []
    for sym in B21_SYMS:
        df = cache21.get((sym, mo21))
        if df is None or len(df) < 100: continue
        df = df.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            if 'timestamp' in df.columns:
                df = df.set_index(pd.to_datetime(df['timestamp']))
            else:
                df.index = pd.to_datetime(df.index)
        t = bt21.backtest(df, symbol=sym)
        for tr in t:
            et = tr['exit_type']
            pnl = B21_SIZE * (B21_TP if et=='tp' else B21_SL if et=='stop' else B21_TM)
            trades.append({'pnl_dollar': pnl, 'sym': sym})
    b21_monthly[mo_label] = trades
    print(f'  B21 {mo_label}: {len(trades)} trades')

# ══════════════════════════════════════════════════════════════════
# B22 — run via backtest_boof22.run_backtest()
# Check what run_backtest returns
# ══════════════════════════════════════════════════════════════════
def run_b22_month(sym, df):
    """B22 inline ATR engine — same fractal SR logic, no ZigZag layer."""
    trades = []
    params   = B22_SP.get(sym, B22_DP)
    vol_mult = params['vol_mult']
    atr_mult = params['atr_mult']
    sr_dist  = params['sr_dist']
    F        = B22_FB

    df = df.copy().reset_index(drop=True)
    atr_s         = b22_atr(df)
    df['atr']     = atr_s
    df['vol_sma'] = df['volume'].rolling(B22_VOL_LEN).mean()
    df['rvol']    = (df['volume'] / df['vol_sma'] * 100).fillna(0)
    df['hi_vol']  = df['volume'] > df['vol_sma'] * vol_mult
    cluster_prices, _ = b22_bca(df, atr_s, vol_mult)

    opens  = df['open'].values;  highs = df['high'].values
    lows   = df['low'].values;   closes= df['close'].values
    atrs   = df['atr'].values;   hi_vol= df['hi_vol'].values

    in_trade = False; trade_end = 0
    warmup = B22_VOL_LEN + B22_ATR_LEN + F

    for i in range(warmup, len(df) - F - MAX_HOLD - 3):
        if in_trade and i <= trade_end: continue
        atr = atrs[i]
        if np.isnan(atr) or atr == 0: continue
        if df.iloc[i]['rvol'] < 80:   continue
        if not hi_vol[i]:             continue
        if b22_nsd(closes[i], cluster_prices, atr) > sr_dist: continue

        lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
        ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
        fp = (highs[i] > lh.max()) and (highs[i] > rh.max())
        ft = (lows[i]  < ll.min()) and (lows[i]  < rl.min())
        ps = (highs[i] - closes[i]) / atr
        ts = (closes[i] - lows[i])  / atr

        direction = None; slack = 0.0
        if fp and ps >= atr_mult:  direction = 'short'; slack = ps
        elif ft and ts >= atr_mult: direction = 'long';  slack = ts
        if direction is None: continue

        entry_bar = i + 1
        if entry_bar >= len(df) - MAX_HOLD - 2: continue
        ep   = float(opens[entry_bar])
        tp_p = ep + atr*ATR_TP if direction=='long' else ep - atr*ATR_TP
        sl_p = ep - atr*ATR_SL if direction=='long' else ep + atr*ATR_SL
        et = 'time'; exit_bar = min(entry_bar + MAX_HOLD, len(df)-1)
        for j in range(entry_bar+1, min(entry_bar+MAX_HOLD+1, len(df))):
            h = highs[j]; l = lows[j]
            if direction=='long':
                if h>=tp_p: et='tp'; exit_bar=j; break
                if l<=sl_p: et='sl'; exit_bar=j; break
            else:
                if l<=tp_p: et='tp'; exit_bar=j; break
                if h>=sl_p: et='sl'; exit_bar=j; break

        in_trade = True; trade_end = exit_bar
        pnl_pct = (ATR_TP/ep*atr if et=='tp'
                   else -ATR_SL/ep*atr if et=='sl'
                   else TIME_EXIT_PCT)
        size = B22_CORE if slack >= 1.4 else B22_EXP
        trades.append({'pnl_dollar': pnl_pct * size, 'sym': sym,
                       'tier': 'core' if slack >= 1.4 else 'expanded'})
    return trades

print('\nRunning Boof 22...')
b22_monthly = {}
for mo_label, mo22 in zip(MONTH_LABELS, MONTHS_22):
    trades = []
    for sym in B22_SYMS:
        df = cache22.get((sym, mo22))
        if df is None or len(df) < 100: continue
        trades.extend(run_b22_month(sym, df))
    b22_monthly[mo_label] = trades
    print(f'  B22 {mo_label}: {len(trades)} trades')

# ══════════════════════════════════════════════════════════════════
# B23 — run inline (same engine used throughout session)
# ══════════════════════════════════════════════════════════════════
print('\nRunning Boof 23...')

def run_b23_month(sym, df):
    trades = []
    params      = SYMBOL_PARAMS.get(sym, DEFAULT_PARAMS)
    vol_mult    = params['vol_mult']
    atr_mult    = params['atr_mult']
    sr_dist_max = params['sr_dist']
    F           = FRACTAL_BARS

    df = df.copy().reset_index(drop=True)
    atr_s         = compute_atr(df)
    df['atr']     = atr_s
    df['vol_sma'] = df['volume'].rolling(VOL_LEN).mean()
    df['rvol']    = (df['volume'] / df['vol_sma'] * 100).fillna(0)
    df['hi_vol']  = df['volume'] > df['vol_sma'] * vol_mult
    cluster_prices, _ = build_cluster_array(df, atr_s, vol_mult)

    opens  = df['open'].values;  highs = df['high'].values
    lows   = df['low'].values;   closes= df['close'].values
    atrs   = df['atr'].values;   hi_vol= df['hi_vol'].values

    trend_arr, _, zz_high_bar, _, zz_low_bar = _build_zigzag(highs, lows, opens, closes)

    in_trade = False; trade_end = 0
    warmup = VOL_LEN + ATR_LEN + F

    for i in range(warmup, len(df) - F - MAX_HOLD - 3):
        if in_trade and i <= trade_end: continue
        atr = atrs[i]; trend = trend_arr[i]
        if np.isnan(atr) or atr == 0: continue
        if df.iloc[i]['rvol'] < 80:   continue
        if not hi_vol[i]:             continue
        if trend == '':               continue
        if nearest_sr_distance(closes[i], cluster_prices, atr) > sr_dist_max: continue

        lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
        ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
        fp = (highs[i] > lh.max()) and (highs[i] > rh.max())
        ft = (lows[i]  < ll.min()) and (lows[i]  < rl.min())
        ps = (highs[i] - closes[i]) / atr
        ts = (closes[i] - lows[i])  / atr

        direction = None; slack = 0.0
        if fp and ps >= atr_mult and trend == 'up':
            if int(zz_high_bar[i]) >= 0 and abs(i - int(zz_high_bar[i])) <= PROX:
                direction = 'short'; slack = ps
        elif ft and ts >= atr_mult and trend == 'down':
            if int(zz_low_bar[i]) >= 0 and abs(i - int(zz_low_bar[i])) <= PROX:
                direction = 'long'; slack = ts
        if direction is None: continue

        entry_bar = i + 1
        if entry_bar >= len(df) - MAX_HOLD - 2: continue
        ep   = float(opens[entry_bar])
        tp_p = ep + atr*ATR_TP if direction=='long' else ep - atr*ATR_TP
        sl_p = ep - atr*ATR_SL if direction=='long' else ep + atr*ATR_SL
        et = 'time'; exit_bar = min(entry_bar + MAX_HOLD, len(df)-1)
        for j in range(entry_bar+1, min(entry_bar+MAX_HOLD+1, len(df))):
            h = highs[j]; l = lows[j]
            if direction=='long':
                if h>=tp_p: et='tp'; exit_bar=j; break
                if l<=sl_p: et='sl'; exit_bar=j; break
            else:
                if l<=tp_p: et='tp'; exit_bar=j; break
                if h>=sl_p: et='sl'; exit_bar=j; break

        in_trade = True; trade_end = exit_bar
        pnl_pct = (ATR_TP/ep*atr if et=='tp'
                   else -ATR_SL/ep*atr if et=='sl'
                   else TIME_EXIT_PCT)
        size = B23_CORE if slack >= 1.4 else B23_EXP
        trades.append({'pnl_dollar': pnl_pct * size, 'sym': sym,
                       'tier': 'core' if slack >= 1.4 else 'expanded'})
    return trades

b23_monthly = {}
for mo_label, mo22 in zip(MONTH_LABELS, MONTHS_22):
    trades = []
    for sym in B23_SYMS:
        df = cache22.get((sym, mo22))
        if df is None or len(df) < 100: continue
        t = run_b23_month(sym, df)
        trades.extend(t)
    b23_monthly[mo_label] = trades
    print(f'  B23 {mo_label}: {len(trades)} trades')

# ══════════════════════════════════════════════════════════════════
# STATS HELPER
# ══════════════════════════════════════════════════════════════════
def stats(trades):
    if not trades: return 0, 0.0, 0.0, 0.0, 0.0
    pnls = np.array([t['pnl_dollar'] for t in trades])
    n    = len(pnls)
    pos  = pnls[pnls > 0]; neg = pnls[pnls < 0]
    wr   = len(pos) / n
    ev   = float(np.mean(pnls))
    pf   = float(sum(pos) / max(abs(sum(neg)), 0.01))
    tot  = float(sum(pnls))
    return n, wr, ev, pf, tot

# ══════════════════════════════════════════════════════════════════
# OUTPUT
# ══════════════════════════════════════════════════════════════════
SEP = '=' * 90

print(f'\n{SEP}')
print(f'  BOOF 21 vs 22 vs 23 — 2025 Full Year Comparison')
print(f'  B21: QQQ+SPY  $250/trade | B22: AAPL,NVDA,META,GOOGL,AMD  $200/$600')
print(f'  B23: 9-sym No-ETF list   $200/$500 (capped)')
print(SEP)

# ── Rolling Monthly P&L ───────────────────────────────────────────
print(f'\n  {"Month":<6}  {"Days":>4}  '
      f'{"B21 P&L":>9}  {"B21/day":>8}  {"B21 T":>6}  '
      f'{"B22 P&L":>9}  {"B22/day":>8}  {"B22 T":>6}  '
      f'{"B23 P&L":>9}  {"B23/day":>8}  {"B23 T":>6}  '
      f'{"Combined":>10}')
print(f'  {"-"*88}')

total_b21 = total_b22 = total_b23 = 0
cum_b21 = cum_b22 = cum_b23 = 0
all_b21  = all_b22  = all_b23  = []
all_b21  = []; all_b22 = []; all_b23 = []

for mo, days in zip(MONTH_LABELS, MONTH_DAYS):
    t21 = b21_monthly.get(mo, [])
    t22 = b22_monthly.get(mo, [])
    t23 = b23_monthly.get(mo, [])
    all_b21 += t21; all_b22 += t22; all_b23 += t23

    p21 = sum(t['pnl_dollar'] for t in t21)
    p22 = sum(t['pnl_dollar'] for t in t22)
    p23 = sum(t['pnl_dollar'] for t in t23)
    cum_b21 += p21; cum_b22 += p22; cum_b23 += p23
    combined = p21 + p22 + p23

    print(f'  {mo:<6}  {days:>4}  '
          f'${p21:>8,.0f}  ${p21/days:>7,.1f}  {len(t21):>6}  '
          f'${p22:>8,.0f}  ${p22/days:>7,.1f}  {len(t22):>6}  '
          f'${p23:>8,.0f}  ${p23/days:>7,.1f}  {len(t23):>6}  '
          f'${combined:>9,.0f}')

print(f'  {"-"*88}')
n21,wr21,ev21,pf21,tot21 = stats(all_b21)
n22,wr22,ev22,pf22,tot22 = stats(all_b22)
n23,wr23,ev23,pf23,tot23 = stats(all_b23)
all_combined = all_b21 + all_b22 + all_b23
nc,wrc,evc,pfc,totc = stats(all_combined)

print(f'  {"TOTAL":<6}  {TOTAL_DAYS:>4}  '
      f'${tot21:>8,.0f}  ${tot21/TOTAL_DAYS:>7,.1f}  {n21:>6}  '
      f'${tot22:>8,.0f}  ${tot22/TOTAL_DAYS:>7,.1f}  {n22:>6}  '
      f'${tot23:>8,.0f}  ${tot23/TOTAL_DAYS:>7,.1f}  {n23:>6}  '
      f'${totc:>9,.0f}')

# ── Per-Strategy Summary ──────────────────────────────────────────
print(f'\n{SEP}')
print(f'  STRATEGY SUMMARY')
print(SEP)
print(f'  {"Metric":<22}  {"Boof 21":>12}  {"Boof 22":>12}  {"Boof 23":>12}  {"Combined":>12}')
print(f'  {"-"*72}')
print(f'  {"Trades total":<22}  {n21:>12}  {n22:>12}  {n23:>12}  {nc:>12}')
print(f'  {"Trades/day":<22}  {n21/TOTAL_DAYS:>11.1f}  {n22/TOTAL_DAYS:>11.1f}  {n23/TOTAL_DAYS:>11.1f}  {nc/TOTAL_DAYS:>11.1f}')
print(f'  {"Win rate":<22}  {wr21*100:>11.1f}%  {wr22*100:>11.1f}%  {wr23*100:>11.1f}%  {wrc*100:>11.1f}%')
print(f'  {"Profit factor":<22}  {pf21:>12.2f}  {pf22:>12.2f}  {pf23:>12.2f}  {pfc:>12.2f}')
print(f'  {"EV/trade":<22}  ${ev21:>11.2f}  ${ev22:>11.2f}  ${ev23:>11.2f}  ${evc:>11.2f}')
print(f'  {"Annual P&L":<22}  ${tot21*2:>10,.0f}  ${tot22*2:>10,.0f}  ${tot23*2:>10,.0f}  ${totc*2:>10,.0f}')
print(f'  {"6mo P&L":<22}  ${tot21:>11,.0f}  ${tot22:>11,.0f}  ${tot23:>11,.0f}  ${totc:>11,.0f}')
print(f'  {"Daily avg P&L":<22}  ${tot21/TOTAL_DAYS:>11,.2f}  ${tot22/TOTAL_DAYS:>11,.2f}  ${tot23/TOTAL_DAYS:>11,.2f}  ${totc/TOTAL_DAYS:>11,.2f}')

# ── Cumulative rolling chart (ASCII) ─────────────────────────────
print(f'\n{SEP}')
print(f'  CUMULATIVE P&L ROLLING (monthly)')
print(SEP)
print(f'  {"Month":<6}  {"B21 cum":>10}  {"B22 cum":>10}  {"B23 cum":>10}  {"Combined cum":>14}')
print(f'  {"-"*54}')
c21=c22=c23=cc=0
for mo in MONTH_LABELS:
    c21 += sum(t['pnl_dollar'] for t in b21_monthly.get(mo,[]))
    c22 += sum(t['pnl_dollar'] for t in b22_monthly.get(mo,[]))
    c23 += sum(t['pnl_dollar'] for t in b23_monthly.get(mo,[]))
    cc   = c21+c22+c23
    bar_len = max(0, int(cc / max(abs(totc),1) * 30))
    bar = '#' * bar_len
    print(f'  {mo:<6}  ${c21:>9,.0f}  ${c22:>9,.0f}  ${c23:>9,.0f}  ${cc:>13,.0f}  {bar}')

print(f'\n{SEP}')
print(f'  VERDICT')
print(SEP)
best = max([('B21', tot21), ('B22', tot22), ('B23', tot23)], key=lambda x: x[1])
print(f'  Highest 6mo P&L:   {best[0]} (${best[1]:,.0f})')
print(f'  Most trades/day:   {"B21" if n21>=n22 and n21>=n23 else "B22" if n22>=n23 else "B23"} '
      f'({max(n21,n22,n23)/TOTAL_DAYS:.1f}/day)')
print(f'  Best EV/trade:     {"B21" if ev21>=ev22 and ev21>=ev23 else "B22" if ev22>=ev23 else "B23"} '
      f'(${max(ev21,ev22,ev23):.2f}/trade)')
print(f'  Combined annual:   ${totc*2:,.0f}')
print(SEP)
