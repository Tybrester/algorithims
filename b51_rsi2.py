"""
BOOF51 RSI(2) Pullback — SPY & QQQ
Trend from 15m: close > EMA20 > EMA50 (up) / close < EMA20 < EMA50 (down)
Long:  trend_up,   close > VWAP, RSI2(1m) < 20, low  <= EMA20(1m)
Short: trend_down, close < VWAP, RSI2(1m) > 80, high >= EMA20(1m)
Entry next bar open. Tests TP/SL: (0.50/0.25) and (0.75/0.50)
"""
import datetime
import pandas as pd
import pytz

ET = pytz.timezone("America/New_York")
SYMBOLS  = ["SPY", "QQQ"]
TP_SL_COMBOS = [
    {"tp": 0.0050, "sl": 0.0025, "label": "TP0.50/SL0.25"},
    {"tp": 0.0075, "sl": 0.0050, "label": "TP0.75/SL0.50"},
]
MAX_TRADES = 5
COOLDOWN   = 10
TIME_STOP  = 90
ALL_DAY    = [("09:30", "15:55")]


def calc_rsi2(s):
    d = s.diff()
    g = d.clip(lower=0).ewm(com=1, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(com=1, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, 1e-9))


def add_15m_trend(df):
    """Compute EMA20/EMA50 on 15m bars, derive trend, merge to 1m."""
    d = df.set_index("time")
    rs = d.resample("15min", closed="left", label="left").agg(
        close=("close","last"), volume=("volume","sum")
    ).dropna()
    rs["ema20_15"] = rs["close"].ewm(span=20, adjust=False).mean()
    rs["ema50_15"] = rs["close"].ewm(span=50, adjust=False).mean()
    rs["trend15"]  = 0
    rs.loc[(rs["close"] > rs["ema20_15"]) & (rs["ema20_15"] > rs["ema50_15"]), "trend15"] =  1
    rs.loc[(rs["close"] < rs["ema20_15"]) & (rs["ema20_15"] < rs["ema50_15"]), "trend15"] = -1
    df = d.reset_index()
    return pd.merge_asof(
        df.sort_values("time"),
        rs[["trend15"]].reset_index().rename(columns={"time":"rt"}),
        left_on="time", right_on="rt", direction="backward"
    )


def compute_1m(df):
    df = df.copy().reset_index(drop=True)
    df["date"]  = df["time"].dt.date
    df["typ"]   = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]    = df["typ"] * df["volume"]
    df["cpv"]   = df.groupby("date")["pv"].cumsum()
    df["cvol"]  = df.groupby("date")["volume"].cumsum()
    df["vwap"]  = df["cpv"] / df["cvol"]
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["rsi2"]  = calc_rsi2(df["close"])
    return df


def lsig(row):
    return (row["trend15"] == 1 and
            row["close"]   >  row["vwap"] and
            row["rsi2"]    <  20 and
            row["low"]     <= row["ema20"])

def ssig(row):
    return (row["trend15"] == -1 and
            row["close"]   <  row["vwap"] and
            row["rsi2"]    >  80 and
            row["high"]    >= row["ema20"])


def sim_exit(ddf, ei, ep, tp, sl, side):
    mi = min(ei + TIME_STOP, len(ddf) - 1)
    H = ddf["high"].values; L = ddf["low"].values; C = ddf["close"].values
    mfe = mae = 0.0; et = "time"; xp = C[mi]
    for j in range(ei, mi + 1):
        if side == "long":
            mfe = max(mfe, (H[j]-ep)/ep*100); mae = max(mae, (ep-L[j])/ep*100)
            if H[j] >= tp: et="tp"; xp=tp; break
            if L[j] <= sl: et="sl"; xp=sl; break
        else:
            mfe = max(mfe, (ep-L[j])/ep*100); mae = max(mae, (H[j]-ep)/ep*100)
            if L[j] <= tp: et="tp"; xp=tp; break
            if H[j] >= sl: et="sl"; xp=sl; break
    pnl = (xp-ep)/ep*100 if side=="long" else (ep-xp)/ep*100
    return et, pnl, mfe, mae


def run(df, tp_pct, sl_pct):
    trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        lc = sc = 0; lcd = scd = None
        for i in range(1, len(ddf)-1):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not ("09:30" <= t < "15:55"): continue
            if pd.isna(row.get("vwap")) or pd.isna(row.get("ema20")) or pd.isna(row.get("rsi2")): continue
            nd = row["time"]
            if lc < MAX_TRADES and (lcd is None or nd >= lcd) and lsig(row):
                ep = ddf.iloc[i+1]["open"]
                et, pnl, mfe, mae = sim_exit(ddf, i+1, ep, ep*(1+tp_pct), ep*(1-sl_pct), "long")
                trades.append({"date":str(date),"side":"long","et":et,"pnl":pnl,"mfe":mfe,"mae":mae})
                lc += 1; lcd = nd + datetime.timedelta(minutes=COOLDOWN)
            if sc < MAX_TRADES and (scd is None or nd >= scd) and ssig(row):
                ep = ddf.iloc[i+1]["open"]
                et, pnl, mfe, mae = sim_exit(ddf, i+1, ep, ep*(1-tp_pct), ep*(1+sl_pct), "short")
                trades.append({"date":str(date),"side":"short","et":et,"pnl":pnl,"mfe":mfe,"mae":mae})
                sc += 1; scd = nd + datetime.timedelta(minutes=COOLDOWN)
    return trades


def report(trades, label):
    if not trades: print(f"\n{label}: No trades"); return
    df   = pd.DataFrame(trades)
    wins = df[df["et"]=="tp"]["pnl"]; loss = df[df["et"]!="tp"]["pnl"]
    wr   = len(wins)/len(df)*100
    pf   = wins.sum()/abs(loss.sum()) if len(loss) and loss.sum()!=0 else 0
    tpd  = len(df)/df["date"].nunique()
    S = "="*60
    print(f"\n{S}\n  {label}\n{S}")
    print(f"  Trades:{len(df):>4}  Days:{df['date'].nunique():>4}  TPD:{tpd:.1f}  WR:{wr:.1f}%  PF:{pf:.2f}")
    print(f"\n  WINNERS ({len(wins)})")
    print(f"    Avg Win      : +{wins.mean():.4f}%")
    print(f"    Median Win   : +{wins.median():.4f}%")
    print(f"    Largest Win  : +{wins.max():.4f}%")
    print(f"\n  LOSERS ({len(loss)})")
    print(f"    Avg Loss     :  {loss.mean():.4f}%")
    print(f"    Median Loss  :  {loss.median():.4f}%")
    print(f"    Largest Loss :  {loss.min():.4f}%")
    print(f"\n  EXCURSION")
    print(f"    Avg MFE      : +{df['mfe'].mean():.4f}%")
    print(f"    Avg MAE      :  {df['mae'].mean():.4f}%")
    print(f"    Median MFE   : +{df['mfe'].median():.4f}%")
    print(f"    Median MAE   :  {df['mae'].median():.4f}%")
    print(f"\n  BY SIDE")
    for side in ["long","short"]:
        s=df[df["side"]==side]
        if s.empty: continue
        sw=s[s["et"]=="tp"]
        print(f"    {side.upper():5}  N={len(s)}  WR={len(sw)/len(s)*100:.1f}%  "
              f"AvgPnL={s['pnl'].mean():.4f}%  AvgMFE={s['mfe'].mean():.4f}%  AvgMAE={s['mae'].mean():.4f}%")


if __name__ == "__main__":
    print("Loading bars...", flush=True)
    bars = {}
    for sym in SYMBOLS:
        df = pd.read_csv(f"boof51_{sym}_1m.csv")
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
        df = compute_1m(df)
        df = add_15m_trend(df)
        df = df.dropna(subset=["vwap","ema20","rsi2","trend15"])
        bars[sym] = df
        print(f"  {sym}: {len(df):,} bars, {df['date'].nunique()} days", flush=True)

    for combo in TP_SL_COMBOS:
        for sym in SYMBOLS:
            trades = run(bars[sym], combo["tp"], combo["sl"])
            report(trades, f"{sym} | RSI(2) Pullback | {combo['label']} | All Day")

