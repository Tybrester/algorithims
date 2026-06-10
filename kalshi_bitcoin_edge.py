"""
Kalshi 15-Minute Bitcoin Target Price Edge Analysis
Tests for edge in Kalshi's short-duration binary Bitcoin markets
"""
import requests
import json
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# Kalshi API Base URL
KALSHI_BASE = 'https://external-api.kalshi.com/trade-api/v2'

# ═══════════════════════════════════════════════════════════════════════════════
# KALSHI API TESTING
# ═══════════════════════════════════════════════════════════════════════════════

def test_kalshi_api():
    """Test basic Kalshi API connectivity"""
    print("Testing Kalshi API...")
    
    url = f"{KALSHI_BASE}/exchange/status"
    
    try:
        resp = requests.get(url, timeout=10)
        print(f"Status Code: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ API Working!")
            print(f"Exchange Status: {data.get('exchange_status', 'unknown')}")
            print(f"Trading Active: {data.get('is_trading_active', False)}")
            return True
        else:
            print(f"❌ Error: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def get_markets():
    """Get available markets from Kalshi"""
    print("\nFetching markets...")
    
    url = f"{KALSHI_BASE}/markets"
    
    try:
        # Try without any filters first
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            markets = data.get('markets', [])
            print(f"✅ Found {len(markets)} markets")
            if markets:
                print(f"   Sample market: {markets[0].get('ticker')}")
            return markets
        else:
            print(f"❌ Error: {resp.status_code} - {resp.text[:200]}")
            return []
    except Exception as e:
        print(f"❌ Exception: {e}")
        return []

def find_bitcoin_15min_markets(markets):
    """Find Bitcoin 15-minute target price markets"""
    bitcoin_markets = []
    
    for market in markets:
        ticker = market.get('ticker', '').upper()
        title = market.get('title', '').upper()
        
        # Look for Bitcoin and 15-minute indicators
        if ('BTC' in ticker or 'BITCOIN' in title or 'BTC' in title):
            if ('15' in title or '15MIN' in ticker or '15-MIN' in title):
                bitcoin_markets.append({
                    'ticker': market.get('ticker'),
                    'title': market.get('title'),
                    'status': market.get('status'),
                    'close_date': market.get('close_date'),
                    'yes_price': market.get('yes_price'),
                    'no_price': market.get('no_price'),
                    'volume': market.get('volume', 0),
                    'open_interest': market.get('open_interest', 0)
                })
    
    return bitcoin_markets

def get_market_history(ticker, lookback_days=7):
    """Get historical price data for a market"""
    print(f"\nFetching history for {ticker}...")
    
    end = datetime.now()
    start = end - timedelta(days=lookback_days)
    
    url = f"{KALSHI_BASE}/markets/{ticker}/history"
    params = {
        'min_ts': int(start.timestamp()),
        'max_ts': int(end.timestamp()),
        'limit': 1000
    }
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            history = data.get('history', [])
            print(f"✅ Got {len(history)} history points")
            return history
        else:
            print(f"❌ Error: {resp.status_code}")
            return []
    except Exception as e:
        print(f"❌ Exception: {e}")
        return []

# ═══════════════════════════════════════════════════════════════════════════════
# EDGE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_edge(market_data):
    """Analyze potential edge in market data"""
    if not market_data or len(market_data) < 10:
        return None
    
    # Convert to DataFrame
    df = pd.DataFrame(market_data)
    
    # Calculate basic statistics
    yes_prices = df['yes_price'] if 'yes_price' in df.columns else []
    
    if len(yes_prices) == 0:
        return None
    
    analysis = {
        'data_points': len(yes_prices),
        'mean_price': np.mean(yes_prices),
        'std_price': np.std(yes_prices),
        'min_price': np.min(yes_prices),
        'max_price': np.max(yes_prices),
        'price_range': np.max(yes_prices) - np.min(yes_prices),
    }
    
    # Look for patterns
    if analysis['mean_price'] < 40:
        analysis['bias'] = 'OVERSOLD (mean < 40)'
    elif analysis['mean_price'] > 60:
        analysis['bias'] = 'OVERBOUGHT (mean > 60)'
    else:
        analysis['bias'] = 'NEUTRAL'
    
    # Volatility check
    if analysis['std_price'] > 15:
        analysis['volatility'] = 'HIGH'
    elif analysis['std_price'] > 8:
        analysis['volatility'] = 'MODERATE'
    else:
        analysis['volatility'] = 'LOW'
    
    return analysis

def simulate_trades(market_data, threshold=10):
    """Simulate simple trading strategy"""
    if not market_data or len(market_data) < 2:
        return None
    
    df = pd.DataFrame(market_data)
    
    if 'yes_price' not in df.columns:
        return None
    
    trades = []
    
    for i in range(1, len(df)):
        prev_price = df.iloc[i-1]['yes_price']
        curr_price = df.iloc[i]['yes_price']
        
        # Mean reversion: Buy YES when price drops below threshold
        if prev_price < threshold and curr_price > prev_price:
            exit_price = min(curr_price + 10, 100)  # Take profit
            pnl = exit_price - curr_price
            trades.append({'entry': curr_price, 'exit': exit_price, 'pnl': pnl, 'type': 'mean_rev'})
        
        # Momentum: Buy YES when price rising
        elif prev_price > 50 and curr_price > prev_price:
            exit_price = min(curr_price + 5, 100)
            pnl = exit_price - curr_price
            trades.append({'entry': curr_price, 'exit': exit_price, 'pnl': pnl, 'type': 'momentum'})
    
    if not trades:
        return None
    
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    
    return {
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(trades) * 100 if trades else 0,
        'total_pnl': sum(t['pnl'] for t in trades),
        'avg_pnl': sum(t['pnl'] for t in trades) / len(trades) if trades else 0
    }

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 80)
    print("KALSHI 15-MIN BITCOIN TARGET PRICE - EDGE ANALYSIS")
    print("=" * 80)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    # Step 1: Test API
    if not test_kalshi_api():
        print("\n⚠️  API test failed. Cannot continue.")
        exit(1)
    
    # Step 2: Get markets
    markets = get_markets()
    if not markets:
        print("\n⚠️  No markets found.")
        exit(1)
    
    # Step 3: Find Bitcoin 15-min markets
    btc_markets = find_bitcoin_15min_markets(markets)
    
    print(f"\n{'=' * 80}")
    print(f"BITCOIN 15-MIN MARKETS FOUND: {len(btc_markets)}")
    print(f"{'=' * 80}")
    
    if not btc_markets:
        print("\nNo 15-minute Bitcoin markets found. Showing sample of all markets:")
        # Show first 20 markets to see what's available
        for i, market in enumerate(markets[:20]):
            ticker = market.get('ticker', '')
            title = market.get('title', '')[:50]
            print(f"  {i+1}. {ticker}: {title}...")
        
        print(f"\n   (showing 20 of {len(markets)} markets)")
        print("\n🔍 Searching for any Bitcoin-related markets...")
        btc_related = []
        for market in markets:
            ticker = market.get('ticker', '').upper()
            title = market.get('title', '').upper()
            if any(word in ticker or word in title for word in ['BTC', 'BITCOIN', 'CRYPTO', 'ETH', 'ETHER']):
                btc_related.append(market)
        
        if btc_related:
            print(f"\n✅ Found {len(btc_related)} crypto-related markets:")
            for m in btc_related:
                print(f"  - {m.get('ticker')}: {m.get('title')}")
        else:
            print("  No crypto markets in current 100 results.")
            print("  Try checking Kalshi website for active Bitcoin markets.")
    else:
        # Analyze each market
        for market in btc_markets:
            print(f"\n{'-' * 80}")
            print(f"Market: {market['ticker']}")
            print(f"Title: {market['title']}")
            print(f"Status: {market['status']}")
            print(f"Current YES Price: {market.get('yes_price', 'N/A')}¢")
            print(f"Current NO Price: {market.get('no_price', 'N/A')}¢")
            print(f"Volume: {market.get('volume', 0)}")
            print(f"Open Interest: {market.get('open_interest', 0)}")
            
            # Get historical data
            history = get_market_history(market['ticker'], lookback_days=7)
            
            if history:
                # Analyze edge
                analysis = analyze_edge(history)
                if analysis:
                    print(f"\n📊 Price Analysis:")
                    print(f"  Data Points: {analysis['data_points']}")
                    print(f"  Mean Price: {analysis['mean_price']:.1f}¢")
                    print(f"  Std Dev: {analysis['std_price']:.1f}¢")
                    print(f"  Range: {analysis['min_price']:.1f}¢ - {analysis['max_price']:.1f}¢")
                    print(f"  Bias: {analysis['bias']}")
                    print(f"  Volatility: {analysis['volatility']}")
                
                # Simulate trades
                sim = simulate_trades(history, threshold=35)
                if sim:
                    print(f"\n🎯 Simulated Strategy Results:")
                    print(f"  Trades: {sim['total_trades']}")
                    print(f"  Win Rate: {sim['win_rate']:.1f}%")
                    print(f"  Total PnL: {sim['total_pnl']:+.1f}¢")
                    print(f"  Avg PnL: {sim['avg_pnl']:+.1f}¢")
                    
                    if sim['win_rate'] > 55 and sim['total_pnl'] > 0:
                        print(f"  ✅ POTENTIAL EDGE DETECTED")
                    elif sim['total_pnl'] > 0:
                        print(f"  ⚠️  Marginal edge - needs more data")
                    else:
                        print(f"  🔴 No edge detected")
    
    print(f"\n{'=' * 80}")
    print("NEXT STEPS:")
    print("=" * 80)
    print("1. If markets found: Collect more historical data (30+ days)")
    print("2. Test multiple strategies (mean reversion, momentum, trend)")
    print("3. Add real Bitcoin price correlation analysis")
    print("4. Paper trade before live deployment")
    print("=" * 80)
