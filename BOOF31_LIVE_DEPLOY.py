#!/usr/bin/env python3
"""
BOOF 31 - STRUCTURE + TREND + VOLUME STARTER
Live Deployment on Alpaca Paper

Strategy: Pivot-based entries with trend confirmation and volume surge
- Long: Near support pivot, trend up, dry volume pullback, green candle
- Short: Near resistance pivot, trend down, dry volume pullback, red candle
"""

import os
import time
import logging
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import pandas as pd
import numpy as np

# Alpaca API Keys - Boof 23/30 account
API_KEY = 'PK2O2N4OQ4PEATNTDN57MNSIB7'
API_SECRET = '894T7WQpHVjfLXitiv1cG1ZkGeQsegtWhA2jLocVfCnc'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('boof31_paper.log'),
        logging.StreamHandler()
    ]
)

# Core Universe - 12 liquid stocks
CORE_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMD", "META", "AMZN",
    "PLTR", "SOFI", "HOOD", "CRWD", "AVGO", "TSLA"
]

# Strategy Parameters
PARAMS = {
    'tp': 0.005,        # +0.50%
    'sl': 0.004,        # -0.40%
    'max_hold_bars': 30,
    'pivot_lookback': 5,
    'zone_tolerance': 0.003,  # 0.30%
    'vol_lookback': 20,
    'trend_score_min': 3,     # Need 3+ of 4 trend criteria
}

RISK_PER_TRADE = 500  # $500 per trade
MAX_POSITIONS = 3

class Boof31Trader:
    def __init__(self):
        self.trading_client = TradingClient(API_KEY, API_SECRET, paper=True)
        self.data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
        self.positions = {}
        self.last_signal_time = {}
        self.account = self.trading_client.get_account()
        logging.info(f"BOOF 31 initialized. Equity: ${self.account.equity}")
        
    def get_bars(self, symbols, lookback_minutes=40):
        """Fetch 1m bars for indicators"""
        try:
            now = datetime.now(ZoneInfo("America/New_York"))
            start = now - timedelta(minutes=lookback_minutes)
            
            request = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Minute,
                start=start,
                end=now
            )
            bars = self.data_client.get_stock_bars(request)
            return bars.df.reset_index() if bars else None
        except Exception as e:
            logging.warning(f"Bar fetch error: {e}")
            return None
    
    def add_indicators(self, df):
        """Add VWAP, RVOL, slope"""
        df = df.copy()
        typical = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (typical * df['volume']).cumsum() / df['volume'].cumsum()
        df['vol_avg'] = df['volume'].rolling(PARAMS['vol_lookback']).mean()
        df['rvol'] = df['volume'] / df['vol_avg']
        df['vwap_slope'] = df['vwap'].pct_change(5)
        return df
    
    def find_pivots(self, df):
        """Find pivot highs and lows"""
        df = df.copy()
        df['pivot_high'] = False
        df['pivot_low'] = False
        lb = PARAMS['pivot_lookback']
        
        for i in range(lb, len(df) - lb):
            high_window = df['high'].iloc[i-lb:i+lb+1]
            low_window = df['low'].iloc[i-lb:i+lb+1]
            
            if df['high'].iloc[i] == high_window.max():
                df.at[df.index[i], 'pivot_high'] = True
            if df['low'].iloc[i] == low_window.min():
                df.at[df.index[i], 'pivot_low'] = True
        
        return df
    
    def recent_pivots(self, df, idx, lookback=80):
        """Get recent pivot highs/lows"""
        start = max(0, idx - lookback)
        chunk = df.iloc[start:idx]
        highs = chunk[chunk['pivot_high']]
        lows = chunk[chunk['pivot_low']]
        return highs, lows
    
    def is_near_zone(self, price, pivot_prices):
        """Check if price is near pivot zone"""
        if len(pivot_prices) == 0:
            return False
        tolerance = PARAMS['zone_tolerance']
        for p in pivot_prices:
            if abs(price - p) / price <= tolerance:
                return True
        return False
    
    def trend_score_long(self, df, i, highs, lows):
        """Calculate long trend score (0-4)"""
        score = 0
        
        # Higher highs
        if len(highs) >= 2:
            last_highs = highs['high'].tail(2).values
            if last_highs[-1] > last_highs[-2]:
                score += 1
        
        # Higher lows
        if len(lows) >= 2:
            last_lows = lows['low'].tail(2).values
            if last_lows[-1] > last_lows[-2]:
                score += 1
        
        # Price above VWAP
        if df['close'].iloc[i] > df['vwap'].iloc[i]:
            score += 1
        
        # VWAP slope positive
        if df['vwap_slope'].iloc[i] > 0:
            score += 1
        
        return score
    
    def trend_score_short(self, df, i, highs, lows):
        """Calculate short trend score (0-4)"""
        score = 0
        
        # Lower highs
        if len(highs) >= 2:
            last_highs = highs['high'].tail(2).values
            if last_highs[-1] < last_highs[-2]:
                score += 1
        
        # Lower lows
        if len(lows) >= 2:
            last_lows = lows['low'].tail(2).values
            if last_lows[-1] < last_lows[-2]:
                score += 1
        
        # Price below VWAP
        if df['close'].iloc[i] < df['vwap'].iloc[i]:
            score += 1
        
        # VWAP slope negative
        if df['vwap_slope'].iloc[i] < 0:
            score += 1
        
        return score
    
    def check_long_signal(self, df, i, highs, lows):
        """Check for long entry signal"""
        if i < 40:
            return False
        
        score = self.trend_score_long(df, i, highs, lows)
        support_prices = lows['low'].values if len(lows) else []
        near_support = self.is_near_zone(df['low'].iloc[i], support_prices)
        
        # Volume conditions
        pullback_dry = df['volume'].iloc[i-1] < df['vol_avg'].iloc[i-1]
        bounce_volume = df['volume'].iloc[i] > df['vol_avg'].iloc[i]
        green_candle = df['close'].iloc[i] > df['open'].iloc[i]
        
        return (
            score >= PARAMS['trend_score_min']
            and near_support
            and pullback_dry
            and bounce_volume
            and green_candle
        )
    
    def check_short_signal(self, df, i, highs, lows):
        """Check for short entry signal"""
        if i < 40:
            return False
        
        score = self.trend_score_short(df, i, highs, lows)
        resistance_prices = highs['high'].values if len(highs) else []
        near_resistance = self.is_near_zone(df['high'].iloc[i], resistance_prices)
        
        # Volume conditions
        pullback_dry = df['volume'].iloc[i-1] < df['vol_avg'].iloc[i-1]
        rejection_volume = df['volume'].iloc[i] > df['vol_avg'].iloc[i]
        red_candle = df['close'].iloc[i] < df['open'].iloc[i]
        
        return (
            score >= PARAMS['trend_score_min']
            and near_resistance
            and pullback_dry
            and rejection_volume
            and red_candle
        )
    
    def scan_for_signals(self):
        """Scan universe for entry signals"""
        signals = []
        
        df = self.get_bars(CORE_UNIVERSE, lookback_minutes=100)
        if df is None or df.empty:
            return signals
        
        for symbol in CORE_UNIVERSE:
            if symbol in self.positions:
                continue
            
            sym_data = df[df['symbol'] == symbol].sort_values('timestamp')
            if len(sym_data) < 60:
                continue
            
            # Add indicators
            sym_data = self.add_indicators(sym_data)
            sym_data = self.find_pivots(sym_data)
            
            # Get last 2 complete bars
            if len(sym_data) < 3:
                continue
            
            i = len(sym_data) - 2  # Last complete bar
            highs, lows = self.recent_pivots(sym_data, i)
            
            # Check signal freshness
            b_timestamp = sym_data['timestamp'].iloc[i]
            now = datetime.now(ZoneInfo("America/New_York"))
            signal_age = (now - b_timestamp).total_seconds()
            if signal_age > 120:  # Skip old signals
                continue
            
            # Check cooldown
            if symbol in self.last_signal_time:
                last = self.last_signal_time[symbol]
                if abs((b_timestamp - last).total_seconds()) < 300:
                    continue
            
            # Check signals
            long_sig = self.check_long_signal(sym_data, i, highs, lows)
            short_sig = self.check_short_signal(sym_data, i, highs, lows)
            
            if long_sig or short_sig:
                direction = 'long' if long_sig else 'short'
                score = self.trend_score_long(sym_data, i, highs, lows) if long_sig else self.trend_score_short(sym_data, i, highs, lows)
                
                self.last_signal_time[symbol] = b_timestamp
                signals.append({
                    'symbol': symbol,
                    'direction': direction,
                    'score': score,
                    'entry': sym_data['close'].iloc[i],
                    'vwap': sym_data['vwap'].iloc[i],
                    'rvol': sym_data['rvol'].iloc[i],
                    'signal_time': b_timestamp
                })
                logging.info(f'FRESH SIGNAL: {symbol} {direction.upper()} Score={score} @ {b_timestamp.strftime("%H:%M:%S")}')
        
        return signals
    
    def submit_order(self, symbol, side, qty):
        """Submit market order"""
        try:
            order = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.DAY
            )
            result = self.trading_client.submit_order(order)
            logging.info(f'ORDER SUBMITTED: {symbol} {side.value} {qty} shares')
            return result
        except Exception as e:
            logging.error(f'Order error: {e}')
            return None
    
    def manage_positions(self):
        """Manage open positions - check TP/SL"""
        positions = self.trading_client.get_all_positions()
        
        for pos in positions:
            symbol = pos.symbol
            entry = float(pos.avg_entry_price)
            current = float(pos.current_price)
            qty = int(float(pos.qty))
            
            # Calculate P&L %
            pnl_pct = (current - entry) / entry if qty > 0 else (entry - current) / entry
            
            # Check TP
            if pnl_pct >= PARAMS['tp']:
                side = OrderSide.SELL if qty > 0 else OrderSide.BUY
                self.submit_order(symbol, side, abs(qty))
                logging.info(f'TP HIT: {symbol} {pnl_pct:.2%}')
                if symbol in self.positions:
                    del self.positions[symbol]
                continue
            
            # Check SL
            if pnl_pct <= -PARAMS['sl']:
                side = OrderSide.SELL if qty > 0 else OrderSide.BUY
                self.submit_order(symbol, side, abs(qty))
                logging.info(f'SL HIT: {symbol} {pnl_pct:.2%}')
                if symbol in self.positions:
                    del self.positions[symbol]
                continue
    
    def run(self):
        """Main trading loop"""
        logging.info('='*60)
        logging.info('BOOF 31 - STRUCTURE + TREND + VOLUME STARTER')
        logging.info(f'Universe: {len(CORE_UNIVERSE)} symbols')
        logging.info(f'TP: {PARAMS["tp"]:.2%} | SL: {PARAMS["sl"]:.2%}')
        logging.info('='*60)
        
        ny_tz = ZoneInfo("America/New_York")
        
        while True:
            try:
                now = datetime.now(ny_tz)
                
                # Market hours check
                if not self.is_market_open(now):
                    logging.info(f'[{now.strftime("%H:%M")}] Market closed - sleeping')
                    time.sleep(60)
                    continue
                
                # Manage positions (TP/SL check)
                self.manage_positions()
                
                # Check position limit
                positions = self.trading_client.get_all_positions()
                if len(positions) >= MAX_POSITIONS:
                    time.sleep(30)
                    continue
                
                # Scan for signals
                signals = self.scan_for_signals()
                for signal in signals[:MAX_POSITIONS - len(positions)]:
                    # Calculate position size ($500 risk)
                    qty = max(1, int(RISK_PER_TRADE / signal['entry']))
                    
                    side = OrderSide.BUY if signal['direction'] == 'long' else OrderSide.SELL
                    order = self.submit_order(signal['symbol'], side, qty)
                    
                    if order:
                        self.positions[signal['symbol']] = {
                            'entry': signal['entry'],
                            'direction': signal['direction'],
                            'qty': qty,
                            'entry_time': now
                        }
                
                time.sleep(30)
                
            except Exception as e:
                logging.error(f'Main loop error: {e}')
                time.sleep(30)
    
    def is_market_open(self, now):
        """Check if market is open"""
        if now.weekday() >= 5:
            return False
        market_open = dtime(9, 30)
        market_close = dtime(16, 0)
        return market_open <= now.time() <= market_close

if __name__ == '__main__':
    trader = Boof31Trader()
    trader.run()
