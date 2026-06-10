"""
Backtest Cooldown Simulation
Runs boof23 across all symbols and simulates the 2-loss per-symbol cooldown (10 min pause).
Compares raw backtest P&L vs cooldown-filtered P&L.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import yfinance as yf

# Import boof23 logic
from backtest_boof23 import run_boof23, ATR_LEN, VOL_LEN, FRACTAL_BARS, MAX_HOLD

# ── Config ────────────────────────────────────────────────────────
SYMBOLS      = ['NVDA', 'AAPL', 'META', 'MSFT', 'AMZN', 'GOOGL', 'AVGO', 'TSLA', 'LLY']
START_DATE   = '2026-01-01'
END_DATE     = '2026-05-28'
INTERVAL     = '1m'
OPTION_TP    = 0.35    # +35% option premium TP
OPTION_SL    = -0.10   # -10% option premium SL
COOLDOWN_MIN = 10      # minutes to pause symbol after 2 consecutive SL hits
CORE_SIZE    = 600     # $ per core trade (slack >= 1.4)
EXP_SIZE     = 200     # $ per expanded trade

# ── Fetch candles ─────────────────────────────────────────────────
def fetch_candles(symbol, start, end):
    print(f"  Fetching {symbol}...")
    df = yf.download(symbol, start=start, end=end, interval=INTERVAL, auto_adjust=True, progress=False)
    if df.empty:
        return pd.DataFrame()
    df = df.reset_index()
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    df = df.rename(columns={'datetime': 'time'})
    df['time'] = pd.to_datetime(df['time'])
    # Market hours only: 9:30–16:00 ET
    df = df[df['time'].dt.tz_convert('America/New_York').dt.time.between(
        pd.Timestamp('09:30').time(), pd.Timestamp('16:00').time()
    )]
    return df.reset_index(drop=True)

# ── Simulate option P&L from underlying trade ─────────────────────
def option_pnl(trade, size):
    et = trade['exit_type']
    if et == 'tp':
        pct = OPTION_TP
    elif et == 'sl':
        pct = OPTION_SL
    else:
        pct = -0.03  # time exit: small loss
    return size * pct

# ── Run simulation ────────────────────────────────────────────────
def run_simulation():
    all_trades_raw      = []  # all trades, no cooldown
    all_trades_cooled   = []  # trades after applying cooldown filter

    for sym in SYMBOLS:
        # Fetch up to 7 days at a time (yfinance 1m limit is 7 days)
        start = datetime.strptime(START_DATE, '%Y-%m-%d')
        end   = datetime.strptime(END_DATE,   '%Y-%m-%d')
        frames = []
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(chunk_start + timedelta(days=5), end)
            df_chunk = fetch_candles(sym, chunk_start.strftime('%Y-%m-%d'), chunk_end.strftime('%Y-%m-%d'))
            if not df_chunk.empty:
                frames.append(df_chunk)
            chunk_start = chunk_end

        if not frames:
            print(f"  No data for {sym}, skipping")
            continue

        df = pd.concat(frames).drop_duplicates(subset='time').reset_index(drop=True)
        if len(df) < VOL_LEN + ATR_LEN + FRACTAL_BARS * 2 + MAX_HOLD + 10:
            print(f"  Not enough bars for {sym}, skipping")
            continue

        trades = run_boof23(df, symbol=sym)
        print(f"  {sym}: {len(trades)} raw signals")

        # Attach timestamps using entry_bar index
        times = df['time'].values
        for t in trades:
            eb = t['entry_bar']
            xb = min(eb + MAX_HOLD, len(times) - 1)
            t['symbol']     = sym
            t['entry_time'] = pd.Timestamp(times[eb])
            t['exit_time']  = pd.Timestamp(times[xb])
            size = CORE_SIZE if t.get('tier') == 'core' else EXP_SIZE
            t['size']       = size
            t['pnl_option'] = option_pnl(t, size)
            all_trades_raw.append(t)

    # Sort all trades by entry time for cooldown simulation
    all_trades_raw.sort(key=lambda t: t['entry_time'])

    # ── Apply cooldown filter ──────────────────────────────────────
    sym_consec_losses  = {}   # symbol -> consecutive SL count
    sym_cooldown_until = {}   # symbol -> datetime when cooldown expires

    for t in all_trades_raw:
        sym  = t['symbol']
        etime = t['entry_time']

        # Check cooldown
        cooldown_until = sym_cooldown_until.get(sym)
        if cooldown_until and etime < cooldown_until:
            t['filtered'] = True
            continue

        # Trade passes — include it
        t['filtered'] = False
        all_trades_cooled.append(t)

        # Update cooldown state
        et = t['exit_type']
        if et == 'sl':
            prev = sym_consec_losses.get(sym, 0)
            new_losses = prev + 1
            sym_consec_losses[sym] = new_losses
            if new_losses >= 2:
                sym_cooldown_until[sym] = t['exit_time'] + timedelta(minutes=COOLDOWN_MIN)
                sym_consec_losses[sym]  = 0  # reset after cooldown triggered
        else:
            sym_consec_losses[sym] = 0  # win resets counter

    # ── Stats ──────────────────────────────────────────────────────
    def stats(trades, label):
        if not trades:
            print(f"\n{label}: No trades")
            return
        total   = len(trades)
        wins    = [t for t in trades if t['exit_type'] == 'tp']
        losses  = [t for t in trades if t['exit_type'] == 'sl']
        time_ex = [t for t in trades if t['exit_type'] == 'time']
        pnls    = [t['pnl_option'] for t in trades]
        total_pnl = sum(pnls)
        wr      = len(wins) / total * 100 if total else 0
        gross_w = sum(t['pnl_option'] for t in wins)
        gross_l = abs(sum(t['pnl_option'] for t in losses))
        pf      = gross_w / gross_l if gross_l else float('inf')

        print(f"\n{'='*50}")
        print(f"{label}")
        print(f"{'='*50}")
        print(f"  Total trades : {total}")
        print(f"  Wins / Losses: {len(wins)} / {len(losses)} / {len(time_ex)} (time)")
        print(f"  Win rate     : {wr:.1f}%")
        print(f"  Total P&L    : ${total_pnl:,.0f}")
        print(f"  Profit factor: {pf:.2f}")
        print(f"  Avg per trade: ${total_pnl/total:,.2f}")
        print(f"\n  By symbol:")
        by_sym = {}
        for t in trades:
            s = t['symbol']
            if s not in by_sym:
                by_sym[s] = []
            by_sym[s].append(t)
        for s, ts in sorted(by_sym.items()):
            s_pnl = sum(x['pnl_option'] for x in ts)
            s_wr  = len([x for x in ts if x['exit_type'] == 'tp']) / len(ts) * 100
            print(f"    {s:6s}: {len(ts):3d} trades  WR={s_wr:.0f}%  P&L=${s_pnl:,.0f}")

    stats(all_trades_raw,    "RAW (no cooldown)")
    stats(all_trades_cooled, f"WITH COOLDOWN (2 SL → {COOLDOWN_MIN}min pause)")

    filtered_count = len(all_trades_raw) - len(all_trades_cooled)
    print(f"\n  Trades filtered out by cooldown: {filtered_count} ({filtered_count/len(all_trades_raw)*100:.1f}%)")

if __name__ == '__main__':
    print(f"Running cooldown simulation: {START_DATE} → {END_DATE}")
    print(f"Symbols: {SYMBOLS}")
    print(f"Cooldown: 2 SL hits → {COOLDOWN_MIN} min pause\n")
    run_simulation()
