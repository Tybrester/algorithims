"""
BOOF60 v2 — Combined Backtest
LONG  : BOOF55 signal  — gap-up >1% + PDH break + 1-bar confirm → call
SHORT : BOOF51 signal  — gap-up >0.5% + pivot level touch + bounce ≥0.15% → put
TP=10%, SL=-35%, Max hold=60 bars (5m), Budget=$750
6 months, 5m cached bars
"""
import pandas as pd
import numpy as np
import pytz
import os

ET     = pytz.timezone('America/New_York')
CACHE  = "boof_data"
SUFFIX = "_5m_6mo.parquet"

# ── Universe ─────────────────────────────────────────────────────
LONG_SYMS = [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX'
]

# BOOF51 routing: (type, lookback, wing)
ROUTING = {
    "UPST":  ("PMH", None, None), "APP":   ("PMH", None, None),
    "SMCI":  ("PMH", None, None), "HIMS":  ("PMH", None, None),
    "GOOGL": ("PMH", None, None), "META":  ("PDH", None, None),
    "AFRM":  ("PDH", None, None), "TSLA":  ("PIV", 10,  2),
    "CLSK":  ("PIV", 10,  2),     "HOOD":  ("PIV", 10,  2),
    "ADBE":  ("PIV", 30,  3),     "PANW":  ("PIV", 30,  3),
    "MU":    ("PIV", 30,  3),     "AMD":   ("PIV", 30,  3),
    "COIN":  ("PIV", 30,  3),     "NVDA":  ("PIV", 30,  3),
    "MRVL":  ("PIV", 120, 4),     "AVGO":  ("PIV", 120, 4),
    "PLTR":  ("PIV", 240, 5),     "CRM":   ("PIV", 390, 5),
}
SHORT_SYMS = list(ROUTING.keys())
ALL_SYMS   = list(set(LONG_SYMS + SHORT_SYMS))

# ── Params ────────────────────────────────────────────────────────
GAP_LONG   = 1.0    # % gap-up for long signal
GAP_SHORT  = 0.5    # % gap-up for short signal
PDH_BREAK  = 0.0    # long: price must exceed PDH
NEAR_PCT   = 0.0015 # short: within 0.15% = touching level
BOUNCE     = 0.0015 # short: bounce ≥ 0.15% off level
OVERLAP    = 0.002  # pivot clustering overlap
TP_PCT     = 10.0
SL_PCT     = 35.0
MAX_BARS   = 60
BUDGET     = 750.0
MAX_POS    = 5
OPTION_MULT = 2.0

# ── Load cache ────────────────────────────────────────────────────
def load_sym(sym):
    path = os.path.join(CACHE, f"{sym}{SUFFIX}")
    if not os.path.exists(path): return pd.DataFrame()
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if df.index.tz is None: df.index = df.index.tz_localize('UTC')
    df.index = df.index.tz_convert(ET)
    return df

print("Loading cache...")
data = {sym: load_sym(sym) for sym in ALL_SYMS + ['SPY']}

print("Building daily OHLC...")
daily = {}
for sym in ALL_SYMS + ['SPY']:
    df = data[sym]
    if df.empty: daily[sym] = pd.DataFrame(); continue
    rth = df.between_time('09:30','16:00')
    d   = rth.resample('1D').agg(open=('open','first'),high=('high','max'),
                                  low=('low','min'),close=('close','last')).dropna()
    daily[sym] = d

all_dates = sorted(daily['SPY'].index.date)[1:]
print(f"Simulating {len(all_dates)} days ({all_dates[0]} → {all_dates[-1]})\n")

# ── BOOF51 pivot builder ──────────────────────────────────────────
def build_pivots(bars, lookback, wing):
    hist = bars[-lookback:] if len(bars) >= lookback else bars
    if len(hist) < wing + 1: return []
    H   = [b['h'] for b in hist]
    raw = [H[i] for i in range(wing, len(hist)) if H[i] == max(H[max(0,i-wing):i+1])]
    if not raw: return []
    raw = sorted(raw)
    cl  = [raw[0]]
    for lv in raw[1:]:
        if abs(lv - cl[-1]) / cl[-1] < OVERLAP: cl[-1] = (cl[-1]+lv)/2
        else: cl.append(lv)
    return cl

def update_level_sm(sm, level, bar):
    high = bar['h']; close = bar['c']
    if close < level: sm['was_below'] = True
    touching = sm['was_below'] and high >= level * (1 - NEAR_PCT)
    if sm['state'] == 'IDLE':
        if touching:
            sm['state'] = 'IN'; sm['extreme'] = close; sm['touch_num'] += 1
    elif sm['state'] == 'IN':
        if high >= level * (1 - NEAR_PCT):
            sm['extreme'] = min(sm['extreme'], close)
        else:
            bounced = sm['extreme'] is not None and (level - sm['extreme']) / level >= BOUNCE
            req     = 2 if sm['broken'] else 1
            if bounced and sm['touch_num'] == req:
                sm['state'] = 'FIRED'; return True
            sm['state'] = 'DEAD'; sm['broken'] = True; sm['was_below'] = False
    elif sm['state'] == 'DEAD':
        if sm['was_below']: sm['state'] = 'IDLE'; sm['extreme'] = None; sm['touch_num'] = 0
    return False

def init_sm(): return {'state':'IDLE','extreme':None,'touch_num':0,'was_below':False,'broken':False}

# ── Backtest ──────────────────────────────────────────────────────
trades = []

for day in all_dates:
    spy_prices = []
    regime     = "neutral"
    active_pos = {}  # sym -> trade dict

    spy_df  = data['SPY']
    spy_rth = spy_df[spy_df.index.date == day].between_time('09:30','15:55') if not spy_df.empty else pd.DataFrame()

    # ── Per-symbol state for this day ──
    sym_state = {}
    for sym in ALL_SYMS:
        dh   = daily.get(sym, pd.DataFrame())
        prev = dh[dh.index.date < day]
        if len(prev) < 1: continue

        prev_close = float(prev['close'].iloc[-1])
        pdh        = float(prev['high'].iloc[-1])
        pdl        = float(prev['low'].iloc[-1])

        bars_5m = data.get(sym, pd.DataFrame())
        if bars_5m.empty: continue
        rth = bars_5m[bars_5m.index.date == day].between_time('09:30','15:55')
        if len(rth) < 2: continue

        day_open  = float(rth['open'].iloc[0])
        gap_pct   = (day_open - prev_close) / prev_close * 100
        gap_long  = gap_pct > GAP_LONG
        gap_short = gap_pct > GAP_SHORT

        # Build pivot levels for short signal (BOOF51 routing)
        levels    = []
        lvl_sms   = {}
        rtype, lb, wing = ROUTING.get(sym, (None, None, None))
        if rtype and gap_short:
            prev_bars_df = bars_5m[bars_5m.index.date < day].between_time('09:30','16:00').tail(500)
            prev_bars    = [{'h': float(r['high']), 'l': float(r['low']), 'c': float(r['close'])}
                            for _, r in prev_bars_df.iterrows()]
            if rtype == 'PMH':
                pm_bars = bars_5m[bars_5m.index.date == day].between_time('04:00','09:29')
                if not pm_bars.empty:
                    levels = [float(pm_bars['high'].max())]
            elif rtype == 'PDH':
                levels = [pdh]
            elif rtype == 'PIV' and lb and wing:
                levels = build_pivots(prev_bars, lb, wing)

            for lv in levels:
                lvl_sms[round(lv,4)] = init_sm()

        sym_state[sym] = {
            'rth': rth, 'prev_close': prev_close, 'pdh': pdh,
            'gap_pct': gap_pct, 'gap_long': gap_long, 'gap_short': gap_short,
            'levels': levels, 'lvl_sms': lvl_sms,
            'confirm_long': False, 'pdh_broken': False, 'short_fired': False,
            'in_trade': None, 'bar_path': [],
        }

    # ── Bar-by-bar simulation ──
    # Get max bars across all syms for this day
    max_len = max((len(ss['rth']) for ss in sym_state.values()), default=0)

    for i in range(max_len):
        # Update SPY regime
        if i < len(spy_rth):
            spy_prices.append(float(spy_rth.iloc[min(i, len(spy_rth)-1)]['close']))
            if len(spy_prices) > 5: spy_prices.pop(0)
            if len(spy_prices) >= 3:
                if   spy_prices[-1] > spy_prices[0] * 1.001:  regime = "bull"
                elif spy_prices[-1] < spy_prices[0] * 0.999:  regime = "bear"
                else:                                           regime = "neutral"

        for sym, ss in sym_state.items():
            rth = ss['rth']
            if i >= len(rth): continue
            ts    = rth.index[i]
            bar   = rth.iloc[i]
            hm    = ts.strftime('%H:%M')
            price = float(bar['close'])
            o_px  = float(bar['open'])
            high  = float(bar['high'])
            low   = float(bar['low'])
            bdict = {'h': high, 'l': low, 'c': price, 'o': o_px}

            # ── Manage open trade ──
            if ss['in_trade']:
                t         = ss['in_trade']
                entry_px  = t['entry_price']
                direction = t['direction']
                if direction == 'long':
                    stk_pct = (price - entry_px) / entry_px * 100
                    mfe_stk = (high  - entry_px) / entry_px * 100
                    mae_stk = (low   - entry_px) / entry_px * 100
                else:
                    stk_pct = (entry_px - price) / entry_px * 100
                    mfe_stk = (entry_px - low)   / entry_px * 100
                    mae_stk = (entry_px - high)  / entry_px * 100

                opt_pct = stk_pct * OPTION_MULT
                mfe_opt = mfe_stk * OPTION_MULT
                mae_opt = mae_stk * OPTION_MULT
                t['bars_held'] += 1
                t['mfe'] = max(t['mfe'], mfe_opt)
                t['mae'] = min(t['mae'], mae_opt)
                ss['bar_path'].append({'opt_pct': opt_pct, 'mfe_opt': mfe_opt, 'mae_opt': mae_opt})

                exit_reason = None
                final_pct   = opt_pct
                if t['mfe'] >= TP_PCT:
                    exit_reason = 'TP'; final_pct = TP_PCT
                elif t['mae'] <= -SL_PCT:
                    exit_reason = 'SL'; final_pct = -SL_PCT
                elif t['bars_held'] >= MAX_BARS or hm >= '15:50':
                    exit_reason = 'EOD' if hm >= '15:50' else 'TIMEOUT'

                if exit_reason:
                    pnl = BUDGET * final_pct / 100
                    trades.append({
                        'date': day, 'sym': sym, 'direction': direction,
                        'entry_time': t['entry_time'], 'exit_time': hm,
                        'bars_held': t['bars_held'], 'opt_pct': round(final_pct,2),
                        'pnl': round(pnl,2), 'mfe': round(t['mfe'],2),
                        'mae': round(t['mae'],2), 'exit': exit_reason,
                        'regime': t['regime'], 'gap_pct': round(ss['gap_pct'],2),
                        'signal': t['signal'],
                    })
                    ss['in_trade'] = None; ss['bar_path'] = []
                    if sym in active_pos: del active_pos[sym]
                continue

            if hm >= '15:30': continue
            if len(active_pos) >= MAX_POS: continue
            if ss['in_trade']: continue

            pdh = ss['pdh']

            # ── LONG signal (BOOF55) ──
            if ss['gap_long'] and price > pdh and not ss['pdh_broken']:
                if not ss['confirm_long']:
                    ss['confirm_long'] = True
                    continue
                if regime in ('bull','neutral'):
                    ss['pdh_broken'] = True
                    ss['in_trade'] = {
                        'direction':'long','entry_price':price,'entry_time':hm,
                        'bars_held':0,'mfe':0.0,'mae':0.0,'regime':regime,'signal':'BOOF55'
                    }
                    active_pos[sym] = True

            # ── SHORT signal (BOOF51) ──
            if ss['gap_short'] and not ss['short_fired'] and not ss['pdh_broken']:
                for lv, sm in ss['lvl_sms'].items():
                    if sm['state'] == 'FIRED': continue
                    if update_level_sm(sm, lv, bdict):
                        if regime in ('bear','neutral'):
                            ss['short_fired'] = True
                            ss['in_trade'] = {
                                'direction':'short','entry_price':price,'entry_time':hm,
                                'bars_held':0,'mfe':0.0,'mae':0.0,'regime':regime,
                                'signal':'BOOF51'
                            }
                            active_pos[sym] = True
                            break

        # EOD cleanup
    for sym, ss in sym_state.items():
        if ss['in_trade']:
            t   = ss['in_trade']
            rth = ss['rth']
            if rth.empty: continue
            exit_px   = float(rth['close'].iloc[-1])
            entry_px  = t['entry_price']
            direction = t['direction']
            stk_pct   = (exit_px - entry_px)/entry_px*100 if direction == 'long' else (entry_px - exit_px)/entry_px*100
            opt_pct   = stk_pct * OPTION_MULT
            pnl       = BUDGET * opt_pct / 100
            trades.append({
                'date': day, 'sym': sym, 'direction': direction,
                'entry_time': t['entry_time'], 'exit_time': '15:55',
                'bars_held': t['bars_held'], 'opt_pct': round(opt_pct,2),
                'pnl': round(pnl,2), 'mfe': round(t['mfe'],2), 'mae': round(t['mae'],2),
                'exit': 'EOD', 'regime': t['regime'],
                'gap_pct': round(ss['gap_pct'],2), 'signal': t['signal'],
            })

# ── Results ───────────────────────────────────────────────────────
df = pd.DataFrame(trades)
if df.empty:
    print("No trades fired.")
else:
    wins   = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    wr     = len(wins)/len(df)
    avg_w  = wins['pnl'].mean()   if len(wins)   else 0
    avg_l  = losses['pnl'].mean() if len(losses) else 0
    pf     = wins['pnl'].sum()/abs(losses['pnl'].sum()) if losses['pnl'].sum() != 0 else 999
    ev     = df['pnl'].mean()

    print(f"\n{'='*60}")
    print(f"BOOF60 v2 (BOOF55 longs + BOOF51 shorts)")
    print(f"{len(all_dates)} days  |  {len(df)} trades  |  TP={TP_PCT}%  SL=-{SL_PCT}%")
    print(f"{'='*60}")
    print(f"\n── CORE METRICS ──────────────────────────────────────────")
    print(f"  Win Rate:       {wr*100:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  Profit Factor:  {pf:.2f}x")
    print(f"  EV per trade:   ${ev:.2f}")
    print(f"  Avg Win:        ${avg_w:.2f}")
    print(f"  Avg Loss:       ${avg_l:.2f}")
    print(f"  Win/Loss ratio: {abs(avg_w/avg_l):.2f}x")
    print(f"  Total P&L:      ${df['pnl'].sum():.2f}")
    print(f"  Avg trades/day: {len(df)/len(all_dates):.1f}")
    print(f"  Avg P&L/day:    ${df['pnl'].sum()/len(all_dates):.2f}")
    print(f"  Annualized EV:  ${ev * len(df)/len(all_dates) * 252:.0f}/yr")

    print(f"\n── MFE / MAE ─────────────────────────────────────────────")
    print(f"  Avg MFE:        {df['mfe'].mean():.1f}%")
    print(f"  Avg MAE:        {df['mae'].mean():.1f}%")
    print(f"  MFE on winners: {wins['mfe'].mean():.1f}%")
    print(f"  MAE on winners: {wins['mae'].mean():.1f}%")
    print(f"  MFE on losers:  {losses['mfe'].mean():.1f}%")
    print(f"  MAE on losers:  {losses['mae'].mean():.1f}%")
    print(f"  TP hits:        {len(df[df['exit']=='TP'])}  ({len(df[df['exit']=='TP'])/len(df)*100:.0f}%)")
    print(f"  SL hits:        {len(df[df['exit']=='SL'])}  ({len(df[df['exit']=='SL'])/len(df)*100:.0f}%)")

    print(f"\n── TIMING ────────────────────────────────────────────────")
    print(f"  Avg hold:       {df['bars_held'].mean():.1f} bars ({df['bars_held'].mean()*5:.0f} min)")
    print(f"  Median hold:    {df['bars_held'].median():.0f} bars")
    print(f"\n  Exit breakdown:")
    print(df.groupby('exit')['pnl'].agg(['count','sum','mean']).round(2)
            .rename(columns={'count':'n','sum':'total$','mean':'avg$'}).to_string())

    print(f"\n── BY SIGNAL ─────────────────────────────────────────────")
    print(df.groupby('signal').agg(
        n=('pnl','count'), wr=('pnl', lambda x: f"{(x>0).mean()*100:.0f}%"),
        total=('pnl','sum'), avg=('pnl','mean'),
        mfe=('mfe','mean'), mae=('mae','mean')
    ).round(2).to_string())

    print(f"\n── BY DIRECTION ──────────────────────────────────────────")
    print(df.groupby('direction').agg(
        n=('pnl','count'), wr=('pnl', lambda x: f"{(x>0).mean()*100:.0f}%"),
        total=('pnl','sum'), avg=('pnl','mean'),
    ).round(2).to_string())

    print(f"\n── BY REGIME ─────────────────────────────────────────────")
    print(df.groupby('regime').agg(
        n=('pnl','count'), wr=('pnl', lambda x: f"{(x>0).mean()*100:.0f}%"),
        total=('pnl','sum'), avg=('pnl','mean')
    ).round(2).to_string())

    print(f"\n── TOP 5 WINS ────────────────────────────────────────────")
    print(df.nlargest(5,'pnl')[['date','sym','signal','direction','entry_time','bars_held','opt_pct','pnl','exit']].to_string(index=False))

    print(f"\n── TOP 5 LOSSES ──────────────────────────────────────────")
    print(df.nsmallest(5,'pnl')[['date','sym','signal','direction','entry_time','bars_held','opt_pct','pnl','exit']].to_string(index=False))

    print(f"\n── MONTHLY BREAKDOWN ─────────────────────────────────────")
    df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
    print(df.groupby('month').agg(
        trades=('pnl','count'), pnl=('pnl','sum'),
        wr=('pnl', lambda x: f"{(x>0).mean()*100:.0f}%"), avg=('pnl','mean')
    ).round(2).to_string())

    df.to_csv('boof60_v2_trades.csv', index=False)
    print(f"\nTrade log → boof60_v2_trades.csv")
