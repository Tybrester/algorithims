"""
Early Move Pattern Analysis
Tests compression → impulse → spike patterns on existing Boof signals
"""
import pandas as pd
import numpy as np
from datetime import datetime

# Load the micro-move data we just collected
try:
    df = pd.read_csv('micro_move_trades_20260605.csv')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    print(f"Loaded {len(df)} trades from micro_move_trades_20260605.csv")
    print(f"Columns: {list(df.columns)}")
    print("\nFirst few rows:")
    print(df.head())
except Exception as e:
    print(f"Error loading CSV: {e}")
    print("Need to re-run backtest with pattern detection...")
