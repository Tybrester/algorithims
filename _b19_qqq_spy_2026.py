"""
Boof 19 QQQ/SPY Backtest — realistic TP/SL, both symbols, Dec 2025–May 2026
Uses the actual live bot signal logic from boof19_qqq.ts / boof19_spy.ts profiles.
TP/SL measured on underlying move (not synthetic options pricing).
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import warnings
warnings.filterwarnings('ignore')

# ── CONFIG ────────────────────────────────────────────────
END   = datetime.now(pytz.UTC).strftime("%Y-%m-%d")
START = (datetime.now(pytz.UTC) - timedelta(days=58)).strftime("%Y-%m-%d")
TF    = "5m"

PROFILES = {
    'QQQ': {
        'tp':            0.45 / 100,   # underlying TP (live bot default 45%)
        'sl':           -0.12 / 100,   # underlying SL
        'max_hold_min':  15,
        'orb_breakout':  0.012,        # 1.2%
        'liq_grab':      0.010,
        'vwap_dist':     0.015,
        'require_trend': True,
    },
    'SPY': {
        'tp':            0.35 / 100,
        'sl':           -0.10 / 100,
        'max_hold_min':  20,
        'orb_breakout':  0.008,        # 0.8%
        'liq_grab':      0.007,
        'vwap_dist':     0.012,
        'require_trend': False,        # SPY allows mean-reversion in chop
    },
}

OPEN_DELAY_MIN = 5   # skip first 5 min after open
MAX_TRADES_DAY = 5

# ── INDICATORS ────────────────────────────────────────────
def calc_vwap(df):
    tp  = (df['High'] + df['Low'] + df['Close']) / 3
    cum = (tp * df['Volume']).cumsum() / df['Volume'].cumsum()
    return cum

def calc_ema(series, n):
    return series.ewm(span=n, adjust=False).mean()

def detect_regime(df, i):
    if i < 30:
        return 'chop'
    v  = calc_vwap(df)
    e9  = calc_ema(df['Close'], 9)
    e21 = calc_ema(df['Close'], 21)
    slope  = (v.iloc[i] - v.iloc[i-10]) / v.iloc[i-10]
    spread = abs(e9.iloc[i] - e21.iloc[i]) / e21.iloc[i]
    sprev  = abs(e9.iloc[i-5] - e21.iloc[i-5]) / e21.iloc[i-5]
    score  = 0
    if abs(slope) >= 0.0001:  score += 30
    elif abs(slope) <= 0.00002: score -= 10
    if spread > sprev * 1.1 and spread > 0.0005: score += 25
    elif spread < 0.0001: score -= 10
    total_move = sum(abs(df['Close'].iloc[j] - df['Open'].iloc[j]) for j in range(i-14, i))
    total_rng  = sum(df['High'].iloc[j] - df['Low'].iloc[j] for j in range(i-14, i))
    adx = total_move / total_rng if total_rng else 0
    if adx >= 0.002: score += 25
    elif adx <= 0.0005: score -= 10
    pv = (df['Close'].iloc[i] - v.iloc[i]) / v.iloc[i]
    s9 = (e9.iloc[i] - e9.iloc[i-5]) / e9.iloc[i-5]
    if (pv > 0.001 and s9 > 0) or (pv < -0.001 and s9 < 0): score += 20
    elif abs(pv) < 0.001: score -= 10
    return 'strong_trend' if score >= 70 else ('weak_trend' if score >= 40 else 'chop')

def detect_momentum_surge(df, i):
    if i < 5: return False, None
    recent = df['Close'].iloc[i-5:i]
    mom = (recent.iloc[-1] - recent.iloc[0]) / recent.iloc[0]
    if mom > 0.005:
        greens = sum(1 for j in range(i-5, i) if df['Close'].iloc[j] > df['Open'].iloc[j])
        if greens >= 4: return True, 'buy'
    elif mom < -0.005:
        reds = sum(1 for j in range(i-5, i) if df['Close'].iloc[j] < df['Open'].iloc[j])
        if reds >= 4: return True, 'sell'
    return False, None

# ── BACKTEST ──────────────────────────────────────────────
def run(sym, prof):
    print(f"\n{'='*55}")
    print(f"  Boof 19 — {sym}  |  {START} → {END}")
    print(f"{'='*55}")

    raw = yf.Ticker(sym).history(start=START, end=END, interval=TF)
    if raw.empty:
        print("No data"); return

    raw.index = raw.index.tz_convert('America/New_York')
    raw = raw.between_time('09:30', '15:59')
    df  = raw.copy()
    print(f"Bars: {len(df)}")

    trades      = []
    in_trade    = False
    entry_price = 0.0
    entry_dir   = ''
    entry_time  = None
    day_trades  = 0
    last_date   = None

    # Build per-day open time map
    days = df.groupby(df.index.date)

    for date, day_df in days:
        day_df = day_df.sort_index()
        if len(day_df) < 10:
            continue

        day_open_time = day_df.index[0]
        orb_end_idx   = None
        # ORB = first 6 bars (30 min on 5m)
        orb_bars = min(6, len(day_df))
        orb_high = day_df['High'].iloc[:orb_bars].max()
        orb_low  = day_df['Low'].iloc[:orb_bars].min()

        day_trade_count = 0

        for i in range(orb_bars, len(day_df)):
            bar  = day_df.iloc[i]
            time = day_df.index[i]

            # Close cutoff
            if time.hour == 15 and time.minute >= 45:
                if in_trade:
                    move = (bar['Close'] - entry_price) / entry_price
                    if entry_dir == 'sell': move = -move
                    trades.append({'sym': sym, 'date': str(date), 'dir': entry_dir,
                                   'move': move, 'reason': 'EOD close', 'time': str(entry_time)})
                    in_trade = False
                break

            if in_trade:
                move = (bar['Close'] - entry_price) / entry_price
                if entry_dir == 'sell': move = -move
                hold = (time - entry_time).total_seconds() / 60
                reason = None
                if move >= prof['tp']:            reason = 'TP'
                elif move <= prof['sl']:          reason = 'SL'
                elif hold >= prof['max_hold_min']: reason = 'MaxHold'
                if reason:
                    trades.append({'sym': sym, 'date': str(date), 'dir': entry_dir,
                                   'move': move, 'reason': reason, 'time': str(entry_time)})
                    in_trade = False
                continue

            if day_trade_count >= MAX_TRADES_DAY:
                continue

            # Need enough history for regime
            global_i = df.index.get_loc(time)
            if global_i < 50:
                continue

            regime = detect_regime(df, global_i)
            if prof['require_trend'] and regime not in ('strong_trend', 'weak_trend'):
                continue

            # VWAP distance filter
            v_val = calc_vwap(df.iloc[:global_i+1]).iloc[-1]
            vdist = abs(bar['Close'] - v_val) / v_val
            if vdist > prof['vwap_dist']:
                continue

            # Momentum surge
            has_surge, surge_dir = detect_momentum_surge(df, global_i)
            if has_surge:
                in_trade    = True
                entry_price = bar['Close']
                entry_dir   = surge_dir
                entry_time  = time
                day_trade_count += 1
                continue

            # ORB breakout/breakdown
            if bar['Close'] > orb_high * (1 + prof['orb_breakout']):
                in_trade    = True
                entry_price = bar['Close']
                entry_dir   = 'buy'
                entry_time  = time
                day_trade_count += 1
            elif bar['Close'] < orb_low * (1 - prof['orb_breakout']):
                in_trade    = True
                entry_price = bar['Close']
                entry_dir   = 'sell'
                entry_time  = time
                day_trade_count += 1

    if not trades:
        print("No trades."); return

    df_t = pd.DataFrame(trades)
    wins = df_t[df_t['move'] > 0]
    loss = df_t[df_t['move'] <= 0]
    wr   = len(wins) / len(df_t) * 100
    avg  = df_t['move'].mean() * 100
    pf   = wins['move'].sum() / abs(loss['move'].sum()) if len(loss) and loss['move'].sum() != 0 else float('inf')
    days_traded = df_t['date'].nunique()
    tpd  = len(df_t) / days_traded if days_traded else 0

    tp_hits = (df_t['reason'] == 'TP').sum()
    sl_hits = (df_t['reason'] == 'SL').sum()
    mh_hits = (df_t['reason'] == 'MaxHold').sum()

    print(f"  Trades:       {len(df_t)}  ({tpd:.1f}/day over {days_traded} days)")
    print(f"  Win Rate:     {wr:.1f}%  ({len(wins)}W / {len(loss)}L)")
    print(f"  Avg Move:     {avg:+.3f}%")
    print(f"  Profit Factor:{pf:.2f}")
    print(f"  TP hits:      {tp_hits}  |  SL hits: {sl_hits}  |  MaxHold: {mh_hits}")
    print(f"  TP={prof['tp']*100:.2f}%  SL={prof['sl']*100:.2f}%  MaxHold={prof['max_hold_min']}min")

    # Monthly breakdown
    df_t['month'] = pd.to_datetime(df_t['date']).dt.to_period('M')
    print(f"\n  Monthly breakdown:")
    for mo, g in df_t.groupby('month'):
        mw = (g['move'] > 0).sum()
        ml = (g['move'] <= 0).sum()
        mwr = mw / len(g) * 100 if len(g) else 0
        print(f"    {mo}: {len(g):3d} trades  WR={mwr:.0f}%  ({mw}W/{ml}L)")

    print(f"{'='*55}")

# ── MAIN ─────────────────────────────────────────────────
if __name__ == '__main__':
    for sym, prof in PROFILES.items():
        run(sym, prof)
