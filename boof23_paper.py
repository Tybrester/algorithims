"""
BOOF 23 — Paper Trading Bot (Alpaca Paper)
5-min signal + 1-min execution | TP=+0.50% | SL=-0.25% | 1% account risk/trade
Strict 4-rule mode: cross filter, one trade per pivot, cooldown, lockout

Setup:
  pip install alpaca-py pandas numpy pytz requests
  python boof23_paper.py          # run full day (waits for market)
  python boof23_paper.py scan     # force signal scan now
  python boof23_paper.py summary  # print today's results
"""

import os, time, datetime, csv, logging, importlib.util, threading
import pandas as pd
import numpy as np
import pytz
import requests as _requests
import alpaca_trade_api as tradeapi
from datetime import timedelta
from zoneinfo import ZoneInfo

# ── KEYS ──────────────────────────────────────────────────────────────
PAPER_KEY    = os.environ.get("ALPACA_PAPER_KEY",    "PK7N52NHGPS2GBVZU64BCUEDNO")
PAPER_SECRET = os.environ.get("ALPACA_PAPER_SECRET", "B3uwbzRDHZeDwt5riUd3G4U9oxnELTukfCKGovZx9K9E")
BASE_URL     = "https://paper-api.alpaca.markets"

SUPABASE_URL     = "https://isanhutzyctcjygjhzbn.supabase.co"
SUPABASE_KEY     = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"
SUPABASE_USER_ID = "d0bb84ba-f968-446c-9792-9bcff8849e37"
BOT_ID           = "63b10810-676a-4c0c-b0bd-d9f09af1a849"

# ── CONFIG ────────────────────────────────────────────────────────────
TP_PCT       = 0.005    # kept for signal logic only
SL_PCT       = 0.0025   # kept for signal logic only
RISK_PCT     = 0.01     # 1% of account per trade
MAX_POSITIONS= 3        # max concurrent open option positions
SIGNAL_TF    = "5Min"   # signal timeframe
EXEC_TF      = "1Min"   # execution timeframe
COOLDOWN_SEC = 50 * 60  # cooldown per symbol after exit

# ── OPTIONS CONFIG ────────────────────────────────────────────────────
OPTION_TARGET  = 3.50   # target option mid price
CONTRACTS      = 1
TP_MULT        = 1.30   # +30%
SL_MULT        = 0.85   # -15%
FILL_WAIT_S    = 7      # seconds between limit price bumps
MAX_LOSSES_SYM = 3      # stop symbol after N consecutive losses
MAX_DAILY_LOSS = 5      # stop bot after N daily losses

SYMS = [
    'TOST','HOOD','ORCL','MSFT','V','JPM','SOUN','PODD','ENTG','GE',
    'MRNA','AI','PATH','GS','BSX','SIMO','SCHW','TEM','AMD','ABNB',
    'NEM','GILD','MCHP','UNP','ETN','LRCX','SMTC','INCY','ITW','LLY',
    'MAR','QRVO','MPC','BKR','TMO','CAT','NVDA','SOFI','XOM','DPZ',
    'FCX','VRTX','S','CSCO','DE','HUM',
]

ET = pytz.timezone("America/New_York")

# ── SUPABASE TRADE LOGGING ────────────────────────────────────────────
_EDGE_URL     = f"{SUPABASE_URL}/functions/v1/boof23-log-trade"
_EDGE_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

def sb_insert_trade(symbol, entry_px, shares, order_id, direction="long"):
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
        data = r.json()
        if r.ok and data.get("ok"):
            log.info(f"  [Supabase] Trade logged {symbol} -> id={data.get('trade_id')}")
            return data.get("trade_id")
        else:
            log.warning(f"  [Supabase] Insert failed {symbol}: {data}")
    except Exception as e:
        log.warning(f"  [Supabase] Insert error {symbol}: {e}")
    return None

def sb_close_trade(trade_id, exit_px, entry_px, shares, direction="long"):
    if not trade_id: return
    pnl = (exit_px - entry_px) * shares if direction == "long" else (entry_px - exit_px) * shares
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

# ── LOAD SIGNAL ENGINE ────────────────────────────────────────────────
spec = importlib.util.spec_from_file_location("b23", "boof23_analysis.py")
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# ── LOGGING ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("boof23_paper.log")]
)
log = logging.getLogger("boof23")

LOG_FILE = "boof23_paper_log.csv"
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", newline="") as f:
        csv.writer(f).writerow([
            "date","symbol","direction","entry_px","exit_px",
            "shares","pnl_pct","pnl_usd","exit_type","status"
        ])

def log_trade(date, sym, direction, entry_px, exit_px, shares, exit_type="tp/sl"):
    pnl_pct = (exit_px - entry_px) / entry_px * 100 if direction == "long" else (entry_px - exit_px) / entry_px * 100
    pnl_usd = (exit_px - entry_px) * shares if direction == "long" else (entry_px - exit_px) * shares
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([date, sym, direction,
            f"{entry_px:.4f}", f"{exit_px:.4f}", shares,
            f"{pnl_pct:.3f}", f"{pnl_usd:.2f}", exit_type, "closed"])
    log.info(f"  {sym:>6} {direction:<5}  entry={entry_px:.2f}  exit={exit_px:.2f}  "
             f"shares={shares}  pnl={pnl_pct:+.2f}%  ${pnl_usd:+.2f}  [{exit_type}]")

# ── ALPACA CLIENTS ────────────────────────────────────────────────────
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest, StockLatestQuoteRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    trade_client = TradingClient(PAPER_KEY, PAPER_SECRET, paper=True)
    data_client  = StockHistoricalDataClient(PAPER_KEY, PAPER_SECRET)
    account = trade_client.get_account()
    log.info(f"Connected — Boof 23 Paper  |  "
             f"Cash: ${float(account.cash):,.2f}  "
             f"Equity: ${float(account.equity):,.2f}  "
             f"Buying power: ${float(account.buying_power):,.2f}")
except Exception as e:
    log.error(f"Alpaca connection failed: {e}")
    log.error("Install: pip install alpaca-py")
    raise

# alpaca_trade_api REST client for options (get_option_contracts, snapshots)
api = tradeapi.REST(PAPER_KEY, PAPER_SECRET, BASE_URL, api_version="v2")
TZ  = ZoneInfo("America/New_York")

# ── HELPERS ───────────────────────────────────────────────────────────
def is_market_open():
    return trade_client.get_clock().is_open

def get_account_equity():
    return float(trade_client.get_account().equity)

def get_bars(symbols, timeframe_str, bars=200):
    """Fetch recent bars for a list of symbols."""
    tf_map = {
        "1Min":  TimeFrame(1,  TimeFrameUnit.Minute),
        "5Min":  TimeFrame(5,  TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    }
    tf = tf_map.get(timeframe_str, TimeFrame(5, TimeFrameUnit.Minute))
    now   = datetime.datetime.now(ET)
    start = now - datetime.timedelta(days=2)
    out   = {}
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i+50]
        try:
            req  = StockBarsRequest(symbol_or_symbols=chunk, timeframe=tf,
                                    start=start, end=now)
            resp = data_client.get_stock_bars(req).df
            if resp.empty: continue
            resp = resp.reset_index()
            if "symbol" in resp.columns:
                for sym in chunk:
                    sym_df = resp[resp["symbol"] == sym].copy().reset_index(drop=True)
                    if sym_df.empty: continue
                    sym_df = sym_df.rename(columns={"timestamp": "time"})
                    sym_df["time"] = pd.to_datetime(sym_df["time"]).dt.tz_convert(ET)
                    out[sym] = sym_df
            else:
                if len(chunk) == 1:
                    resp = resp.rename(columns={"timestamp": "time"})
                    resp["time"] = pd.to_datetime(resp["time"]).dt.tz_convert(ET)
                    out[chunk[0]] = resp
                else:
                    log.warning(f"Bar fetch: no symbol column in response for chunk {chunk[:3]}")
        except Exception as e:
            log.warning(f"Bar fetch error ({chunk[:3]}...): {e}")
    return out

def get_latest_price(symbol):
    try:
        req   = StockLatestTradeRequest(symbol_or_symbols=symbol)
        trade = data_client.get_stock_latest_trade(req)
        return float(trade[symbol].price)
    except:
        return None


def get_spread_pct(symbol):
    """Get bid-ask spread as percentage of mid price."""
    try:
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quote = data_client.get_stock_latest_quote(req)
        bid = float(quote[symbol].bid_price)
        ask = float(quote[symbol].ask_price)
        if bid <= 0 or ask <= 0:
            return 0
        mid = (bid + ask) / 2
        spread = (ask - bid) / mid
        return spread
    except:
        return 0

# ── STATE ─────────────────────────────────────────────────────────────
open_positions  = {}   # sym -> {opt_sym, entry, tp, sl, direction, opened_at}
cooldown_until  = {}   # sym -> datetime
used_pivots     = set()
_lock           = threading.Lock()
daily_losses    = 0
bot_stopped     = False
consec_loss     = {}   # sym -> int

# ── 1DTE OPTION HELPERS ────────────────────────────────────────────────
def get_1dte_expiry():
    now = datetime.datetime.now(TZ)
    exp = now + timedelta(days=1)
    while exp.weekday() >= 5:
        exp += timedelta(days=1)
    return exp.strftime("%Y-%m-%d")

def select_option(sym, side, underlying_price):
    opt_type = "call" if side == "long" else "put"
    expiry   = get_1dte_expiry()
    try:
        chain = api.get_option_contracts(
            underlying_symbol=sym,
            expiration_date=expiry,
            option_type=opt_type,
            limit=50,
        )
        best = None; best_diff = float("inf")
        for contract in chain:
            snap = api.get_option_snapshot(contract.symbol)
            if not snap: continue
            bid = snap.latest_quote.bid_price
            ask = snap.latest_quote.ask_price
            if bid is None or ask is None or bid <= 0: continue
            mid  = (bid + ask) / 2
            diff = abs(mid - OPTION_TARGET)
            if diff < best_diff:
                best_diff = diff
                best = {"symbol": contract.symbol, "bid": bid, "ask": ask, "mid": mid}
        return best
    except Exception as e:
        log.error(f"Option chain error {sym}: {e}")
        return None

def place_option_entry(sym, direction, underlying_price):
    global daily_losses, bot_stopped
    if bot_stopped:
        log.warning("Bot stopped — skipping"); return
    with _lock:
        if len(open_positions) >= MAX_POSITIONS:
            log.info(f"Max positions — skipping {sym}"); return
        if sym in open_positions:
            log.info(f"{sym} already open — skipping"); return

    contract = select_option(sym, direction, underlying_price)
    if not contract:
        log.warning(f"No suitable option for {sym} {direction}"); return

    opt_sym = contract["symbol"]
    bid = contract["bid"]; ask = contract["ask"]; mid = contract["mid"]
    spread = ask - bid
    log.info(f"OPTION {sym:5s} {direction:5s}  {opt_sym}  bid={bid:.2f} ask={ask:.2f} mid={mid:.2f}")

    prices = [round(mid, 2), round(mid + 0.25*spread, 2), round(mid + 0.50*spread, 2)]
    order_id = None
    for attempt, limit_px in enumerate(prices):
        try:
            if order_id:
                api.cancel_order(order_id)
            order = api.submit_order(
                symbol=opt_sym, qty=CONTRACTS, side="buy",
                type="limit", time_in_force="day", limit_price=str(limit_px)
            )
            order_id = order.id
            log.info(f"  Attempt {attempt+1}: BUY LIMIT {opt_sym} @ {limit_px:.2f}")
            time.sleep(FILL_WAIT_S)
            o = api.get_order(order_id)
            if o.status == "filled":
                fill = float(o.filled_avg_price)
                tp_price = round(fill * TP_MULT, 2)
                sl_price = round(fill * SL_MULT, 2)
                log.info(f"FILL   {sym:5s} {direction:5s}  {opt_sym} @ {fill:.2f}  TP={tp_price:.2f}  SL={sl_price:.2f}")
                try:
                    tp_order = api.submit_order(
                        symbol=opt_sym, qty=CONTRACTS, side="sell",
                        type="limit", time_in_force="day",
                        limit_price=str(tp_price),
                        order_class="oco",
                        stop_loss={"stop_price": str(sl_price)},
                    )
                    with _lock:
                        open_positions[sym] = {
                            "opt_sym": opt_sym, "entry": fill,
                            "tp": tp_price, "sl": sl_price,
                            "direction": direction,
                            "opened_at": datetime.datetime.now(TZ),
                            "order_id": tp_order.id,
                        }
                        sb_insert_trade(sym, fill, CONTRACTS, str(tp_order.id), direction)
                except Exception as e:
                    log.error(f"OCO exit error {sym}: {e}")
                return
        except Exception as e:
            log.error(f"Entry order error {sym} attempt {attempt+1}: {e}")
            return

    if order_id:
        try: api.cancel_order(order_id)
        except: pass
    log.info(f"SKIP   {sym} {direction} — no fill after 3 attempts")

# ── SIGNAL SCAN ───────────────────────────────────────────────────────
def scan_signals():
    """Run Boof 23 strict signal on 5-min bars for all symbols."""
    log.info("-" * 55)
    log.info("SCAN: checking Boof 23 signals on 5-min bars...")

    bars_5m = get_bars(SYMS, "5Min", bars=300)
    bars_1m = get_bars(SYMS, "1Min", bars=100)

    equity   = get_account_equity()
    now_et   = datetime.datetime.now(ET)
    signals  = []

    for sym in SYMS:
        # Cooldown guard
        if sym in cooldown_until and now_et < cooldown_until[sym]:
            continue
        # Lockout guard
        if sym in open_positions:
            continue

        df5 = bars_5m.get(sym)
        df1 = bars_1m.get(sym)
        if df5 is None or df1 is None or len(df5) < 80:
            continue

        try:
            trades = mod.run_boof23_strict_5sig_1exec(
                df1, sym, tp_pct=TP_PCT, sl_pct=SL_PCT, cooldown_bars=10
            )
            if not trades:
                log.info(f"  {sym}: no setup")
                continue
            last = trades[-1]
            sig_time = last.get('signal_time')
            if sig_time is not None:
                age_secs = (now_et - sig_time).total_seconds()
                log.info(f"  {sym}: {last['direction'].upper()} signal | fired {sig_time.strftime('%H:%M')} ET ({age_secs/60:.1f} min old)")
                if age_secs > 900:
                    continue
            else:
                log.info(f"  {sym}: {last['direction'].upper()} signal (no time)")
            signals.append((sym, last['direction'], df1.iloc[-1]['close'], last))
        except Exception as e:
            log.warning(f"  {sym} signal error: {e}")

    if not signals:
        log.info("No signals this scan.")
        return

    log.info(f"Signals: {[(s[0], s[1]) for s in signals]}")

    # Cap to MAX_POSITIONS
    available = MAX_POSITIONS - len(open_positions)
    if available <= 0:
        log.info(f"At max positions ({MAX_POSITIONS}) — skipping all signals")
        return

    for sym, direction, price, trade_info in signals[:available]:
        price = get_latest_price(sym) or price
        if price <= 0:
            continue
        threading.Thread(
            target=place_option_entry, args=(sym, direction, price), daemon=True
        ).start()

# ── TP/SL MONITOR ─────────────────────────────────────────────────────
def check_exits():
    """OCO exits are handled by Alpaca automatically. This checks for timed-out positions."""
    now_et = datetime.datetime.now(TZ)
    to_close = []
    for sym, pos in list(open_positions.items()):
        if "opened_at" not in pos: continue
        age_min = (now_et - pos["opened_at"]).total_seconds() / 60
        if age_min >= 120:  # 2hr max hold
            log.info(f"TIMEOUT {sym} — closing after {age_min:.0f} min")
            try:
                api.submit_order(pos["opt_sym"], CONTRACTS, "sell", "market", "day")
            except Exception as e:
                log.error(f"Timeout close failed {sym}: {e}")
            to_close.append(sym)
    for sym in to_close:
        open_positions.pop(sym, None)
        cooldown_until[sym] = datetime.datetime.now(ET) + datetime.timedelta(seconds=COOLDOWN_SEC)

# ── EOD EXIT ──────────────────────────────────────────────────────────
def close_all_eod():
    """Force-close all open Boof 23 option positions at end of day."""
    log.info("EOD: closing all open positions...")
    for sym, pos in list(open_positions.items()):
        try:
            api.submit_order(pos["opt_sym"], CONTRACTS, "sell", "market", "day")
            log.info(f"  EOD closed {sym} {pos['opt_sym']}")
        except Exception as e:
            log.error(f"  EOD close failed {sym}: {e}")
    open_positions.clear()
    log.info("All positions closed.")

# ── SUMMARY ───────────────────────────────────────────────────────────
def print_summary():
    if not os.path.exists(LOG_FILE):
        return
    df    = pd.read_csv(LOG_FILE)
    today = datetime.date.today().isoformat()
    df    = df[df["date"] == today]
    if len(df) == 0:
        log.info("No trades today.")
        return
    pnl_pct = df["pnl_pct"].astype(float)
    pnl_usd = df["pnl_usd"].astype(float)
    wins    = pnl_pct > 0
    log.info(f"\n  TODAY ({today})  Boof 23 Paper")
    log.info(f"  Trades:   {len(df)}")
    log.info(f"  Win Rate: {wins.mean()*100:.1f}%")
    log.info(f"  Total:    ${pnl_usd.sum():+.2f}  ({pnl_pct.sum():+.3f}%)")
    log.info(f"  Avg/trade:${pnl_usd.mean():+.2f}  ({pnl_pct.mean():+.3f}%)")
    log.info(f"  TPs:      {(df['exit_type']=='tp').sum()}  "
             f"SLs: {(df['exit_type']=='sl').sum()}  "
             f"EOD: {(df['exit_type']=='eod').sum()}")

# ── MAIN LOOP ─────────────────────────────────────────────────────────
def wait_until_et(hour, minute, label):
    now_et = datetime.datetime.now(ET)
    target = now_et.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now_et >= target:
        log.info(f"{label} time already passed ({now_et.strftime('%H:%M:%S')} ET)")
        return False
    secs = (target - now_et).total_seconds()
    log.info(f"Waiting {secs/60:.1f} min until {label} ({target.strftime('%H:%M')} ET)...")
    time.sleep(secs)
    return True

_last_hb_min_b23 = -1
def wait_for_market_open():
    """Sleep until the next market open (9:30 ET), polling every 60s."""
    global _last_hb_min_b23
    while True:
        try:
            now_et = datetime.datetime.now(ET)
            if now_et.minute != _last_hb_min_b23:
                log.info(f"[Heartbeat] Boof 23 Alive — {now_et.strftime('%Y-%m-%d %H:%M')} ET")
                _last_hb_min_b23 = now_et.minute
            clock = trade_client.get_clock()
            if clock.is_open:
                return
            # next_open is timezone-aware
            next_open = clock.next_open.astimezone(ET)
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
    """Trade one full day: 9:35 open → 3:55 EOD close."""
    now_et = datetime.datetime.now(ET)
    log.info(f"=== NEW DAY {now_et.strftime('%Y-%m-%d')} ===  "
             f"TP=+{TP_PCT*100:.2f}%  SL=-{SL_PCT*100:.2f}%  "
             f"Risk={RISK_PCT*100:.0f}%/trade  MaxPos={MAX_POSITIONS}")

    used_pivots.clear()
    open_positions.clear()
    cooldown_until.clear()

    # Wait until 9:30 market open
    wait_until_et(9, 30, "MARKET OPEN")

    log.info("Active trading loop (9:35 -> 3:45 ET)...")
    last_heartbeat_min = -1
    while True:
        now_et     = datetime.datetime.now(ET)
        eod_cutoff = now_et.replace(hour=15, minute=45, second=0, microsecond=0)
        hard_close = now_et.replace(hour=15, minute=59, second=0, microsecond=0)

        if now_et >= hard_close:
            break

        if now_et.minute != last_heartbeat_min:
            log.info(f"[Heartbeat] Boof 23 Alive — {now_et.strftime('%Y-%m-%d %H:%M')} ET")
            last_heartbeat_min = now_et.minute

        if now_et < eod_cutoff:
            check_exits()
            if now_et.second < 5:  # scan once per minute
                scan_signals()

        time.sleep(5)

    close_all_eod()
    print_summary()
    log.info("Day complete.")


# ── ENTRY ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        scan_signals()
    elif len(sys.argv) > 1 and sys.argv[1] == "close":
        close_all_eod()
    elif len(sys.argv) > 1 and sys.argv[1] == "summary":
        print_summary()
    else:
        log.info("Boof 23 Paper Bot — 24/7 mode started")
        log.info(f"Account equity: ${get_account_equity():,.2f}")
        while True:
            try:
                wait_for_market_open()
                run_day()
                # After day ends sleep 5 min before looping to next open check
                time.sleep(300)
            except KeyboardInterrupt:
                log.info("Stopped by user.")
                close_all_eod()
                break
            except Exception as e:
                log.error(f"Day loop error: {e} — restarting in 60s")
                time.sleep(60)
