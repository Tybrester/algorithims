#!/usr/bin/env python3
"""
BOOF 31 - RESISTANCE SWEEP / FAILED BREAKOUT ALGORITHM
Live Trading Bot - Paper Trading

Strategy: Resistance sweep detection with BOOF scoring
- Detect multi-touch resistance levels (2+ touches)
- Identify 0.20% sweeps above resistance
- Score setups: volume, rejection, level quality (0-7 points)
- Enter short on breakdown with minimum score of 6
- Exit: 50% at 0.50% profit, trail remaining 50%
"""

import os
import time
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# BOOF31 Parameters
SWEEP_BUFFER = 0.002     # 0.20% sweep above resistance
MIN_SCORE = 6            # Minimum BOOF score required
COOLDOWN_MINUTES = 30    # 30-minute cooldown
LOOKBACK = 80            # Resistance lookback period
RES_TOL = 0.002          # Resistance tolerance
MAX_CONFIRM_BARS = 5     # Break confirmation within 5 bars

# Exit Parameters
STOP_LOSS = 0.0025       # 0.25% stop loss
TP1 = 0.005              # 0.50% first target
TRAIL_STOP = 0.0025      # 0.25% trailing stop
MAX_HOLD_BARS = 30       # Max hold time

# Paper Trading Keys
API_KEY = 'PKY5XANXLZXX5HHRRA4PHAY2WV'
API_SECRET = 'DtYBZgpzVVRstALWcvyN9H7E827i4XPJZUsWs2sdhaC2'

# Core Universe - High probability symbols (score ≥ 6)
CORE_UNIVERSE = [
    # Tech Giants
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "AMD", "NFLX",
    # Cloud/SaaS
    "CRM", "NOW", "SNOW", "PLTR", "DDOG", "MDB", "CRWD", "ZS", "NET", "SHOP",
    # Software
    "ADBE", "INTU", "PANW", "TEAM", "HUBS", "UBER", "ABNB", "BKNG", "RBLX", "DASH",
    # Financials
    "JPM", "GS", "MS", "AXP", "SCHW", "BLK", "SPGI"
]

# Extended Universe - Additional symbols (score ≥ 3)
EXTENDED_UNIVERSE = [
    # Latin America/E-commerce
    "MELI", "ETSY",
    # Healthcare/Biotech
    "LLY", "NVO", "ISRG", "VRTX", "REGN", "MRNA", "GILD",
    # Industrial/Defense
    "GEV", "RTX", "BA", "CAT", "DE", "ETN", "PH", "TT",
    # Energy
    "XOM", "CVX", "COP", "SLB", "HAL", "OXY", "EOG", "MPC",
    # Telecom/Media
    "TMUS", "ROKU", "SPOT", "PINS", "SNAP", "RDDT", "COIN",
    # Crypto Mining
    "HUT", "MARA", "RIOT", "CLSK",
    # Semiconductor/Hardware
    "MSTR", "HOOD", "APP", "SMCI", "ARM", "MU", "QCOM", "MRVL", "TSM", "ASML",
    # Semicap Equipment
    "AMAT", "LRCX", "KLAC", "MCHP", "ON", "NXPI",
    # ETFs
    "SPY", "QQQ", "IWM", "SMH", "SOXX"
]

# Combined universe for scanning
SYMBOLS = CORE_UNIVERSE + EXTENDED_UNIVERSE

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('boof31.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

class BOOF31Bot:
    def __init__(self):
        self.trading_client = TradingClient(API_KEY, API_SECRET, paper=True)
        self.data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
        self.last_trade_time = {}
        
    def add_indicators(self, df):
        """Add technical indicators"""
        df = df.copy()
        df['avg_vol_20'] = df['volume'].rolling(20).mean()
        df['body'] = abs(df['close'] - df['open'])
        return df
    
    def find_resistance(self, df, i):
        """Find most touched resistance in lookback window"""
        window = df.iloc[max(0, i - LOOKBACK):i]
        
        if len(window) < 20:
            return None, 0
        
        highs = window["high"].values
        best_level = None
        best_touches = 0
        
        for h in highs:
            touches = np.sum(np.abs(highs - h) / h <= RES_TOL)
            if touches > best_touches:
                best_touches = touches
                best_level = h
        
        if best_touches < 2:
            return None, 0
        
        return best_level, best_touches
    
    def prior_swing_low(self, df, i, lookback=20):
        """Get prior swing low"""
        if i < lookback:
            return None
        return df["low"].iloc[i - lookback:i].min()
    
    def detect_short_sequence(self, df, i):
        """Detect short sequence: sweep + breakdown"""
        resistance, touches = self.find_resistance(df, i)
        
        if resistance is None:
            return False, {}
        
        bar = df.iloc[i]
        swept = bar["high"] > resistance * (1 + SWEEP_BUFFER)
        closed_back_below = bar["close"] < resistance
        
        if not (swept and closed_back_below):
            return False, {}
        
        swing_low = self.prior_swing_low(df, i)
        if swing_low is None:
            return False, {}
        
        for j in range(i + 1, min(i + 1 + MAX_CONFIRM_BARS, len(df) - 1)):
            confirm_bar = df.iloc[j]
            if confirm_bar["close"] < swing_low:
                entry_i = j + 1
                return True, {
                    "sweep_i": i,
                    "break_i": j,
                    "entry_i": entry_i,
                    "resistance": resistance,
                    "touches": touches,
                    "swing_low": swing_low,
                }
        
        return False, {}
    
    def score_short_setup(self, df, signal):
        """Score short setup (0-7 points)"""
        score = 0
        
        sweep_i = signal["sweep_i"]
        break_i = signal["break_i"]
        resistance = signal["resistance"]
        touches = signal["touches"]
        
        sweep_bar = df.iloc[sweep_i]
        break_bar = df.iloc[break_i]
        avg_vol = df["avg_vol_20"].iloc[break_i]
        
        if pd.isna(avg_vol) or avg_vol <= 0:
            return 0
        
        # Volume score (+2)
        if sweep_bar["volume"] > avg_vol:
            score += 1
        if break_bar["volume"] > avg_vol:
            score += 1
        
        # Rejection strength (+3)
        upper_wick = sweep_bar["high"] - max(sweep_bar["open"], sweep_bar["close"])
        body = abs(sweep_bar["close"] - sweep_bar["open"])
        
        if body > 0 and upper_wick > body * 1.5:
            score += 1
        if sweep_bar["close"] < sweep_bar["open"]:
            score += 1
        if sweep_bar["close"] < resistance:
            score += 1
        
        # Level quality (+2)
        if touches >= 3:
            score += 1
        if 0 <= break_i - sweep_i <= MAX_CONFIRM_BARS:
            score += 1
        
        return score
    
    def get_recent_data(self, symbol):
        """Get recent 1-minute data"""
        try:
            end = datetime.now()
            start = end - timedelta(hours=2)
            
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Minute,
                start=start,
                end=end
            )
            
            bars = self.data_client.get_stock_bars(request)
            if bars and bars.df is not None:
                df = bars.df.reset_index()
                if isinstance(df.index, pd.MultiIndex):
                    df = df.xs(symbol, level="symbol")
                return df
        except Exception as e:
            log.error(f"Error fetching data for {symbol}: {e}")
        
        return None
    
    def check_cooldown(self, symbol):
        """Check if symbol is in cooldown"""
        if symbol not in self.last_trade_time:
            return False
        
        time_since_trade = datetime.now() - self.last_trade_time[symbol]
        return time_since_trade < timedelta(minutes=COOLDOWN_MINUTES)
    
    def scan_symbol(self, symbol):
        """Scan single symbol for BOOF31 setups"""
        if self.check_cooldown(symbol):
            return None
        
        df = self.get_recent_data(symbol)
        if df is None or len(df) < LOOKBACK + 20:
            return None
        
        df = self.add_indicators(df)
        
        for i in range(LOOKBACK + 20, len(df) - MAX_CONFIRM_BARS - 2):
            found, signal = self.detect_short_sequence(df, i)
            
            if not found:
                continue
            
            score = self.score_short_setup(df, signal)
            
            # Different score thresholds for core vs extended universe
            is_core = symbol in CORE_UNIVERSE
            required_score = 3 if is_core else 6
            universe_type = "CORE" if is_core else "EXTENDED"

            log.info(f"SETUP DETECTED: {symbol} ({universe_type}) Score={score}/{required_score} Res=${signal['resistance']:.2f} Touches={signal['touches']} {'✅ TRADING' if score >= required_score else '❌ BELOW THRESHOLD'}")

            if score >= required_score:
                
                # Place short order
                entry_price = df["open"].iloc[signal["entry_i"]]
                self.place_short_order(symbol, entry_price, score, signal)
                
                self.last_trade_time[symbol] = datetime.now()
                return signal
        
        return None
    
    def place_short_order(self, symbol, entry_price, score, signal):
        """Place put option order for resistance sweep setup"""
        try:
            # For now, simulate options trading with stock position
            # TODO: Implement actual options trading when API is available
            
            # Simulate finding a put option around $3.50
            option_price = 3.50  # Target option price
            contracts = 1  # 1 contract = 100 shares
            
            # Calculate equivalent stock position for simulation
            simulated_shares = contracts * 100
            
            # Place market sell order to simulate short position
            order_request = MarketOrderRequest(
                symbol=symbol,
                qty=simulated_shares,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            
            order = self.trading_client.submit_order(order_request)
            
            log.info(f"PUT OPTION SIMULATION: {symbol}")
            log.info(f"   Simulated: {contracts} put option @ ${option_price:.2f}")
            log.info(f"   Equivalent: Short {simulated_shares} shares @ ${entry_price:.2f}")
            log.info(f"   Score: {score} | Resistance: ${signal['resistance']:.2f}")
            log.info(f"   NOTE: Using stock position to simulate options trading")
            
        except Exception as e:
            log.error(f"Error placing simulated put option order for {symbol}: {e}")
    
    def run(self):
        """Main bot loop"""
        log.info("BOOF31 Bot Started - Resistance Sweep Algorithm")
        log.info(f"Parameters: Sweep={SWEEP_BUFFER:.1%}, MinScore={MIN_SCORE}, Cooldown={COOLDOWN_MINUTES}min")
        log.info(f"Watchlist: {', '.join(SYMBOLS)}")
        
        while True:
            try:
                current_time = datetime.now()
                
                # Scan all symbols
                for symbol in SYMBOLS:
                    self.scan_symbol(symbol)
                    time.sleep(0.5)  # Brief pause between symbols
                
                log.info("Heartbeat - Scan complete")
                time.sleep(5)  # Wait 5 seconds between scans
                
            except KeyboardInterrupt:
                log.info("BOOF31 Bot stopped by user")
                break
            except Exception as e:
                log.error(f"Bot error: {e}")
                time.sleep(10)

if __name__ == "__main__":
    bot = BOOF31Bot()
    bot.run()
