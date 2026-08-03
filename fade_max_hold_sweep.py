"""
Fade Max Hold Time Sweep
Tests max hold times: 2, 3, 4, 5 minutes
using live fade parameters (20pt body, 25pt SL, 7pt floor, 3pt trail, 120s cooldown).
Uses all available NQ_mbp1 tick data.
"""

import pandas as pd
import numpy as np
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import databento as db

DATA_DIR = Path(r"C:\Users\tybre\Desktop\aivibe\boof_data")
TZ = ZoneInfo("America/New_York")

# Live fade parameters (fixed)
CANDLE_THRESH = 20.0
SL_PTS = 25.0
FLOOR_PTS = 7.0
TRAIL_PTS = 3.0
MAX_DAILY_LOSS = -300.0
MAX_DAILY_TRADES = 30
COOLDOWN_SEC = 120
QTY = 1
MV = 2
DOLLAR_PER_PT = QTY * MV
ENTRY_START = dtime(9, 30)
ENTRY_CUTOFF = dtime(15, 45)
EOD_EXIT = dtime(15, 55)

MAX_HOLD_MINUTES = [2, 3, 4, 5]


def load_all_sessions():
    paths = sorted(DATA_DIR.glob("NQ_mbp1_*.dbn.zst"))
    print(f"Found {len(paths)} NQ tick data files")
    day_ticks = {}

    for path in paths:
        print(f"  Decoding {path.name}...", end=" ", flush=True)
        count = 0
        for record in db.DBNStore.from_file(path):
            if record.action == "T":
                ts_ns = int(record.ts_event)
                px = float(record.pretty_price)
                ts_dt = pd.Timestamp(ts_ns, unit="ns", tz="UTC").tz_convert(TZ)
                if ts_dt.weekday() >= 5:
                    continue
                t = ts_dt.time()
                if t < ENTRY_START or t > EOD_EXIT:
                    continue
                d = ts_dt.date()
                if d not in day_ticks:
                    day_ticks[d] = ([], [])
                day_ticks[d][0].append(ts_ns)
                day_ticks[d][1].append(px)
                count += 1
        print(f"{count:,} trades")

    print(f"\nBuilding sessions for {len(day_ticks)} trading days...")
    sessions = []
    for date in sorted(day_ticks.keys()):
        ts_list, px_list = day_ticks[date]
        ts_arr = np.asarray(ts_list, dtype=np.int64)
        px_arr = np.asarray(px_list, dtype=np.float64)
        index = pd.to_datetime(ts_arr, unit="ns", utc=True).tz_convert(TZ)
        ticks = pd.DataFrame({"price": px_arr}, index=index).sort_index()
        bars_1m = ticks["price"].resample("1min").ohlc().dropna()
        if len(bars_1m) < 5:
            continue
        sessions.append((date, ticks.index, ticks["price"].to_numpy(), bars_1m))

    print(f"Ready: {len(sessions)} trading days | {sessions[0][0]} -> {sessions[-1][0]}")
    return sessions


def find_exit_tick(tick_times, tick_prices, entry_t, direction, entry_px, max_hold_min):
    eod_cut = pd.Timestamp(entry_t.date(), tz=TZ) + pd.Timedelta(hours=EOD_EXIT.hour, minutes=EOD_EXIT.minute)
    max_hold_cut = entry_t + pd.Timedelta(minutes=max_hold_min)
    deadline = min(eod_cut, max_hold_cut)

    start_i = tick_times.searchsorted(entry_t)
    end_i = tick_times.searchsorted(deadline, side="right")

    if start_i >= end_i:
        return entry_px, "no_data", entry_t

    prices = tick_prices[start_i:end_i]
    times = tick_times[start_i:end_i]

    best_px = entry_px
    trail_active = False

    if direction == "long":
        sl_px = entry_px - SL_PTS
        for i in range(len(prices)):
            px = prices[i]
            if px > best_px:
                best_px = px
            if px <= sl_px:
                return px, "sl", times[i]
            favorable = best_px - entry_px
            if not trail_active and favorable >= FLOOR_PTS:
                trail_active = True
            if trail_active:
                trail_stop = best_px - TRAIL_PTS
                if px <= trail_stop:
                    return px, "trail", times[i]
    else:
        sl_px = entry_px + SL_PTS
        for i in range(len(prices)):
            px = prices[i]
            if px < best_px:
                best_px = px
            if px >= sl_px:
                return px, "sl", times[i]
            favorable = entry_px - best_px
            if not trail_active and favorable >= FLOOR_PTS:
                trail_active = True
            if trail_active:
                trail_stop = best_px + TRAIL_PTS
                if px >= trail_stop:
                    return px, "trail", times[i]

    last_px = prices[-1]
    last_ts = times[-1]
    reason = "timeout" if max_hold_cut <= eod_cut else "eod"
    return last_px, reason, last_ts


def run_backtest(sessions, max_hold_min):
    all_trades = []
    daily_summaries = []

    for date, tick_times, tick_prices, bars_1m in sessions:
        daily_pnl = 0.0
        daily_trades = 0
        halted = False
        last_exit_time = None

        for i in range(len(bars_1m)):
            bar = bars_1m.iloc[i]
            bar_time = bars_1m.index[i]

            if halted:
                break
            if daily_trades >= MAX_DAILY_TRADES:
                break

            t = bar_time.time()
            if t < ENTRY_START or t > ENTRY_CUTOFF:
                continue

            body = abs(bar["close"] - bar["open"])
            if body < CANDLE_THRESH:
                continue

            if last_exit_time is not None:
                secs_since = (bar_time - last_exit_time).total_seconds()
                if secs_since < COOLDOWN_SEC:
                    continue

            candle_dir = "up" if bar["close"] > bar["open"] else "down"
            fade_dir = "short" if candle_dir == "up" else "long"
            entry_px = float(bar["close"])
            entry_t = bar_time + pd.Timedelta(minutes=1)

            exit_px, reason, exit_time = find_exit_tick(
                tick_times, tick_prices, entry_t, fade_dir, entry_px, max_hold_min
            )

            if fade_dir == "long":
                pnl_pts = exit_px - entry_px
            else:
                pnl_pts = entry_px - exit_px

            pnl_usd = pnl_pts * DOLLAR_PER_PT
            daily_pnl += pnl_usd
            daily_trades += 1
            hold_sec = (exit_time - entry_t).total_seconds() if exit_time is not None else 0

            all_trades.append({
                "date": str(date),
                "time": bar_time.strftime("%H:%M"),
                "direction": fade_dir,
                "entry_px": round(entry_px, 2),
                "exit_px": round(exit_px, 2),
                "pnl_pts": round(pnl_pts, 2),
                "pnl_usd": round(pnl_usd, 2),
                "exit_reason": reason,
                "hold_sec": round(hold_sec, 0),
                "body_pts": round(body, 2),
            })

            last_exit_time = exit_time

            if daily_pnl <= MAX_DAILY_LOSS:
                halted = True

        daily_summaries.append({
            "date": str(date),
            "trades": daily_trades,
            "pnl": round(daily_pnl, 2),
            "halted": halted,
        })

    return all_trades, daily_summaries


def summarize(label, trades, daily_summaries):
    if not trades:
        print(f"\n{label}: No trades")
        return None

    arr = np.array([t["pnl_usd"] for t in trades])
    n = len(arr)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    wr = 100 * len(wins) / n
    total_pnl = arr.sum()
    avg_trade = arr.mean()
    avg_w = wins.mean() if len(wins) else 0
    avg_l = losses.mean() if len(losses) else 0
    gw = wins.sum() if len(wins) else 0
    gl = abs(losses.sum()) if len(losses) else 1
    pf = gw / gl if gl > 0 else float("inf")

    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    mdd = dd.max()

    exits = {}
    for t in trades:
        exits[t["exit_reason"]] = exits.get(t["exit_reason"], 0) + 1

    daily_pnls = np.array([d["pnl"] for d in daily_summaries])
    pos_days = np.sum(daily_pnls > 0)
    neg_days = np.sum(daily_pnls < 0)
    trading_days = np.sum(daily_pnls != 0)
    pct_pos = 100 * pos_days / trading_days if trading_days > 0 else 0

    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"  Params: 20pt body | SL=25 | Floor=7 | Trail=3 | Cooldown={COOLDOWN_SEC}s")
    print(f"{'='*80}")
    print(f"  Total Trades:      {n}")
    print(f"  Win Rate:          {wr:.1f}%")
    print(f"  Profit Factor:     {pf:.2f}")
    print(f"  Total PnL:         ${total_pnl:+,.0f}")
    print(f"  Avg Trade:         ${avg_trade:+.2f}")
    print(f"  Avg Win:           ${avg_w:+.2f}")
    print(f"  Avg Loss:          ${avg_l:+.2f}")
    print(f"  Max Drawdown:      ${mdd:,.0f}")
    print(f"  Exit Reasons:      {' | '.join(f'{k}={v}' for k, v in sorted(exits.items()))}")
    print(f"  Positive Days:     {pos_days}/{trading_days} ({pct_pos:.0f}%)")

    return {
        "label": label,
        "trades": n,
        "wr": wr,
        "pf": pf,
        "total_pnl": total_pnl,
        "avg_trade": avg_trade,
        "mdd": mdd,
    }


def main():
    sessions = load_all_sessions()
    results = []

    for max_hold_min in MAX_HOLD_MINUTES:
        trades, daily = run_backtest(sessions, max_hold_min)
        label = f"MaxHold={max_hold_min}min"
        res = summarize(label, trades, daily)
        if res:
            results.append(res)
        if trades:
            out_csv = DATA_DIR.parent / f"fade_max_hold_{max_hold_min}min_trades.csv"
            pd.DataFrame(trades).to_csv(out_csv, index=False)
            print(f"  Trade log saved: {out_csv}")

    if len(results) > 1:
        print(f"\n{'='*80}")
        print("  COMPARISON")
        print(f"{'='*80}")
        print(f"  {'Max Hold':<10} {'Trades':>8} {'Win%':>8} {'PF':>8} {'Total PnL':>12} {'Avg Trade':>10} {'MDD':>10}")
        for r in results:
            print(f"  {r['label']:<10} {r['trades']:>8} {r['wr']:>7.1f}% {r['pf']:>8.2f} ${r['total_pnl']:>+10,.0f} ${r['avg_trade']:>+9.2f} ${r['mdd']:>9,.0f}")
        print(f"{'='*80}")


if __name__ == "__main__":
    main()
