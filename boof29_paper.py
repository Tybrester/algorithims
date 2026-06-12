"""
BOOF 31 v2 — Paper Trading Bot (Alpaca Paper)
Optimized resistance sweep short strategy with Exit C

Setup:
  1. Get paper API keys from: https://app.alpaca.markets  (toggle Paper in top-left)
  2. pip install alpaca-trade-api schedule pandas numpy
  3. Set ALPACA_PAPER_KEY and ALPACA_PAPER_SECRET below (or env vars)
  4. Run: python boof29_paper.py

The bot will:
  - Connect to Alpaca paper environment
  - Scan for BOOF 31 v2 resistance sweep setups during market hours
  - Enter short positions on qualifying symbols (Score >= 6, Sweep >= 0.20%)
  - Use Exit C strategy: 50% at 0.50% + 0.25% trailing stop
  - Apply 30-minute cooldown per symbol
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
BOT_NAME     = "BOOF 31 v2 Paper"   # shows on trades page

# BOOF 31 v2 OPTIMIZED PARAMETERS
SWEEP_OPTIMIZED = 0.0020    # 0.20% sweep requirement
TP1 = 0.0050                # 0.50% first target
SL_OPTIMIZED = 0.0025        # 0.25% stop loss
COOLDOWN_MINUTES = 30        # 30-minute cooldown per symbol
MIN_SCORE = 6                # Minimum BOOF score
SLIPPAGE = 0.0005            # 0.05% slippage

# POSITION SIZING
POSITION_SIZE_USD = 1000     # Fixed $1000 per position
MAX_POSITIONS = 8             # Max concurrent positions
MAX_DAILY_LOSS = 0.02         # 2% max daily loss
RISK_PER_TRADE = 0.01         # 1% risk per trade
PDT_GUARD = True              # Block trades if near PDT limit

WATCHLIST = [
    # Tech Giants
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","AMD","NFLX",
    # Cloud/SaaS
    "CRM","NOW","SNOW","PLTR","DDOG","MDB","CRWD","ZS","NET","SHOP",
    # Software
    "ADBE","INTU","PANW","TEAM","HUBS","UBER","ABNB","BKNG","RBLX","DASH",
    # Latin America/E-commerce
    "MELI","ETSY",
    # Financials
    "JPM","GS","MS","BAC","WFC","AXP","COF","SCHW","BLK","SPGI",
    # Healthcare/Biotech
    "LLY","NVO","UNH","ISRG","VRTX","REGN","MRNA","BIIB","GILD","BMY",
    # Industrial/Defense
    "GE","RTX","LMT","BA","CAT","DE","ETN","PH","TT",
    # Energy
    "XOM","CVX","COP","SLB","HAL","OXY","EOG","MPC","VLO","DVN",
    # Telecom/Media
    "TMUS","CMCSA","ROKU","SPOT","PINS","SNAP","RDDT","COIN",
    # Semiconductor/Hardware
    "MSTR","HOOD","SMCI","ARM","MU","QCOM","MRVL","TSM","ASML",
    # Semicap Equipment
    "AMAT","LRCX","KLAC","MCHP","ON","NXPI",
    # ETFs
    "SPY","QQQ","IWM","SMH"
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

# ── BOOF 31 v2 STRATEGY FUNCTIONS ───────────────────────────────────────
def calculate_boof_score(symbol):
    """Calculate BOOF score for a symbol using recent data"""
    try:
        import pytz
        et = pytz.timezone("America/New_York")
        end = datetime.datetime.now(et)
        start = end - datetime.timedelta(hours=2)
        
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute,
                              start=start, end=end, limit=120)
        bars = data_client.get_stock_bars(req).df
        
        if isinstance(bars.index, pd.MultiIndex):
            bars = bars.xs(symbol, level="symbol")
        
        if len(bars) < 50:
            return 0
        
        # Calculate technical indicators
        bars['sma_20'] = bars['close'].rolling(window=20).mean()
        bars['sma_50'] = bars['close'].rolling(window=50).mean()
        bars['volume_sma_20'] = bars['volume'].rolling(window=20).mean()
        bars['resistance_10'] = bars['high'].rolling(window=10).max()
        bars['price_change_5'] = bars['close'].pct_change(5)
        bars['volatility_10'] = bars['close'].pct_change().rolling(window=10).std()
        
        # Get latest values
        latest = bars.iloc[-1]
        
        score = 0
        
        # Volume expansion (score +2)
        if latest['volume'] > latest['volume_sma_20'] * 1.2:
            score += 2
        
        # Price above moving averages (score +2)
        if latest['close'] > latest['sma_20']:
            score += 1
        if latest['close'] > latest['sma_50']:
            score += 1
        
        # Near resistance (score +2)
        if latest['close'] > latest['resistance_10'] * 0.98:
            score += 2
        
        # Recent strength (score +2)
        if latest['price_change_5'] > 0.01:
            score += 2
        
        # Volatility bonus (score +1)
        if latest['volatility_10'] > latest['volatility_10'].quantile(0.7):
            score += 1
        
        return min(10, max(0, int(score)))
        
    except Exception as e:
        log.warning(f"Error calculating BOOF score for {symbol}: {e}")
        return 0

def check_sweep_condition(symbol):
    """Check if sweep condition is met (price spike above resistance)"""
    try:
        import pytz
        et = pytz.timezone("America/New_York")
        end = datetime.datetime.now(et)
        start = end - datetime.timedelta(minutes=10)
        
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute,
                              start=start, end=end, limit=10)
        bars = data_client.get_stock_bars(req).df
        
        if isinstance(bars.index, pd.MultiIndex):
            bars = bars.xs(symbol, level="symbol")
        
        if len(bars) < 5:
            return False
        
        # Check for sweep (price spike above resistance)
        latest = bars.iloc[-1]
        previous = bars.iloc[-2]
        
        # Calculate resistance
        resistance = bars['high'].rolling(window=5).max().iloc[-2]
        
        # Check if price swept above resistance
        if latest['close'] > resistance * 1.002:  # 0.2% sweep
            return True
        
        return False
        
    except Exception as e:
        log.warning(f"Error checking sweep condition for {symbol}: {e}")
        return False

def check_cooldown(symbol):
    """Check if cooldown period has passed"""
    if not os.path.exists("boof31_cooldowns.json"):
        return True
    
    try:
        with open("boof31_cooldowns.json", "r") as f:
            cooldowns = json.load(f)
        
        if symbol not in cooldowns:
            return True
        
        last_trade = datetime.datetime.fromisoformat(cooldowns[symbol])
        time_since = datetime.datetime.now() - last_trade
        
        return time_since.total_seconds() >= COOLDOWN_MINUTES * 60
        
    except Exception as e:
        log.warning(f"Error checking cooldown for {symbol}: {e}")
        return True

def update_cooldown(symbol):
    """Update cooldown timestamp for symbol"""
    try:
        cooldowns = {}
        if os.path.exists("boof31_cooldowns.json"):
            with open("boof31_cooldowns.json", "r") as f:
                cooldowns = json.load(f)
        
        cooldowns[symbol] = datetime.datetime.now().isoformat()
        
        with open("boof31_cooldowns.json", "w") as f:
            json.dump(cooldowns, f)
            
    except Exception as e:
        log.warning(f"Error updating cooldown for {symbol}: {e}")

def calculate_position_size(symbol):
    """Calculate position size based on fixed USD amount"""
    try:
        current_price = get_current_price(symbol)
        if not current_price or current_price <= 0:
            return 0
        
        shares = int(POSITION_SIZE_USD / current_price)
        return max(1, shares)
        
    except Exception as e:
        log.warning(f"Error calculating position size for {symbol}: {e}")
        return 0

# ── SCAN AND ENTER (CONTINUOUS) ────────────────────────────────────────
def scan_and_enter():
    """Scan for BOOF 31 v2 setups and enter positions"""
    log.info("=" * 60)
    log.info("BOOF 31 v2 SCAN — checking for resistance sweep setups...")

    positions = get_open_boof29_positions()
    if len(positions) >= MAX_POSITIONS:
        log.info(f"Max positions reached ({MAX_POSITIONS})")
        return

    opportunities = []
    for symbol in WATCHLIST:
        if symbol in positions:
            continue
        
        if not check_cooldown(symbol):
            continue
        
        # Calculate BOOF score
        score = calculate_boof_score(symbol)
        if score < MIN_SCORE:
            continue
        
        # Check sweep condition
        if not check_sweep_condition(symbol):
            continue
        
        current_price = get_current_price(symbol)
        if not current_price:
            continue
        
        opportunities.append((symbol, score, current_price))
    
    if not opportunities:
        log.info("No BOOF 31 v2 setups found")
        return

    log.info(f"BOOF 31 v2 setups found: {[f'{s[0]}(score:{s[1]})' for s in opportunities]}")

    today = datetime.date.today().isoformat()
    entered = []
    
    for symbol, score, price in opportunities:
        if len(positions) + len(entered) >= MAX_POSITIONS:
            break
        
        shares = calculate_position_size(symbol)
        if shares == 0:
            log.warning(f"  {symbol}: insufficient funds for position")
            continue
        
        try:
            req = MarketOrderRequest(symbol=symbol, qty=shares,
                                   side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
            order = trade_client.submit_order(req)
            log.info(f"  SHORT {symbol} {shares} shares @ ${price:.2f} (Score: {score})  id: {order.id}")
            
            sb_id = sb_insert_trade(symbol, price, shares, str(order.id))
            entered.append({"symbol": symbol, "shares": shares, "entry_price": price,
                          "order_id": str(order.id), "sb_trade_id": sb_id or "", 
                          "date": today, "score": score})
            
            update_cooldown(symbol)
            positions[symbol] = True
            
        except Exception as e:
            log.error(f"  Order failed for {symbol}: {e}")

    if entered:
        pd.DataFrame(entered).to_csv("boof31_today_entries.csv", index=False)
        log.info(f"Entered {len(entered)} BOOF 31 v2 positions.")
    else:
        log.info("No positions entered.")

# ── EXIT C STRATEGY (CONTINUOUS) ────────────────────────────────────────
def manage_positions():
    """Manage existing positions with Exit C strategy"""
    log.info("=" * 60)
    log.info("EXIT C MANAGEMENT — checking positions...")

    positions = get_open_boof29_positions()
    if not positions:
        log.info("No open positions to manage.")
        return

    # Load entry data
    entry_data = {}
    if os.path.exists("boof31_today_entries.csv"):
        edf = pd.read_csv("boof31_today_entries.csv")
        entry_data = {row["symbol"]: row for _, row in edf.iterrows()}

    today = datetime.date.today().isoformat()
    positions_to_close = []

    for symbol, pos in positions.items():
        try:
            current_price = get_current_price(symbol)
            if not current_price:
                continue

            entry_price = float(pos.avg_entry_price)
            shares = int(float(pos.qty))
            
            # Calculate unrealized PnL
            pnl_pct = (entry_price - current_price) / entry_price

            # Exit C logic: 50% at 0.50% target
            entry_info = entry_data.get(symbol, {})
            exit1_triggered = entry_info.get("exit1_triggered", False)

            if not exit1_triggered and current_price <= entry_price * (1 - TP1):
                # Close 50% of position
                exit_shares = shares // 2
                if exit_shares > 0:
                    req = MarketOrderRequest(symbol=symbol, qty=exit_shares,
                                           side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
                    order = trade_client.submit_order(req)
                    log.info(f"  EXIT 1 {symbol}: {exit_shares} shares @ ${current_price:.2f} (Target: {TP1:.1%})")
                    
                    # Update entry data
                    if symbol in entry_data:
                        entry_data[symbol]["exit1_triggered"] = True
                        entry_data[symbol]["trail_stop"] = current_price * (1 + SL_OPTIMIZED)
                        pd.DataFrame(entry_data.values()).to_csv("boof31_today_entries.csv", index=False)

            # Trailing stop for remaining position
            if exit1_triggered:
                trail_stop = entry_info.get("trail_stop", entry_price * (1 + SL_OPTIMIZED))
                
                # Update trailing stop if price moved favorably
                new_trail_stop = current_price * (1 + SL_OPTIMIZED)
                if new_trail_stop < trail_stop:
                    trail_stop = new_trail_stop
                    if symbol in entry_data:
                        entry_data[symbol]["trail_stop"] = trail_stop
                        pd.DataFrame(entry_data.values()).to_csv("boof31_today_entries.csv", index=False)

                # Check trailing stop
                if current_price >= trail_stop:
                    positions_to_close.append(symbol)
                    log.info(f"  TRAILING STOP {symbol}: {symbol} @ ${current_price:.2f}")

            # Stop loss check
            if current_price >= entry_price * (1 + SL_OPTIMIZED):
                positions_to_close.append(symbol)
                log.info(f"  STOP LOSS {symbol}: {symbol} @ ${current_price:.2f}")

        except Exception as e:
            log.error(f"  Error managing {symbol}: {e}")
            positions_to_close.append(symbol)

    # Close positions that need to be closed
    for symbol in positions_to_close:
        close_position(symbol)

def close_position(symbol):
    """Close a specific position"""
    try:
        pos = trade_client.get_open_position(symbol)
        shares = int(float(pos.qty))
        entry_price = float(pos.avg_entry_price)
        
        trade_client.close_position(symbol)
        exit_price = get_current_price(symbol) or entry_price
        
        # Log trade
        today = datetime.date.today().isoformat()
        log_trade(today, symbol, entry_price, exit_price, shares)
        
        # Close Supabase trade
        entry_data = {}
        if os.path.exists("boof31_today_entries.csv"):
            edf = pd.read_csv("boof31_today_entries.csv")
            entry_data = {row["symbol"]: row for _, row in edf.iterrows()}
        
        sb_trade_id = entry_data.get(symbol, {}).get("sb_trade_id", "")
        sb_close_trade(sb_trade_id, exit_price, entry_price, shares)
        
        log.info(f"  CLOSED {symbol}: PnL {((entry_price - exit_price) / entry_price):+.2%}")
        
    except Exception as e:
        log.error(f"  Failed to close {symbol}: {e}")

def exit_all():
    """Emergency close all positions"""
    log.info("=" * 60)
    log.info("EMERGENCY EXIT — closing all positions...")

    positions = get_open_boof29_positions()
    if not positions:
        log.info("No open positions to close.")
        return

    for symbol in positions.keys():
        close_position(symbol)

    # Clean up entry files
    if os.path.exists("boof31_today_entries.csv"):
        os.remove("boof31_today_entries.csv")

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


def run_continuous():
    """Run BOOF 31 v2 bot continuously during market hours."""
    import pytz
    et = pytz.timezone("America/New_York")
    
    log.info("BOOF 31 v2 Bot — Continuous mode started")
    
    while True:
        try:
            now_et = datetime.datetime.now(et)
            
            # Check if market is open
            if not is_market_open():
                log.info(f"Market closed ({now_et.strftime('%H:%M:%S')} ET)")
                time.sleep(60)  # Check every minute
                continue
            
            # Log new day
            if now_et.hour == 9 and now_et.minute == 30:
                log.info(f"=== NEW DAY {now_et.strftime('%Y-%m-%d')} === BOOF 31 v2 Paper")
                print_summary()
            
            # Scan for new opportunities
            scan_and_enter()
            
            # Manage existing positions
            manage_positions()
            
            # Wait before next iteration
            time.sleep(60)  # Check every minute
            
        except KeyboardInterrupt:
            log.info("Stopped by user.")
            exit_all()
            break
        except Exception as e:
            log.error(f"Continuous loop error: {e} — restarting in 60s")
            time.sleep(60)


# ── ENTRY POINT ───────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "exit":
        exit_all()
    elif len(sys.argv) > 1 and sys.argv[1] == "scan":
        scan_and_enter()
    elif len(sys.argv) > 1 and sys.argv[1] == "manage":
        manage_positions()
    elif len(sys.argv) > 1 and sys.argv[1] == "summary":
        print_summary()
    else:
        run_continuous()
