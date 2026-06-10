"""
Boof 23 — Live Micro-Scale Validation Tracker
===============================================
Run this DAILY after market close while paper/micro trading Boof 23.
Tracks only 3 things:

  1. Realized EV vs Expected EV
     - expected_ev: backtest EV per trade = $7.98 (prox=30, engulf=off)
     - realized_ev: actual mean P&L per closed trade
     - drift: how far live is from backtest, and in which direction

  2. Slippage deviation
     - expected_slip: 0 (clean open fill assumed in backtest)
     - actual_slip: entry_fill_price - signal_price (long) or reversed (short)
     - slip_atr: slippage expressed as fraction of ATR
     - flag if consistently > 0.15 ATR (our stress test warning level)

  3. Streak behavior in live fills
     - current streak (win/loss)
     - max streak seen live vs backtest max (9)
     - streak cost vs expected backtest cost

USAGE:
  python _b23_live_tracker.py log              — open the trade log
  python _b23_live_tracker.py add <fields>     — log a completed trade
  python _b23_live_tracker.py report           — print live validation report

TRADE LOG FORMAT (JSON lines, one per trade):
  {
    "date":        "2026-05-25",
    "sym":         "NVDA",
    "direction":   "long",
    "signal_price": 123.45,      # price when signal fired (open of entry bar)
    "fill_price":   123.52,      # actual fill price
    "atr":          1.23,        # ATR at signal bar
    "tier":         "core",      # core | expanded
    "size":         600,         # dollar size used
    "exit_type":    "tp",        # tp | sl | time
    "exit_price":   127.77,
    "pnl":          24.60        # realized dollar P&L
  }
"""
import sys, json, os
from pathlib import Path
import numpy as np
from datetime import datetime

LOG_FILE = Path('_b23_live_log.jsonl')

# ── Backtest benchmarks (prox=30, engulf=off, 17 months) ──────────
EXPECTED_EV       = 7.98    # $/trade
EXPECTED_WR       = 0.610   # 61.0%
EXPECTED_PF       = 29.37
EXPECTED_P90_SLIP = 0.10    # ATR — baseline p90 slippage
CORE_SIZE  = 600
EXP_SIZE   = 200
SAMPLE_WARN = 30

# ── 3-Tier monitoring thresholds ──────────────────────────────────
# Tier 1 🟢 — Early warning (noise filter)
T1_EV_DRIFT    = 0.15   # EV drift >15%
T1_SLIP_P90    = 0.12   # p90 slippage creeping up
T1_STREAK      = 7      # streak >= 7

# Tier 2 🟡 — Structural degradation
T2_EV_DRIFT    = 0.25   # EV drift >25%
T2_SLIP_MEAN   = 0.15   # mean slippage > 0.15 ATR
T2_STREAK      = 7      # repeated 7–9 streaks (>1 occurrence)

# Tier 3 🔴 — Edge failure
T3_EV_DRIFT    = 0.40   # EV drift >40%
T3_STREAK      = 9      # streak > 9 (exceeds backtest max)
T3_SLIP_SHIFT  = 0.20   # mean slippage regime shift confirmed

# ── Helpers ────────────────────────────────────────────────────────
def load_trades():
    if not LOG_FILE.exists():
        return []
    trades = []
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return trades

def save_trade(trade: dict):
    with open(LOG_FILE, 'a') as f:
        f.write(json.dumps(trade) + '\n')

def streak_analysis(trades):
    win_seq = [t['pnl'] > 0 for t in trades]
    streaks = []; cur = 0
    for w in win_seq:
        if not w: cur += 1
        else:
            if cur > 0: streaks.append(cur)
            cur = 0
    if cur > 0: streaks.append(cur)
    # Current streak
    cur_streak = 0; cur_type = 'none'
    for t in reversed(trades):
        if t['pnl'] > 0:
            if cur_type == 'none': cur_type = 'win'
            if cur_type == 'win':  cur_streak += 1
            else: break
        else:
            if cur_type == 'none': cur_type = 'loss'
            if cur_type == 'loss': cur_streak += 1
            else: break
    return streaks, cur_streak, cur_type

def slippage_stats(trades):
    slips = []
    for t in trades:
        sp = t.get('signal_price', 0)
        fp = t.get('fill_price', 0)
        atr = t.get('atr', 0)
        if sp <= 0 or fp <= 0 or atr <= 0: continue
        if t['direction'] == 'long':
            slip_pts = fp - sp        # positive = paid more (bad)
        else:
            slip_pts = sp - fp        # positive = sold lower (bad)
        slips.append(slip_pts / atr)
    return slips

# ── Commands ───────────────────────────────────────────────────────
def cmd_log():
    trades = load_trades()
    if not trades:
        print('No trades logged yet.')
        print(f'Log file: {LOG_FILE.absolute()}')
        return
    print(f'\n{"="*72}')
    print(f'  Boof 23 Live Trade Log  ({len(trades)} trades)')
    print(f'{"="*72}')
    print(f'  {"#":>4}  {"Date":<12}  {"Sym":<6}  {"Dir":<6}  {"Tier":<8}  {"Size":>6}  {"Fill":>8}  {"Exit":<5}  {"PnL":>8}')
    print(f'  {"-"*70}')
    for i, t in enumerate(trades, 1):
        print(f'  {i:>4}  {t.get("date","?"):<12}  {t.get("sym","?"):<6}  '
              f'{t.get("direction","?"):<6}  {t.get("tier","?"):<8}  '
              f'${t.get("size",0):>5}  ${t.get("fill_price",0):>7.2f}  '
              f'{t.get("exit_type","?"):<5}  ${t.get("pnl",0):>7.2f}')
    print(f'{"="*72}\n')

def cmd_add(args):
    """Interactive add or positional: add date sym dir sig_price fill atr tier size exit exit_price pnl"""
    if len(args) >= 12:
        date, sym, direction, sig_price, fill, atr, tier, size, exit_type, exit_price, pnl = (
            args[0], args[1], args[2], float(args[3]), float(args[4]),
            float(args[5]), args[6], float(args[7]), args[8], float(args[9]), float(args[10])
        )
    else:
        print('Interactive trade entry:')
        date        = input('  Date (YYYY-MM-DD) [today]: ').strip() or datetime.now().strftime('%Y-%m-%d')
        sym         = input('  Symbol: ').strip().upper()
        direction   = input('  Direction (long/short): ').strip().lower()
        sig_price   = float(input('  Signal price (open of entry bar): '))
        fill        = float(input('  Actual fill price: '))
        atr         = float(input('  ATR at signal bar: '))
        tier        = input('  Tier (core/expanded): ').strip().lower()
        size        = float(input(f'  Size ($) [{CORE_SIZE if tier=="core" else EXP_SIZE}]: ') or
                           (CORE_SIZE if tier == 'core' else EXP_SIZE))
        exit_type   = input('  Exit type (tp/sl/time): ').strip().lower()
        exit_price  = float(input('  Exit price: '))
        pnl         = float(input('  Realized P&L ($): '))

    trade = {
        'date': date, 'sym': sym, 'direction': direction,
        'signal_price': sig_price, 'fill_price': fill, 'atr': atr,
        'tier': tier, 'size': size,
        'exit_type': exit_type, 'exit_price': exit_price, 'pnl': pnl,
        'logged_at': datetime.now().isoformat(),
    }
    save_trade(trade)
    slip_pts = (fill - sig_price) if direction == 'long' else (sig_price - fill)
    slip_atr = slip_pts / atr if atr > 0 else 0
    print(f'\n  Logged: {sym} {direction} {tier} ${size} | PnL=${pnl:.2f} | slip={slip_atr:+.3f} ATR')

TIER_LABELS = {
    0: ('     ', 'OK'),
    1: ('🟢 T1', 'WATCH'),
    2: ('🟡 T2', 'INVESTIGATE'),
    3: ('🔴 T3', 'PROTECT CAPITAL'),
}
TIER_ACTIONS = {
    0: 'No action required.',
    1: 'Observe only — do not change sizing or parameters yet.',
    2: 'Reduce size 50%. Analyze regime conditions and execution quality.',
    3: 'Stop / pause trading immediately. Full revalidation required.',
}

def tier_label(t):
    icon, name = TIER_LABELS.get(t, ('     ', 'OK'))
    return f'{icon} {name}'

def ev_tier(drift_pct):
    d = abs(drift_pct)
    if d > T3_EV_DRIFT * 100: return 3
    if d > T2_EV_DRIFT * 100: return 2
    if d > T1_EV_DRIFT * 100: return 1
    return 0

def slip_tier(mean_slip, p90_slip):
    if mean_slip > T3_SLIP_SHIFT: return 3
    if mean_slip > T2_SLIP_MEAN:  return 2
    if p90_slip  > T1_SLIP_P90:   return 1
    return 0

def streak_tier(max_streak, n_heavy_streaks):
    if max_streak > T3_STREAK:    return 3
    if n_heavy_streaks > 1:       return 2
    if max_streak >= T1_STREAK:   return 1
    return 0

def cmd_report():
    trades = load_trades()
    if not trades:
        print('No trades logged. Use: python _b23_live_tracker.py add')
        return

    n      = len(trades)
    pnls   = np.array([t['pnl'] for t in trades])
    pos    = pnls[pnls > 0]; neg = pnls[pnls < 0]
    wr     = len(pos) / n
    ev     = float(np.mean(pnls))
    pf     = float(sum(pos) / max(abs(sum(neg)), 0.01)) if len(neg) else float('inf')
    total  = float(sum(pnls))
    slips  = slippage_stats(trades)
    streaks, cur_streak, cur_type = streak_analysis(trades)
    exit_counts = {'tp': 0, 'sl': 0, 'time': 0}
    for t in trades:
        k = t.get('exit_type', 'time')
        exit_counts[k] = exit_counts.get(k, 0) + 1

    ev_drift_pct = (ev - EXPECTED_EV) / EXPECTED_EV * 100
    ev_drift     = ev - EXPECTED_EV
    wr_drift     = (wr - EXPECTED_WR) * 100
    pf_drift     = pf - EXPECTED_PF

    slip_arr   = np.array(slips) if slips else np.array([0.0])
    mean_slip  = float(np.mean(slip_arr))
    p90_slip   = float(np.percentile(slip_arr, 90))

    max_streak     = max(streaks) if streaks else 0
    heavy_streaks  = [s for s in streaks if s >= T1_STREAK]   # 7+
    n_heavy        = len(heavy_streaks)

    t_ev     = ev_tier(ev_drift_pct)
    t_slip   = slip_tier(mean_slip, p90_slip)
    t_streak = streak_tier(max_streak, n_heavy)
    overall  = max(t_ev, t_slip, t_streak)

    overall_label = {
        0: '     OK  — live behavior matches backtest',
        1: '🟢 T1 WATCH  — observe only, no sizing changes',
        2: '🟡 T2 INVESTIGATE  — reduce size 50%, analyze regime/execution',
        3: '🔴 T3 PROTECT CAPITAL  — stop / pause / revalidate now',
    }[overall]

    print(f'\n{"="*72}')
    print(f'  BOOF 23 — Live Micro Validation Report')
    print(f'  {n} trades  |  Benchmark: EV=${EXPECTED_EV}  WR={EXPECTED_WR*100:.0f}%  PF={EXPECTED_PF}')
    if n < SAMPLE_WARN:
        print(f'  ** Only {n} trades — stats unreliable below {SAMPLE_WARN}. Read directionally only.')
    print(f'{"="*72}')

    # ── 1. Realized EV vs Expected EV ────────────────────────────
    lbl = tier_label(t_ev)
    print(f'\n  1. REALIZED EV vs EXPECTED EV                        {lbl}')
    print(f'  {"─"*68}')
    print(f'    Expected EV/trade:   ${EXPECTED_EV:.2f}')
    print(f'    Realized EV/trade:   ${ev:.2f}  ({ev_drift:+.2f} / {ev_drift_pct:+.1f}%)')
    print(f'    Expected WR:         {EXPECTED_WR*100:.1f}%  |  Realized: {wr*100:.1f}%  ({wr_drift:+.1f}pp)')
    print(f'    Expected PF:         {EXPECTED_PF:.2f}  |  Realized: {pf:.2f}  ({pf_drift:+.2f})')
    print(f'    Total P&L:           ${total:,.2f}  |  TP={exit_counts["tp"]} SL={exit_counts["sl"]} Time={exit_counts["time"]}')
    if t_ev == 1: print(f'    → OBSERVE ONLY. Wait for 20+ more trades before acting.')
    if t_ev == 2: print(f'    → REDUCE SIZE 50%. Check: regime shift? execution timing?')
    if t_ev == 3: print(f'    → STOP TRADING. ZigZag filter likely failing. Revalidate.')

    # ── 2. Slippage Deviation ─────────────────────────────────────
    lbl = tier_label(t_slip)
    print(f'\n  2. SLIPPAGE DEVIATION                                {lbl}')
    print(f'  {"─"*68}')
    if not slips:
        print(f'    No signal_price/fill_price logged yet — add fills to track')
    else:
        print(f'    Mean slippage:       {mean_slip:+.3f} ATR  (T2 >0.15 | T3 >0.20)')
        print(f'    p90 slippage:        {p90_slip:+.3f} ATR  (T1 >0.12)')
        if t_slip == 0: print(f'    Fill quality nominal.')
        if t_slip == 1: print(f'    → OBSERVE ONLY. p90 creeping — check fills not lagging by >1 bar.')
        if t_slip == 2: print(f'    → REDUCE SIZE 50%. Systematic delay detected. Fix execution latency.')
        if t_slip == 3: print(f'    → STOP TRADING. Slippage regime shift confirmed. Fix fills first.')

    # ── 3. Streak Behavior ────────────────────────────────────────
    lbl = tier_label(t_streak)
    print(f'\n  3. STREAK BEHAVIOR                                   {lbl}')
    print(f'  {"─"*68}')
    cur_dir = f'{cur_streak} consecutive {cur_type}s' if cur_type != 'none' else 'none'
    print(f'    Current streak:      {cur_dir}')
    print(f'    Max streak (live):   {max_streak}  (backtest max: 9, cost: $4)')
    print(f'    Streak clusters 7+:  {n_heavy} occurrences')
    if streaks:
        print(f'    Avg streak:          {np.mean(streaks):.2f}  (backtest: 1.63)')
        print(f'    p90 streak:          {int(np.percentile(streaks, 90))}  (backtest: 3)')
    if t_streak == 0: print(f'    Streak behavior normal.')
    if t_streak == 1: print(f'    → OBSERVE ONLY. Streak of {max_streak} — watch next 5 trades.')
    if t_streak == 2: print(f'    → REDUCE SIZE 50%. Repeated 7–9 streak clusters ({n_heavy}x) — analyze regime.')
    if t_streak == 3: print(f'    → STOP TRADING. Streak >{T3_STREAK} exceeds backtest max. Full revalidation.')

    # ── Overall status ────────────────────────────────────────────
    print(f'\n  {"="*70}')
    print(f'  STATUS:  {overall_label}')
    print(f'  ACTION:  {TIER_ACTIONS[overall]}')
    print(f'\n  Signals: EV {tier_label(t_ev)}  |  Slip {tier_label(t_slip)}  |  Streak {tier_label(t_streak)}')
    print(f'  {"="*70}\n')

# ── Main ───────────────────────────────────────────────────────────
if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'report'
    if cmd == 'log':
        cmd_log()
    elif cmd == 'add':
        cmd_add(sys.argv[2:])
    elif cmd == 'report':
        cmd_report()
    else:
        print(__doc__)
