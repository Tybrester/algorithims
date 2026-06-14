import pandas as pd
import numpy as np
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import time
import warnings
import logging
warnings.filterwarnings('ignore')

# Setup logging to match Boof 23/29 format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-5s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# PAPER TRADING KEYS
API_KEY = 'PK7OQWKVUULJ7KRHMOQTUQS3QX'
API_SECRET = 'AFJBzr795JzeLwCtEMfyuHR7xE7xq1euTNCbYrD22xUd'

# Initialize clients
trading_client = TradingClient(API_KEY, API_SECRET, paper=True)
data_client = StockHistoricalDataClient(API_KEY, API_SECRET)

# UNIVERSES
CORE_UNIVERSE = [
    # FinTech / SaaS
    'UPST', 'AFRM', 'PLTR', 'RBLX', 'LMND', 'ROOT', 'SOFI', 'HOOD', 'DASH',
    'SNOW', 'NET', 'DDOG', 'CRWD', 'CFLT', 'SHOP',
    # Semis / Hardware
    'NVDA', 'AMD', 'AVGO', 'ARM', 'SMCI', 'MU', 'TSM', 'MRVL', 'ANET',
    # Crypto
    'COIN', 'MSTR', 'RIOT', 'MARA', 'HUT', 'CLSK', 'BTBT', 'BITF', 'IREN',
    # Space
    'RKLB', 'LUNR', 'ASTS', 'RDW', 'SPIR', 'SPCX',
    # EVs
    'TSLA', 'RIVN', 'LCID', 'NIO', 'XPEV'
]

EXTENDED_UNIVERSE = [
    'IONQ', 'SOUN', 'SERV', 'CVNA', 'DUOL', 'CAVA', 'HIMS',
    'BKSY', 'INTA', 'ACHR', 'SPCE', 'PL', 'VORB',
    'INTC', 'QCOM', 'LRCX', 'TXN', 'ASML',
    'COMP', 'DNUT', 'U', 'S', 'ZS', 'PANW', 'FTNT',
    'LI', 'PSNY', 'FSR', 'GOEV'
]

# PARAMETERS
PARAMS = {'rvol': 3, 'bar1_body': 0.5, 'vwap_slope': 0.25, 'bar2_body': 0.3}
TP_1, TP_2, SL = 1.0, 1.75, 1.0

# RISK SETTINGS
RISK_PER_TRADE = 0.05  # 5% of account
MAX_POSITIONS = 5
WIDE_SPREAD_THRESHOLD = 0.005  # 0.5% spread

class Boof30Trader:
    def __init__(self):
        self.positions = {}  # Track active positions
        self.trade_log = []
        
    def get_account_value(self):
        """Get current account equity"""
        account = trading_client.get_account()
        return float(account.equity)
    
    def get_position_size(self, entry_price, stop_price):
        """Calculate position size based on 5% risk"""
        account_value = self.get_account_value()
        risk_amount = account_value * RISK_PER_TRADE
        risk_per_share = abs(entry_price - stop_price)
        
        if risk_per_share == 0:
            return 0
        
        shares = int(risk_amount / risk_per_share)
        max_shares = int(account_value * 0.25 / entry_price)  # Max 25% in one trade
        return min(shares, max_shares)
    
    def check_spread(self, bar):
        """Check if spread is too wide"""
        spread = (bar['ask'] - bar['bid']) / bar['bid'] if 'ask' in bar and 'bid' in bar else 0
        return spread > WIDE_SPREAD_THRESHOLD
    
    def enter_position(self, symbol, entry_price, is_core=True):
        """Enter a new position with partial exit setup"""
        try:
            # Calculate position size
            stop_price = entry_price * (1 - SL/100)
            shares = self.get_position_size(entry_price, stop_price)
            
            if shares < 1:
                print(f"  Risk too high or account too small for {symbol}")
                return False
            
            # Check current positions
            current_positions = len(self.positions)
            if current_positions >= MAX_POSITIONS:
                print(f"  Max positions ({MAX_POSITIONS}) reached, skipping {symbol}")
                return False
            
            # Check if already in position
            if symbol in self.positions:
                print(f"  Already in position for {symbol}")
                return False
            
            # Place limit order for wide spreads, market for tight
            spread_wide = self.check_spread({'bid': entry_price * 0.999, 'ask': entry_price * 1.001})
            
            if spread_wide:
                # Limit order slightly above entry
                order = LimitOrderRequest(
                    symbol=symbol,
                    qty=shares,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                    limit_price=round(entry_price * 1.002, 2)
                )
            else:
                order = MarketOrderRequest(
                    symbol=symbol,
                    qty=shares,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY
                )
            
            submitted = trading_client.submit_order(order)
            
            # Track position
            self.positions[symbol] = {
                'entry_price': entry_price,
                'shares': shares,
                'tp1_price': entry_price * (1 + TP_1/100),
                'tp2_price': entry_price * (1 + TP_2/100),
                'sl_price': stop_price,
                'tp1_hit': False,
                'entry_time': datetime.now(),
                'is_core': is_core,
                'order_id': submitted.id
            }
            
            print(f"  ✓ ENTERED {symbol}: {shares} shares @ ${entry_price:.2f}")
            print(f"    TP1: ${self.positions[symbol]['tp1_price']:.2f} (+1%)")
            print(f"    TP2: ${self.positions[symbol]['tp2_price']:.2f} (+1.75%)")
            print(f"    SL: ${stop_price:.2f} (-1%)")
            
            return True
            
        except Exception as e:
            print(f"  Error entering {symbol}: {e}")
            return False
    
    def check_exits(self, symbol, current_price):
        """Check and execute exits"""
        if symbol not in self.positions:
            return
        
        pos = self.positions[symbol]
        
        # Check SL
        if current_price <= pos['sl_price']:
            self.exit_position(symbol, current_price, 'STOP LOSS')
            return
        
        # Check TP1 (50%)
        if not pos['tp1_hit'] and current_price >= pos['tp1_price']:
            try:
                # Sell 50%
                half_shares = pos['shares'] // 2
                if half_shares > 0:
                    order = MarketOrderRequest(
                        symbol=symbol,
                        qty=half_shares,
                        side=OrderSide.SELL,
                        time_in_force=TimeInForce.DAY
                    )
                    trading_client.submit_order(order)
                    pos['shares'] -= half_shares
                    pos['tp1_hit'] = True
                    pos['tp1_price_actual'] = current_price
                    print(f"  ✓ TP1 HIT {symbol}: Sold {half_shares} shares @ ${current_price:.2f} (+1%)")
            except Exception as e:
                print(f"  Error at TP1 for {symbol}: {e}")
        
        # Check TP2 (remaining 50%)
        if pos['tp1_hit'] and current_price >= pos['tp2_price']:
            self.exit_position(symbol, current_price, 'TP2 FULL')
    
    def exit_position(self, symbol, exit_price, reason):
        """Exit remaining position"""
        try:
            pos = self.positions[symbol]
            
            if pos['shares'] > 0:
                order = MarketOrderRequest(
                    symbol=symbol,
                    qty=pos['shares'],
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY
                )
                trading_client.submit_order(order)
            
            # Calculate P&L
            entry = pos['entry_price']
            if pos['tp1_hit']:
                # Half at TP1, half at exit
                pnl = (TP_1 + (exit_price - entry) / entry * 100) / 2
            else:
                pnl = (exit_price - entry) / entry * 100
            
            print(f"  ✓ EXIT {symbol}: ${exit_price:.2f} | {reason} | P&L: {pnl:+.2f}%")
            
            # Log trade
            self.trade_log.append({
                'symbol': symbol,
                'entry': entry,
                'exit': exit_price,
                'pnl_pct': pnl,
                'reason': reason,
                'is_core': pos['is_core'],
                'time': datetime.now().strftime('%H:%M:%S')
            })
            
            del self.positions[symbol]
            
        except Exception as e:
            print(f"  Error exiting {symbol}: {e}")
    
    def __init__(self):
        self.positions = {}
        self.trade_log = []
        self.last_signal_time = {}  # Track last signal per symbol to avoid duplicates
        
    def scan_for_signals(self, symbols, score_thresh, is_core=True):
        """Scan for 2-bar ignition patterns - with fresh signal detection"""
        signals = []
        
        try:
            # Get 30 minutes of data for accurate VWAP/RVOL calculation
            now = datetime.now()
            start = now - timedelta(minutes=30)
            
            request = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Minute,
                start=start,
                end=now
            )
            
            bars = data_client.get_stock_bars(request)
            df = bars.df.reset_index()
            
            # Group by symbol
            for symbol in symbols:
                if symbol in self.positions:
                    continue
                
                sym_data = df[df['symbol'] == symbol].sort_values('timestamp')
                
                if len(sym_data) < 25:  # Need at least 25 bars for proper VWAP
                    continue
                
                # Calculate metrics
                sym_data['vwap'] = ((sym_data['high'] + sym_data['low'] + sym_data['close']) / 3 * sym_data['volume']).cumsum() / sym_data['volume'].cumsum()
                sym_data['avg_vol'] = sym_data['volume'].rolling(20, min_periods=20).mean()
                sym_data['rvol'] = sym_data['volume'] / sym_data['avg_vol']
                sym_data['body'] = abs(sym_data['close'] - sym_data['open']) / sym_data['open']
                sym_data['vwap_slope'] = sym_data['vwap'].diff(10) / sym_data['vwap'].shift(10) * 100
                
                # Get last 2 complete bars (skip current in-progress bar)
                if len(sym_data) >= 3:
                    b1 = sym_data.iloc[-3]  # 2 bars ago
                    b2 = sym_data.iloc[-2]  # 1 bar ago (most recent complete bar)
                    b2_timestamp = b2['timestamp']
                    
                    # Skip if we already traded this signal (1 min cooldown)
                    if symbol in self.last_signal_time:
                        last_time = self.last_signal_time[symbol]
                        if abs((b2_timestamp - last_time).total_seconds()) < 60:  # 1 min cooldown
                            continue
                    
                    # 2-bar long ignition pattern
                    if (b1['body'] >= 0.004 and b1['rvol'] >= 2.0 and b2['rvol'] >= 1.5 and 
                        b1['close'] > b1['vwap'] and b2['close'] > b2['vwap'] and b2['close'] > b1['high']):
                        
                        # Calculate Score
                        score = 0
                        if b1['rvol'] > PARAMS['rvol']: score += 1
                        if b1['body'] * 100 > PARAMS['bar1_body']: score += 1
                        if b1['vwap_slope'] > PARAMS['vwap_slope']: score += 1
                        if b2['body'] * 100 > PARAMS['bar2_body']: score += 1
                        
                        if score >= score_thresh:
                            # Record this signal time
                            self.last_signal_time[symbol] = b2_timestamp
                            
                            signals.append({
                                'symbol': symbol,
                                'score': score,
                                'entry': b2['close'],
                                'rvol': b1['rvol'],
                                'body': b1['body'],
                                'vwap_slope': b1['vwap_slope'],
                                'is_core': is_core,
                                'signal_time': b2_timestamp
                            })
                            logging.info(f'SIGNAL: {symbol} Score={score} @ {b2_timestamp.strftime("%H:%M:%S")}')
            
        except Exception as e:
            logging.warning(f'Scan error: {e}')
        
        return signals
    
    def run(self):
        """Main trading loop"""
        print('='*80)
        print('BOOF 30 LIVE TRADER - PAPER')
        print('='*80)
        print(f'Core Universe: {len(CORE_UNIVERSE)} symbols (Score ≥ 3)')
        print(f'Extended Universe: {len(EXTENDED_UNIVERSE)} symbols (Score ≥ 6)')
        print(f'Risk per trade: {RISK_PER_TRADE*100}%')
        print(f'Max positions: {MAX_POSITIONS}')
        print(f'Time window: 9:30 AM - 4:00 PM EST')
        print('='*80)
        print()
        
        # Verify connection
        try:
            account = trading_client.get_account()
            print(f'✓ Connected to Alpaca Paper')
            print(f'  Account Value: ${float(account.equity):,.2f}')
            print(f'  Buying Power: ${float(account.buying_power):,.2f}')
            print()
        except Exception as e:
            print(f'✗ Connection failed: {e}')
            return
        
        # Trading loop
        while True:
            now = datetime.now()
            hour, minute = now.hour, now.minute
            
            # Check market hours (9:30 - 16:00)
            if hour < 9 or (hour == 9 and minute < 30) or hour > 15:
                # Market closed - sleep with heartbeat
                next_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
                if hour >= 16:
                    next_open += timedelta(days=1)
                sleep_seconds = (next_open - now).total_seconds()
                sleep_hours = sleep_seconds / 3600
                
                logging.info(f'Market closed. Next open: {next_open.strftime("%Y-%m-%d %H:%M")} ET (sleeping {sleep_hours:.1f}h)')
                
                # Heartbeat every minute while sleeping
                while datetime.now() < next_open:
                    hb_now = datetime.now()
                    logging.info(f'[Heartbeat] Boof 30 Alive — {hb_now.strftime("%Y-%m-%d %H:%M")} ET')
                    time.sleep(60)
                
                logging.info('Market open! Starting trading...')
                continue
            
            # Check exits every minute
            try:
                for symbol in list(self.positions.keys()):
                    # Get current price
                    request = StockBarsRequest(
                        symbol_or_symbols=symbol,
                        timeframe=TimeFrame.Minute,
                        start=now - timedelta(minutes=2),
                        end=now
                    )
                    bars = data_client.get_stock_bars(request)
                    if not bars.df.empty:
                        current = bars.df.iloc[-1]['close']
                        self.check_exits(symbol, current)
            except Exception as e:
                pass
            
            # Scan for new signals every 30 seconds
            if now.second % 30 == 0:
                print(f'\n[{now.strftime("%H:%M:%S")}] Scanning...')
                print(f'  Active positions: {len(self.positions)}')
                
                # Scan Core Universe (Score >= 3)
                core_signals = self.scan_for_signals(CORE_UNIVERSE, 3, is_core=True)
                for sig in core_signals:
                    print(f"  🎯 CORE SIGNAL: {sig['symbol']} Score={sig['score']} @ ${sig['entry']:.2f}")
                    self.enter_position(sig['symbol'], sig['entry'], is_core=True)
                
                # Scan Extended Universe (Score >= 6)
                if len(self.positions) < MAX_POSITIONS:
                    ext_signals = self.scan_for_signals(EXTENDED_UNIVERSE, 6, is_core=False)
                    for sig in ext_signals:
                        print(f"  🎯 EXT SIGNAL: {sig['symbol']} Score={sig['score']} @ ${sig['entry']:.2f}")
                        self.enter_position(sig['symbol'], sig['entry'], is_core=False)
            
            time.sleep(1)

if __name__ == '__main__':
    trader = Boof30Trader()
    try:
        trader.run()
    except KeyboardInterrupt:
        print('\n\nShutting down...')
        # Save trade log
        if trader.trade_log:
            log_df = pd.DataFrame(trader.trade_log)
            log_df.to_csv(f'boof30_trades_{datetime.now().strftime("%Y%m%d")}.csv', index=False)
            print(f'Saved {len(log_df)} trades to CSV')
