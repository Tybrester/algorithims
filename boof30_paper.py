"""
BOOF 30 — Morning Spike Paper Trading Bot (Alpaca Paper)
Morning spike detection on high RVOL | TP=+0.40% | SL=-0.20%

Setup:
  pip install alpaca-py pandas numpy pytz requests
  python boof30_paper.py          # run full day (waits for market)
  python boof30_paper.py scan     # force scan now
  python boof30_paper.py summary  # print today's results
"""

import os, time, datetime, csv, logging, importlib.util
import pandas as pd
import numpy as np
import pytz
import requests as _requests

# ── KEYS ──────────────────────────────────────────────────────────────
PAPER_KEY    = os.environ.get("ALPACA_PAPER_KEY",    "PKAJ7LELQVQMPJPEJTGZDRT3XP")
PAPER_SECRET = os.environ.get("ALPACA_PAPER_SECRET", "53BHpMNadsdZ6gUx4DmU7wHD7eGu1SNwnHKPqFHhqwhZ")
BASE_URL     = "https://paper-api.alpaca.markets"

SUPABASE_URL     = "https://isanhutzyctcjygjhzbn.supabase.co"
SUPABASE_KEY     = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"
SUPABASE_USER_ID = "d0bb84ba-f968-446c-9792-9bcff8849e37"
BOT_ID           = "63b10810-676a-4c0c-b0bd-d9f09af1a849"  # UPDATE THIS for boof30

# ── CONFIG ────────────────────────────────────────────────────────────
TP_PCT       = 0.004    # +0.40%
SL_PCT       = 0.002    # -0.20%
MIN_RVOL     = 2.0      # volume spike requirement
MIN_MOVE     = 0.0015   # 0.15% candle move
CONFIRM_BARS = 5        # wait 5 min confirmation

MAX_OPEN_POSITIONS = 2
BUYING_POWER_FRACTION = 0.50

SYMBOLS = [
    "NVDA", "TSLA", "META", "AVGO", "AMZN",
    "MSFT", "AAPL", "GOOGL", "AMD", "COIN"
]

ET = pytz.timezone("America/New_York")

SCAN_START = datetime.time(9, 35)
SCAN_END   = datetime.time(11, 0)
FORCE_CLOSE = datetime.time(15, 55)

# ── SUPABASE TRADE LOGGING ────────────────────────────────────────────
_EDGE_URL     = f"{SUPABASE_URL}/functions/v1/boof23-log-trade"
_EDGE_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

def sb_insert_trade(symbol, entry_px, shares, order_id, direction):
    """Log open to Supabase via edge function."""
    try:
        r = _requests.post(_EDGE_URL, headers=_EDGE_HEADERS, timeout=10, json={
            "action":    "open",
            "user_id":   SUPABASE_USER_ID,
            "bot_id":    BOT_ID,
            "symbol":    symbol,
            "entry_px":  entry_px,
            "shares":    shares,
            "order_id":  order_id,
            "direction": direction,
        })
        if r.status_code == 200:
            return r.json().get("trade_id")
        else:
            log.warning(f"[Supabase] Insert failed {symbol}: {r.text}")
            return None
    except Exception as e:
        log.error(f"[Supabase] Error {symbol}: {e}")
        return None

# ── LOGGING ───────────────────────────────────────────────────────────
LOG_DIR  = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(LOG_DIR, "boof30_paper.csv")

csv_headers = ["date","symbol","direction","entry_px","exit_px",
               "shares","pnl_pct","pnl_usd","exit_type","status"]
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", newline="") as f:
        csv.writer(f).writerow(csv_headers)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger("boof30")

# ── CSV HELPERS ───────────────────────────────────────────────────────
def log_exit(date, sym, direction, entry_px, exit_px, shares, pnl_pct, pnl_usd, exit_type):
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([date, sym, direction,
            f"{entry_px:.4f}", f"{exit_px:.4f}", shares,
            f"{pnl_pct:.3f}", f"{pnl_usd:.2f}", exit_type, "closed"])
    log.info(f"  {sym:>6} {direction:<5}  entry={entry_px:.2f}  exit={exit_px:.2f}  "
             f"shares={shares}  pnl={pnl_pct:+.2f}%  ${pnl_usd:+.2f}  [{exit_type}]")

def print_summary():
    df = pd.read_csv(LOG_FILE)
    if df.empty:
        print("No trades logged.")
        return
    df['date'] = pd.to_datetime(df['date'])
    today = datetime.datetime.now(ET).strftime('%Y-%m-%d')
    day = df[df['date'].dt.strftime('%Y-%m-%d') == today]
    if day.empty:
        print(f"No trades for {today}.")
        return
    wins = day[day['pnl_usd'] > 0]
    loss = day[day['pnl_usd'] <= 0]
    print(f"\n{'='*60}")
    print(f"BOOF 30 SUMMARY — {today}")
    print(f"{'='*60}")
    print(f"Trades: {len(day)} | Wins: {len(wins)} | Losses: {len(loss)}")
    print(f"P&L: ${day['pnl_usd'].sum():+.2f}  (avg ${day['pnl_usd'].mean():+.2f}/trade)")
    print(f"{'='*60}\n")

# ── ALPACA CLIENT ─────────────────────────────────────────────────────
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    trade_client = TradingClient(PAPER_KEY, PAPER_SECRET, paper=True)
    data_client  = StockHistoricalDataClient(PAPER_KEY, PAPER_SECRET)
    account = trade_client.get_account()
    log.info(f"Connected — Boof 30 Paper  |  "
             f"Cash: ${float(account.cash):,.2f}  "
             f"Equity: ${float(account.equity):,.2f}  "
             f"BP: ${float(account.buying_power):,.2f}")
except Exception as e:
    log.error(f"Alpaca connection failed: {e}")
    raise

# ── UTILS ─────────────────────────────────────────────────────────────
def now_et():
    return datetime.datetime.now(ET)


def wait_until_et(hour, minute, label):
    while True:
        n = now_et()
        target = n.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if n >= target:
            return
        secs = (target - n).total_seconds()
        log.info(f"Waiting for {label} ({hour:02d}:{minute:02d} ET) — {secs/60:.1f} min remaining...")
        time.sleep(min(60, secs))


def get_bars(symbol, limit=60):
    end = now_et()
    start = end - pd.Timedelta(minutes=limit + 10)

    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
    )

    bars = data_client.get_stock_bars(req).df

    if bars.empty:
        return pd.DataFrame()

    if isinstance(bars.index, pd.MultiIndex):
        bars = bars.xs(symbol)

    return bars.tail(limit)


def get_open_positions():
    return {p.symbol: p for p in trade_client.get_all_positions()}


def has_open_position(symbol):
    return symbol in get_open_positions()


def get_buying_power():
    account = trade_client.get_account()
    return float(account.buying_power)


def calc_shares(price):
    buying_power = get_buying_power()
    position_value = buying_power * BUYING_POWER_FRACTION
    shares = int(position_value / price)
    return max(shares, 0)


# ── SIGNAL DETECTION ──────────────────────────────────────────────────
def detect_morning_spike(symbol):
    bars = get_bars(symbol, 60)

    if len(bars) < 25:
        return None

    recent = bars.iloc[-1]
    prev = bars.iloc[-2]

    avg_volume = bars["volume"].iloc[-21:-1].mean()
    rvol = recent["volume"] / avg_volume if avg_volume > 0 else 0

    candle_move = (recent["close"] - recent["open"]) / recent["open"]

    if rvol < MIN_RVOL:
        return None

    if abs(candle_move) < MIN_MOVE:
        return None

    # Direction confirmation over last 5 bars
    confirm = bars.tail(CONFIRM_BARS)
    start_price = confirm["open"].iloc[0]
    end_price = confirm["close"].iloc[-1]
    confirm_move = (end_price - start_price) / start_price

    if candle_move > 0 and confirm_move > 0:
        return "long"

    if candle_move < 0 and confirm_move < 0:
        return "short"

    return None


# ── ORDER EXECUTION ───────────────────────────────────────────────────
def submit_entry(symbol, direction):
    bars = get_bars(symbol, 5)
    if bars.empty:
        return

    price = float(bars["close"].iloc[-1])
    shares = calc_shares(price)

    if shares <= 0:
        log.warning(f"{symbol}: no shares calculated")
        return

    side = OrderSide.BUY if direction == "long" else OrderSide.SELL

    try:
        order_req = MarketOrderRequest(
            symbol=symbol,
            qty=shares,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        order = trade_client.submit_order(order_req)
        sb_id = sb_insert_trade(symbol, price, shares, str(order.id), direction)
        log.info(f"ENTRY {symbol} {direction.upper()} {shares} shares @ {price:.2f}  id={order.id}")
    except Exception as e:
        log.error(f"Order failed {symbol}: {e}")


# ── TP/SL MANAGEMENT ──────────────────────────────────────────────────
def manage_exits():
    positions = trade_client.get_all_positions()
    now = now_et()

    for pos in positions:
        symbol = pos.symbol
        qty = abs(float(pos.qty))
        entry = float(pos.avg_entry_price)
        current = float(pos.current_price)
        side = "long" if float(pos.qty) > 0 else "short"

        if side == "long":
            pnl_pct = (current - entry) / entry
        else:
            pnl_pct = (entry - current) / entry

        should_exit = False
        exit_type = None

        if pnl_pct >= TP_PCT:
            log.info(f"TP HIT {symbol}: {pnl_pct:.3%}")
            should_exit = True
            exit_type = "tp"

        elif pnl_pct <= -SL_PCT:
            log.info(f"SL HIT {symbol}: {pnl_pct:.3%}")
            should_exit = True
            exit_type = "sl"

        elif now.time() >= FORCE_CLOSE:
            log.info(f"EOD CLOSE {symbol}: {pnl_pct:.3%}")
            should_exit = True
            exit_type = "eod"

        if should_exit:
            try:
                trade_client.close_position(symbol)
                pnl_usd = (current - entry) * qty if side == "long" else (entry - current) * qty
                log_exit(now.strftime('%Y-%m-%d'), symbol, side, entry, current, int(qty), pnl_pct, pnl_usd, exit_type)
            except Exception as e:
                log.error(f"Exit failed {symbol}: {e}")


# ── MAIN LOOP ─────────────────────────────────────────────────────────
def main():
    log.info("="*60)
    log.info("BOOF 30 Morning Spike Bot Starting...")
    log.info(f"TP={TP_PCT*100:.2f}%  SL={SL_PCT*100:.2f}%  MinRVOL={MIN_RVOL}")
    log.info(f"Symbols: {SYMBOLS}")
    log.info("="*60)

    # Wait for market open
    wait_until_et(9, 30, "MARKET OPEN")

    log.info("Active trading loop (9:35 -> 11:00 ET scan window)...")
    last_heartbeat_min = -1

    while True:
        current_time = now_et()
        current_time_only = current_time.time()

        # Manage exits continuously
        manage_exits()

        # Heartbeat
        if current_time.minute != last_heartbeat_min:
            log.info(f"[Heartbeat] Boof 30 Alive — {current_time.strftime('%Y-%m-%d %H:%M')} ET")
            last_heartbeat_min = current_time.minute

        # Scan window
        if SCAN_START <= current_time_only <= SCAN_END:
            open_positions = get_open_positions()

            if len(open_positions) < MAX_OPEN_POSITIONS:
                for symbol in SYMBOLS:
                    if len(get_open_positions()) >= MAX_OPEN_POSITIONS:
                        break

                    if has_open_position(symbol):
                        continue

                    signal = detect_morning_spike(symbol)

                    if signal:
                        submit_entry(symbol, signal)

        # End of day
        if current_time_only >= FORCE_CLOSE:
            log.info("Force close time reached. Exiting loop.")
            break

        time.sleep(60)

    # Final close all and summary
    manage_exits()
    print_summary()
    log.info("Day complete.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        # Force scan now
        for sym in SYMBOLS:
            sig = detect_morning_spike(sym)
            if sig:
                log.info(f"{sym}: {sig.upper()} spike detected")
            else:
                log.info(f"{sym}: no spike")
    elif len(sys.argv) > 1 and sys.argv[1] == "summary":
        print_summary()
    else:
        main()
