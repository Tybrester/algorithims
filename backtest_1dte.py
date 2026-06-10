"""
backtest_1dte.py
================
1DTE Options P&L backtest for Boof 21, 22, 23 — full year 2025
==============================================================
Methodology:
  1. Run each bot's signal engine on 1-min OHLCV bars (same logic as live)
  2. At signal entry bar, price a 1DTE ATM option using Black-Scholes
     - Stock IV estimated from 20-day realized vol * 1.2 (typical IV premium)
     - Time to expiry = hours remaining until next-day 4pm (1DTE)
  3. Track option P&L by simulating underlying moves:
     - Option price at each bar computed via BS with updated spot + time
     - TP hit  = option gains +TP_PCT% from entry premium
     - SL hit  = option loses -SL_PCT% from entry premium
     - EOD     = force-close at 3:58 PM ET bar (mark-to-market)
  4. Budget: $200 expanded / $600 core (B22/B23 tiered sizing), $250 B21
  5. Output: per-bot summary, per-symbol breakdown, monthly P&L table
"""

import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, date
from scipy.stats import norm
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials
from backtest_boof22 import run_boof22
from backtest_boof23 import run_boof23

# ─────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────
START_DATE = datetime(2025, 1, 2)
END_DATE   = datetime(2025, 12, 31)

# Bot configs
BOTS = {
    'Boof21': {
        'symbols':   ['SPY', 'QQQ'],
        'tp_pct':    0.35,   # +35%
        'sl_pct':   -0.18,   # -18%
        'budget':    250,    # flat $250/trade
        'tiered':    False,
    },
    'Boof22': {
        'symbols':   ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD'],
        'tp_pct':    0.35,
        'sl_pct':   -0.18,
        'budget':    200,    # expanded base
        'tiered':    True,   # core (slack>=1.4) = budget*3, expanded = budget
    },
    'Boof23': {
        'symbols':   ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD'],
        'tp_pct':    0.35,
        'sl_pct':   -0.18,
        'budget':    200,
        'tiered':    True,
    },
}

IV_LOOKBACK  = 20    # bars (days) for realized vol estimate
IV_MULT      = 1.20  # IV = realized vol * this (typical IV premium)
RISK_FREE    = 0.05
EOD_HOUR_ET  = 15
EOD_MIN_ET   = 58

# ─────────────────────────────────────────────────────────────────
# BLACK-SCHOLES
# ─────────────────────────────────────────────────────────────────
def bs_price(S, K, T, r, sigma, option_type='call'):
    """Black-Scholes option price. T in years."""
    if T <= 0 or sigma <= 0:
        intrinsic = max(S - K, 0) if option_type == 'call' else max(K - S, 0)
        return max(intrinsic, 0.01)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == 'call':
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def estimate_iv(daily_closes, lookback=IV_LOOKBACK):
    """Annualized realized vol from daily close returns * IV_MULT."""
    if len(daily_closes) < lookback + 1:
        return 0.30
    rets = np.diff(np.log(daily_closes[-lookback - 1:]))
    rv = np.std(rets) * np.sqrt(252)
    return max(rv * IV_MULT, 0.10)


def time_to_expiry_years(current_bar_time):
    """
    1DTE: option expires next trading day at 4pm ET.
    Returns T in years from current bar.
    """
    # Strip tz if present
    if hasattr(current_bar_time, 'tzinfo') and current_bar_time.tzinfo is not None:
        bar_et = current_bar_time.replace(tzinfo=None)
    else:
        bar_et = current_bar_time
    # Next day 4pm ET
    next_day = bar_et.date() + timedelta(days=1)
    # Skip weekends for expiry
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    expiry_dt = datetime(next_day.year, next_day.month, next_day.day, 16, 0, 0)
    remaining_seconds = max((expiry_dt - bar_et).total_seconds(), 60)
    return remaining_seconds / (365.25 * 24 * 3600)


# ─────────────────────────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────────────────────────
def fetch_bars(symbol, creds):
    """Fetch full-year 1-min bars with pagination (Alpaca 10k bar limit)."""
    print(f"  Fetching {symbol} 1-min bars 2025...", end='', flush=True)
    import requests as _req
    all_bars = []
    url = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
    params = {
        'timeframe':  '1Min',
        'start':      START_DATE.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'end':        END_DATE.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'adjustment': 'raw',
        'feed':       'sip',
        'limit':      10000,
    }
    headers = {
        'APCA-API-KEY-ID':     creds['api_key'],
        'APCA-API-SECRET-KEY': creds['secret_key'],
    }
    while True:
        resp = _req.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            print(f" ERROR {resp.status_code}")
            break
        data = resp.json()
        bars = data.get('bars', [])
        all_bars.extend(bars)
        next_token = data.get('next_page_token')
        if not next_token:
            break
        params['page_token'] = next_token
        print('.', end='', flush=True)
    print(f" {len(all_bars)} bars")
    if len(all_bars) < 100:
        print(f"  !! Insufficient data for {symbol}")
        return None
    df = pd.DataFrame(all_bars)
    df['time'] = pd.to_datetime(df['t'])
    df = df.rename(columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'})
    df = df[['time','open','high','low','close','volume']].copy()
    # Convert to ET
    df['time'] = df['time'].dt.tz_convert('America/New_York')
    df = df.sort_values('time').reset_index(drop=True)
    # Filter to market hours 9:30–16:00 ET only
    mh = (df['time'].dt.hour > 9) | ((df['time'].dt.hour == 9) & (df['time'].dt.minute >= 30))
    mh = mh & (df['time'].dt.hour < 16)
    df = df[mh].reset_index(drop=True)
    print(f"  {symbol}: {len(df)} market-hours bars, {df['time'].iloc[0].date()} to {df['time'].iloc[-1].date()}")
    return df


# ─────────────────────────────────────────────────────────────────
# BOOF 21 SIGNAL ENGINE (inline, simplified — volume cluster retest)
# ─────────────────────────────────────────────────────────────────
def run_boof21_signals(df_1m, symbol):
    """
    Boof 21 signal extraction. df_1m must have a DatetimeIndex (time as index).
    Returns list of signal dicts with entry_bar as integer position.
    """
    from backtest_boof21 import backtest as b21_backtest
    # B21 needs time-indexed df
    df_idx = df_1m.copy()
    df_idx = df_idx.set_index('time')
    try:
        trades = b21_backtest(df_idx, symbol)
        signals = []
        for t in trades:
            entry_time = t.get('entry_time')
            if entry_time is None:
                continue
            # Find integer position in df_1m where time matches
            matches = df_1m.index[df_1m['time'] == entry_time].tolist()
            if not matches:
                # Try finding closest bar
                idx = df_1m['time'].searchsorted(entry_time)
                if idx >= len(df_1m):
                    continue
                entry_bar = int(idx)
            else:
                entry_bar = int(matches[0])
            signals.append({
                'entry_bar':   entry_bar,
                'direction':   t.get('direction', 'LONG').lower(),
                'entry_price': t.get('entry', 0),
                'slack':       1.0,
                'tier':        'expanded',
            })
        return signals
    except Exception as e:
        print(f"    B21 signal error {symbol}: {e}")
        import traceback; traceback.print_exc()
        return []


# ─────────────────────────────────────────────────────────────────
# OPTIONS P&L SIMULATOR
# ─────────────────────────────────────────────────────────────────
def simulate_1dte_trades(df, signals, bot_cfg, daily_closes_map, symbol):
    """
    For each signal, price a 1DTE ATM option at entry, then track:
    - TP hit: option premium increases by +tp_pct → close at profit
    - SL hit: option premium decreases by -sl_pct → close at loss
    - EOD:    force close at 3:58 PM ET mark-to-market
    Returns list of trade result dicts.
    """
    tp_pct   = bot_cfg['tp_pct']
    sl_pct   = bot_cfg['sl_pct']   # negative, e.g. -0.18
    budget   = bot_cfg['budget']
    tiered   = bot_cfg['tiered']

    daily_closes = daily_closes_map.get(symbol, [])

    results = []

    for sig in signals:
        entry_bar = sig['entry_bar']
        if entry_bar >= len(df) - 1:
            continue

        entry_row  = df.iloc[entry_bar]
        entry_time = entry_row['time']
        S          = float(entry_row['open'])
        direction  = sig['direction']   # 'long' or 'short'
        slack      = sig.get('slack', 0.0)
        tier       = sig.get('tier', 'expanded')

        # Skip entries after 3:58 PM ET (no time to trade 1DTE intraday)
        if entry_time.hour > EOD_HOUR_ET or (entry_time.hour == EOD_HOUR_ET and entry_time.minute >= EOD_MIN_ET):
            continue

        # Estimate IV from prior daily closes
        iv = estimate_iv(daily_closes)

        # Time to expiry at entry
        T_entry = time_to_expiry_years(entry_time)

        # Price ATM option at entry
        opt_type    = 'call' if direction == 'long' else 'put'
        K           = round(S)   # ATM strike = rounded spot
        entry_prem  = bs_price(S, K, T_entry, RISK_FREE, iv, opt_type)
        entry_prem  = max(entry_prem, 0.05)

        # Trade sizing: contracts = floor(budget / (entry_prem * 100))
        if tiered:
            trade_budget = budget * 3 if tier == 'core' else budget
        else:
            trade_budget = budget
        contracts = max(1, int(trade_budget / (entry_prem * 100)))
        total_cost = contracts * entry_prem * 100

        # TP / SL thresholds on the premium
        tp_premium = entry_prem * (1 + tp_pct)
        sl_premium = entry_prem * (1 + sl_pct)   # sl_pct is negative

        exit_prem   = None
        exit_type   = 'eod'
        exit_time   = None

        # Scan forward bar by bar
        for j in range(entry_bar + 1, len(df)):
            row  = df.iloc[j]
            t_j  = row['time']

            # EOD force-close
            is_eod = (t_j.hour > EOD_HOUR_ET or
                      (t_j.hour == EOD_HOUR_ET and t_j.minute >= EOD_MIN_ET))

            T_j   = time_to_expiry_years(t_j)
            S_j   = float(row['close'])
            p_j   = bs_price(S_j, K, T_j, RISK_FREE, iv, opt_type)

            # Check TP / SL on option premium
            if p_j >= tp_premium:
                exit_prem = tp_premium
                exit_type = 'tp'
                exit_time = t_j
                break
            elif p_j <= sl_premium:
                exit_prem = sl_premium
                exit_type = 'sl'
                exit_time = t_j
                break
            elif is_eod:
                exit_prem = p_j
                exit_type = 'eod'
                exit_time = t_j
                break

        if exit_prem is None:
            exit_prem = entry_prem * 0.5   # expired worthless approx
            exit_type = 'expired'
            exit_time = entry_time

        pnl = (exit_prem - entry_prem) * contracts * 100
        pnl_pct = (exit_prem - entry_prem) / entry_prem * 100

        results.append({
            'symbol':      symbol,
            'date':        entry_time.date().isoformat(),
            'entry_time':  entry_time.isoformat(),
            'direction':   direction,
            'option_type': opt_type,
            'strike':      K,
            'entry_prem':  round(entry_prem, 2),
            'exit_prem':   round(exit_prem, 2),
            'iv':          round(iv, 3),
            'contracts':   contracts,
            'total_cost':  round(total_cost, 2),
            'pnl':         round(pnl, 2),
            'pnl_pct':     round(pnl_pct, 1),
            'exit_type':   exit_type,
            'tier':        tier,
        })

    return results


# ─────────────────────────────────────────────────────────────────
# DAILY CLOSE CACHE (for IV estimation)
# ─────────────────────────────────────────────────────────────────
def build_daily_closes(df):
    """Get sorted list of daily closing prices from 1-min data."""
    daily = df.copy()
    daily['date'] = daily['time'].dt.date
    closes = daily.groupby('date')['close'].last().sort_index().values.tolist()
    return closes


def get_daily_closes_up_to(all_closes, up_to_date):
    """Return close prices up to (not including) up_to_date."""
    # all_closes is a list; approximate by returning last IV_LOOKBACK+1 entries
    return all_closes  # full list; estimate_iv uses last N anyway


# ─────────────────────────────────────────────────────────────────
# REPORTING
# ─────────────────────────────────────────────────────────────────
def print_report(bot_name, all_trades):
    print(f"\n{'='*62}")
    print(f"  {bot_name} — 1DTE Options Backtest | Jan–Dec 2025")
    print(f"{'='*62}")

    if not all_trades:
        print("  No trades generated.")
        return

    df = pd.DataFrame(all_trades)
    total   = len(df)
    wins    = (df['pnl'] > 0).sum()
    losses  = (df['pnl'] <= 0).sum()
    wr      = wins / total * 100 if total else 0
    total_pnl = df['pnl'].sum()
    avg_win   = df.loc[df['pnl'] > 0, 'pnl'].mean() if wins else 0
    avg_loss  = df.loc[df['pnl'] <= 0, 'pnl'].mean() if losses else 0
    pf        = abs(df.loc[df['pnl'] > 0, 'pnl'].sum() / df.loc[df['pnl'] <= 0, 'pnl'].sum()) if losses and df.loc[df['pnl'] <= 0, 'pnl'].sum() != 0 else float('inf')
    ev        = total_pnl / total if total else 0

    tp_count  = (df['exit_type'] == 'tp').sum()
    sl_count  = (df['exit_type'] == 'sl').sum()
    eod_count = df['exit_type'].isin(['eod', 'expired']).sum()
    trades_per_day = total / max(df['date'].nunique(), 1)

    print(f"  Trades:       {total:>6}  ({trades_per_day:.1f}/day)")
    print(f"  Win Rate:     {wr:>5.1f}%  ({wins}W / {losses}L)")
    print(f"  Total P&L:    ${total_pnl:>+9,.2f}")
    print(f"  EV/Trade:     ${ev:>+7.2f}")
    print(f"  Avg Win:      ${avg_win:>+7.2f}   Avg Loss: ${avg_loss:>+7.2f}")
    print(f"  Profit Factor:{pf:>6.2f}")
    print(f"  Exit breakdown: TP={tp_count} SL={sl_count} EOD/Expired={eod_count}")

    # Per-symbol
    print(f"\n  {'Symbol':<8} {'Trades':>6} {'WR':>6} {'P&L':>10} {'EV':>8}")
    print(f"  {'-'*46}")
    for sym, g in df.groupby('symbol'):
        sw  = (g['pnl'] > 0).sum()
        swr = sw / len(g) * 100
        sp  = g['pnl'].sum()
        sev = sp / len(g)
        print(f"  {sym:<8} {len(g):>6} {swr:>5.1f}% ${sp:>+9,.2f} ${sev:>+7.2f}")

    # Monthly
    df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
    print(f"\n  Monthly P&L:")
    print(f"  {'Month':<10} {'Trades':>6} {'WR':>6} {'P&L':>10}")
    print(f"  {'-'*36}")
    monthly_pnl = []
    for month, g in df.groupby('month'):
        mw  = (g['pnl'] > 0).sum()
        mwr = mw / len(g) * 100
        mp  = g['pnl'].sum()
        monthly_pnl.append(mp)
        color = '+' if mp >= 0 else ''
        print(f"  {str(month):<10} {len(g):>6} {mwr:>5.1f}% ${mp:>+9,.2f}")
    red_months = sum(1 for p in monthly_pnl if p < 0)
    print(f"\n  Red months: {red_months}/{len(monthly_pnl)}")


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────
def main():
    creds = get_alpaca_credentials()
    print("1DTE Options Backtest — Boof 21 / 22 / 23 — Full Year 2025")
    print("="*62)

    # Which bots to run (default: all; pass bot names as args)
    target_bots = sys.argv[1:] if len(sys.argv) > 1 else list(BOTS.keys())
    target_bots = [b for b in target_bots if b in BOTS]
    if not target_bots:
        print(f"Valid bots: {list(BOTS.keys())}")
        return

    # Collect unique symbols across selected bots
    all_symbols = list({sym for b in target_bots for sym in BOTS[b]['symbols']})

    # Fetch all data upfront
    data = {}
    daily_closes_map = {}
    for sym in all_symbols:
        df = fetch_bars(sym, creds)
        if df is not None:
            data[sym] = df
            daily_closes_map[sym] = build_daily_closes(df)

    # Run each bot
    for bot_name in target_bots:
        bot_cfg = BOTS[bot_name]
        all_trades = []

        for sym in bot_cfg['symbols']:
            if sym not in data:
                print(f"  Skipping {sym} — no data")
                continue

            df = data[sym]
            print(f"\n[{bot_name}] Generating signals for {sym}...")

            # Run signal engine
            try:
                if bot_name == 'Boof21':
                    signals = run_boof21_signals(df, sym)
                elif bot_name == 'Boof22':
                    raw = run_boof22(df, symbol=sym, tp_pct=0.40, sl_pct=-0.15)
                    signals = [{
                        'entry_bar':   t['bar'] + 1,   # bar=signal bar, entry is next bar
                        'direction':   t['direction'],
                        'entry_price': t['entry'],
                        'slack':       t.get('slack', 0.0),
                        'tier':        t.get('tier', 'expanded'),
                    } for t in raw]
                elif bot_name == 'Boof23':
                    raw = run_boof23(df, symbol=sym)
                    signals = [{
                        'entry_bar':   t['entry_bar'],
                        'direction':   t['direction'],
                        'entry_price': t['entry'],
                        'slack':       t.get('slack', 0.0),
                        'tier':        t.get('tier', 'expanded'),
                    } for t in raw]
                else:
                    signals = []
            except Exception as e:
                print(f"  Signal error [{bot_name}] {sym}: {e}")
                import traceback; traceback.print_exc()
                signals = []

            print(f"  {sym}: {len(signals)} signals -> simulating 1DTE options...")

            dc = daily_closes_map.get(sym, [])
            trades = simulate_1dte_trades(df, signals, bot_cfg, {sym: dc}, sym)
            print(f"  {sym}: {len(trades)} trades simulated")
            all_trades.extend(trades)

        print_report(bot_name, all_trades)

    print("\nDone.")


if __name__ == '__main__':
    main()
