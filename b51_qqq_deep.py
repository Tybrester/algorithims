import datetime, os
import pandas as pd
import pytz

ET = pytz.timezone("America/New_York")
SYM = "QQQ"
CONFIG = {"long": {"tp": 0.0045, "sl": 0.0030}, "short": {"tp": 0.0040, "sl": 0.0030}}
MAX_TRADES = 5
COOLDOWN   = 10
TIME_STOP  = 90

# Best windows from Test C sweep
WINDOWS = [("09:30","15:55")]


def resample_trend(df, minutes):
    df = df.set_index("time")
    rs = df.resample(f"{minutes}min", closed="left", label="left").agg(
        open=("open","first"), high=("high","max"), low=("low","min"),
        close=("close","last"), volume=("volume","sum")
    ).dropna()
    rs["date"] = rs.index.date
    rs["typ"]  = (rs["high"] + rs["low"] + rs["close"]) / 3
    rs["pv"]   = rs["typ"] * rs["volume"]
    rs["cpv"]  = rs.groupby("date")["pv"].cumsum()
    rs["cvol"] = rs.groupby("date")["volume"].cumsum()
    rs["vwap"] = rs["cpv"] / rs["cvol"]
    rs[f"t{minutes}"] = (rs["close"] > rs["vwap"]).astype(int) * 2 - 1
    df = df.reset_index()
    out = pd.merge_asof(
        df.sort_values("time"),
        rs[[f"t{minutes}"]].reset_index().rename(columns={"time": "rt"}),
        left_on="time", right_on="rt", direction="backward"
    )
    return out


def compute_indicators(df):
    df = df.copy().reset_index(drop=True)
    df["date"]   = df["time"].dt.date
    df["typ"]    = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]     = df["typ"] * df["volume"]
    df["cpv"]    = df.groupby("date")["pv"].cumsum()
    df["cvol"]   = df.groupby("date")["volume"].cumsum()
    df["vwap"]   = df["cpv"] / df["cvol"]
    df["ema9"]   = df["close"].ewm(span=9, adjust=False).mean()
    df["vsma20"] = df["volume"].rolling(20).mean()
    df["prev_c"] = df["close"].shift(1)
    df["prev_v"] = df["vwap"].shift(1)
    return df


def lsig(row):
    return (row["close"] > row["vwap"] and row["prev_c"] <= row["prev_v"] and
            row["volume"] > row["vsma20"] * 1.2 and row["close"] > row["ema9"])

def ssig(row):
    return (row["close"] < row["vwap"] and row["prev_c"] >= row["prev_v"] and
            row["volume"] > row["vsma20"] * 1.2 and row["close"] < row["ema9"])


def sim_exit_full(ddf, ei, ep, tp, sl, side):
    mi = min(ei + TIME_STOP, len(ddf) - 1)
    H = ddf["high"].values; L = ddf["low"].values; C = ddf["close"].values
    mfe = mae = 0.0
    et = "time"; exit_px = C[mi]
    for j in range(ei, mi + 1):
        if side == "long":
            mfe = max(mfe, (H[j] - ep) / ep * 100)
            mae = max(mae, (ep - L[j]) / ep * 100)
            if et == "time" and H[j] >= tp: et = "tp"; exit_px = tp
            if et == "time" and L[j] <= sl: et = "sl"; exit_px = sl
        else:
            mfe = max(mfe, (ep - L[j]) / ep * 100)
            mae = max(mae, (H[j] - ep) / ep * 100)
            if et == "time" and L[j] <= tp: et = "tp"; exit_px = tp
            if et == "time" and H[j] >= sl: et = "sl"; exit_px = sl
        if et != "time":
            break
    pnl = (exit_px - ep) / ep * 100 if side == "long" else (ep - exit_px) / ep * 100
    return et, pnl, mfe, mae


def run(df, windows):
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        lc = sc = 0; lcd = scd = None
        for i in range(1, len(ddf) - 1):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not any(ws <= t < we for ws, we in windows): continue
            if pd.isna(row.get("vwap")) or pd.isna(row.get("vsma20")): continue
            t5 = row.get("t5", 0); t10 = row.get("t10", 0)
            lok = (t5 == 1  and t10 == 1)
            sok = (t5 == -1 and t10 == -1)
            nd = row["time"]

            if lc < MAX_TRADES and lok and (lcd is None or nd >= lcd) and lsig(row):
                ep  = ddf.iloc[i+1]["open"]
                tp_ = ep * (1 + CONFIG["long"]["tp"])
                sl_ = ep * (1 - CONFIG["long"]["sl"])
                et, pnl, mfe, mae = sim_exit_full(ddf, i+1, ep, tp_, sl_, "long")
                trades.append({"date": str(date), "side": "long", "entry": ep,
                               "et": et, "pnl": pnl, "mfe": mfe, "mae": mae})
                lc += 1; lcd = nd + datetime.timedelta(minutes=COOLDOWN)

            if sc < MAX_TRADES and sok and (scd is None or nd >= scd) and ssig(row):
                ep  = ddf.iloc[i+1]["open"]
                tp_ = ep * (1 - CONFIG["short"]["tp"])
                sl_ = ep * (1 + CONFIG["short"]["sl"])
                et, pnl, mfe, mae = sim_exit_full(ddf, i+1, ep, tp_, sl_, "short")
                trades.append({"date": str(date), "side": "short", "entry": ep,
                               "et": et, "pnl": pnl, "mfe": mfe, "mae": mae})
                sc += 1; scd = nd + datetime.timedelta(minutes=COOLDOWN)
    return trades


if __name__ == "__main__":
    print("Loading QQQ bars...", flush=True)
    df = pd.read_csv("boof51_QQQ_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df = compute_indicators(df)
    df = resample_trend(df, 5)
    df = resample_trend(df, 10)
    df = df.dropna(subset=["vwap", "ema9", "vsma20"])
    print(f"  {len(df):,} bars, {df['date'].nunique()} days", flush=True)

    trades = run(df, WINDOWS)
    tdf = pd.DataFrame(trades)
    tdf.to_csv("boof51_qqq_trades.csv", index=False)
    print(f"  {len(tdf)} trades saved to boof51_qqq_trades.csv\n", flush=True)

    wins = tdf[tdf["et"] == "tp"]["pnl"]
    loss = tdf[tdf["et"] != "tp"]["pnl"]
    wr   = len(wins) / len(tdf) * 100
    pf   = wins.sum() / abs(loss.sum()) if len(loss) else 0

    SEP = "=" * 55
    print(SEP)
    print(f"  QQQ | Test C | {WINDOWS}")
    print(SEP)
    print(f"  Trades      : {len(tdf)}  ({tdf['date'].nunique()} days)")
    print(f"  Win Rate    : {wr:.1f}%")
    print(f"  Profit Factor: {pf:.2f}")
    print()
    print(f"  {'WINNERS':}")
    print(f"    Count       : {len(wins)}")
    print(f"    Avg Win     : +{wins.mean():.4f}%")
    print(f"    Median Win  : +{wins.median():.4f}%")
    print(f"    Largest Win : +{wins.max():.4f}%")
    print()
    print(f"  LOSERS")
    print(f"    Count       : {len(loss)}")
    print(f"    Avg Loss    : {loss.mean():.4f}%")
    print(f"    Median Loss : {loss.median():.4f}%")
    print(f"    Largest Loss: {loss.min():.4f}%")
    print()
    print(f"  EXCURSION")
    print(f"    Avg MFE     : +{tdf['mfe'].mean():.4f}%")
    print(f"    Avg MAE     :  {tdf['mae'].mean():.4f}%")
    print(f"    Median MFE  : +{tdf['mfe'].median():.4f}%")
    print(f"    Median MAE  :  {tdf['mae'].median():.4f}%")
    print(f"    MFE p90     : +{tdf['mfe'].quantile(0.9):.4f}%")
    print(f"    MAE p90     :  {tdf['mae'].quantile(0.9):.4f}%")
    print(SEP)

    print(f"\n  BY SIDE:")
    for side in ["long", "short"]:
        s = tdf[tdf["side"] == side]
        sw = s[s["et"] == "tp"]; sl = s[s["et"] != "tp"]
        print(f"    {side.upper():5}  N={len(s)}  WR={len(sw)/len(s)*100:.1f}%  "
              f"AvgPnL={s['pnl'].mean():.4f}%  AvgMFE={s['mfe'].mean():.4f}%  AvgMAE={s['mae'].mean():.4f}%")
