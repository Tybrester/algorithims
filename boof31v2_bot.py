#!/usr/bin/env python3
"""
BOOF 31 v2 - PRODUCTION TRADING BOT
Deployable trading bot for EC2 with real-time execution
"""

import os
import sys
import json
import time
import logging
import pandas as pd
import numpy as np
import alpaca_trade_api as tradeapi
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import threading
import signal
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('boof31v2_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# TRADING PARAMETERS
SYMBOLS = [
    # Tech Giants
    'AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA', 'AVGO', 'AMD', 'NFLX',
    # Cloud/SaaS
    'CRM', 'NOW', 'SNOW', 'PLTR', 'DDOG', 'MDB', 'CRWD', 'ZS', 'NET', 'SHOP',
    # Software
    'ADBE', 'INTU', 'PANW', 'TEAM', 'HUBS', 'UBER', 'ABNB', 'BKNG', 'RBLX', 'DASH',
    # Latin America/E-commerce
    'MELI', 'ETSY',
    # Financials
    'JPM', 'GS', 'MS', 'BAC', 'WFC', 'AXP', 'COF', 'SCHW', 'BLK', 'SPGI',
    # Healthcare/Biotech
    'LLY', 'NVO', 'UNH', 'ISRG', 'VRTX', 'REGN', 'MRNA', 'BIIB', 'GILD', 'BMY',
    # Industrial/Defense
    'GE', 'RTX', 'LMT', 'BA', 'CAT', 'DE', 'ETN', 'PH', 'TT',
    # Energy
    'XOM', 'CVX', 'COP', 'SLB', 'HAL', 'OXY', 'EOG', 'MPC', 'VLO', 'DVN',
    # Telecom/Media
    'TMUS', 'CMCSA', 'ROKU', 'SPOT', 'PINS', 'SNAP', 'RDDT', 'COIN',
    # Semiconductor/Hardware
    'MSTR', 'HOOD', 'SMCI', 'ARM', 'MU', 'QCOM', 'MRVL', 'TSM', 'ASML',
    # Semicap Equipment
    'AMAT', 'LRCX', 'KLAC', 'MCHP', 'ON', 'NXPI',
    # ETFs
    'SPY', 'QQQ', 'IWM', 'SMH'
]

# STRATEGY PARAMETERS
SWEEP_OPTIMIZED = 0.0020  # 0.20% sweep
TP1 = 0.0050             # 0.50% first target
SL_OPTIMIZED = 0.0025     # 0.25% SL
COOLDOWN_MINUTES = 30
MIN_SCORE = 6
SLIPPAGE = 0.0005         # 0.05% slippage

# RISK MANAGEMENT
MAX_POSITIONS = 8
RISK_PER_TRADE = 0.01     # 1% risk per trade
MAX_DAILY_LOSS = 0.02     # 2% max daily loss
POSITION_SIZE_USD = 1000  # Fixed position size

class BOOF31V2Bot:
    def __init__(self):
        self.api_key = os.getenv('ALPACA_API_KEY')
        self.api_secret = os.getenv('ALPACA_API_SECRET')
        self.base_url = 'https://paper-api.alpaca.markets'
        
        if not self.api_key or not self.api_secret:
            raise ValueError("Please set ALPACA_API_KEY and ALPACA_API_SECRET environment variables")
        
        # Initialize Alpaca API
        self.api = tradeapi.REST(
            self.api_key,
            self.api_secret,
            self.base_url,
            api_version='v2'
        )
        
        # Initialize WebSocket
        self.stream = tradeapi.StreamConn(
            self.api_key,
            self.api_secret,
            base_url='https://paper-api.alpaca.markets'
        )
        
        # Bot state
        self.running = False
        self.positions = {}
        self.last_trade_time = {}
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.trade_log = []
        
        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        
        logger.info("BOOF 31 v2 Bot initialized")
    
    def calculate_boof_score(self, symbol: str) -> int:
        """Calculate BOOF score for a symbol"""
        try:
            # Get recent data
            bars = self.api.get_bars(
                symbol,
                tradeapi.TimeFrame.Minute,
                limit=100
            ).df
            
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
            logger.error(f"Error calculating BOOF score for {symbol}: {e}")
            return 0
    
    def check_sweep_condition(self, symbol: str) -> bool:
        """Check if sweep condition is met"""
        try:
            # Get recent price action
            bars = self.api.get_bars(
                symbol,
                tradeapi.TimeFrame.Minute,
                limit=10
            ).df
            
            if len(bars) < 5:
                return False
            
            # Check for sweep (simplified - look for price spike above resistance)
            latest = bars.iloc[-1]
            previous = bars.iloc[-2]
            
            # Calculate resistance
            resistance = bars['high'].rolling(window=5).max().iloc[-2]
            
            # Check if price swept above resistance
            if latest['close'] > resistance * 1.002:  # 0.2% sweep
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking sweep condition for {symbol}: {e}")
            return False
    
    def check_cooldown(self, symbol: str) -> bool:
        """Check if cooldown period has passed"""
        if symbol not in self.last_trade_time:
            return True
        
        time_since_last = datetime.now() - self.last_trade_time[symbol]
        return time_since_last.total_seconds() >= COOLDOWN_MINUTES * 60
    
    def calculate_position_size(self, symbol: str) -> int:
        """Calculate position size based on risk management"""
        try:
            # Get current price
            current_price = self.api.get_latest_trade(symbol).price
            
            # Calculate shares based on fixed position size
            shares = int(POSITION_SIZE_USD / current_price)
            
            # Ensure minimum order size
            if shares < 1:
                shares = 1
            
            return shares
            
        except Exception as e:
            logger.error(f"Error calculating position size for {symbol}: {e}")
            return 0
    
    def enter_short_position(self, symbol: str, score: int):
        """Enter short position"""
        try:
            # Check if we already have position
            if symbol in self.positions:
                return
            
            # Check cooldown
            if not self.check_cooldown(symbol):
                return
            
            # Calculate position size
            shares = self.calculate_position_size(symbol)
            if shares == 0:
                return
            
            # Submit short order
            order = self.api.submit_order(
                symbol=symbol,
                qty=shares,
                side='sell',
                type='market',
                time_in_force='day'
            )
            
            # Track position
            entry_price = self.api.get_latest_trade(symbol).price
            self.positions[symbol] = {
                'order_id': order.id,
                'shares': shares,
                'entry_price': entry_price,
                'entry_time': datetime.now(),
                'score': score,
                'exit1_triggered': False,
                'stop_loss': entry_price * (1 + SL_OPTIMIZED),
                'target1': entry_price * (1 - TP1),
                'trail_stop': entry_price * (1 + SL_OPTIMIZED)
            }
            
            self.last_trade_time[symbol] = datetime.now()
            self.daily_trades += 1
            
            logger.info(f"Entered short position in {symbol}: {shares} shares @ {entry_price:.2f} (Score: {score})")
            
            # Log trade
            self.trade_log.append({
                'timestamp': datetime.now(),
                'symbol': symbol,
                'action': 'SHORT',
                'shares': shares,
                'price': entry_price,
                'score': score
            })
            
        except Exception as e:
            logger.error(f"Error entering short position in {symbol}: {e}")
    
    def manage_positions(self):
        """Manage existing positions with Exit C strategy"""
        try:
            positions_to_close = []
            
            for symbol, position in list(self.positions.items()):
                try:
                    # Get current price
                    current_price = self.api.get_latest_trade(symbol).price
                    
                    # Calculate unrealized PnL
                    unrealized_pnl = (position['entry_price'] - current_price) / position['entry_price']
                    
                    # Exit C logic: 50% at 0.50% target
                    if not position['exit1_triggered'] and current_price <= position['target1']:
                        # Close 50% of position
                        exit_shares = position['shares'] // 2
                        if exit_shares > 0:
                            self.api.submit_order(
                                symbol=symbol,
                                qty=exit_shares,
                                side='buy',
                                type='market',
                                time_in_force='day'
                            )
                            
                            position['shares'] -= exit_shares
                            position['exit1_triggered'] = True
                            
                            # Update trailing stop
                            position['trail_stop'] = current_price * (1 + SL_OPTIMIZED)
                            
                            logger.info(f"Exit 1 triggered for {symbol}: {exit_shares} shares @ {current_price:.2f}")
                    
                    # Trailing stop for remaining position
                    if position['exit1_triggered']:
                        # Update trailing stop if price moved favorably
                        new_trail_stop = current_price * (1 + SL_OPTIMIZED)
                        if new_trail_stop < position['trail_stop']:
                            position['trail_stop'] = new_trail_stop
                        
                        # Check trailing stop
                        if current_price >= position['trail_stop']:
                            positions_to_close.append(symbol)
                            logger.info(f"Trailing stop triggered for {symbol} @ {current_price:.2f}")
                    
                    # Stop loss check
                    if current_price >= position['stop_loss']:
                        positions_to_close.append(symbol)
                        logger.info(f"Stop loss triggered for {symbol} @ {current_price:.2f}")
                    
                except Exception as e:
                    logger.error(f"Error managing position {symbol}: {e}")
                    positions_to_close.append(symbol)
            
            # Close positions that need to be closed
            for symbol in positions_to_close:
                self.close_position(symbol)
                
        except Exception as e:
            logger.error(f"Error managing positions: {e}")
    
    def close_position(self, symbol: str):
        """Close position and log results"""
        try:
            if symbol not in self.positions:
                return
            
            position = self.positions[symbol]
            current_price = self.api.get_latest_trade(symbol).price
            
            # Close remaining shares
            if position['shares'] > 0:
                self.api.submit_order(
                    symbol=symbol,
                    qty=position['shares'],
                    side='buy',
                    type='market',
                    time_in_force='day'
                )
            
            # Calculate PnL
            total_pnl = (position['entry_price'] - current_price) / position['entry_price']
            self.daily_pnl += total_pnl
            self.total_pnl += total_pnl
            
            # Update statistics
            self.total_trades += 1
            if total_pnl > 0:
                self.winning_trades += 1
            else:
                self.losing_trades += 1
            
            logger.info(f"Closed position {symbol}: PnL {total_pnl:.2%}")
            
            # Log trade
            self.trade_log.append({
                'timestamp': datetime.now(),
                'symbol': symbol,
                'action': 'COVER',
                'shares': position['shares'],
                'price': current_price,
                'pnl': total_pnl,
                'score': position['score']
            })
            
            # Remove from positions
            del self.positions[symbol]
            
        except Exception as e:
            logger.error(f"Error closing position {symbol}: {e}")
    
    def scan_for_opportunities(self):
        """Scan all symbols for trading opportunities"""
        try:
            for symbol in SYMBOLS:
                try:
                    # Check if we can trade this symbol
                    if symbol in self.positions:
                        continue
                    
                    if len(self.positions) >= MAX_POSITIONS:
                        break
                    
                    # Check cooldown
                    if not self.check_cooldown(symbol):
                        continue
                    
                    # Calculate BOOF score
                    score = self.calculate_boof_score(symbol)
                    
                    if score >= MIN_SCORE:
                        # Check sweep condition
                        if self.check_sweep_condition(symbol):
                            self.enter_short_position(symbol, score)
                    
                    # Small delay to avoid API rate limits
                    time.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"Error scanning {symbol}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error scanning for opportunities: {e}")
    
    def check_risk_limits(self):
        """Check if risk limits are breached"""
        try:
            # Check daily loss limit
            if self.daily_pnl <= -MAX_DAILY_LOSS:
                logger.warning(f"Daily loss limit reached: {self.daily_pnl:.2%}")
                self.emergency_close_all()
                return False
            
            # Check position limits
            if len(self.positions) > MAX_POSITIONS:
                logger.warning(f"Too many positions: {len(self.positions)}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking risk limits: {e}")
            return False
    
    def emergency_close_all(self):
        """Emergency close all positions"""
        try:
            logger.warning("Emergency close all positions!")
            
            for symbol in list(self.positions.keys()):
                self.close_position(symbol)
                
        except Exception as e:
            logger.error(f"Error in emergency close: {e}")
    
    def get_performance_stats(self) -> Dict:
        """Get performance statistics"""
        try:
            win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0
            
            return {
                'total_trades': self.total_trades,
                'winning_trades': self.winning_trades,
                'losing_trades': self.losing_trades,
                'win_rate': win_rate,
                'total_pnl': self.total_pnl,
                'daily_pnl': self.daily_pnl,
                'daily_trades': self.daily_trades,
                'open_positions': len(self.positions),
                'active_symbols': list(self.positions.keys())
            }
            
        except Exception as e:
            logger.error(f"Error getting performance stats: {e}")
            return {}
    
    def log_performance(self):
        """Log performance statistics"""
        try:
            stats = self.get_performance_stats()
            
            logger.info(f"""
Performance Update:
Total Trades: {stats['total_trades']}
Win Rate: {stats['win_rate']:.1%}
Total PnL: {stats['total_pnl']:.2%}
Daily PnL: {stats['daily_pnl']:.2%}
Open Positions: {stats['open_positions']}
Active Symbols: {stats['active_symbols']}
            """)
            
        except Exception as e:
            logger.error(f"Error logging performance: {e}")
    
    def run(self):
        """Main bot loop"""
        logger.info("Starting BOOF 31 v2 Bot...")
        self.running = True
        
        try:
            while self.running:
                try:
                    # Check if market is open
                    clock = self.api.get_clock()
                    if not clock.is_open:
                        logger.info("Market is closed. Waiting...")
                        time.sleep(60)
                        continue
                    
                    # Check risk limits
                    if not self.check_risk_limits():
                        time.sleep(60)
                        continue
                    
                    # Manage existing positions
                    self.manage_positions()
                    
                    # Scan for new opportunities
                    self.scan_for_opportunities()
                    
                    # Log performance every 10 minutes
                    if datetime.now().minute % 10 == 0:
                        self.log_performance()
                    
                    # Wait before next iteration
                    time.sleep(60)  # Check every minute
                    
                except KeyboardInterrupt:
                    logger.info("Received interrupt signal...")
                    break
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    time.sleep(60)
                    
        except Exception as e:
            logger.error(f"Fatal error: {e}")
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Shutdown the bot"""
        logger.info("Shutting down BOOF 31 v2 Bot...")
        self.running = False
        
        # Close all positions
        self.emergency_close_all()
        
        # Save trade log
        try:
            if self.trade_log:
                df = pd.DataFrame(self.trade_log)
                df.to_csv(f'trade_log_{datetime.now().strftime("%Y%m%d")}.csv', index=False)
                logger.info("Trade log saved")
        except Exception as e:
            logger.error(f"Error saving trade log: {e}")
        
        logger.info("Bot shutdown complete")

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info("Received shutdown signal")
    raise KeyboardInterrupt

def main():
    """Main function"""
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create and run bot
    try:
        bot = BOOF31V2Bot()
        bot.run()
    except Exception as e:
        logger.error(f"Bot failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
