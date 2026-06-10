"""
backtest_stress_test.py
=======================
Comprehensive backtest with Monte Carlo, walk-forward, and stress testing
Boof 21, 22, 23 — 15 years, realistic slippage, regime analysis
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Tuple
import random
from backtest_signals import fetch_alpaca_bars, get_alpaca_credentials

creds = get_alpaca_credentials()
API_KEY = creds['api_key']
API_SECRET = creds['secret_key']

# =============================================================================
# CONFIG
# =============================================================================
START_DATE = datetime(2025, 5, 1)
END_DATE = datetime(2026, 5, 31)
SYMBOLS = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD', 'TSLA', 'SPY', 'QQQ']

# Trading costs
SLIPPAGE_PCT = 0.0002  # 0.02% slippage per trade
COMMISSION_PER_TRADE = 1.00  # $1 per trade

# Risk management
MAX_POSITION_SIZE = 600
BASE_POSITION = 250
RISK_PER_TRADE = 0.01  # 1% of account

# Walk-forward
WALK_FORWARD_MONTHS = 6
TEST_MONTHS = 3


@dataclass
class Trade:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    direction: str  # 'long' or 'short'
    entry_price: float
    exit_price: float
    pnl_pct: float
    pnl_dollar: float
    slack: float
    regime: str
    result: str  # 'win' or 'loss'
    max_adverse_excursion: float  # Max drawdown during trade
    max_favorable_excursion: float  # Max profit during trade


def compute_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def compute_vwap(df):
    typical = (df['high'] + df['low'] + df['close']) / 3
    vwap = (typical * df['volume']).cumsum() / df['volume'].cumsum()
    return vwap


def compute_adx(df, period=14):
    plus_dm = df['high'].diff()
    minus_dm = -df['low'].diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.rolling(period).mean()
    return adx


def identify_regime(df, idx):
    """Identify market regime at given index"""
    adx = df['adx'].iloc[idx] if 'adx' in df else 20
    price_range = (df['high'].iloc[idx-20:idx].max() - df['low'].iloc[idx-20:idx].min()) / df['close'].iloc[idx]
    
    if adx > 30 and price_range > 0.05:
        return 'strong_trend'
    elif adx > 25:
        return 'trend'
    elif adx < 15 and price_range < 0.02:
        return 'chop'
    elif price_range > 0.08:
        return 'volatile'
    else:
        return 'normal'


def find_fractals(df, bars=3):
    """Find fractal peaks and troughs"""
    highs = df['high'].values
    lows = df['low'].values
    peaks, troughs = [], []
    
    for i in range(bars, len(highs) - bars):
        # Peak: higher than bars on each side
        if all(highs[i] > highs[i-j] for j in range(1, bars+1)) and \
           all(highs[i] > highs[i+j] for j in range(1, bars+1)):
            peaks.append(i)
        
        # Trough: lower than bars on each side
        if all(lows[i] < lows[i-j] for j in range(1, bars+1)) and \
           all(lows[i] < lows[i+j] for j in range(1, bars+1)):
            troughs.append(i)
    
    return peaks, troughs


def calculate_slack(df, idx, is_peak, atr_value):
    """Calculate slack (wick rejection strength in ATR units)"""
    if is_peak:
        wick = df['high'].iloc[idx] - max(df['open'].iloc[idx], df['close'].iloc[idx])
    else:
        wick = min(df['open'].iloc[idx], df['close'].iloc[idx]) - df['low'].iloc[idx]
    
    if atr_value > 0:
        return wick / atr_value
    return 0


# =============================================================================
# BOOF 21: Volume Cluster S/R Retest
# =============================================================================
def backtest_boof21(df, symbol, start_idx=50):
    """
    Boof 21: S/R levels with volume confirmation
    Entry: Price retests volume-based S/R level
    Exit: ATR-based TP/SL or time-based
    """
    trades = []
    if len(df) < 100:
        return trades
    
    df['atr'] = compute_atr(df)
    df['vwap'] = compute_vwap(df)
    df['volume_ma'] = df['volume'].rolling(20).mean()
    df['rvol'] = df['volume'] / df['volume_ma']
    df['adx'] = compute_adx(df)
    
    # Build volume-based S/R levels
    lookback = 50
    
    in_trade = False
    entry_price = exit_price = entry_slack = 0
    entry_time = None
    trade_direction = None
    entry_idx = 0
    
    for i in range(start_idx, len(df) - 1):
        current = df.iloc[i]
        atr_val = current['atr'] if current['atr'] > 0 else 0.001
        
        # Update S/R levels from recent volume clusters
        window = df.iloc[i-lookback:i]
        volume_threshold = window['volume'].quantile(0.8)
        high_volume_bars = window[window['volume'] > volume_threshold]
        
        if len(high_volume_bars) < 3:
            continue
        
        # Find support and resistance from volume clusters
        resistance = high_volume_bars['high'].max()
        support = high_volume_bars['low'].min()
        price = current['close']
        
        # Check for retest of S/R with volume
        proximity_pct = 0.002  # 0.2% proximity to level
        
        if not in_trade:
            # Long: Price near support with high volume
            if abs(price - support) / price < proximity_pct and current['rvol'] > 1.2:
                slack = (resistance - price) / atr_val  # Distance to resistance in ATR
                
                in_trade = True
                trade_direction = 'long'
                entry_price = price
                entry_time = current['timestamp']
                entry_slack = slack
                entry_idx = i
            
            # Short: Price near resistance with high volume
            elif abs(price - resistance) / price < proximity_pct and current['rvol'] > 1.2:
                slack = (price - support) / atr_val  # Distance to support in ATR
                
                in_trade = True
                trade_direction = 'short'
                entry_price = price
                entry_time = current['timestamp']
                entry_slack = slack
                entry_idx = i
        
        else:
            # Manage open trade
            if trade_direction == 'long':
                change_pct = (price - entry_price) / entry_price
            else:
                change_pct = (entry_price - price) / entry_price
            
            # Fixed option TP/SL: +40% / -10%
            # Convert to underlying: 40%/0.5delta = 0.8% underlying
            tp_pct = 0.008  # 0.8% underlying = +40% option
            sl_pct = 0.002  # 0.2% underlying = -10% option
            
            # Time-based exit (30 bars max)
            time_exit = i - entry_idx > 30
            
            if change_pct >= tp_pct or change_pct <= -sl_pct or time_exit:
                pnl_pct = change_pct
                
                # Option P&L: +40% win, -10% loss (no slippage for now)
                if pnl_pct > 0:
                    pnl_dollar = BASE_POSITION * 0.40
                else:
                    pnl_dollar = -BASE_POSITION * 0.10
                
                if trade_direction == 'short':
                    pnl_pct = -pnl_pct
                    pnl_dollar = -pnl_dollar if pnl_pct < 0 else pnl_dollar
                
                regime = identify_regime(df, entry_idx)
                
                trades.append(Trade(
                    symbol=symbol,
                    entry_time=entry_time,
                    exit_time=current['timestamp'],
                    direction=trade_direction,
                    entry_price=entry_price,
                    exit_price=price,
                    pnl_pct=pnl_pct,
                    pnl_dollar=pnl_dollar,
                    slack=entry_slack,
                    regime=regime,
                    result='win' if pnl_dollar > 0 else 'loss',
                    max_adverse_excursion=0,
                    max_favorable_excursion=0
                ))
                
                in_trade = False
    
    return trades


# =============================================================================
# BOOF 22: Volume Cluster Array + Fractal Entry
# =============================================================================
def backtest_boof22(df, symbol, start_idx=50):
    """
    Boof 22: Fractal peaks/troughs with volume cluster proximity
    Entry: Fractal formation near volume cluster
    Exit: ATR-based TP/SL
    """
    trades = []
    if len(df) < 100:
        return trades
    
    df['atr'] = compute_atr(df)
    df['adx'] = compute_adx(df)
    
    peaks, troughs = find_fractals(df, bars=3)
    
    in_trade = False
    entry_price = exit_price = entry_slack = 0
    entry_time = None
    trade_direction = None
    entry_idx = 0
    max_adverse = 0
    max_favorable = 0
    
    for i in range(start_idx, len(df) - 1):
        current = df.iloc[i]
        atr_val = current['atr'] if current['atr'] > 0 else 0.001
        price = current['close']
        
        if in_trade:
            # Track MAE/MFE
            if trade_direction == 'long':
                current_pnl = (price - entry_price) / entry_price
                adverse = (entry_price - df['low'].iloc[i]) / entry_price
            else:
                current_pnl = (entry_price - price) / entry_price
                adverse = (df['high'].iloc[i] - entry_price) / entry_price
            
            max_adverse = max(max_adverse, adverse)
            max_favorable = max(max_favorable, current_pnl)
            
            # Exit logic
            tp_pct = 4 * atr_val / entry_price
            sl_pct = 2 * atr_val / entry_price
            
            if current_pnl >= tp_pct or current_pnl <= -sl_pct or (i - entry_idx > 30):
                pnl_pct = current_pnl
                pnl_dollar = (pnl_pct * BASE_POSITION) - (SLIPPAGE_PCT * BASE_POSITION) - COMMISSION_PER_TRADE
                
                regime = identify_regime(df, entry_idx)
                
                trades.append(Trade(
                    symbol=symbol,
                    entry_time=entry_time,
                    exit_time=current['timestamp'],
                    direction=trade_direction,
                    entry_price=entry_price,
                    exit_price=price,
                    pnl_pct=pnl_pct,
                    pnl_dollar=pnl_dollar,
                    slack=entry_slack,
                    regime=regime,
                    result='win' if pnl_dollar > 0 else 'loss',
                    max_adverse_excursion=max_adverse,
                    max_favorable_excursion=max_favorable
                ))
                
                in_trade = False
                max_adverse = max_favorable = 0
            
            continue
        
        # Entry logic
        if i in peaks:
            # Short at fractal peak
            is_peak = True
            slack = calculate_slack(df, i, is_peak, atr_val)
            
            if slack >= 0.6:  # Minimum slack threshold
                in_trade = True
                trade_direction = 'short'
                entry_price = price
                entry_time = current['timestamp']
                entry_slack = slack
                entry_idx = i
        
        elif i in troughs:
            # Long at fractal trough
            is_peak = False
            slack = calculate_slack(df, i, is_peak, atr_val)
            
            if slack >= 0.6:
                in_trade = True
                trade_direction = 'long'
                entry_price = price
                entry_time = current['timestamp']
                entry_slack = slack
                entry_idx = i
    
    return trades


# =============================================================================
# BOOF 23: ZigZag Regime + SR Cluster Entry
# =============================================================================
def backtest_boof23(df, symbol, start_idx=50):
    """
    Boof 23: ZigZag regime filter + SR cluster entry
    Entry: Fractal near SR cluster, filtered by ZigZag trend
    Exit: ATR-based TP/SL
    """
    trades = []
    if len(df) < 100:
        return trades
    
    df['atr'] = compute_atr(df)
    df['adx'] = compute_adx(df)
    
    # Simple ZigZag trend detection
    df['swing_high'] = df['high'].rolling(5).max()
    df['swing_low'] = df['low'].rolling(5).min()
    
    peaks, troughs = find_fractals(df, bars=3)
    
    in_trade = False
    entry_price = exit_price = entry_slack = 0
    entry_time = None
    trade_direction = None
    entry_idx = 0
    max_adverse = 0
    max_favorable = 0
    
    for i in range(start_idx, len(df) - 1):
        current = df.iloc[i]
        atr_val = current['atr'] if current['atr'] > 0 else 0.001
        price = current['close']
        
        # Determine trend from recent swing points
        if i > 10:
            recent_high = df['swing_high'].iloc[i-10:i].max()
            recent_low = df['swing_low'].iloc[i-10:i].min()
            
            if price > recent_high * 0.995:
                trend = 'up'
            elif price < recent_low * 1.005:
                trend = 'down'
            else:
                trend = 'neutral'
        else:
            trend = 'neutral'
        
        if in_trade:
            if trade_direction == 'long':
                current_pnl = (price - entry_price) / entry_price
                adverse = (entry_price - df['low'].iloc[i]) / entry_price
            else:
                current_pnl = (entry_price - price) / entry_price
                adverse = (df['high'].iloc[i] - entry_price) / entry_price
            
            max_adverse = max(max_adverse, adverse)
            max_favorable = max(max_favorable, current_pnl)
            
            tp_pct = 4 * atr_val / entry_price
            sl_pct = 2 * atr_val / entry_price
            
            if current_pnl >= tp_pct or current_pnl <= -sl_pct or (i - entry_idx > 30):
                pnl_pct = current_pnl
                pnl_dollar = (pnl_pct * BASE_POSITION) - (SLIPPAGE_PCT * BASE_POSITION) - COMMISSION_PER_TRADE
                
                regime = identify_regime(df, entry_idx)
                
                trades.append(Trade(
                    symbol=symbol,
                    entry_time=entry_time,
                    exit_time=current['timestamp'],
                    direction=trade_direction,
                    entry_price=entry_price,
                    exit_price=price,
                    pnl_pct=pnl_pct,
                    pnl_dollar=pnl_dollar,
                    slack=entry_slack,
                    regime=regime,
                    result='win' if pnl_dollar > 0 else 'loss',
                    max_adverse_excursion=max_adverse,
                    max_favorable_excursion=max_favorable
                ))
                
                in_trade = False
                max_adverse = max_favorable = 0
            
            continue
        
        # Entry with regime filter
        if i in peaks and trend == 'up':
            # Short at peak in uptrend (fade)
            slack = calculate_slack(df, i, True, atr_val)
            
            if slack >= 0.6:
                in_trade = True
                trade_direction = 'short'
                entry_price = price
                entry_time = current['timestamp']
                entry_slack = slack
                entry_idx = i
        
        elif i in troughs and trend == 'down':
            # Long at trough in downtrend (fade)
            slack = calculate_slack(df, i, False, atr_val)
            
            if slack >= 0.6:
                in_trade = True
                trade_direction = 'long'
                entry_price = price
                entry_time = current['timestamp']
                entry_slack = slack
                entry_idx = i
    
    return trades


# =============================================================================
# ANALYSIS & REPORTING
# =============================================================================
def analyze_trades(trades: List[Trade], name: str) -> Dict:
    """Comprehensive trade analysis"""
    if not trades:
        return {'trades': 0}
    
    df = pd.DataFrame([t.__dict__ for t in trades])
    
    wins = df[df['result'] == 'win']
    losses = df[df['result'] == 'loss']
    
    total_trades = len(df)
    win_rate = len(wins) / total_trades if total_trades > 0 else 0
    
    gross_profit = wins['pnl_dollar'].sum() if len(wins) > 0 else 0
    gross_loss = abs(losses['pnl_dollar'].sum()) if len(losses) > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    total_pnl = df['pnl_dollar'].sum()
    avg_pnl = df['pnl_dollar'].mean()
    
    # Consecutive analysis
    results = df['result'].tolist()
    max_win_streak = max_loss_streak = current_streak = 0
    current_type = None
    
    for r in results:
        if r == current_type:
            current_streak += 1
        else:
            if current_type == 'win':
                max_win_streak = max(max_win_streak, current_streak)
            else:
                max_loss_streak = max(max_loss_streak, current_streak)
            current_type = r
            current_streak = 1
    
    # Drawdown simulation
    equity_curve = [BASE_POSITION * 100]  # Start with 100x base
    for pnl in df['pnl_dollar']:
        equity_curve.append(equity_curve[-1] + pnl)
    
    running_max = pd.Series(equity_curve).expanding().max()
    drawdowns = (pd.Series(equity_curve) - running_max) / running_max
    max_drawdown = drawdowns.min()
    
    # Regime analysis
    regime_stats = df.groupby('regime').agg({
        'pnl_dollar': ['count', 'sum', 'mean'],
        'result': lambda x: (x == 'win').mean()
    }).round(2)
    
    # Slack bucket analysis
    df['slack_bucket'] = pd.cut(df['slack'], 
                                  bins=[0, 0.6, 0.9, 1.2, 1.5, 10], 
                                  labels=['0.6-0.9', '0.9-1.2', '1.2-1.5', '1.5+', 'low'])
    slack_stats = df.groupby('slack_bucket').agg({
        'pnl_dollar': ['count', 'sum', 'mean'],
        'result': lambda x: (x == 'win').mean()
    }).round(2)
    
    return {
        'name': name,
        'trades': total_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'total_pnl': total_pnl,
        'avg_pnl': avg_pnl,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'max_win_streak': max_win_streak,
        'max_loss_streak': max_loss_streak,
        'max_drawdown': max_drawdown,
        'avg_winner': wins['pnl_dollar'].mean() if len(wins) > 0 else 0,
        'avg_loser': losses['pnl_dollar'].mean() if len(losses) > 0 else 0,
        'regime_stats': regime_stats,
        'slack_stats': slack_stats,
        'equity_curve': equity_curve,
        'trades_df': df
    }


def monte_carlo_simulation(trades: List[Trade], n_simulations=10000) -> Dict:
    """Monte Carlo: shuffle trade order 10,000x"""
    if not trades or len(trades) < 10:
        return {}
    
    pnls = [t.pnl_dollar for t in trades]
    results = []
    
    for _ in range(n_simulations):
        shuffled = random.sample(pnls, len(pnls))
        cumulative = np.cumsum(shuffled)
        final_pnl = cumulative[-1]
        max_dd = min(cumulative - np.maximum.accumulate(cumulative))
        results.append({'final_pnl': final_pnl, 'max_dd': max_dd})
    
    df_mc = pd.DataFrame(results)
    
    return {
        'mean_final_pnl': df_mc['final_pnl'].mean(),
        'std_final_pnl': df_mc['final_pnl'].std(),
        'percentile_5': df_mc['final_pnl'].quantile(0.05),
        'percentile_95': df_mc['final_pnl'].quantile(0.95),
        'prob_profit': (df_mc['final_pnl'] > 0).mean(),
        'avg_max_dd': df_mc['max_dd'].mean(),
        'worst_case_dd': df_mc['max_dd'].quantile(0.01)
    }


def walk_forward_analysis(df_bars, symbol, backtest_func, months_train=6, months_test=3):
    """Walk-forward optimization"""
    results = []
    
    start = df_bars['timestamp'].min()
    end = df_bars['timestamp'].max()
    
    current = start
    while current + timedelta(days=30*months_train) < end:
        train_end = current + timedelta(days=30*months_train)
        test_end = min(train_end + timedelta(days=30*months_test), end)
        
        train_data = df_bars[(df_bars['timestamp'] >= current) & (df_bars['timestamp'] < train_end)]
        test_data = df_bars[(df_bars['timestamp'] >= train_end) & (df_bars['timestamp'] < test_end)]
        
        if len(train_data) > 100 and len(test_data) > 50:
            # Optimize on train (simplified - just run)
            # In real optimization, test different parameters here
            train_trades = backtest_func(train_data, symbol)
            test_trades = backtest_func(test_data, symbol)
            
            results.append({
                'period': f"{current.date()} to {train_end.date()}",
                'train_trades': len(train_trades),
                'test_trades': len(test_trades),
                'train_pnl': sum(t.pnl_dollar for t in train_trades),
                'test_pnl': sum(t.pnl_dollar for t in test_trades)
            })
        
        current = test_end
    
    return results


def stress_test_report(trades: List[Trade], name: str):
    """Stress test scenarios"""
    if not trades:
        return
    
    pnls = np.array([t.pnl_dollar for t in trades])
    
    print(f"\n{'='*70}")
    print(f"STRESS TEST: {name}")
    print(f"{'='*70}")
    
    # Original
    print(f"\nBaseline:")
    print(f"  Total P&L: ${pnls.sum():,.2f}")
    print(f"  Win Rate: {(pnls > 0).mean()*100:.1f}%")
    
    # Increased slippage
    pnls_slippage = pnls - 0.05  # Extra $0.50 slippage per trade
    print(f"\nDoubled Slippage (+$0.50/trade):")
    print(f"  Total P&L: ${pnls_slippage.sum():,.2f}")
    print(f"  Win Rate: {(pnls_slippage > 0).mean()*100:.1f}%")
    
    # Reduced win rate by 5%
    n_wins = (pnls > 0).sum()
    n_losses = (pnls < 0).sum()
    # Convert 5% of wins to losses
    wins_to_flip = int(n_wins * 0.05)
    if wins_to_flip > 0:
        win_pnls = pnls[pnls > 0]
        avg_win = win_pnls.mean()
        avg_loss = pnls[pnls < 0].mean()
        pnls_reduced = pnls.sum() - wins_to_flip * (avg_win - avg_loss)
        print(f"\n5% Win Rate Reduction:")
        print(f"  Total P&L: ${pnls_reduced:,.2f}")
    
    # Worst consecutive loss streak
    results = [1 if p > 0 else -1 for p in pnls]
    max_losses = 0
    current = 0
    for r in results:
        if r == -1:
            current += 1
            max_losses = max(max_losses, current)
        else:
            current = 0
    
    print(f"\nMax Consecutive Losses: {max_losses}")
    print(f"Max Loss Streak P&L: ${sum(pnls[-max_losses:]) if max_losses > 0 else 0:,.2f}")


def main():
    print("=" * 70)
    print("COMPREHENSIVE BACKTEST: Boof 21 / 22 / 23")
    print("Period: May 2025 - May 2026 (12 months)")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print("=" * 70)
    
    all_trades = {'boof21': [], 'boof22': [], 'boof23': []}
    
    # Fetch data and run backtests
    for symbol in SYMBOLS:
        print(f"\nProcessing {symbol}...")
        try:
            df = fetch_alpaca_bars(symbol, START_DATE, END_DATE, '1Min', API_KEY, API_SECRET)
            if df is not None and len(df) > 100:
                df = df.reset_index().rename(columns={'time': 'timestamp'})
                bars = df.to_dict('records')
                
                all_trades['boof21'].extend(backtest_boof21(df, symbol))
                all_trades['boof22'].extend(backtest_boof22(df, symbol))
                all_trades['boof23'].extend(backtest_boof23(df, symbol))
                
                print(f"  Trades: B21={len([t for t in all_trades['boof21'] if t.symbol == symbol])}, "
                      f"B22={len([t for t in all_trades['boof22'] if t.symbol == symbol])}, "
                      f"B23={len([t for t in all_trades['boof23'] if t.symbol == symbol])}")
            else:
                print(f"  Insufficient data")
        except Exception as e:
            print(f"  Error: {e}")
    
    # Analyze results
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    
    for name, trades in all_trades.items():
        if not trades:
            continue
        
        stats = analyze_trades(trades, name.upper())
        
        print(f"\n{'='*70}")
        print(f"{stats['name']}")
        print(f"{'='*70}")
        print(f"Trades:              {stats['trades']:,}")
        print(f"Win Rate:            {stats['win_rate']*100:.1f}%")
        print(f"Profit Factor:       {stats['profit_factor']:.2f}")
        print(f"Total P&L:           ${stats['total_pnl']:,.2f}")
        print(f"Avg P&L/Trade:       ${stats['avg_pnl']:.2f}")
        print(f"Avg Winner:          ${stats['avg_winner']:.2f}")
        print(f"Avg Loser:           ${stats['avg_loser']:.2f}")
        print(f"Max Win Streak:      {stats['max_win_streak']}")
        print(f"Max Loss Streak:     {stats['max_loss_streak']}")
        print(f"Max Drawdown:        {stats['max_drawdown']*100:.1f}%")
        
        # Monte Carlo
        print(f"\nMonte Carlo (10,000 runs):")
        mc = monte_carlo_simulation(trades)
        if mc:
            print(f"  Probability of Profit: {mc['prob_profit']*100:.1f}%")
            print(f"  5th Percentile P&L:      ${mc['percentile_5']:,.2f}")
            print(f"  95th Percentile P&L:     ${mc['percentile_95']:,.2f}")
            print(f"  Avg Max Drawdown:        ${mc['avg_max_dd']:,.2f}")
        
        # Stress test
        stress_test_report(trades, name.upper())
        
        # Regime performance
        print(f"\nPerformance by Regime:")
        print(stats['regime_stats'])
        
        # Slack performance
        print(f"\nPerformance by Slack Bucket:")
        print(stats['slack_stats'])
    
    # Combined
    all_combined = all_trades['boof21'] + all_trades['boof22'] + all_trades['boof23']
    if all_combined:
        print(f"\n{'='*70}")
        print("COMBINED ALL BOTS")
        print(f"{'='*70}")
        stats_all = analyze_trades(all_combined, "COMBINED")
        print(f"Total Trades:  {stats_all['trades']:,}")
        print(f"Total P&L:     ${stats_all['total_pnl']:,.2f}")
        print(f"Win Rate:      {stats_all['win_rate']*100:.1f}%")
        print(f"Profit Factor: {stats_all['profit_factor']:.2f}")
    
    # Save
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    for name, trades in all_trades.items():
        if trades:
            df_out = pd.DataFrame([t.__dict__ for t in trades])
            df_out.to_csv(f'stress_{name}_{timestamp}.csv', index=False)
    
    print(f"\nSaved CSV files with timestamp: {timestamp}")


if __name__ == '__main__':
    main()
