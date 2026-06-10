import pandas as pd
import numpy as np
from dataclasses import dataclass


@dataclass
class Boof23Config:
    atr_period: int = 14
    ema_fast: int = 9
    ema_slow: int = 50

    swing_lookback: int = 5
    min_swing_atr: float = 1.0
    max_swing_age: int = 150

    entry_time_start: str = "09:35"
    entry_time_end: str = "15:30"

    breakout_buffer_atr: float = 0.10
    pullback_buffer_atr: float = 0.35

    tp_pct: float = 0.006
    sl_pct: float = 0.003
    max_hold_bars: int = 30

    mode: str = "breakout"

    allow_longs: bool = True
    allow_shorts: bool = True


CONFIG23 = Boof23Config()


def add_boof23_indicators(df: pd.DataFrame, cfg=CONFIG23):
    df = df.copy()

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs()
    ], axis=1).max(axis=1)

    df["atr"] = tr.rolling(cfg.atr_period).mean()
    df["ema_fast"] = df["close"].ewm(span=cfg.ema_fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=cfg.ema_slow, adjust=False).mean()

    return df


def detect_confirmed_swings(df: pd.DataFrame, i: int, cfg=CONFIG23):
    k = cfg.swing_lookback

    if i < 2 * k + 1:
        return None

    pivot_idx = i - k
    window = df.iloc[pivot_idx - k:pivot_idx + k + 1]

    pivot_high = df.iloc[pivot_idx]["high"]
    pivot_low = df.iloc[pivot_idx]["low"]
    atr = df.iloc[pivot_idx]["atr"]

    if pd.isna(atr) or atr <= 0:
        return None

    is_high = pivot_high == window["high"].max()
    is_low = pivot_low == window["low"].min()

    if is_high:
        return {"type": "HIGH", "idx": pivot_idx, "time": df.index[pivot_idx], "price": pivot_high}

    if is_low:
        return {"type": "LOW", "idx": pivot_idx, "time": df.index[pivot_idx], "price": pivot_low}

    return None


def run_boof23(df: pd.DataFrame, cfg=CONFIG23):
    df = add_boof23_indicators(df, cfg)

    trades = []
    swings = []

    for i in range(cfg.ema_slow + cfg.swing_lookback * 2 + 5, len(df) - cfg.max_hold_bars - 1):
        now = df.index[i]

        new_swing = detect_confirmed_swings(df, i, cfg)
        if new_swing is not None:
            swings.append(new_swing)

        swings = [s for s in swings if i - s["idx"] <= cfg.max_swing_age]

        if not (cfg.entry_time_start <= now.strftime("%H:%M") <= cfg.entry_time_end):
            continue

        row = df.iloc[i]
        prev = df.iloc[i - 1]

        if pd.isna(row["atr"]):
            continue

        atr = row["atr"]

        recent_highs = [s for s in swings if s["type"] == "HIGH"]
        recent_lows = [s for s in swings if s["type"] == "LOW"]

        direction = None
        structure_price = None
        setup_type = None

        trend_up = row["ema_fast"] > row["ema_slow"]
        trend_down = row["ema_fast"] < row["ema_slow"]

        if cfg.mode == "breakout":
            if cfg.allow_longs and trend_up and recent_highs:
                swing_high = recent_highs[-1]["price"]
                trigger = swing_high + atr * cfg.breakout_buffer_atr
                if prev["close"] <= trigger and row["close"] > trigger:
                    direction = "LONG"
                    structure_price = swing_high
                    setup_type = "BREAKOUT_HIGH"

            if direction is None and cfg.allow_shorts and trend_down and recent_lows:
                swing_low = recent_lows[-1]["price"]
                trigger = swing_low - atr * cfg.breakout_buffer_atr
                if prev["close"] >= trigger and row["close"] < trigger:
                    direction = "SHORT"
                    structure_price = swing_low
                    setup_type = "BREAKDOWN_LOW"

        elif cfg.mode == "reversal":
            if cfg.allow_longs and recent_lows:
                swing_low = recent_lows[-1]["price"]
                near_support = abs(row["low"] - swing_low) <= atr * cfg.pullback_buffer_atr
                reclaim = row["close"] > swing_low and row["close"] > prev["close"]
                if near_support and reclaim:
                    direction = "LONG"
                    structure_price = swing_low
                    setup_type = "REVERSAL_SUPPORT"

            if direction is None and cfg.allow_shorts and recent_highs:
                swing_high = recent_highs[-1]["price"]
                near_resistance = abs(row["high"] - swing_high) <= atr * cfg.pullback_buffer_atr
                reject = row["close"] < swing_high and row["close"] < prev["close"]
                if near_resistance and reject:
                    direction = "SHORT"
                    structure_price = swing_high
                    setup_type = "REVERSAL_RESISTANCE"

        if direction is None:
            continue

        entry_idx = i + 1
        entry = df.iloc[entry_idx]["open"]

        tp = entry * (1 + cfg.tp_pct) if direction == "LONG" else entry * (1 - cfg.tp_pct)
        sl = entry * (1 - cfg.sl_pct) if direction == "LONG" else entry * (1 + cfg.sl_pct)

        exit_price = None
        exit_idx = None
        result = None

        for j in range(entry_idx, entry_idx + cfg.max_hold_bars):
            bar = df.iloc[j]

            if direction == "LONG":
                if bar["low"] <= sl:
                    exit_price = sl; exit_idx = j; result = "SL"; break
                if bar["high"] >= tp:
                    exit_price = tp; exit_idx = j; result = "TP"; break
            else:
                if bar["high"] >= sl:
                    exit_price = sl; exit_idx = j; result = "SL"; break
                if bar["low"] <= tp:
                    exit_price = tp; exit_idx = j; result = "TP"; break

        if exit_price is None:
            exit_idx = entry_idx + cfg.max_hold_bars
            exit_price = df.iloc[exit_idx]["close"]
            result = "TIME"

        pnl = (exit_price - entry) / entry if direction == "LONG" else (entry - exit_price) / entry

        trades.append({
            "entry_time": df.index[entry_idx],
            "exit_time": df.index[exit_idx],
            "direction": direction,
            "setup": setup_type,
            "entry": entry,
            "exit": exit_price,
            "pnl": pnl,
            "result": result,
            "structure_price": structure_price,
        })

    return pd.DataFrame(trades)
