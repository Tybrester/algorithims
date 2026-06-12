"""
BOOF 31 v2 — OPTIONS TRADING BOT (Alpaca Paper)
Options version with +40% TP, -15% SL, 20-minute timeout

Strategy:
- Uses BOOF 31 v2 setup detection for entry timing
- Buys PUT options on resistance sweep setups
- TP: +40% gain, SL: -15% loss, Time: 20 minutes
- Real-time scanning every 5 seconds
- Risk management with position sizing

Setup:
1. Get paper API keys from Alpaca with options trading enabled
2. pip install alpaca-trade-api pandas numpy
3. Set ALPACA_PAPER_KEY and ALPACA_PAPER_SECRET
4. Run: python options_bot_v2.py
"""

import os, time, datetime, csv, logging, json
import pandas as pd
import numpy as np

# ── CONFIG ────────────────────────────────────────────────────────────
PAPER_KEY    = os.environ.get("ALPACA_PAPER_KEY",    "PKU37C3QZHELGN2IDQLNYAEFJR")
PAPER_SECRET = os.environ.get("ALPACA_PAPER_SECRET", "CTcQtRqgC5SkKxo9q7sAn8iwTZt5CWWtvueiPjvbC22w")
BASE_URL     = "https://paper-api.alpaca.markets"

# OPTIONS TRADING PARAMETERS
OPTIONS_TP = 0.40      # +40% take profit
OPTIONS_SL = 0.15      # -15% stop loss
TIMEOUT_MINUTES = 20   # 20 minute timeout
POSITION_SIZE_USD = 500  # $500 per options position
MAX_POSITIONS = 999     # Effectively unlimited concurrent options positions
COOLDOWN_MINUTES = 30   # 30-minute cooldown per symbol

# BOOF 31 v2 PARAMETERS
SWEEP_OPTIMIZED = 0.0020  # 0.20% sweep requirement
MIN_SCORE = 6             # Minimum BOOF score

# HIGH-VOLUME OPTIONS SYMBOLS (liquid options)
OPTIONS_WATCHLIST = [
    # Tech Giants (most liquid options)
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "NFLX",
    # ETFs (very liquid options)
    "SPY", "QQQ", "IWM",
    # High-volume stocks
    "AMD", "AVGO", "CRM", "PYPL", "UBER", "COIN", "HOOD", "MSTR",
    # Semiconductors
    "SMH", "SOXX"
]

# ── LOGGING ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("boof31_options.log")]
)
log = logging.getLogger("boof31_options")

LOG_FILE = "boof31_options_log.csv"
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", newline="") as f:
        csv.writer(f).writerow(["timestamp","symbol","option_symbol","entry_px","exit_px","pnl_pct","pnl_usd","exit_reason"])

def log_option_trade(symbol, option_symbol, entry_px, exit_px, exit_reason="timeout"):
    pnl_pct = (exit_px - entry_px) / entry_px * 100 if entry_px else 0
    pnl_usd = (exit_px - entry_px) * 100 if entry_px else 0  # Assuming 1 contract = 100 shares
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([datetime.datetime.now().isoformat(), symbol, option_symbol, 
                               f"{entry_px:.4f}", f"{exit_px:.4f}", f"{pnl_pct:.2f}", 
                               f"{pnl_usd:.2f}", exit_reason])
    log.info(f"  {symbol:>6} {option_symbol:>15}  entry=${entry_px:.2f}  exit=${exit_px:.2f}  "
             f"pnl={pnl_pct:+.1f}%  ${pnl_usd:+.2f}  ({exit_reason})")

# ── ALPACA CLIENT ─────────────────────────────────────────────────────
try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, GetOptionContractsRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, AssetStatus, OptionType
    from alpaca.data.historical import StockHistoricalDataClient, OptionHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest, OptionLatestQuoteRequest
    from alpaca.data.timeframe import TimeFrame
    
    trade_client = TradingClient(PAPER_KEY, PAPER_SECRET, paper=True)
    stock_data_client = StockHistoricalDataClient(PAPER_KEY, PAPER_SECRET)
    option_data_client = OptionHistoricalDataClient(PAPER_KEY, PAPER_SECRET)
    
    account = trade_client.get_account()
    log.info(f"Connected to Alpaca Paper Options | Cash: ${float(account.cash):,.2f}  "
             f"Buying power: ${float(account.buying_power):,.2f}")
except Exception as e:
    log.error(f"Alpaca connection failed: {e}")
    log.error("Install: python -m pip install alpaca-py")
    raise

# ── OPTIONS FUNCTIONS ────────────────────────────────────────────────
def get_nearest_put_options(symbol, target_dte=7):
    """Get PUT options targeting $350 price, walking strikes up/down to find available"""
    try:
        # Get current date and target expiration
        current_date = datetime.date.today()
        target_date = current_date + datetime.timedelta(days=target_dte)
        
        # Request options contracts
        request = GetOptionContractsRequest(
            underlying_symbols=[symbol],
            status=AssetStatus.ACTIVE,
            type=OptionType.PUT,
            expiration_date_gte=target_date,
            expiration_date_lte=target_date + datetime.timedelta(days=7),
            limit=50  # Get more contracts to walk through
        )
        
        contracts = trade_client.get_option_contracts(request)
        if not contracts:
            return []
        
        # Get current stock price
        stock_req = StockLatestTradeRequest(symbol_or_symbols=symbol)
        stock_price = stock_data_client.get_stock_latest_trade(stock_req)[symbol].price
        
        # Target $350 price - find options closest to this price
        target_price = 350.0
        valid_options = []
        
        for contract in contracts:
            strike = float(contract.strike_price)
            
            # Get option price to check if it's close to target
            try:
                option_price = get_option_price(contract.symbol)
                if option_price is None:
                    continue
                    
                # Calculate difference from target price
                price_diff = abs(option_price - target_price)
                
                # Include options within reasonable range of target ($100-$600)
                if 100 <= option_price <= 600:
                    valid_options.append({
                        'symbol': contract.symbol,
                        'strike': strike,
                        'expiration': contract.expiration_date,
                        'option_price': option_price,
                        'price_diff': price_diff,
                        'delta': contract.delta if hasattr(contract, 'delta') else None
                    })
                    
            except Exception:
                continue
        
        if not valid_options:
            # Fallback: if no options in target price range, get closest to ATM
            for contract in contracts:
                strike = float(contract.strike_price)
                if abs(strike - stock_price) / stock_price <= 0.20:  # Within 20%
                    try:
                        option_price = get_option_price(contract.symbol)
                        if option_price and option_price <= 1000:  # Reasonable price limit
                            valid_options.append({
                                'symbol': contract.symbol,
                                'strike': strike,
                                'expiration': contract.expiration_date,
                                'option_price': option_price,
                                'price_diff': abs(option_price - target_price),
                                'delta': contract.delta if hasattr(contract, 'delta') else None
                            })
                    except Exception:
                        continue
        
        # Sort by price difference from $350 target (closest first)
        valid_options.sort(key=lambda x: x['price_diff'])
        return valid_options[:5]  # Return top 5 closest to target price
        
    except Exception as e:
        log.warning(f"Error getting options for {symbol}: {e}")
        return []

def get_option_price(option_symbol):
    """Get current price of an option"""
    try:
        req = OptionLatestQuoteRequest(symbol_or_symbols=option_symbol)
        quote = option_data_client.get_option_latest_quote(req)
        if option_symbol in quote:
            return (quote[option_symbol].bid_price + quote[option_symbol].ask_price) / 2
    except Exception as e:
        log.warning(f"Error getting option price for {option_symbol}: {e}")
    return None

def buy_put_option(symbol, option_symbol):
    """Buy a PUT option"""
    try:
        # Get current price
        price = get_option_price(option_symbol)
        if not price:
            return None
        
        # Calculate contracts (1 contract = 100 shares)
        max_contracts = int(POSITION_SIZE_USD / (price * 100))
        contracts = max(1, min(max_contracts, 5))  # Max 5 contracts
        
        req = MarketOrderRequest(
            symbol=option_symbol,
            qty=contracts,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        
        order = trade_client.submit_order(req)
        log.info(f"  BOUGHT PUT {symbol} {option_symbol} {contracts} contracts @ ${price:.2f} (target: $350)  id: {order.id}")
        
        return {
            'symbol': symbol,
            'option_symbol': option_symbol,
            'contracts': contracts,
            'entry_price': price,
            'entry_time': datetime.datetime.now(),
            'order_id': order.id
        }
        
    except Exception as e:
        log.error(f"  Failed to buy PUT option for {symbol}: {e}")
        return None

def sell_option(position, exit_reason):
    """Sell an option position"""
    try:
        req = MarketOrderRequest(
            symbol=position['option_symbol'],
            qty=position['contracts'],
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY
        )
        
        order = trade_client.submit_order(req)
        exit_price = get_option_price(position['option_symbol']) or position['entry_price']
        
        log_option_trade(
            position['symbol'], 
            position['option_symbol'],
            position['entry_price'], 
            exit_price, 
            exit_reason
        )
        
        log.info(f"  SOLD PUT {position['symbol']} {position['option_symbol']} @ ${exit_price:.2f} ({exit_reason})")
        return True
        
    except Exception as e:
        log.error(f"  Failed to sell option {position['option_symbol']}: {e}")
        return False

# ── BOOF 31 v2 STRATEGY FUNCTIONS ───────────────────────────────────────
def calculate_boof_score(symbol):
    """Calculate BOOF score for a symbol using recent data"""
    try:
        import pytz
        et = pytz.timezone("US/Eastern")  # EST timezone
        end = datetime.datetime.now(et)
        start = end - datetime.timedelta(hours=2)
        
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute,
                              start=start, end=end, limit=120)
        bars = stock_data_client.get_stock_bars(req).df
        
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
        et = pytz.timezone("US/Eastern")  # EST timezone
        end = datetime.datetime.now(et)
        start = end - datetime.timedelta(minutes=10)
        
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute,
                              start=start, end=end, limit=10)
        bars = stock_data_client.get_stock_bars(req).df
        
        if isinstance(bars.index, pd.MultiIndex):
            bars = bars.xs(symbol, level="symbol")
        
        if len(bars) < 5:
            return False
        
        # Check for sweep (price spike above resistance)
        latest = bars.iloc[-1]
        
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
    if not os.path.exists("boof31_options_cooldowns.json"):
        return True
    
    try:
        with open("boof31_options_cooldowns.json", "r") as f:
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
        if os.path.exists("boof31_options_cooldowns.json"):
            with open("boof31_options_cooldowns.json", "r") as f:
                cooldowns = json.load(f)
        
        cooldowns[symbol] = datetime.datetime.now().isoformat()
        
        with open("boof31_options_cooldowns.json", "w") as f:
            json.dump(cooldowns, f)
            
    except Exception as e:
        log.warning(f"Error updating cooldown for {symbol}: {e}")

# ── OPTIONS POSITION MANAGEMENT ─────────────────────────────────────────
def manage_options_positions():
    """Manage existing options positions with TP/SL/timeout"""
    if not os.path.exists("boof31_options_positions.json"):
        return
    
    try:
        with open("boof31_options_positions.json", "r") as f:
            positions = json.load(f)
        
        positions_to_close = []
        current_time = datetime.datetime.now()
        
        for pos_id, position in positions.items():
            # Get current option price
            current_price = get_option_price(position['option_symbol'])
            if not current_price:
                continue
            
            entry_price = position['entry_price']
            pnl_pct = (current_price - entry_price) / entry_price
            
            # Check take profit (+40%)
            if pnl_pct >= OPTIONS_TP:
                positions_to_close.append((pos_id, position, "take_profit"))
                continue
            
            # Check stop loss (-15%)
            if pnl_pct <= -OPTIONS_SL:
                positions_to_close.append((pos_id, position, "stop_loss"))
                continue
            
            # Check timeout (20 minutes)
            time_held = current_time - datetime.datetime.fromisoformat(position['entry_time'])
            if time_held.total_seconds() >= TIMEOUT_MINUTES * 60:
                positions_to_close.append((pos_id, position, "timeout"))
                continue
        
        # Close positions that need closing
        for pos_id, position, reason in positions_to_close:
            if sell_option(position, reason):
                del positions[pos_id]
        
        # Save updated positions
        with open("boof31_options_positions.json", "w") as f:
            json.dump(positions, f)
            
    except Exception as e:
        log.error(f"Error managing options positions: {e}")

# ── SCAN AND ENTER OPTIONS ────────────────────────────────────────────
def scan_and_enter_options():
    """Scan for BOOF 31 v2 setups and enter PUT option positions"""
    log.info("=" * 60)
    log.info("OPTIONS SCAN — checking for BOOF 31 v2 setups...")

    # Check current positions
    current_positions = {}
    if os.path.exists("boof31_options_positions.json"):
        with open("boof31_options_positions.json", "r") as f:
            current_positions = json.load(f)
    
    if len(current_positions) >= MAX_POSITIONS:
        log.info(f"Max options positions reached ({MAX_POSITIONS})")
        return

    opportunities = []
    for symbol in OPTIONS_WATCHLIST:
        if symbol in [pos['symbol'] for pos in current_positions.values()]:
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
        
        opportunities.append((symbol, score))
    
    if not opportunities:
        log.info("No BOOF 31 v2 setups found for options")
        return

    log.info(f"BOOF 31 v2 setups for options: {[f'{s[0]}(score:{s[1]})' for s in opportunities]}")

    entered = []
    for symbol, score in opportunities:
        if len(current_positions) + len(entered) >= MAX_POSITIONS:
            break
        
        # Get available PUT options
        options = get_nearest_put_options(symbol)
        if not options:
            log.warning(f"  {symbol}: No liquid PUT options available")
            continue
        
        # Buy the first (closest to $350 target) option
        option = options[0]
        log.info(f"  {symbol}: Selected option {option['symbol']} @ ${option['option_price']:.2f} (target: $350, diff: ${option['price_diff']:.2f})")
        position = buy_put_option(symbol, option['symbol'])
        
        if position:
            pos_id = f"{symbol}_{datetime.datetime.now().strftime('%H%M%S')}"
            current_positions[pos_id] = position
            entered.append((symbol, option['symbol'], score))
            update_cooldown(symbol)
    
    # Save positions
    with open("boof31_options_positions.json", "w") as f:
        json.dump(current_positions, f)
    
    if entered:
        log.info(f"Entered {len(entered)} options positions: {entered}")
    else:
        log.info("No options positions entered.")

# ── MARKET HOURS ───────────────────────────────────────────────────────
def is_market_open():
    """Check if market is open"""
    try:
        clock = trade_client.get_clock()
        return clock.is_open
    except:
        return False

# ── MAIN LOOP ─────────────────────────────────────────────────────────
def run_options_continuous():
    """Run BOOF 31 v2 options bot continuously during market hours."""
    import pytz
    et = pytz.timezone("US/Eastern")  # EST timezone for proper market hours
    
    log.info("BOOF 31 v2 OPTIONS Bot — 24/7 Continuous mode started")
    log.info(f"Parameters: TP={OPTIONS_TP:.0%}, SL={OPTIONS_SL:.0%}, Timeout={TIMEOUT_MINUTES}min, UNLIMITED daily trades")
    log.info("24/7 monitoring: Active during market hours, standby when closed")
    log.info(f"Timezone: EST (US/Eastern) - Trading starts at 9:30 AM EST")
    
    while True:
        try:
            now_et = datetime.datetime.now(et)
            
            # Check if market is open
            if not is_market_open():
                log.info(f"Market closed ({now_et.strftime('%H:%M:%S')} ET) - 24/7 monitoring active")
                time.sleep(60)  # Check every minute when closed (24/7 monitoring)
                continue
            
            # Log new day and heartbeat
            if now_et.hour == 9 and now_et.minute == 30:
                log.info(f"=== NEW DAY {now_et.strftime('%Y-%m-%d')} === BOOF 31 v2 OPTIONS")
            
            # Hourly heartbeat for 24/7 monitoring
            if now_et.minute == 0:
                log.info(f"HEARTBEAT {now_et.strftime('%H:%M')} ET - 24/7 Options Bot Active")
            
            # Manage existing options positions (TP/SL/timeout)
            manage_options_positions()
            
            # Scan for new opportunities
            scan_and_enter_options()
            
            # Wait before next iteration - REAL-TIME SCANNING
            time.sleep(5)  # Check every 5 seconds when market is open
            
        except KeyboardInterrupt:
            log.info("Stopped by user.")
            # Emergency close all positions
            if os.path.exists("boof31_options_positions.json"):
                with open("boof31_options_positions.json", "r") as f:
                    positions = json.load(f)
                for position in positions.values():
                    sell_option(position, "manual_shutdown")
                os.remove("boof31_options_positions.json")
            break
        except Exception as e:
            log.error(f"Options loop error: {e} — restarting in 60s")
            time.sleep(60)

# ── ENTRY POINT ───────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "manage":
        manage_options_positions()
    elif len(sys.argv) > 1 and sys.argv[1] == "scan":
        scan_and_enter_options()
    else:
        run_options_continuous()
