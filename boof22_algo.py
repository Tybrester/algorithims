import pandas as pd
import numpy as np
from dataclasses import dataclass


@dataclass
class Boof22Config:
    lookback_bars: int = 200
    zone_atr_mult: float = 0.35
    min_zone_touches: int = 3
    volume_zscore_min: float = 1.25

    atr_period: int = 14
    volume_period: int = 50
    ema_period: int = 50
    rsi_period: int = 14

    entry_time_start: str = "09:35"
    entry_time_end: str = "15:30"

    tp_pct: float = 0.006
    sl_pct: float = 0.003
    max_hold_bars: int = 30

    allow_longs: bool = True
    allow_shorts: bool = True


CONFIG22 = Boof22Config()


def add_indicators(df: pd.DataFrame, cfg=CONFIG22):
    df = df.copy()

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs()
    ], axis=1).max(axis=1)

    df["atr"] = tr.rolling(cfg.atr_period).mean()
    df["ema"] = df["close"].ewm(span=cfg.ema_period, adjust=False).mean()

    vol_mean = df["volume"].rolling(cfg.volume_period).mean()
    vol_std = df["volume"].rolling(cfg.volume_period).std()
    df["vol_z"] = (df["volume"] - vol_mean) / vol_std

    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(cfg.rsi_period).mean()
    loss = (-delta.clip(upper=0)).rolling(cfg.rsi_period).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    return df


def update_zones(zones, price, volume, atr, bar_index, cfg):
    zone_width = atr * cfg.zone_atr_mult

    for z in zones:
        if abs(price - z["price"]) <= zone_width:
            z["price"] = (z["price"] * z["touches"] + price) / (z["touches"] + 1)
            z["touches"] += 1
            z["volume"] += volume
            z["last_seen"] = bar_index
            return zones

    zones.append({
        "price": price,
        "touches": 1,
        "volume": volume,
        "last_seen": bar_index,
    })

    return zones


def run_boof22(df: pd.DataFrame, cfg=CONFIG22):
    df = add_indicators(df, cfg)
    trades = []
    zones = []

    for i in range(cfg.lookback_bars, len(df) - cfg.max_hold_bars - 1):
        row = df.iloc[i]

        if pd.isna(row["atr"]) or pd.isna(row["vol_z"]):
            continue

        # Incrementally update zones with current bar if high-volume
        if row["vol_z"] >= cfg.volume_zscore_min:
            zones = update_zones(zones, row["close"], row["volume"], row["atr"], i, cfg)

        # Prune zones older than lookback_bars
        zones = [z for z in zones if i - z["last_seen"] <= cfg.lookback_bars]

        # Keep strongest zones only
        zones = sorted(zones, key=lambda z: z["volume"], reverse=True)[:20]

        now = df.index[i]
        if not (cfg.entry_time_start <= now.strftime("%H:%M") <= cfg.entry_time_end):
            continue

        prev = df.iloc[i - 1]

        if pd.isna(row["rsi"]):
            continue

        strong = [z for z in zones if z["touches"] >= cfg.min_zone_touches]
        if not strong:
            continue

        price = row["close"]
        atr = row["atr"]

        nearest = min(strong, key=lambda z: abs(price - z["price"]))
        zone_price = nearest["price"]
        distance = abs(price - zone_price)

        if distance > atr * cfg.zone_atr_mult:
            continue

        direction = None

        if (
            cfg.allow_longs
            and row["low"] <= zone_price
            and row["close"] > zone_price
            and row["close"] > prev["close"]
            and row["rsi"] < 55
            and row["close"] > row["ema"] * 0.995
        ):
            direction = "LONG"

        elif (
            cfg.allow_shorts
            and row["high"] >= zone_price
            and row["close"] < zone_price
            and row["close"] < prev["close"]
            and row["rsi"] > 45
            and row["close"] < row["ema"] * 1.005
        ):
            direction = "SHORT"

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
            "entry": entry,
            "exit": exit_price,
            "pnl": pnl,
            "result": result,
            "zone_price": zone_price,
            "zone_touches": nearest["touches"],
            "zone_volume": nearest["volume"],
        })

    return pd.DataFrame(trades)
