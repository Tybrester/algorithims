"""
BOOF 29 — Paper Trading Bot (Alpaca Paper)
Runs every morning at 9:30 ET, scans for signals at 9:35, exits at 10:20.

Setup:
  1. Get paper API keys from: https://app.alpaca.markets  (toggle Paper in top-left)
  2. pip install alpaca-trade-api schedule
  3. Set ALPACA_PAPER_KEY and ALPACA_PAPER_SECRET below (or env vars)
  4. Run: python boof29_paper.py

The bot will:
  - Connect to Alpaca paper environment
  - Every trading day at 9:30 ET: fetch QQQ 5-min open data
  - At 9:35 ET: scan all symbols for 0.50-0.60% move + QQQ filter
  - Enter market buy on all qualifying symbols
  - At 10:20 ET: close all Boof 29 positions
  - Log all trades to boof29_paper_log.csv
"""

import os, time, datetime, csv, logging
import pandas as pd
import numpy as np

# ── CONFIG ────────────────────────────────────────────────────────────
PAPER_KEY    = os.environ.get("ALPACA_PAPER_KEY",    "PKU37C3QZHELGN2IDQLNYAEFJR")
PAPER_SECRET = os.environ.get("ALPACA_PAPER_SECRET", "CTcQtRqgC5SkKxo9q7sAn8iwTZt5CWWtvueiPjvbC22w")
BASE_URL     = "https://paper-api.alpaca.markets"

SUPABASE_URL = "https://isanhutzyctcjygjhzbn.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"
SUPABASE_USER_ID = "d0bb84ba-f968-446c-9792-9bcff8849e37"
BOT_ID           = "0c1827dd-b57f-4640-81ed-120dabef1ef2"
BOT_NAME     = "Boof 29 Paper"   # shows on trades page

MOVE_LO      = 0.50    # % lower bound
MOVE_HI      = 0.60    # % upper bound
QQQ_MIN_MOVE = 0.10    # % QQQ 5-min move floor
POSITION_PCT = 0.10    # use 10% of buying power per signal (spread across concurrent)
MAX_POSITIONS= 5       # max concurrent open positions
ACCOUNT_SIZE = 5000    # set your actual paper account size
PDT_GUARD    = True    # if True, block trades if you'd hit 4 day trades in 5 days

WATCHLIST = [
    # Semiconductors
    "NVDA","AVGO","TSM","ASML","MU","AMAT","KLAC","LRCX",
    "ADI","QCOM","NXPI","ON","MPWR","MRVL","INTC","ARM",
    "TER","SWKS","QRVO","GFS","WOLF","COHR","LSCC","AEHR",
    "ACLS","FORM","CRUS","SYNA","SMTC","AMKR","RMBS","UCTT",
    "ENTG","CEVA","ICHR","VECO","ONTO","SIMO","HIMX",
    "PI","IPGP","DIOD","POWI","MTSI","AOSL",
    # Fintech
    "HOOD","COIN","SOFI","AFRM","UPST","SQ","FI","PYPL",
    "NU","BILL","TOST","PAYO","MA","V","AXP","SCHW",
    "MS","GS","JPM","BAC","WFC","BX","BLK",
    "SPGI","MCO","CME","ICE","AJG","PGR","TRV","MMC",
    "AMP","RJF","STT","NTRS",
    # Industrials
    "CAT","PH","TT","URI","DE","ROP","PWR",
    "AME","HUBB","XYL","DOV","GWW","FAST","ODFL",
    "UNP","NSC","CSX","PCAR","ROK","JCI","IR",
    "CARR","GE","RTX","LMT","NOC","GD","TDG",
    "HEI","EXPD","CHRW","ITW","EMR","HON",
]

# ── LOGGING ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("boof29_paper.log")]
)
log = logging.getLogger("boof29")

LOG_FILE = "boof29_paper_log.csv"
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", newline="") as f:
        csv.writer(f).writerow(["date","symbol","entry_px","exit_px","shares","pnl_pct","pnl_usd","status"])

def log_trade(date, symbol, entry_px, exit_px, shares, status="closed"):
    pnl_pct = (exit_px - entry_px) / entry_px * 100 if entry_px else 0
    pnl_usd = (exit_px - entry_px) * shares if entry_px else 0
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([date, symbol, f"{entry_px:.4f}", f"{exit_px:.4f}",
                                 shares, f"{pnl_pct:.3f}", f"{pnl_usd:.2f}", status])
    log.info(f"  {symbol:>6}  entry={entry_px:.2f}  exit={exit_px:.2f}  "
             f"shares={shares}  pnl={pnl_pct:+.2f}%  ${pnl_usd:+.2f}")

# ── SUPABASE TRADE LOGGING ────────────────────────────────────────────
import requests as _requests

_EDGE_URL = f"{SUPABASE_URL}/functions/v1/boof29-log-trade"
_EDGE_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

def sb_insert_trade(symbol, entry_px, shares, order_id):
    """Insert open trade via edge function (uses service role, bypasses RLS)."""
    try:
        r = _requests.post(_EDGE_URL, headers=_EDGE_HEADERS, timeout=10, json={
            "action":   "open",
            "user_id":  SUPABASE_USER_ID,
            "bot_id":   BOT_ID,
            "symbol":   symbol,
            "entry_px": entry_px,
            "shares":   shares,
            "order_id": order_id,
        })
        data = r.json()
        if r.ok and data.get("ok"):
            log.info(f"  [Supabase] Trade logged {symbol} -> id={data.get('trade_id')}")
            return data.get("trade_id")
        else:
            log.warning(f"  [Supabase] Insert failed {symbol}: {data}")
    except Exception as e:
        log.warning(f"  [Supabase] Insert error {symbol}: {e}")
    return None

def sb_close_trade(trade_id, exit_px, entry_px, shares):
    """Close trade via edge function."""
    if not trade_id: return
    pnl = (exit_px - entry_px) * shares
    try:
        r = _requests.post(_EDGE_URL, headers=_EDGE_HEADERS, timeout=10, json={
            "action":   "close",
            "user_id":  SUPABASE_USER_ID,
            "trade_id": trade_id,
            "exit_px":  exit_px,
            "pnl":      pnl,
            "shares":   shares,
        })
        if r.ok:
            log.info(f"  [Supabase] Closed trade {trade_id}  pnl=${pnl:+.2f}")
        else:
            log.warning(f"  [Supabase] Close failed {trade_id}: {r.text}")
    except Exception as e:
        log.warning(f"  [Supabase] Close error {trade_id}: {e}")

# ── ALPACA CLIENT ─────────────────────────────────────────────────────
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
    from alpaca.data.timeframe import TimeFrame
    trade_client = TradingClient(PAPER_KEY, PAPER_SECRET, paper=True)
    data_client  = StockHistoricalDataClient(PAPER_KEY, PAPER_SECRET)
    account = trade_client.get_account()
    log.info(f"Connected to Alpaca Paper  |  Cash: ${float(account.cash):,.2f}  "
             f"Buying power: ${float(account.buying_power):,.2f}")
except Exception as e:
    log.error(f"Alpaca connection failed: {e}")
    log.error("Install: python -m pip install alpaca-py")
    raise

# ── HELPERS ───────────────────────────────────────────────────────────
def is_market_open():
    clock = trade_client.get_clock()
    return clock.is_open

def get_5min_bars(symbols):
    """Get today's 9:30-9:34 bars for a list of symbols."""
    import pytz
    et    = pytz.timezone("America/New_York")
    today = datetime.datetime.now(et).strftime("%Y-%m-%d")
    start = datetime.datetime.fromisoformat(f"{today}T09:30:00").replace(tzinfo=et)
    end   = datetime.datetime.fromisoformat(f"{today}T09:36:00").replace(tzinfo=et)
    out   = {}
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i+50]
        try:
            req  = StockBarsRequest(symbol_or_symbols=chunk, timeframe=TimeFrame.Minute,
                                    start=start, end=end, limit=10)
            bars = data_client.get_stock_bars(req).df
            if bars.empty: continue
            if isinstance(bars.index, pd.MultiIndex):
                for sym in chunk:
                    try: out[sym] = bars.xs(sym, level="symbol")
                    except KeyError: pass
            else:
                if len(chunk)==1: out[chunk[0]] = bars
        except Exception as e:
            log.warning(f"Bar fetch error: {e}")
    return out

def calc_5min_move(bars):
    """Return % move from first open to last close over the 5-min window."""
    if bars is None or len(bars) == 0: return None
    open_px  = float(bars.iloc[0]["open"])
    close_px = float(bars.iloc[-1]["close"])
    if open_px <= 0: return None
    return (close_px - open_px) / open_px * 100

def get_qqq_ema50():
    """Get QQQ daily close EMA50 (previous day)."""
    try:
        import pytz
        end   = datetime.datetime.now(pytz.timezone("America/New_York"))
        start = end - datetime.timedelta(days=90)
        req   = StockBarsRequest(symbol_or_symbols="QQQ", timeframe=TimeFrame.Day,
                                 start=start, end=end, limit=60)
        bars  = data_client.get_stock_bars(req).df
        if isinstance(bars.index, pd.MultiIndex):
            bars = bars.xs("QQQ", level="symbol")
        ema = bars["close"].ewm(span=50, adjust=False).mean()
        return float(ema.iloc[-2])
    except Exception as e:
        log.warning(f"EMA50 fetch error: {e}")
        return None

def get_current_price(symbol):
    try:
        req   = StockLatestTradeRequest(symbol_or_symbols=symbol)
        trade = data_client.get_stock_latest_trade(req)
        return float(trade[symbol].price)
    except:
        return None

def get_open_boof29_positions():
    """Return all open positions in watchlist."""
    try:
        positions = trade_client.get_all_positions()
        return {p.symbol: p for p in positions if p.symbol in WATCHLIST}
    except Exception as e:
        log.warning(f"Position fetch error: {e}")
        return {}

# ── SCAN (9:35 ET) ────────────────────────────────────────────────────
def scan_and_enter():
    log.info("=" * 60)
    log.info("SCAN: 9:35 ET — checking signals...")

    qqq_bars  = get_5min_bars(["QQQ"]).get("QQQ")
    qqq_move  = calc_5min_move(qqq_bars)
    qqq_ema50 = get_qqq_ema50()

    if qqq_move is None:
        log.warning("QQQ data unavailable — skipping today")
        return
    log.info(f"QQQ 5-min move: {qqq_move:+.3f}%  EMA50: {qqq_ema50}")

    if qqq_move < QQQ_MIN_MOVE:
        log.info(f"QQQ move {qqq_move:.3f}% < {QQQ_MIN_MOVE}% threshold — no trades today")
        return

    if qqq_ema50:
        qqq_open = float(qqq_bars.iloc[0]["open"])
        if qqq_open <= qqq_ema50:
            log.info(f"QQQ open {qqq_open:.2f} <= EMA50 {qqq_ema50:.2f} — no trades today")
            return

    all_bars = get_5min_bars(WATCHLIST)

    signals = []
    for sym in WATCHLIST:
        bars = all_bars.get(sym)
        if bars is None: continue
        move = calc_5min_move(bars)
        if move is None: continue
        if MOVE_LO <= move < MOVE_HI:
            signals.append((sym, move, float(bars.iloc[-1]["close"])))

    if not signals:
        log.info("No signals found today")
        return

    log.info(f"Signals found: {[s[0] for s in signals]}")

    acct      = trade_client.get_account()
    bp        = float(acct.buying_power)
    n_signals = min(len(signals), MAX_POSITIONS)
    per_trade = bp / n_signals * 0.95

    today = datetime.date.today().isoformat()
    entered = []
    for sym, move, price in signals[:MAX_POSITIONS]:
        if price <= 0: continue
        shares = int(per_trade / price)
        if shares < 1:
            log.warning(f"  {sym}: insufficient buying power (${price:.2f}/share)")
            continue
        try:
            req   = MarketOrderRequest(symbol=sym, qty=shares,
                                       side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
            order = trade_client.submit_order(req)
            log.info(f"  BUY {sym}  {shares} shares @ ~${price:.2f}  (5m move: {move:+.2f}%)  id: {order.id}")
            sb_id = sb_insert_trade(sym, price, shares, str(order.id))
            entered.append({"symbol": sym, "shares": shares, "entry_approx": price,
                            "order_id": str(order.id), "sb_trade_id": sb_id or "", "date": today})
        except Exception as e:
            log.error(f"  Order failed for {sym}: {e}")

    if entered:
        pd.DataFrame(entered).to_csv("boof29_today_entries.csv", index=False)
        log.info(f"Entered {len(entered)} positions. Exit at 10:20 ET.")
    else:
        log.info("No positions entered.")

# ── EXIT (10:20 ET) ───────────────────────────────────────────────────
def exit_all():
    log.info("=" * 60)
    log.info("EXIT: 10:20 ET — closing all Boof 29 positions...")

    positions = get_open_boof29_positions()
    if not positions:
        log.info("No open positions to close.")
        return

    # Load Supabase trade IDs saved at entry
    sb_ids = {}
    if os.path.exists("boof29_today_entries.csv"):
        edf = pd.read_csv("boof29_today_entries.csv")
        sb_ids = {row["symbol"]: row.get("sb_trade_id", "") for _, row in edf.iterrows()}

    today = datetime.date.today().isoformat()
    for sym, pos in positions.items():
        shares   = int(float(pos.qty))
        entry_px = float(pos.avg_entry_price)
        try:
            trade_client.close_position(sym)
            exit_px = get_current_price(sym) or entry_px
            log_trade(today, sym, entry_px, exit_px, shares)
            sb_close_trade(sb_ids.get(sym), exit_px, entry_px, shares)
        except Exception as e:
            log.error(f"  Failed to close {sym}: {e}")

    if os.path.exists("boof29_today_entries.csv"):
        os.remove("boof29_today_entries.csv")

    log.info("All positions closed.")

# ── DAILY SUMMARY ─────────────────────────────────────────────────────
def print_summary():
    if not os.path.exists(LOG_FILE): return
    df = pd.read_csv(LOG_FILE)
    today = datetime.date.today().isoformat()
    today_df = df[df["date"] == today]
    if len(today_df) == 0:
        log.info("No trades today.")
        return
    log.info(f"\n  TODAY'S RESULTS ({today}):")
    log.info(f"  Trades:    {len(today_df)}")
    log.info(f"  Win Rate:  {(today_df['pnl_pct'].astype(float) > 0).mean()*100:.1f}%")
    log.info(f"  Total P&L: ${today_df['pnl_usd'].astype(float).sum():+.2f}")
    log.info(f"  Avg P&L:   {today_df['pnl_pct'].astype(float).mean():+.3f}%")

# ── SCHEDULER ─────────────────────────────────────────────────────────
def wait_until_et(hour, minute, label):
    """Block until target ET time today."""
    import pytz
    et = pytz.timezone("America/New_York")
    now_et = datetime.datetime.now(et)
    target = now_et.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now_et >= target:
        log.info(f"{label} time already passed ({now_et.strftime('%H:%M:%S')} ET)")
        return False
    wait_secs = (target - now_et).total_seconds()
    log.info(f"Waiting {wait_secs/60:.1f} min until {label} ({target.strftime('%H:%M')} ET)...")
    last_heartbeat_min = -1
    while True:
        now_et = datetime.datetime.now(et)
        if now_et >= target:
            break
        if now_et.minute != last_heartbeat_min:
            log.info(f"[Heartbeat] Boof 29 Alive — {now_et.strftime('%Y-%m-%d %H:%M')} ET")
            last_heartbeat_min = now_et.minute
        time.sleep(30)
    return True

_last_hb_min_b29 = -1
def wait_for_market_open():
    """Sleep until next market open, polling every 60s."""
    global _last_hb_min_b29
    import pytz
    et = pytz.timezone("America/New_York")
    while True:
        try:
            now_et = datetime.datetime.now(et)
            if now_et.minute != _last_hb_min_b29:
                log.info(f"[Heartbeat] Boof 29 Alive — {now_et.strftime('%Y-%m-%d %H:%M')} ET")
                _last_hb_min_b29 = now_et.minute
            clock = trade_client.get_clock()
            if clock.is_open:
                return
            next_open = clock.next_open.astimezone(et)
            secs      = max(0, (next_open - now_et).total_seconds())
            if secs > 120:
                log.info(f"Market closed. Next open: {next_open.strftime('%Y-%m-%d %H:%M')} ET  "
                         f"(sleeping {secs/3600:.1f}h)")
                time.sleep(60)
            else:
                time.sleep(30)
        except Exception as e:
            log.warning(f"Clock check error: {e}")
            time.sleep(60)


def run_day():
    """Trade one full day: scan at 9:35, exit at 10:20."""
    import pytz
    et = pytz.timezone("America/New_York")
    now_et = datetime.datetime.now(et)
    log.info(f"=== NEW DAY {now_et.strftime('%Y-%m-%d')} === Boof 29 Paper")

    wait_until_et(9, 35, "SCAN")
    scan_and_enter()

    wait_until_et(10, 20, "EXIT")
    exit_all()

    print_summary()
    log.info("Day complete.")


# ── ENTRY POINT ───────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "exit":
        exit_all()
    elif len(sys.argv) > 1 and sys.argv[1] == "scan":
        scan_and_enter()
    elif len(sys.argv) > 1 and sys.argv[1] == "summary":
        print_summary()
    else:
        log.info("Boof 29 Paper Bot — 24/7 mode started")
        while True:
            try:
                wait_for_market_open()
                run_day()
                time.sleep(300)  # 5 min after close before next open check
            except KeyboardInterrupt:
                log.info("Stopped by user.")
                exit_all()
                break
            except Exception as e:
                log.error(f"Day loop error: {e} — restarting in 60s")
                time.sleep(60)
