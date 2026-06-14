import datetime, os
import pandas as pd
import pytz

ET = pytz.timezone("America/New_York")
SYMBOLS = ["SPY", "QQQ"]
CONFIG = {
    "SPY": {"long": {"tp": 0.0035, "sl": 0.0025}, "short": {"tp": 0.0030, "sl": 0.0025}},
    "QQQ": {"long": {"tp": 0.0045, "sl": 0.0030}, "short": {"tp": 0.0040, "sl": 0.0030}},
}
MAX_TRADES = 5
COOLDOWN   = 10
TIME_STOP  = 90

MORNING = [
    ("09:30","10:00"),("09:30","10:30"),("09:30","11:00"),("09:30","11:30"),("09:30","12:00"),
    ("09:45","11:00"),("10:00","11:00"),("10:00","11:30"),("10:00","12:00"),("11:00","12:00"),
]
AFTERNOON = [("13:30","15:00"),("13:30","15:30"),("14:00","15:30")]
ALL_DAY   = [("09:30","15:55")]


def resample_trend(df, minutes):
    df = df.set_index("time")
    rs = df.resample(f"{minutes}min", closed="left", label="left").agg(
        open=("open","first"), high=("high","max"), low=("low","min"),
        close=("close","last"), volume=("volume","sum")
    ).dropna()
    rs["date"]  = rs.index.date
    rs["typ"]   = (rs["high"] + rs["low"] + rs["close"]) / 3
    rs["pv"]    = rs["typ"] * rs["volume"]
    rs["cpv"]   = rs.groupby("date")["pv"].cumsum()
    rs["cvol"]  = rs.groupby("date")["volume"].cumsum()
    rs["vwap"]  = rs["cpv"] / rs["cvol"]
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
    df["date"] = df["time"].dt.date
    df["typ"]  = (df["high"] + df["low"] + df["close"]) / 3
    df["pv"]   = df["typ"] * df["volume"]
    df["cpv"]  = df.groupby("date")["pv"].cumsum()
    df["cvol"] = df.groupby("date")["volume"].cumsum()
    df["vwap"] = df["cpv"] / df["cvol"]
    df["ema9"]     = df["close"].ewm(span=9, adjust=False).mean()
    df["vsma20"]   = df["volume"].rolling(20).mean()
    df["prev_c"]   = df["close"].shift(1)
    df["prev_v"]   = df["vwap"].shift(1)
    return df


def lsig(row):
    return (row["close"] > row["vwap"] and row["prev_c"] <= row["prev_v"] and
            row["volume"] > row["vsma20"] * 1.2 and row["close"] > row["ema9"])

def ssig(row):
    return (row["close"] < row["vwap"] and row["prev_c"] >= row["prev_v"] and
            row["volume"] > row["vsma20"] * 1.2 and row["close"] < row["ema9"])


def sim_exit(ddf, ei, ep, tp, sl, side):
    mi = min(ei + TIME_STOP, len(ddf) - 1)
    H = ddf["high"].values; L = ddf["low"].values; C = ddf["close"].values
    for j in range(ei, mi + 1):
        if side == "long":
            if H[j] >= tp: return ("tp",  (tp - ep) / ep * 100)
            if L[j] <= sl: return ("sl",  (sl - ep) / ep * 100)
        else:
            if L[j] <= tp: return ("tp",  (ep - tp) / ep * 100)
            if H[j] >= sl: return ("sl",  (ep - sl) / ep * 100)
    px = C[mi]
    return ("time", (px - ep) / ep * 100 if side == "long" else (ep - px) / ep * 100)


def run(df, sym, windows):
    cfg = CONFIG[sym]; trades = []
    for date, ddf in df.groupby("date"):
        ddf = ddf.reset_index(drop=True)
        lc = sc = 0; lcd = scd = None
        for i in range(1, len(ddf) - 1):
            row = ddf.iloc[i]; t = row["time"].strftime("%H:%M")
            if not any(ws <= t < we for ws, we in windows): continue
            if pd.isna(row.get("vwap")) or pd.isna(row.get("vsma20")): continue
            t5  = row.get("t5",  0)
            t10 = row.get("t10", 0)
            lok = (t5 == 1  and t10 == 1)
            sok = (t5 == -1 and t10 == -1)
            nd  = row["time"]
            if lc < MAX_TRADES and lok and (lcd is None or nd >= lcd) and lsig(row):
                ep = ddf.iloc[i+1]["open"]
                tp_ = ep * (1 + cfg["long"]["tp"]); sl_ = ep * (1 - cfg["long"]["sl"])
                et, pnl = sim_exit(ddf, i+1, ep, tp_, sl_, "long")
                trades.append({"et": et, "pnl": pnl, "date": str(date), "sym": sym})
                lc += 1; lcd = nd + datetime.timedelta(minutes=COOLDOWN)
            if sc < MAX_TRADES and sok and (scd is None or nd >= scd) and ssig(row):
                ep = ddf.iloc[i+1]["open"]
                tp_ = ep * (1 - cfg["short"]["tp"]); sl_ = ep * (1 + cfg["short"]["sl"])
                et, pnl = sim_exit(ddf, i+1, ep, tp_, sl_, "short")
                trades.append({"et": et, "pnl": pnl, "date": str(date), "sym": sym})
                sc += 1; scd = nd + datetime.timedelta(minutes=COOLDOWN)
    return trades


def stats(trades, label):
    if not trades:
        return {"label": label, "n": 0, "wr": 0, "avg": 0, "tot": 0, "pf": 0, "tpd": 0}
    df = pd.DataFrame(trades)
    wins = df[df["et"] == "tp"]; loss = df[df["et"] != "tp"]
    wr  = len(wins) / len(df) * 100
    avg = df["pnl"].mean(); tot = df["pnl"].sum()
    gw  = wins["pnl"].sum() if len(wins) else 0
    gl  = abs(loss["pnl"].sum()) if len(loss) else 1e-9
    return {"label": label, "n": len(df), "wr": wr, "avg": avg, "tot": tot,
            "pf": gw / gl, "tpd": len(df) / df["date"].nunique()}


if __name__ == "__main__":
    print("Loading bars...", flush=True)
    bars = {}
    for sym in SYMBOLS:
        f = f"boof51_{sym}_1m.csv"
        df = pd.read_csv(f)
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
        df = compute_indicators(df)
        df = resample_trend(df, 5)
        df = resample_trend(df, 10)
        df = df.dropna(subset=["vwap", "ema9", "vsma20"])
        bars[sym] = df
        print(f"  {sym}: {len(df):,} bars, {df['date'].nunique()} days", flush=True)

    morning_singles   = [[s] for s in MORNING]
    afternoon_singles = [[s] for s in AFTERNOON]
    ma_pairs          = [[m, a] for m in MORNING for a in AFTERNOON]
    all_configs       = morning_singles + afternoon_singles + ma_pairs + [ALL_DAY]

    results = []; total = len(SYMBOLS) * len(all_configs); done = 0
    for sym in SYMBOLS:
        df = bars[sym]
        for windows in all_configs:
            lbl = f"{sym} | " + " + ".join(f"{w[0]}-{w[1]}" for w in windows)
            trades = run(df, sym, windows)
            results.append(stats(trades, lbl))
            done += 1
            if done % 20 == 0:
                print(f"  {done}/{total} done...", flush=True)

    rdf = pd.DataFrame(results).sort_values("pf", ascending=False)
    rdf.to_csv("boof51_testC_all.csv", index=False)

    W = 95
    print(f"\n{'='*W}")
    print("  BOOF51 TEST C (5m+10m agree) -- ALL WINDOWS")
    print(f"{'='*W}")
    print(f"{'Label':<55} {'N':>5} {'WR%':>6} {'Avg':>8} {'Tot':>9} {'PF':>6} {'TPD':>5}")
    print(f"{'-'*W}")
    for _, r in rdf.iterrows():
        print(f"{r['label']:<55} {r['n']:>5} {r['wr']:>6.1f} {r['avg']:>8.4f} {r['tot']:>9.3f} {r['pf']:>6.2f} {r['tpd']:>5.1f}")

    print(f"\nTOP 10:")
    for _, r in rdf.head(10).iterrows():
        print(f"  {r['label']:<55}  PF={r['pf']:.2f}  WR={r['wr']:.1f}%  N={r['n']}  TPD={r['tpd']:.1f}")
    print("\nSaved to boof51_testC_all.csv")
