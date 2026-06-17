"""
BOOF60 Full Stats Backtest — 6 months, 1-min bars via Alpaca
Metrics: Win Rate, Profit Factor, EV, MFE, MAE, Avg Hold, TP/SL hit rates
"""
import requests
import pandas as pd
import numpy as np
import pytz
import os
from datetime import date, datetime, timedelta
import time as time_mod

ET      = pytz.timezone('America/New_York')
UTC     = pytz.utc
CACHE   = "boof_data"
SUFFIX  = "_5m_6mo.parquet"

SYMBOLS = [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX'
]

GAP_UP_MIN   = 1.0
PDH_NEAR_PCT = 0.8
REJECT_PCT   = 0.50
MAX_POS      = 5
TP_PCT       = 35.0
SL_PCT       = 30.0
MAX_BARS     = 60
BUDGET       = 750.0
OPTION_MULT  = 2.0   # ~delta 0.5 * 2x gamma on 1DTE ATM = ~2x stock move → opt move

def load_sym(sym):
    path = os.path.join(CACHE, f"{sym}{SUFFIX}")
    if not os.path.exists(path):
        print(f"  WARNING: no cache for {sym}")
        return pd.DataFrame()
    df = pd.read_parquet(path)
    # Normalize columns to lowercase
    df.columns = [c.lower() for c in df.columns]
    # Ensure UTC-aware index then convert to ET
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    df.index = df.index.tz_convert(ET)
    return df

print(f"Loading 5m parquet cache for {len(SYMBOLS)+1} symbols...")
data = {}
for sym in SYMBOLS + ['SPY']:
    df = load_sym(sym)
    data[sym] = df
    print(f"  {sym}: {len(df)} bars")

# ── Build daily OHLC from 5m bars (RTH only) ──────────────────────
print("\nBuilding daily OHLC...")
daily = {}
for sym in SYMBOLS + ['SPY']:
    df = data[sym]
    if df.empty:
        daily[sym] = pd.DataFrame()
        continue
    rth = df.between_time('09:30', '16:00')
    d = rth.resample('1D').agg(
        open=('open','first'), high=('high','max'),
        low=('low','min'),   close=('close','last')
    ).dropna()
    daily[sym] = d

# ── Get all trading days ──────────────────────────────────────────
spy_daily = daily['SPY']
all_dates = sorted(spy_daily.index.date)[1:]
print(f"\nSimulating {len(all_dates)} trading days ({all_dates[0]} → {all_dates[-1]})\n")

# ── Backtest loop ─────────────────────────────────────────────────
trades = []

for day in all_dates:
    pdh_broken  = set()
    pdh_touched = set()
    spy_prices  = []
    regime      = "neutral"
    active_pos  = {}  # sym -> trade dict

    # SPY regime bars for this day
    spy_1m = data.get('SPY', pd.DataFrame())
    spy_rth = spy_1m[spy_1m.index.date == day].between_time('09:30','15:55') if not spy_1m.empty else pd.DataFrame()

    for sym in SYMBOLS:
        dh = daily.get(sym, pd.DataFrame())
        if dh.empty:
            continue
        prev = dh[dh.index.date < day]
        if len(prev) < 1:
            continue
        prev_close = float(prev['close'].iloc[-1])
        pdh        = float(prev['high'].iloc[-1])

        bars_1m = data.get(sym, pd.DataFrame())
        if bars_1m.empty:
            continue
        rth = bars_1m[bars_1m.index.date == day].between_time('09:30','15:55')
        if len(rth) < 2:
            continue

        day_open = float(rth['open'].iloc[0])
        gap_pct  = (day_open - prev_close) / prev_close * 100
        gap_ok   = gap_pct > GAP_UP_MIN
        confirm  = False
        in_trade = None

        for i, (ts, bar) in enumerate(rth.iterrows()):
            hm    = ts.strftime('%H:%M')
            price = float(bar['close'])
            o_px  = float(bar['open'])
            high  = float(bar['high'])
            low   = float(bar['low'])

            # Update SPY regime from matching bar
            if i < len(spy_rth):
                spy_prices.append(float(spy_rth.iloc[min(i, len(spy_rth)-1)]['close']))
                if len(spy_prices) > 5: spy_prices.pop(0)
                if len(spy_prices) >= 3:
                    if   spy_prices[-1] > spy_prices[0] * 1.001:  regime = "bull"
                    elif spy_prices[-1] < spy_prices[0] * 0.999:  regime = "bear"
                    else:                                           regime = "neutral"

            # ── Manage open trade bar-by-bar ──
            if in_trade:
                entry_px  = in_trade['entry_price']
                direction = in_trade['direction']

                if direction == 'long':
                    stock_pct = (price - entry_px) / entry_px * 100
                    mfe_bar   = (high  - entry_px) / entry_px * 100
                    mae_bar   = (low   - entry_px) / entry_px * 100
                else:
                    stock_pct = (entry_px - price) / entry_px * 100
                    mfe_bar   = (entry_px - low)   / entry_px * 100
                    mae_bar   = (entry_px - high)  / entry_px * 100

                opt_pct = stock_pct * OPTION_MULT
                mfe_opt = mfe_bar   * OPTION_MULT
                mae_opt = mae_bar   * OPTION_MULT

                in_trade['bars_held'] += 1
                in_trade['mfe'] = max(in_trade['mfe'], mfe_opt)
                in_trade['mae'] = min(in_trade['mae'], mae_opt)

                exit_reason = None
                if opt_pct >= TP_PCT:
                    exit_reason = 'TP';  opt_pct = TP_PCT
                elif opt_pct <= -SL_PCT:
                    exit_reason = 'SL';  opt_pct = -SL_PCT
                elif in_trade['bars_held'] >= MAX_BARS:
                    exit_reason = 'TIMEOUT'
                elif hm >= '15:50':
                    exit_reason = 'EOD'

                if exit_reason:
                    pnl = BUDGET * opt_pct / 100
                    trades.append({
                        'date':      day,       'sym':       sym,
                        'direction': direction, 'entry_time':in_trade['entry_time'],
                        'exit_time': hm,        'bars_held': in_trade['bars_held'],
                        'opt_pct':   round(opt_pct,2),
                        'pnl':       round(pnl,2),
                        'mfe':       round(in_trade['mfe'],2),
                        'mae':       round(in_trade['mae'],2),
                        'exit':      exit_reason,
                        'regime':    in_trade['regime'],
                        'gap_pct':   round(gap_pct,2),
                    })
                    if sym in active_pos: del active_pos[sym]
                    in_trade = None
                continue

            if hm >= '15:30':
                break
            if len(active_pos) >= MAX_POS:
                continue

            # ── LONG signal: gap-up + PDH break + 1 bar confirm ──
            if gap_ok and price > pdh and sym not in pdh_broken:
                if not confirm:
                    confirm = True
                    continue
                if regime in ('bull', 'neutral'):
                    pdh_broken.add(sym)
                    in_trade = {
                        'sym': sym, 'direction': 'long', 'entry_price': price,
                        'entry_time': hm, 'bars_held': 0,
                        'mfe': 0.0, 'mae': 0.0, 'regime': regime,
                    }
                    active_pos[sym] = in_trade

            # ── SHORT signal: PDH touch + bar rejection, no gap conflict ──
            near_pdh = abs(price - pdh) / pdh < (PDH_NEAR_PCT / 100)
            reject   = o_px > 0 and price < o_px * (1 - REJECT_PCT / 100)
            if near_pdh and reject and sym not in pdh_touched and sym not in pdh_broken and not gap_ok:
                if regime in ('bear', 'neutral'):
                    pdh_touched.add(sym)
                    in_trade = {
                        'sym': sym, 'direction': 'short', 'entry_price': price,
                        'entry_time': hm, 'bars_held': 0,
                        'mfe': 0.0, 'mae': 0.0, 'regime': regime,
                    }
                    active_pos[sym] = in_trade

        # EOD force close
        if in_trade:
            exit_px   = float(rth['close'].iloc[-1])
            entry_px  = in_trade['entry_price']
            direction = in_trade['direction']
            stock_pct = (exit_px - entry_px) / entry_px * 100 if direction == 'long' else (entry_px - exit_px) / entry_px * 100
            opt_pct   = stock_pct * OPTION_MULT
            pnl       = BUDGET * opt_pct / 100
            trades.append({
                'date': day, 'sym': sym, 'direction': direction,
                'entry_time': in_trade['entry_time'], 'exit_time': '15:55',
                'bars_held': in_trade['bars_held'],
                'opt_pct': round(opt_pct,2), 'pnl': round(pnl,2),
                'mfe': round(in_trade['mfe'],2), 'mae': round(in_trade['mae'],2),
                'exit': 'EOD', 'regime': in_trade['regime'], 'gap_pct': round(gap_pct,2),
            })

# ── RESULTS ───────────────────────────────────────────────────────
df = pd.DataFrame(trades)
if df.empty:
    print("No trades fired.")
else:
    wins   = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    wr     = len(wins) / len(df)
    avg_w  = wins['pnl'].mean()   if len(wins)   else 0
    avg_l  = losses['pnl'].mean() if len(losses) else 0
    pf     = wins['pnl'].sum() / abs(losses['pnl'].sum()) if losses['pnl'].sum() != 0 else float('inf')
    ev     = df['pnl'].mean()

    print(f"\n{'='*55}")
    print(f"BOOF60 BACKTEST — {len(all_dates)} days  |  {len(df)} trades")
    print(f"{'='*55}")

    print(f"\n── CORE METRICS ──────────────────────────────────────")
    print(f"  Win Rate:        {wr*100:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  Profit Factor:   {pf:.2f}x")
    print(f"  EV per trade:    ${ev:.2f}")
    print(f"  Avg Win:         ${avg_w:.2f}")
    print(f"  Avg Loss:        ${avg_l:.2f}")
    print(f"  Win/Loss ratio:  {abs(avg_w/avg_l):.2f}x")
    print(f"  Total P&L:       ${df['pnl'].sum():.2f}")
    print(f"  Avg trades/day:  {len(df)/len(all_dates):.1f}")
    print(f"  Avg P&L/day:     ${df['pnl'].sum()/len(all_dates):.2f}")
    print(f"  Annualized EV:   ${ev * len(df)/len(all_dates) * 252:.0f}/yr")

    print(f"\n── MFE / MAE ─────────────────────────────────────────")
    print(f"  Avg MFE:               {df['mfe'].mean():.1f}%")
    print(f"  Avg MAE:               {df['mae'].mean():.1f}%")
    print(f"  MFE winners:           {wins['mfe'].mean():.1f}%")
    print(f"  MAE winners:           {wins['mae'].mean():.1f}%")
    print(f"  MFE losers:            {losses['mfe'].mean():.1f}%")
    print(f"  MAE losers:            {losses['mae'].mean():.1f}%")
    print(f"  Hit TP ({TP_PCT}%) MFE:   {len(df[df['mfe']>=TP_PCT])} ({len(df[df['mfe']>=TP_PCT])/len(df)*100:.0f}%)")
    print(f"  Hit SL (-{SL_PCT}%) MAE:  {len(df[df['mae']<=-SL_PCT])} ({len(df[df['mae']<=-SL_PCT])/len(df)*100:.0f}%)")

    print(f"\n── TIMING ────────────────────────────────────────────")
    print(f"  Avg hold:    {df['bars_held'].mean():.1f} min")
    print(f"  Median hold: {df['bars_held'].median():.0f} min")
    print(f"  Min hold:    {df['bars_held'].min()} min")
    print(f"  Max hold:    {df['bars_held'].max()} min")
    print(f"\n  Exit breakdown:")
    print(df.groupby('exit')['pnl'].agg(['count','sum','mean']).round(2)
            .rename(columns={'count':'n','sum':'total$','mean':'avg$'}).to_string())

    print(f"\n── BY DIRECTION ──────────────────────────────────────")
    print(df.groupby('direction').agg(
        n=('pnl','count'),
        wr=('pnl', lambda x: f"{(x>0).mean()*100:.0f}%"),
        total=('pnl','sum'), avg=('pnl','mean'),
        mfe=('mfe','mean'), mae=('mae','mean')
    ).round(2).to_string())

    print(f"\n── BY REGIME ─────────────────────────────────────────")
    print(df.groupby('regime').agg(
        n=('pnl','count'),
        wr=('pnl', lambda x: f"{(x>0).mean()*100:.0f}%"),
        total=('pnl','sum'), avg=('pnl','mean')
    ).round(2).to_string())

    print(f"\n── TOP 5 WINS ────────────────────────────────────────")
    print(df.nlargest(5,'pnl')[['date','sym','direction','entry_time','exit_time','bars_held','opt_pct','pnl','exit']].to_string(index=False))

    print(f"\n── TOP 5 LOSSES ──────────────────────────────────────")
    print(df.nsmallest(5,'pnl')[['date','sym','direction','entry_time','exit_time','bars_held','opt_pct','pnl','exit']].to_string(index=False))

    print(f"\n── MONTHLY BREAKDOWN ─────────────────────────────────")
    df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
    print(df.groupby('month').agg(
        trades=('pnl','count'), pnl=('pnl','sum'),
        wr=('pnl', lambda x: f"{(x>0).mean()*100:.0f}%"),
        avg=('pnl','mean')
    ).round(2).to_string())

    df.to_csv('boof60_trades.csv', index=False)
    print(f"\nFull trade log saved to boof60_trades.csv")
