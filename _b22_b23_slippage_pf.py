"""
B22 / B23 — Realistic Slippage & Market Impact PF Test
=======================================================
For each trade applies:
  Entry cost  = entry_slip + spread/2 + impact_cost
  Exit cost   = exit_slip  + spread/2 + impact_cost
  Total drag  = entry_cost + exit_cost  (as % of price)

Impact cost model (scalping):
  High-vol ETFs (SPY/QQQ): 0.005% – 0.02%  per side
  Small-liq names:         0.010% – 0.05%   per side

Spread model (1-min bar, typical for liquid names):
  SPY/QQQ:  ~$0.01 spread on ~$500 price  → 0.002%
  AAPL/MSFT/GOOGL/AMZN: ~$0.02 on ~$180   → 0.011%
  NVDA/META/TSLA/AVGO:  ~$0.03 on ~$130   → 0.023%
  AMD/LLY:              ~$0.02 on ~$120    → 0.017%

Entry/exit slippage (1-min scalp, market order):
  Liquid large-cap: 0.005% – 0.010% per side
  Mid-vol:          0.010% – 0.020% per side

Runs 3 scenarios:
  1. Optimistic  — low end of all ranges
  2. Base        — midpoint
  3. Pessimistic — high end
"""
import pickle, sys, numpy as np
sys.path.insert(0, 'c:/Users/tybre/Desktop/aivibe')
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
B22_SYMS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD']
B23_SYMS = ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'AVGO', 'META', 'TSLA', 'LLY']

B22_EXP = 200; B22_CORE = 600
B23_EXP = 200; B23_CORE = 500

MONTHS_22   = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
MONTH_DAYS  = [23,20,21,22,21,21,23,21,22,23,20,23]
TOTAL_DAYS  = sum(MONTH_DAYS)
PROX        = 30

# ── Per-symbol market microstructure params ───────────────────────
# (spread_pct, slip_lo, slip_hi, impact_lo, impact_hi)  all as decimals
MICRO = {
    'SPY':  (0.00002, 0.00005, 0.00010, 0.00005, 0.00020),
    'QQQ':  (0.00002, 0.00005, 0.00010, 0.00005, 0.00020),
    'AAPL': (0.00011, 0.00005, 0.00010, 0.00010, 0.00040),
    'MSFT': (0.00011, 0.00005, 0.00010, 0.00010, 0.00040),
    'GOOGL':(0.00011, 0.00005, 0.00010, 0.00010, 0.00040),
    'AMZN': (0.00011, 0.00005, 0.00010, 0.00010, 0.00040),
    'NVDA': (0.00023, 0.00010, 0.00020, 0.00010, 0.00050),
    'META': (0.00023, 0.00010, 0.00020, 0.00010, 0.00050),
    'TSLA': (0.00023, 0.00010, 0.00020, 0.00010, 0.00050),
    'AVGO': (0.00023, 0.00010, 0.00020, 0.00010, 0.00050),
    'AMD':  (0.00017, 0.00010, 0.00020, 0.00010, 0.00050),
    'LLY':  (0.00017, 0.00010, 0.00020, 0.00010, 0.00050),
}
DEFAULT_MICRO = (0.00020, 0.00010, 0.00020, 0.00010, 0.00050)

def total_drag(sym, scenario):
    """Returns total round-trip drag as price fraction."""
    spread, slip_lo, slip_hi, imp_lo, imp_hi = MICRO.get(sym, DEFAULT_MICRO)
    if scenario == 'optimistic':
        slip = slip_lo; imp = imp_lo
    elif scenario == 'pessimistic':
        slip = slip_hi; imp = imp_hi
    else:  # base
        slip = (slip_lo + slip_hi) / 2
        imp  = (imp_lo  + imp_hi)  / 2
    # entry: slip + spread/2 + impact
    # exit:  slip + spread/2 + impact
    return 2 * (slip + spread / 2 + imp)

# ── Engines ───────────────────────────────────────────────────────
def run_b22_trades(sym, df):
    trades = []
    params   = B22_SP.get(sym, B22_DP)
    vol_mult = params['vol_mult']; atr_mult = params['atr_mult']; sr_dist = params['sr_dist']
    F = B22_FB
    df = df.copy().reset_index(drop=True)
    atr_s = b22_atr(df)
    df['atr']    = atr_s
    df['vol_sma']= df['volume'].rolling(B22_VOL_LEN).mean()
    df['rvol']   = (df['volume'] / df['vol_sma'] * 100).fillna(0)
    df['hi_vol'] = df['volume'] > df['vol_sma'] * vol_mult
    cluster_prices, _ = b22_bca(df, atr_s, vol_mult)
    opens = df['open'].values; highs = df['high'].values
    lows  = df['low'].values;  closes= df['close'].values
    atrs  = df['atr'].values;  hi_vol= df['hi_vol'].values
    in_trade = False; trade_end = 0
    warmup = B22_VOL_LEN + B22_ATR_LEN + F
    for i in range(warmup, len(df) - F - MAX_HOLD - 3):
        if in_trade and i <= trade_end: continue
        atr = atrs[i]
        if np.isnan(atr) or atr == 0: continue
        if df.iloc[i]['rvol'] < 80: continue
        if not hi_vol[i]: continue
        if b22_nsd(closes[i], cluster_prices, atr) > sr_dist: continue
        lh = highs[i-F:i]; rh = highs[i+1:i+F+1]
        ll = lows[i-F:i];  rl = lows[i+1:i+F+1]
        fp = (highs[i] > lh.max()) and (highs[i] > rh.max())
        ft = (lows[i]  < ll.min()) and (lows[i]  < rl.min())
        ps = (highs[i] - closes[i]) / atr
        ts = (closes[i] - lows[i])  / atr
        direction = None; slack = 0.0
        if fp and ps >= atr_mult:   direction = 'short'; slack = ps
        elif ft and ts >= atr_mult: direction = 'long';  slack = ts
        if direction is None: continue
        entry_bar = i + 1
        if entry_bar >= len(df) - MAX_HOLD - 2: continue
        ep = float(opens[entry_bar])
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
        raw_pnl_pct = (ATR_TP/ep*atr if et=='tp'
                       else -ATR_SL/ep*atr if et=='sl'
                       else TIME_EXIT_PCT)
        size = B22_CORE if slack >= 1.4 else B22_EXP
        trades.append({'raw_pnl_pct': raw_pnl_pct, 'size': size, 'sym': sym,
                       'tier': 'core' if slack >= 1.4 else 'expanded', 'ep': ep})
    return trades

def run_b23_trades(sym, df):
    trades = []
    params      = SYMBOL_PARAMS.get(sym, DEFAULT_PARAMS)
    vol_mult    = params['vol_mult']; atr_mult = params['atr_mult']; sr_dist_max = params['sr_dist']
    F = FRACTAL_BARS
    df = df.copy().reset_index(drop=True)
    atr_s = compute_atr(df)
    df['atr']    = atr_s
    df['vol_sma']= df['volume'].rolling(VOL_LEN).mean()
    df['rvol']   = (df['volume'] / df['vol_sma'] * 100).fillna(0)
    df['hi_vol'] = df['volume'] > df['vol_sma'] * vol_mult
    cluster_prices, _ = build_cluster_array(df, atr_s, vol_mult)
    opens = df['open'].values; highs = df['high'].values
    lows  = df['low'].values;  closes= df['close'].values
    atrs  = df['atr'].values;  hi_vol= df['hi_vol'].values
    trend_arr, _, zz_high_bar, _, zz_low_bar = _build_zigzag(highs, lows, opens, closes)
    in_trade = False; trade_end = 0
    warmup = VOL_LEN + ATR_LEN + F
    for i in range(warmup, len(df) - F - MAX_HOLD - 3):
        if in_trade and i <= trade_end: continue
        atr = atrs[i]; trend = trend_arr[i]
        if np.isnan(atr) or atr == 0: continue
        if df.iloc[i]['rvol'] < 80: continue
        if not hi_vol[i]: continue
        if trend == '': continue
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
        ep = float(opens[entry_bar])
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
        raw_pnl_pct = (ATR_TP/ep*atr if et=='tp'
                       else -ATR_SL/ep*atr if et=='sl'
                       else TIME_EXIT_PCT)
        size = B23_CORE if slack >= 1.4 else B23_EXP
        trades.append({'raw_pnl_pct': raw_pnl_pct, 'size': size, 'sym': sym,
                       'tier': 'core' if slack >= 1.4 else 'expanded', 'ep': ep})
    return trades

# ── Load cache ────────────────────────────────────────────────────
print('Loading cache...')
cache22 = pickle.load(open('_boof22_cache.pkl', 'rb'))
print('  Done.\n')

# ── Collect raw trades ────────────────────────────────────────────
print('Running B22...')
b22_raw = []
for mo in MONTHS_22:
    for sym in B22_SYMS:
        df = cache22.get((sym, mo))
        if df is None or len(df) < 100: continue
        b22_raw.extend(run_b22_trades(sym, df))
print(f'  {len(b22_raw)} trades total')

print('Running B23...')
b23_raw = []
for mo in MONTHS_22:
    for sym in B23_SYMS:
        df = cache22.get((sym, mo))
        if df is None or len(df) < 100: continue
        b23_raw.extend(run_b23_trades(sym, df))
print(f'  {len(b23_raw)} trades total\n')

# ── Apply slippage and compute stats ─────────────────────────────
def apply_slip(trades, scenario):
    pnls = []
    for t in trades:
        drag = total_drag(t['sym'], scenario)
        net_pct = t['raw_pnl_pct'] - drag
        pnls.append(net_pct * t['size'])
    return np.array(pnls)

def pf_wr_ev(pnls):
    if len(pnls) == 0: return 0, 0, 0
    pos = pnls[pnls > 0]; neg = pnls[pnls < 0]
    pf  = float(sum(pos) / max(abs(sum(neg)), 0.01))
    wr  = len(pos) / len(pnls)
    ev  = float(np.mean(pnls))
    return round(pf, 2), round(wr*100, 1), round(ev, 2)

SEP = '=' * 72
print(SEP)
print('  B22 vs B23 — Realistic Slippage Impact on PF, WR, EV')
print(SEP)

scenarios = ['raw (no slip)', 'optimistic', 'base', 'pessimistic']

print(f'\n  {"Scenario":<20}  {"B22 PF":>7}  {"B22 WR":>7}  {"B22 EV":>8}  {"B22 Ann":>10}  '
      f'{"B23 PF":>7}  {"B23 WR":>7}  {"B23 EV":>8}  {"B23 Ann":>10}')
print(f'  {"-"*70}')

for sc in scenarios:
    if sc == 'raw (no slip)':
        p22 = np.array([t['raw_pnl_pct'] * t['size'] for t in b22_raw])
        p23 = np.array([t['raw_pnl_pct'] * t['size'] for t in b23_raw])
    else:
        p22 = apply_slip(b22_raw, sc)
        p23 = apply_slip(b23_raw, sc)
    pf22, wr22, ev22 = pf_wr_ev(p22)
    pf23, wr23, ev23 = pf_wr_ev(p23)
    ann22 = sum(p22) * 2
    ann23 = sum(p23) * 2
    print(f'  {sc:<20}  {pf22:>7.2f}  {wr22:>6.1f}%  ${ev22:>7.2f}  ${ann22:>9,.0f}  '
          f'{pf23:>7.2f}  {wr23:>6.1f}%  ${ev23:>7.2f}  ${ann23:>9,.0f}')

# ── Drag breakdown per scenario ───────────────────────────────────
print(f'\n{SEP}')
print('  DRAG BREAKDOWN — round-trip cost per trade (both sides)')
print(SEP)
print(f'\n  {"Symbol":<8}  {"Spread":>8}  {"Slip (base)":>12}  {"Impact (base)":>14}  {"Total drag (base)":>18}  {"Total drag (pess)":>18}')
print(f'  {"-"*68}')
for sym in sorted(set(B22_SYMS + B23_SYMS)):
    sp, sl_lo, sl_hi, im_lo, im_hi = MICRO.get(sym, DEFAULT_MICRO)
    slip_b = (sl_lo+sl_hi)/2; imp_b = (im_lo+im_hi)/2
    slip_p = sl_hi;            imp_p = im_hi
    drag_b = 2*(slip_b + sp/2 + imp_b)
    drag_p = 2*(slip_p + sp/2 + imp_p)
    print(f'  {sym:<8}  {sp*100:>7.4f}%  {slip_b*100:>11.4f}%  {imp_b*100:>13.4f}%  '
          f'{drag_b*100:>17.4f}%  {drag_p*100:>17.4f}%')

# ── EV erosion table ─────────────────────────────────────────────
print(f'\n{SEP}')
print('  EV EROSION — how much each scenario eats into EV/trade')
print(SEP)
raw22 = np.array([t['raw_pnl_pct'] * t['size'] for t in b22_raw])
raw23 = np.array([t['raw_pnl_pct'] * t['size'] for t in b23_raw])
_, _, ev22_raw = pf_wr_ev(raw22)
_, _, ev23_raw = pf_wr_ev(raw23)

print(f'\n  {"Scenario":<20}  {"B22 EV":>8}  {"B22 erosion":>12}  {"B23 EV":>8}  {"B23 erosion":>12}')
print(f'  {"-"*60}')
for sc in ['optimistic', 'base', 'pessimistic']:
    p22 = apply_slip(b22_raw, sc); p23 = apply_slip(b23_raw, sc)
    _, _, ev22 = pf_wr_ev(p22);    _, _, ev23 = pf_wr_ev(p23)
    e22 = ev22_raw - ev22;          e23 = ev23_raw - ev23
    print(f'  {sc:<20}  ${ev22:>7.2f}  -${e22:>10.2f}  ${ev23:>7.2f}  -${e23:>10.2f}')

print(f'\n{SEP}')
print('  VERDICT')
print(SEP)
p22_base = apply_slip(b22_raw, 'base')
p23_base = apply_slip(b23_raw, 'base')
pf22b, wr22b, ev22b = pf_wr_ev(p22_base)
pf23b, wr23b, ev23b = pf_wr_ev(p23_base)
print(f'  B22 base-case: PF={pf22b}  WR={wr22b}%  EV=${ev22b}/trade  Annual=${sum(p22_base)*2:,.0f}')
print(f'  B23 base-case: PF={pf23b}  WR={wr23b}%  EV=${ev23b}/trade  Annual=${sum(p23_base)*2:,.0f}')
print(f'\n  Raw PF (25x) is structurally inflated by 2:1 ATR R:R construction.')
print(f'  Base-case realistic PF for B22: {pf22b}x  |  B23: {pf23b}x')
print(SEP)
