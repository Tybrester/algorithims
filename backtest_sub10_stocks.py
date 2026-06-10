import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from backtest_signals import (
    fetch_alpaca_bars, generate_entries, backtest, 
    classify_regime, run_system
)

# =========================================================
# BOOF 16.0 STOCK BACKTEST - SUB-$10 STOCKS
# =========================================================

ALPACA_API_KEY = "AK5QL43AEYXZSYCRSNSIDYO36D"
ALPACA_SECRET_KEY = "qwEfPQ2CWZYzDzJLn4QQNYcs9tdNprxP44C4dWT5md3"

# Sub-$10 stocks to test
sub10_stocks = ["SOFI", "RIVN", "LCID", "AMC", "NIO", "XPEV"]

if __name__ == "__main__":
    # Backtest last week (May 16 - May 23, 2026)
    end_date = datetime(2026, 5, 23)
    start_date = datetime(2026, 5, 16)
    
    print(f"\n{'='*60}")
    print(f"BOOF 16.0 STOCK BACKTEST: SUB-$10 STOCKS")
    print(f"{start_date.date()} to {end_date.date()}")
    print(f"{'='*60}\n")
    
    print("Using provided Alpaca credentials...\n")
    
    all_results = {}
    
    for ticker in sub10_stocks:
        print(f"\n{'='*60}")
        print(f"BACKTEST: {ticker} | {start_date.date()} to {end_date.date()}")
        print(f"{'='*60}\n")
        
        # Download data
        print(f"  Downloading {ticker} data from Alpaca API...")
        df = fetch_alpaca_bars(ticker, start_date, end_date, '1Min', 
                              ALPACA_API_KEY, ALPACA_SECRET_KEY)
        
        if df is None or len(df) == 0:
            print(f"No data found for {ticker}")
            continue
        
        print(f"Downloaded {len(df)} candles\n")
        
        # Run Boof 16.0 with Kelly criterion
        print("Running Boof 16.0 with Kelly criterion...")
        result = run_system(
            df, 
            symbol=ticker,
            tp_pct=0.005,
            sl_pct=-0.003,
            use_ev=False,
            use_continuous_ev=True,
            use_dynamic_risk=False,
            use_kelly=True
        )
        
        # Print results
        print(f"\n{'='*60}")
        print(f"RESULTS")
        print(f"{'='*60}\n")
        
        print(f"Regime: {result['regime']}")
        print(f"Total Trades: {result['trades']}")
        print(f"Win Rate: {result['win_rate']*100:.1f}%")
        print(f"Avg PnL: {result['avg_pnl']*100:.2f}%")
        print(f"Expectancy: {result['expectancy']*100:.2f}%")
        print(f"Profit Factor: {result['profit_factor']:.2f}")
        
        all_results[ticker] = result
    
    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}\n")
    
    total_trades = sum(r['trades'] for r in all_results.values())
    
    if all_results:
        avg_win_rate = np.mean([r['win_rate'] for r in all_results.values()])
        avg_expectancy = np.mean([r['expectancy'] for r in all_results.values()])
        avg_profit_factor = np.mean([r['profit_factor'] for r in all_results.values()])
    else:
        avg_win_rate = 0
        avg_expectancy = 0
        avg_profit_factor = 0
    
    print(f"Total Trades: {total_trades}")
    print(f"Average Win Rate: {avg_win_rate*100:.1f}%")
    print(f"Average Expectancy: {avg_expectancy*100:.2f}%")
    print(f"Average Profit Factor: {avg_profit_factor:.2f}")
    
    print(f"\n{'='*60}")
    print(f"BACKTEST COMPLETE")
    print(f"{'='*60}")
