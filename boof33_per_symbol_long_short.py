import os
import pandas as pd
import numpy as np
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

API_KEY    = "AKPDLKERTEC2OG42UROO65QMW7"
API_SECRET = "MTDQmZk5KuQU5p5ZQE4YWMvksTLcxJeGJiCeA4j2vPM"
client = StockHistoricalDataClient(API_KEY, API_SECRET)

SYMBOLS = [
    "AAPL","MSFT","NVDA","AMD","META",
    "AMZN","TSLA","AVGO","MU","QCOM",
    "CRWD","PANW","DDOG","NET","ZS",
    "HOOD","COIN","PLTR","APP","SMCI"
]

START="2025-12-13"; END="2026-06-13"
TP1=0.005; RUNNER=0.015; STOP=0.004; MAX_HOLD_BARS=30
MIN_RVOL=1.5; MIN_BODY=0.0025; VWAP_SLOPE_BARS=5
MARKET_OPEN="09:30"; SIGNAL_END="10:30"


def fetch_bars(symbol):
    cache = f"boof32_data_{symbol}.csv"
    if os.path.exists(cache):
        df = pd.read_csv(cache, dtype_backend="numpy_nullable")
        if "datetime" in df.columns: df = df.rename(columns={"datetime":"timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("America/New_York")
        for col in ["open","high","low","close","volume"]: df[col]=df[col].astype(float)
        for col in ["vwap","trade_count"]:
            if col in df.columns: df=df.drop(columns=[col])
        return df.sort_values("timestamp").reset_index(drop=True)
    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute,
                           start=pd.Timestamp(START,tz="America/New_York"),
                           end=pd.Timestamp(END,tz="America/New_York"), feed="iex")
    bars = client.get_stock_bars(req).df
    if bars.empty: return pd.DataFrame()
    if isinstance(bars.index, pd.MultiIndex): bars=bars.reset_index()
    bars["timestamp"]=pd.to_datetime(bars["timestamp"]).dt.tz_convert("America/New_York")
    return bars.sort_values("timestamp").reset_index(drop=True)


def add_features(df):
    df=df.copy()
    df["date"]=df["timestamp"].dt.date
    df["time"]=df["timestamp"].dt.strftime("%H:%M")
    typ=(df["high"]+df["low"]+df["close"])/3
    df["pv"]=typ*df["volume"]
    df["cum_pv"]=df.groupby("date")["pv"].cumsum()
    df["cum_vol"]=df.groupby("date")["volume"].cumsum()
    df["vwap"]=df["cum_pv"]/df["cum_vol"]
    df["vwap_slope"]=df.groupby("date")["vwap"].pct_change(VWAP_SLOPE_BARS)
    df["body_pct"]=(df["close"]-df["open"]).abs()/df["open"]
    df["avg_vol_20"]=df.groupby("date")["volume"].transform(lambda x: x.rolling(20,min_periods=5).mean())
    df["rvol"]=df["volume"]/df["avg_vol_20"]
    return df


def simulate_trade(day_df, entry_i, direction):
    entry=day_df.iloc[entry_i]["close"]; entry_time=day_df.iloc[entry_i]["timestamp"]
    if direction=="LONG":
        sp=entry*(1-STOP); tp1p=entry*(1+TP1); rp=entry*(1+RUNNER)
    else:
        sp=entry*(1+STOP); tp1p=entry*(1-TP1); rp=entry*(1-RUNNER)
    hit_tp1=False; pnl=0.0; end_i=min(entry_i+MAX_HOLD_BARS,len(day_df)-1)
    for j in range(entry_i+1,end_i+1):
        row=day_df.iloc[j]; h=row["high"]; l=row["low"]
        if direction=="LONG":
            if not hit_tp1:
                if l<=sp: return -STOP,entry_time
                if h>=tp1p: hit_tp1=True; pnl+=TP1*0.5; sp=entry
            if hit_tp1:
                if l<=sp: return pnl,entry_time
                if h>=rp: pnl+=RUNNER*0.5; return pnl,entry_time
        else:
            if not hit_tp1:
                if h>=sp: return -STOP,entry_time
                if l<=tp1p: hit_tp1=True; pnl+=TP1*0.5; sp=entry
            if hit_tp1:
                if h>=sp: return pnl,entry_time
                if l<=rp: pnl+=RUNNER*0.5; return pnl,entry_time
    ep=day_df.iloc[end_i]["close"]
    raw=(ep-entry)/entry if direction=="LONG" else (entry-ep)/entry
    return (pnl+raw*0.5 if hit_tp1 else raw),entry_time


def backtest_symbol(symbol):
    df=fetch_bars(symbol)
    if df.empty: return []
    df=add_features(df); trades=[]
    for date,day in df.groupby("date"):
        day=day.reset_index(drop=True)
        sig=day[(day["time"]>=MARKET_OPEN)&(day["time"]<=SIGNAL_END)]
        for i in sig.index:
            row=day.iloc[i]
            if pd.isna(row["vwap"]) or pd.isna(row["vwap_slope"]) or pd.isna(row["rvol"]): continue
            if row["rvol"]<MIN_RVOL or row["body_pct"]<MIN_BODY: continue
            ls=row["close"]>row["vwap"] and row["vwap_slope"]>0 and row["close"]>row["open"]
            ss=row["close"]<row["vwap"] and row["vwap_slope"]<0 and row["close"]<row["open"]
            if ls:
                pnl,t=simulate_trade(day,i,"LONG")
                trades.append({"symbol":symbol,"date":date,"time":t,"side":"LONG","pnl":pnl})
            if ss:
                pnl,t=simulate_trade(day,i,"SHORT")
                trades.append({"symbol":symbol,"date":date,"time":t,"side":"SHORT","pnl":pnl})
    return trades


def summarize(trades):
    df=pd.DataFrame(trades)
    if df.empty: print("No trades."); return df
    rows=[]
    for (symbol,side),g in df.groupby(["symbol","side"]):
        wins=g[g["pnl"]>0]; losses=g[g["pnl"]<0]
        gw=wins["pnl"].sum(); gl=abs(losses["pnl"].sum())
        pf=gw/gl if gl>0 else float("inf")
        rows.append({"Symbol":symbol,"Side":side,"Trades":len(g),
                     "WR":len(wins)/len(g)*100,"PF":pf,
                     "EV%":g["pnl"].mean()*100,"Total%":g["pnl"].sum()*100})
    out=pd.DataFrame(rows).sort_values(["PF","EV%"],ascending=False)
    print("\n==============================")
    print("BOOF33 PER-SYMBOL DIRECTION STUDY")
    print("==============================")
    print(out.to_string(index=False,formatters={
        "WR":"{:.1f}%".format,
        "PF":lambda x:"inf" if np.isinf(x) else f"{x:.2f}",
        "EV%":"{:.4f}%".format,"Total%":"{:.2f}%".format}))
    print("\n==============================")
    print("RECOMMENDED SYMBOL PROFILES")
    print("==============================")
    for symbol,g in out.groupby("Symbol"):
        good=g[(g["PF"]>=1.10)&(g["Trades"]>=10)&(g["EV%"]>0)]
        if len(good)==2: rec="BOTH"
        elif len(good)==1: rec=good.iloc[0]["Side"]+" ONLY"
        else: rec="KILL / RETEST"
        print(f"  {symbol}: {rec}")
    return out


if __name__=="__main__":
    all_trades=[]
    for symbol in SYMBOLS:
        print(f"Scanning {symbol}...")
        t=backtest_symbol(symbol)
        all_trades.extend(t)
        print(f"  -> {len(t)} trades")
    pd.DataFrame(all_trades).to_csv("boof33_per_symbol_trades.csv",index=False)
    summary=summarize(all_trades)
    summary.to_csv("boof33_per_symbol_summary.csv",index=False)
    print("\nSaved: boof33_per_symbol_trades.csv  boof33_per_symbol_summary.csv")
