"""
BOOF 28 - FINAL STRATEGY (User Version)
Opening Momentum Strategy - Optimal Configuration
"""
import pandas as pd

# =========================
# CONFIG
# =========================

TECH_SEMI_UNIVERSE = [
    "NVDA", "AMD", "AVGO", "QCOM", "AMAT", "MU", "MRVL",
    "LRCX", "KLAC", "ASML", "TSM", "ARM", "INTC", "ON",
    "MCHP", "ADI", "NXPI", "TXN", "MPWR", "TER",
    "MSFT", "GOOGL", "META", "AMZN", "AAPL", "TSLA", "NFLX",
    "PLTR", "SMCI", "ANET", "DELL", "CRWD", "PANW", "NOW"
]

MIN_OPEN_MOVE = 0.005   # +0.50%
MAX_OPEN_MOVE = 0.0075  # +0.75%
MAX_OPEN_RANGE = 0.015  # +1.50% (optional filter)

ENTRY_TIME = "09:35"
EXIT_TIME = "10:00"

MARKET_SYMBOL = "QQQ"


# =========================
# HELPERS
# =========================

def get_first_5m_move(df: pd.DataFrame) -> float | None:
    """
    df must be 1-minute data indexed by datetime.
    Uses 9:30-9:34 as the first 5-minute candle.
    Entry happens at 9:35.
    """
    opening = df.between_time("09:30", "09:34")

    if len(opening) < 5:
        return None

    open_price = opening.iloc[0]["open"]
    close_price = opening.iloc[-1]["close"]
    high_price = opening["high"].max()
    low_price = opening["low"].min()
    
    move = (close_price - open_price) / open_price
    range_pct = (high_price - low_price) / open_price

    return move, range_pct


def get_price_at_time(df: pd.DataFrame, time_str: str):
    bars = df.between_time(time_str, time_str)

    if len(bars) == 0:
        return None

    return bars.iloc[0]["close"]


# =========================
# STRATEGY
# =========================

def run_opening_momentum_strategy(
    stock_data: dict[str, pd.DataFrame],
    qqq_df: pd.DataFrame
) -> list[dict]:
    """
    stock_data:
        {
            "NVDA": dataframe,
            "AMD": dataframe,
            ...
        }

    Each dataframe must:
        - be indexed by datetime
        - contain open/high/low/close/volume
        - include multiple trading days
    """

    trades = []

    qqq_df = qqq_df.copy()
    qqq_df["date"] = qqq_df.index.date

    all_dates = sorted(qqq_df["date"].unique())

    for date in all_dates:
        qqq_day = qqq_df[qqq_df["date"] == date]

        qqq_result = get_first_5m_move(qqq_day)
        
        if qqq_result is None:
            continue
            
        qqq_move, qqq_range = qqq_result

        # Market filter
        if qqq_move <= 0:
            continue

        for symbol, df in stock_data.items():
            if symbol not in TECH_SEMI_UNIVERSE:
                continue

            df = df.copy()
            df["date"] = df.index.date

            day = df[df["date"] == date]

            if len(day) == 0:
                continue

            stock_result = get_first_5m_move(day)
            
            if stock_result is None:
                continue
                
            stock_move, stock_range = stock_result

            # Entry filter: only moderate opening strength (0.50-0.75%)
            if not (MIN_OPEN_MOVE <= stock_move <= MAX_OPEN_MOVE):
                continue
            
            # Optional: opening range filter (avoids chop)
            # if stock_range >= MAX_OPEN_RANGE:
            #     continue

            entry_price = get_price_at_time(day, ENTRY_TIME)
            exit_price = get_price_at_time(day, EXIT_TIME)

            if entry_price is None or exit_price is None:
                continue

            pnl = (exit_price - entry_price) / entry_price

            trades.append({
                "date": date,
                "symbol": symbol,
                "direction": "LONG",
                "qqq_5m_move": qqq_move,
                "stock_5m_move": stock_move,
                "stock_5m_range": stock_range,
                "entry_time": ENTRY_TIME,
                "exit_time": EXIT_TIME,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
            })

    return trades


# =========================
# REPORTING
# =========================

def summarize_trades(trades: list[dict]) -> None:
    if not trades:
        print("No trades found.")
        return

    df = pd.DataFrame(trades)

    wins = df[df["pnl"] > 0]
    losses = df[df["pnl"] <= 0]

    print("=" * 80)
    print("BOOF 28 - OPENING MOMENTUM STRATEGY RESULTS")
    print("=" * 80)
    print(f"Filters: {MIN_OPEN_MOVE*100:.2f}% <= move <= {MAX_OPEN_MOVE*100:.2f}%, QQQ > 0%")
    print(f"Entry: {ENTRY_TIME} | Exit: {EXIT_TIME}")
    print("=" * 80)

    print(f"\nTrades: {len(df)}")
    print(f"Win Rate: {len(wins) / len(df) * 100:.1f}%")
    print(f"Avg P&L: {df['pnl'].mean() * 100:+.3f}%")
    print(f"Total P&L: {df['pnl'].sum() * 100:+.2f}%")
    print(f"Best: {df['pnl'].max() * 100:+.2f}%")
    print(f"Worst: {df['pnl'].min() * 100:+.2f}%")
    print(f"Avg Move: {df['stock_5m_move'].mean() * 100:.2f}%")

    print("\nBY SYMBOL:")
    symbol_stats = (
        df.groupby("symbol")
        .agg(
            trades=("pnl", "count"),
            win_rate=("pnl", lambda x: (x > 0).mean() * 100),
            avg_pnl=("pnl", lambda x: x.mean() * 100),
            total_pnl=("pnl", lambda x: x.sum() * 100),
        )
        .sort_values("total_pnl", ascending=False)
    )

    print(symbol_stats.round(2).to_string())
    print("=" * 80)


# =========================
# USAGE
# =========================

if __name__ == "__main__":
    # Example usage:
    # from your_data_loader import load_stock_data
    # 
    # stock_data = {
    #     "NVDA": load_stock_data("NVDA"),
    #     "AMD": load_stock_data("AMD"),
    #     ...
    # }
    # qqq_df = load_stock_data("QQQ")
    # 
    # trades = run_opening_momentum_strategy(stock_data, qqq_df)
    # summarize_trades(trades)
    pass
