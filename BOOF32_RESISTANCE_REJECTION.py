#!/usr/bin/env python3
"""
BOOF 32 - RESISTANCE REJECTION STRATEGY
Based on successful backtest results
Short-only strategy focusing on resistance level rejections
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data import StockHistoricalDataClient, StockLatestQuoteRequest
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# CONFIGURATION
SYMBOLS = ["SPY", "QQQ", "NVDA", "TSLA", "META", "AMZN", "MSFT", "AVGO", "PLTR", "AMD"]
API_KEY = 'PK2O2N4OQ4PEATNTDN57MNSIB7'
API_SECRET = '894T7WQpHVjfLXitiv1cG1ZkGeQsegtWhA2jLocVfCnc'
PAPER_API_KEY = 'PK2O2N4OQ4PEATNTDN57MNSIB7'
PAPER_API_SECRET = '894T7WQpHVjfLXitiv1cG1ZkGeQsegtWhA2jLocVfCnc'

# STRATEGY PARAMETERS
MIN_SCORE = 8  # Only trade setups with score >= 8 (based on backtest results)
MIN_RESISTANCE_TOUCHES = 3  # Need at least 3 touches
RESISTANCE_LOOKBACK = 50  # Look 50 bars for resistance touches
SWING_LOW_LOOKBACK = 10  # For finding swing lows
VOLUME_LOOKBACK = 20  # For average volume
MAX_HOLD_BARS = 30  # Maximum bars to hold position

# RISK MANAGEMENT
RISK_PER_TRADE = 0.02  # 2% risk per trade
MAX_POSITIONS = 5
TP_PCT = 0.005  # 0.5% take profit
SL_PCT = 0.003  # 0.3% stop loss

class Boof32Trader:
    def __init__(self):
        self.trading_client = TradingClient(PAPER_API_KEY, PAPER_API_SECRET, paper=True)
        self.data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
        self.positions = {}
        self.last_signal_time = {}
        
    def resistance_score(self, touches):
        """Resistance score based on touch count"""
        if touches >= 4:
            return 3
        elif touches == 3:
            return 2
        elif touches == 2:
            return 1
        return 0
    
    def rejection_score(self, open_, high, low, close, resistance):
        """Rejection pattern score"""
        score = 0
        body = abs(close - open_)
        wick = high - max(open_, close)
        
        if wick > body * 1.5:
            score += 1
        if close < open_:
            score += 1
        if close < resistance:
            score += 1
        
        return score
    
    def structure_score(self, close, prev_swing_low, vwap, vwap_slope):
        """Structure break score"""
        score = 0
        if close < prev_swing_low:
            score += 1
        if close < vwap:
            score += 1
        if vwap_slope < 0:
            score += 1
        return score
    
    def volume_score(self, rejection_vol, breakdown_vol, expansion_vol, avg_vol):
        """Volume confirmation score"""
        score = 0
        if rejection_vol > avg_vol:
            score += 1
        if breakdown_vol > avg_vol:
            score += 1
        if expansion_vol > avg_vol:
            score += 1
        return score
    
    def find_resistance_levels(self, df):
        """Find resistance levels with touch counts"""
        df = df.copy()
        df['resistance'] = np.nan
        df['resistance_touches'] = 0
        
        for i in range(20, len(df) - 20):
            current_high = df['high'].iloc[i]
            
            # Check if local high
            is_local_high = True
            for j in range(i - 20, i + 21):
                if j != i and df['high'].iloc[j] >= current_high:
                    is_local_high = False
                    break
            
            if is_local_high:
                # Count touches
                tolerance = current_high * 0.005
                touches = 0
                for j in range(max(0, i - RESISTANCE_LOOKBACK), min(len(df), i + RESISTANCE_LOOKBACK)):
                    if abs(df['high'].iloc[j] - current_high) <= tolerance:
                        touches += 1
                
                if touches >= MIN_RESISTANCE_TOUCHES:
                    for j in range(max(0, i - RESISTANCE_LOOKBACK), min(len(df), i + RESISTANCE_LOOKBACK)):
                        if abs(df['high'].iloc[j] - current_high) <= tolerance:
                            if pd.isna(df.loc[df.index[j], 'resistance']) or touches > df.loc[df.index[j], 'resistance_touches']:
                                df.loc[df.index[j], 'resistance'] = current_high
                                df.loc[df.index[j], 'resistance_touches'] = touches
        
        return df
    
    def find_swing_lows(self, df):
        """Find swing lows"""
        df = df.copy()
        df['swing_low'] = np.nan
        
        for i in range(SWING_LOW_LOOKBACK, len(df) - SWING_LOW_LOOKBACK):
            current_low = df['low'].iloc[i]
            is_local_low = True
            for j in range(i - SWING_LOW_LOOKBACK, i + SWING_LOW_LOOKBACK + 1):
                if j != i and df['low'].iloc[j] <= current_low:
                    is_local_low = False
                    break
            
            if is_local_low:
                df.loc[df.index[i], 'swing_low'] = current_low
        
        return df
    
    def add_indicators(self, df):
        """Add technical indicators"""
        df = df.copy()
        typical = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (typical * df['volume']).cumsum() / df['volume'].cumsum()
        df['vwap_slope'] = df['vwap'].pct_change(5)
        df['avg_vol'] = df['volume'].rolling(VOLUME_LOOKBACK).mean()
        return df
    
    def check_setup(self, df, i):
        """Check for resistance rejection setup"""
        if pd.isna(df.loc[df.index[i], 'resistance']):
            return None
        
        resistance = df.loc[df.index[i], 'resistance']
        resistance_touches = df.loc[df.index[i], 'resistance_touches']
        
        # Get previous swing low
        prev_swing_lows = df.loc[:df.index[i-1], 'swing_low'].dropna()
        if len(prev_swing_lows) == 0:
            return None
        prev_swing_low = prev_swing_lows.iloc[-1]
        
        # Get volumes
        if i < 2:
            return None
        
        rejection_vol = df.loc[df.index[i], 'volume']
        breakdown_vol = df.loc[df.index[i-1], 'volume']
        expansion_vol = df.loc[df.index[i-2], 'volume']
        avg_vol = df.loc[df.index[i], 'avg_vol']
        
        # Calculate scores
        res_score = self.resistance_score(resistance_touches)
        rej_score = self.rejection_score(
            df.loc[df.index[i], 'open'],
            df.loc[df.index[i], 'high'],
            df.loc[df.index[i], 'low'],
            df.loc[df.index[i], 'close'],
            resistance
        )
        struct_score = self.structure_score(
            df.loc[df.index[i], 'close'],
            prev_swing_low,
            df.loc[df.index[i], 'vwap'],
            df.loc[df.index[i], 'vwap_slope']
        )
        vol_score = self.volume_score(rejection_vol, breakdown_vol, expansion_vol, avg_vol)
        
        total_score = res_score + rej_score + struct_score + vol_score
        
        if total_score >= MIN_SCORE:
            return {
                'score': total_score,
                'resistance': resistance,
                'resistance_touches': resistance_touches,
                'entry': df.loc[df.index[i], 'close'],
                'components': {
                    'resistance_score': res_score,
                    'rejection_score': rej_score,
                    'structure_score': struct_score,
                    'volume_score': vol_score
                }
            }
        
        return None
    
    def get_latest_data(self, symbol, bars=200):
        """Get latest data for symbol"""
        try:
            end = datetime.now()
            start = end - timedelta(days=7)  # Get last week for enough bars
            
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Minute,
                start=start,
                end=end
            )
            
            bars_data = self.data_client.get_stock_bars(request)
            if bars_data and bars_data.df is not None:
                df = bars_data.df.reset_index()
                return df.tail(bars)  # Return last N bars
        except Exception as e:
            logging.error(f"Error fetching data for {symbol}: {e}")
        
        return None
    
    def scan_for_setups(self):
        """Scan all symbols for resistance rejection setups"""
        setups = []
        
        for symbol in SYMBOLS:
            try:
                # Skip if we already traded this symbol recently
                if symbol in self.last_signal_time:
                    time_since = (datetime.now() - self.last_signal_time[symbol]).total_seconds()
                    if time_since < 300:  # 5 minute cooldown
                        continue
                
                df = self.get_latest_data(symbol)
                if df is None or len(df) < 100:
                    continue
                
                df = self.add_indicators(df)
                df = self.find_resistance_levels(df)
                df = self.find_swing_lows(df)
                
                # Check most recent complete bar
                if len(df) >= 2:
                    setup = self.check_setup(df, -2)  # Second to last bar (most recent complete)
                    if setup:
                        setups.append({
                            'symbol': symbol,
                            'timestamp': df.iloc[-2]['timestamp'],
                            **setup
                        })
                        logging.info(f"SETUP FOUND: {symbol} Score={setup['score']} @ {setup['entry']:.2f}")
                        logging.info(f"  Components: {setup['components']}")
                        logging.info(f"  Resistance: {setup['resistance']:.2f} ({setup['resistance_touches']} touches)")
                        
            except Exception as e:
                logging.error(f"Error scanning {symbol}: {e}")
        
        return setups
    
    def enter_short(self, symbol, entry_price, setup_info):
        """Enter short position"""
        try:
            # Calculate position size
            stop_price = entry_price * (1 + SL_PCT)
            account = self.trading_client.get_account()
            account_value = float(account.equity)
            risk_amount = account_value * RISK_PER_TRADE
            shares = int(risk_amount / (entry_price * SL_PCT))
            
            if shares <= 0:
                return False
            
            # Submit short order
            order = MarketOrderRequest(
                symbol=symbol,
                qty=shares,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            
            trade = self.trading_client.submit_order(order)
            
            # Track position
            self.positions[symbol] = {
                'entry': entry_price,
                'shares': shares,
                'stop': stop_price,
                'target': entry_price * (1 - TP_PCT),
                'timestamp': datetime.now(),
                'setup': setup_info
            }
            
            self.last_signal_time[symbol] = datetime.now()
            
            logging.info(f"SHORT ENTERED: {symbol} {shares} shares @ ${entry_price:.2f}")
            logging.info(f"  Stop: ${stop_price:.2f} (-{SL_PCT:.1%})")
            logging.info(f"  Target: ${self.positions[symbol]['target']:.2f} (-{TP_PCT:.1%})")
            
            return True
            
        except Exception as e:
            logging.error(f"Error entering short {symbol}: {e}")
            return False
    
    def check_exits(self):
        """Check and manage existing positions"""
        for symbol in list(self.positions.keys()):
            try:
                # Get current price
                quote_request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
                quotes = self.data_client.get_stock_latest_quote(quote_request)
                
                if not quotes or symbol not in quotes:
                    continue
                
                current_price = float(quotes[symbol].ask_price)
                position = self.positions[symbol]
                
                # Check stop loss
                if current_price >= position['stop']:
                    self.exit_position(symbol, current_price, 'STOP LOSS')
                    continue
                
                # Check take profit
                if current_price <= position['target']:
                    self.exit_position(symbol, current_price, 'TAKE PROFIT')
                    continue
                
                # Time-based exit
                time_held = (datetime.now() - position['timestamp']).total_seconds() / 60
                if time_held > MAX_HOLD_BARS:
                    self.exit_position(symbol, current_price, 'TIME EXIT')
                
            except Exception as e:
                logging.error(f"Error checking exits for {symbol}: {e}")
    
    def exit_position(self, symbol, exit_price, reason):
        """Exit short position"""
        try:
            position = self.positions[symbol]
            
            # Buy to cover
            order = MarketOrderRequest(
                symbol=symbol,
                qty=position['shares'],
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY
            )
            
            self.trading_client.submit_order(order)
            
            # Calculate PnL
            pnl = (position['entry'] - exit_price) / position['entry'] * position['shares']
            pnl_pct = (position['entry'] - exit_price) / position['entry']
            
            logging.info(f"SHORT EXITED: {symbol} @ ${exit_price:.2f} ({reason})")
            logging.info(f"  PnL: ${pnl:.2f} ({pnl_pct:.2%})")
            logging.info(f"  Setup Score: {position['setup']['score']}")
            
            del self.positions[symbol]
            
        except Exception as e:
            logging.error(f"Error exiting {symbol}: {e}")
    
    def run(self):
        """Main trading loop"""
        logging.info("Boof 32 - Resistance Rejection Strategy Started")
        logging.info(f"Symbols: {SYMBOLS}")
        logging.info(f"Min Score: {MIN_SCORE}")
        logging.info(f"Risk per trade: {RISK_PER_TRADE:.1%}")
        
        while True:
            try:
                # Check if market is open
                now = datetime.now()
                if now.weekday() >= 5:  # Weekend
                    time.sleep(300)
                    continue
                
                if now.hour < 9 or now.hour > 16:  # Outside market hours
                    time.sleep(300)
                    continue
                
                # Check exits first
                self.check_exits()
                
                # Scan for new setups
                if len(self.positions) < MAX_POSITIONS:
                    setups = self.scan_for_setups()
                    
                    for setup in setups:
                        if len(self.positions) >= MAX_POSITIONS:
                            break
                        
                        symbol = setup['symbol']
                        if symbol not in self.positions:
                            self.enter_short(symbol, setup['entry'], setup)
                
                # Wait before next scan
                time.sleep(60)  # Scan every minute
                
            except KeyboardInterrupt:
                logging.info("Shutting down...")
                break
            except Exception as e:
                logging.error(f"Error in main loop: {e}")
                time.sleep(30)

if __name__ == '__main__':
    trader = Boof32Trader()
    trader.run()
