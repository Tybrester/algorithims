"""
BOOF51 Options Simulation — QQQ Gap-Down Reversal
Signal: gap_pct <= -0.5%, first green/red candle entry
Simulate: 0DTE and 1DTE ATM calls/puts at entry, exit after 15/30/60 min
Uses Black-Scholes to price options at entry and exit
IV estimated from recent VIX proxy (flat assumption, can be improved)
"""
import pandas as pd
import numpy as np
import pytz
from scipy.stats import norm

ET = pytz.timezone("America/New_York")

# ── Black-Scholes ─────────────────────────────────────────────────────────────

def bs_price(S, K, T, r, sigma, opt):
    """T in years. opt = 'call' or 'put'"""
    if T <= 0: return max(0, S - K) if opt == "call" else max(0, K - S)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if opt == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_delta(S, K, T, r, sigma, opt):
    if T <= 0: return 1.0 if (opt == "call" and S > K) else 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return norm.cdf(d1) if opt == "call" else norm.cdf(d1) - 1


def find_strike(S, target_delta, T, r, sigma, opt, step=1.0):
    """Find strike closest to target delta."""
    best_K = S; best_diff = 99
    # Search strikes from deep ITM to deep OTM
    for K in np.arange(S * 0.90, S * 1.10, step):
        d = abs(bs_delta(S, K, T, r, sigma, opt))
        diff = abs(d - target_delta)
        if diff < best_diff:
            best_diff = diff; best_K = K
    return round(best_K)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_pm(sym):
    df = pd.read_csv(f"boof51_{sym}_pm.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    return df


def load_rt(sym):
    df = pd.read_csv(f"boof51_{sym}_1m.csv")
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(ET)
    df["date"] = df["time"].dt.date
    return df


def build_pm_stats(pm_df, rt_df):
    pm_df["date"] = pm_df["time"].dt.date
    daily_close = rt_df.groupby("date")["close"].last().reset_index()
    daily_close.columns = ["date", "prev_close"]
    daily_close["date"] = pd.to_datetime(daily_close["date"])
    daily_close["next_date"] = daily_close["date"] + pd.Timedelta(days=1)
    stats = pd.DataFrame([
        {"date": pd.Timestamp(d), "pm_high": g["high"].max(), "pm_low": g["low"].min()}
        for d, g in pm_df.groupby("date")
    ])
    stats = stats.merge(
        daily_close[["next_date","prev_close"]].rename(columns={"next_date":"date"}),
        on="date", how="left"
    )
    rth = rt_df[rt_df["time"].dt.strftime("%H:%M") == "09:30"].copy()
    rth["date"] = pd.to_datetime(rth["date"])
    rth = rth.groupby("date")["open"].first().reset_index()
    rth.columns = ["date", "rth_open"]
    stats = stats.merge(rth, on="date", how="left")
    stats["gap_pct"] = (stats["rth_open"] - stats["prev_close"]) / stats["prev_close"] * 100
    return stats.dropna(subset=["gap_pct"])


# ── Main sim ──────────────────────────────────────────────────────────────────

def simulate(rt_df, pm_stats, iv=0.20, r=0.05, gap_thresh=-0.5):
    """
    For each gap-down day:
      Find first green candle (long) and first red candle (short)
      Price ATM and 50-delta options at entry
      Reprice at +15, +30, +60 bars using actual QQQ price
      Compute P&L per contract (x100)
    """
    rt_df = rt_df.copy()
    rt_df["date"] = pd.to_datetime(rt_df["date"])
    gap_days = pm_stats[pm_stats["gap_pct"] <= gap_thresh].set_index("date")

    CONFIGS = [
        {"dte": 0, "delta_target": 0.50, "label": "0DTE ATM"},
        {"dte": 1, "delta_target": 0.50, "label": "1DTE ATM"},
        {"dte": 0, "delta_target": 0.45, "label": "0DTE ~45d"},
        {"dte": 1, "delta_target": 0.45, "label": "1DTE ~45d"},
    ]
    EXIT_BARS = [15, 30, 60]

    all_trades = []

    for date, ddf in rt_df.groupby("date"):
        date = pd.Timestamp(date)
        if date not in gap_days.index: continue
        day = gap_days.loc[date]

        ddf = ddf.reset_index(drop=True)
        rth = ddf[ddf["time"].dt.strftime("%H:%M") >= "09:30"].reset_index(drop=True)
        if len(rth) < 62: continue

        long_fired = short_fired = False

        for j in range(len(rth) - 61):
            row = rth.iloc[j]; t = row["time"].strftime("%H:%M")
            if t >= "12:00": break

            for side, fired, flag in [("long", long_fired, row["close"] > row["open"]),
                                       ("short", short_fired, row["close"] < row["open"])]:
                if fired or not flag: continue
                if side == "long":   long_fired  = True
                else:                short_fired = True

                ei = j + 1
                if ei >= len(rth): continue
                ep    = rth.iloc[ei]["open"]
                opt   = "call" if side == "long" else "put"

                for cfg in CONFIGS:
                    dte   = cfg["dte"]
                    T_entry = (dte + (390 - (ei * 1)) / 390) / 252   # remaining trading day fraction
                    T_entry = max(T_entry, 1/(252*390))

                    K_atm = round(ep)   # ATM = nearest dollar strike

                    if cfg["delta_target"] == 0.50:
                        K = K_atm
                    else:
                        K = find_strike(ep, cfg["delta_target"], T_entry, r, iv, opt)

                    price_entry = bs_price(ep, K, T_entry, r, iv, opt)
                    delta_entry = abs(bs_delta(ep, K, T_entry, r, iv, opt))

                    for bars in EXIT_BARS:
                        xi = min(ei + bars, len(rth) - 1)
                        xp = rth.iloc[xi]["close"]
                        T_exit = max(T_entry - bars / (252 * 390), 1/(252*390))

                        # IV expansion on gap days — slight bump
                        iv_exit = iv * 0.95  # slight IV crush as day progresses

                        price_exit = bs_price(xp, K, T_exit, r, iv_exit, opt)
                        pnl_pct    = (price_exit - price_entry) / price_entry * 100
                        pnl_dollar = (price_exit - price_entry) * 100  # per contract

                        # underlying move
                        und_move = (xp - ep) / ep * 100 if side == "long" else (ep - xp) / ep * 100

                        all_trades.append({
                            "date":        str(date.date()),
                            "side":        side,
                            "gap_pct":     round(day["gap_pct"], 3),
                            "config":      cfg["label"],
                            "exit_bars":   bars,
                            "ep":          round(ep, 2),
                            "K":           K,
                            "delta":       round(delta_entry, 3),
                            "opt_entry":   round(price_entry, 3),
                            "opt_exit":    round(price_exit, 3),
                            "und_move":    round(und_move, 4),
                            "pnl_pct":     round(pnl_pct, 2),
                            "pnl_dollar":  round(pnl_dollar, 2),
                        })

            if long_fired and short_fired: break

    return pd.DataFrame(all_trades)


def report(df):
    W = 92
    print(f"\n{'='*W}")
    print(f"  QQQ Options Sim | Gap Down ≤-0.5% | 1st Green/Red Candle | IV=20%")
    print(f"{'='*W}")
    print(f"  {'Config':<14} {'Side':<7} {'Exit':>6}  "
          f"{'N':>4}  {'Avg Und%':>9} {'WR%':>6}  "
          f"{'AvgPnL%':>8} {'AvgPnL$':>8} {'Med PnL$':>9} {'Best$':>8} {'Worst$':>8}")
    print(f"  {'-'*88}")

    for config in df["config"].unique():
        for side in ["long","short"]:
            for bars in [15, 30, 60]:
                s = df[(df["config"]==config) & (df["side"]==side) & (df["exit_bars"]==bars)]
                if s.empty: continue
                wr      = (s["pnl_dollar"] > 0).mean() * 100
                avg_und = s["und_move"].mean()
                avg_pct = s["pnl_pct"].mean()
                avg_d   = s["pnl_dollar"].mean()
                med_d   = s["pnl_dollar"].median()
                best    = s["pnl_dollar"].max()
                worst   = s["pnl_dollar"].min()
                print(f"  {config:<14} {side:<7} {bars:>4}m  "
                      f"{len(s):>4}  {avg_und:>+8.3f}% {wr:>6.1f}%  "
                      f"{avg_pct:>+7.1f}% {avg_d:>+8.2f} {med_d:>+9.2f} {best:>+8.2f} {worst:>+8.2f}")
        print(f"  {'-'*88}")


if __name__ == "__main__":
    print("Loading QQQ...", flush=True)
    pm_df    = load_pm("QQQ")
    rt_df    = load_rt("QQQ")
    pm_stats = build_pm_stats(pm_df, rt_df)

    n_gap = (pm_stats["gap_pct"] <= -0.5).sum()
    print(f"  {n_gap} gap-down days", flush=True)

    print("Simulating options...", flush=True)
    df = simulate(rt_df, pm_stats, iv=0.20, gap_thresh=-0.5)
    df.to_csv("boof51_QQQ_options.csv", index=False)
    print(f"  {len(df)} option trade records saved", flush=True)

    report(df)

    # Quick summary table
    print(f"\n{'='*60}")
    print("  SUMMARY — Avg P&L per contract by config + exit time")
    print(f"{'='*60}")
    print(f"  {'Config':<14} {'15m':>10} {'30m':>10} {'60m':>10}")
    print(f"  {'-'*50}")
    for config in df["config"].unique():
        vals = []
        for bars in [15, 30, 60]:
            s = df[(df["config"]==config) & (df["exit_bars"]==bars)]
            vals.append(f"{s['pnl_dollar'].mean():>+9.2f}")
        print(f"  {config:<14} {'  '.join(vals)}")
