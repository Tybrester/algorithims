"""
Attention Acceleration Scanner
Sources:
  - Reddit (JSON API, no key)
  - StockTwits (public API, no key)
  - Yahoo Finance news + trending (public, no key)
  - Google News RSS (no key)
  - Seeking Alpha via RSS (limited but free)
  - Google Trends via pytrends (no key)
  - Earnings calendar via Yahoo Finance
  - Analyst coverage via Yahoo Finance quote summary

Output: ranked table by attention acceleration score
"""
import requests, re, time, os, json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import pytz, warnings
warnings.filterwarnings("ignore")

ET  = pytz.timezone("America/New_York")
NOW = datetime.now(ET)

STOPWORDS = {
    "THE","AND","FOR","ARE","BUT","NOT","YOU","ALL","CAN","HER","WAS","ONE",
    "OUR","OUT","DAY","GET","HAS","HIM","HIS","HOW","ITS","LET","MAY","NEW",
    "NOW","OLD","SEE","TWO","WAY","WHO","BOY","DID","SHE","TOO","USE","ETF",
    "IPO","SEC","FDA","CEO","CFO","USA","NYSE","AMC","GME","SPY","QQQ","SPX",
    "VIX","EPS","ATH","ATL","WSB","IMO","EOD","BUY","SELL","PUTS","CALL",
    "SHORT","LONG","BULL","BEAR","THIS","THAT","FROM","WITH","THEY","BEEN",
    "HAVE","WILL","WHAT","WHEN","THEN","THAN","JUST","LIKE","INTO","OVER",
    "ALSO","BACK","YEAR","GOOD","SOME","WELL","MOST","MAKE","SAID","EACH",
    "WHICH","THEIR","THERE","CALLS","HOLD","YOLO","HODL","HIGH","LOW","NEWS",
    "RATE","WEEK","NEXT","LAST","MORE","AFTER","BEFORE","ABOUT","COULD","WOULD",
    "SHOULD","STOCK","STOCKS","MARKET","PRICE","TRADE","TRADING","SHARE","SHARES",
}
HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def extract_tickers(text):
    found = re.findall(r'\b\$?([A-Z]{1,5})\b', text.upper())
    return [t.lstrip("$") for t in found if t not in STOPWORDS and 2 <= len(t) <= 5]

def in_window(timestamps, days):
    cutoff = NOW - timedelta(days=days)
    return sum(1 for t in timestamps if t >= cutoff)

# ─────────────────────────────────────────────────────────────────────────────
# 1. REDDIT
# ─────────────────────────────────────────────────────────────────────────────
def fetch_reddit(days_back=84):
    print("  Reddit...", flush=True)
    mentions = defaultdict(list)
    subs = ["wallstreetbets","stocks","investing","options","StockMarket","Daytrading","pennystocks"]
    cutoff = NOW - timedelta(days=days_back)
    for sub in subs:
        for sort in ["hot","new"]:
            url = f"https://www.reddit.com/r/{sub}/{sort}.json?limit=100"
            try:
                r = requests.get(url, headers=HDRS, timeout=12)
                if r.status_code != 200: continue
                posts = r.json().get("data",{}).get("children",[])
                for post in posts:
                    d = post.get("data",{})
                    ts = datetime.fromtimestamp(d.get("created_utc",0), tz=ET)
                    if ts < cutoff: continue
                    text = d.get("title","") + " " + d.get("selftext","")
                    for t in extract_tickers(text):
                        mentions[t].append(ts)
                time.sleep(0.4)
            except Exception as e:
                print(f"    reddit {sub}/{sort}: {e}")
    print(f"    {len(mentions)} tickers, {sum(len(v) for v in mentions.values())} mentions")
    return mentions

# ─────────────────────────────────────────────────────────────────────────────
# 2. STOCKTWITS
# ─────────────────────────────────────────────────────────────────────────────
def fetch_stocktwits():
    print("  StockTwits trending...", flush=True)
    scores = {}
    try:
        r = requests.get("https://api.stocktwits.com/api/2/trending/symbols.json", timeout=10)
        for s in r.json().get("symbols",[]):
            scores[s["symbol"]] = {"st_watchlist": s.get("watchlist_count",0), "st_trending": True}
    except Exception as e:
        print(f"    StockTwits: {e}")
    print(f"    {len(scores)} trending symbols")
    return scores

def fetch_stocktwits_symbol(sym, days_back=84):
    """Get message count for a specific symbol."""
    mentions = []
    cutoff = NOW - timedelta(days=days_back)
    try:
        r = requests.get(f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json", timeout=8)
        msgs = r.json().get("messages",[])
        for m in msgs:
            try:
                ts = datetime.strptime(m["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc).astimezone(ET)
                if ts >= cutoff:
                    mentions.append(ts)
            except: pass
    except: pass
    return mentions

# ─────────────────────────────────────────────────────────────────────────────
# 3. YAHOO FINANCE — trending + news
# ─────────────────────────────────────────────────────────────────────────────
def fetch_yahoo_trending():
    print("  Yahoo Finance trending...", flush=True)
    tickers = set()
    for url in [
        "https://query1.finance.yahoo.com/v1/finance/trending/US?count=200",
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=most_actives&count=200",
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers&count=200",
    ]:
        try:
            r = requests.get(url, headers=HDRS, timeout=10)
            data = r.json()
            result = data.get("finance",{}).get("result",[{}])
            if not result: continue
            quotes = result[0].get("quotes",[])
            for q in quotes:
                sym = q.get("symbol","")
                if sym and "." not in sym and len(sym) <= 5:
                    tickers.add(sym)
        except Exception as e:
            print(f"    Yahoo: {e}")
    print(f"    {len(tickers)} symbols from Yahoo")
    return tickers

def fetch_yahoo_news(sym, days_back=84):
    """Fetch news count for a symbol via Yahoo Finance."""
    mentions = []
    cutoff = NOW - timedelta(days=days_back)
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={sym}&newsCount=50&quotesCount=0"
        r = requests.get(url, headers=HDRS, timeout=8)
        news = r.json().get("news",[])
        for n in news:
            ts_raw = n.get("providerPublishTime",0)
            if not ts_raw: continue
            ts = datetime.fromtimestamp(ts_raw, tz=ET)
            if ts >= cutoff:
                mentions.append(ts)
    except: pass
    return mentions

# ─────────────────────────────────────────────────────────────────────────────
# 4. GOOGLE NEWS RSS
# ─────────────────────────────────────────────────────────────────────────────
def fetch_google_news(sym, days_back=84):
    import xml.etree.ElementTree as EX
    mentions = []
    cutoff = NOW - timedelta(days=days_back)
    try:
        url = f"https://news.google.com/rss/search?q={sym}+stock+NYSE+NASDAQ&hl=en-US&gl=US&ceid=US:en"
        r = requests.get(url, headers=HDRS, timeout=10)
        root = EX.fromstring(r.content)
        for item in root.findall(".//item"):
            pub = item.find("pubDate")
            if pub is None: continue
            try:
                ts = datetime.strptime(pub.text[:25].strip(), "%a, %d %b %Y %H:%M:%S")
                ts = pytz.utc.localize(ts).astimezone(ET)
                if ts >= cutoff: mentions.append(ts)
            except: pass
    except: pass
    return mentions

# ─────────────────────────────────────────────────────────────────────────────
# 5. SEEKING ALPHA (via RSS — limited to 10 recent articles)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_seekingalpha(sym, days_back=84):
    import xml.etree.ElementTree as EX
    mentions = []
    cutoff = NOW - timedelta(days=days_back)
    try:
        url = f"https://seekingalpha.com/api/sa/combined/{sym}.xml"
        r = requests.get(url, headers=HDRS, timeout=10)
        root = EX.fromstring(r.content)
        for item in root.findall(".//item"):
            pub = item.find("pubDate")
            if pub is None: continue
            try:
                ts = datetime.strptime(pub.text[:25].strip(), "%a, %d %b %Y %H:%M:%S")
                ts = pytz.utc.localize(ts).astimezone(ET)
                if ts >= cutoff: mentions.append(ts)
            except: pass
    except: pass
    return mentions

# ─────────────────────────────────────────────────────────────────────────────
# 6. GOOGLE TRENDS (pytrends)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_google_trends(syms):
    print("  Google Trends...", flush=True)
    trends = {}
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=300)
        # Process in batches of 5
        for i in range(0, len(syms), 5):
            batch = syms[i:i+5]
            try:
                pt.build_payload(batch, timeframe="today 3-m", geo="US")
                df = pt.interest_over_time()
                if df.empty: continue
                for sym in batch:
                    if sym in df.columns:
                        vals = df[sym].values
                        if len(vals) >= 8:
                            recent = vals[-4:].mean()
                            older  = vals[-12:-8].mean() if len(vals) >= 12 else vals[:4].mean()
                            trends[sym] = round((recent - older) / (older + 1) * 100, 1)
                time.sleep(1)
            except Exception as e:
                pass
    except ImportError:
        print("    pytrends not installed — skip (pip install pytrends)")
    except Exception as e:
        print(f"    Google Trends: {e}")
    print(f"    {len(trends)} symbols with trend data")
    return trends

# ─────────────────────────────────────────────────────────────────────────────
# 7. EARNINGS + ANALYST coverage via Yahoo
# ─────────────────────────────────────────────────────────────────────────────
def fetch_yahoo_meta(sym):
    """Get analyst count and upcoming earnings flag."""
    meta = {"analysts": 0, "earnings_soon": False}
    try:
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{sym}?modules=recommendationTrend,calendarEvents"
        r = requests.get(url, headers=HDRS, timeout=8)
        data = r.json().get("quoteSummary",{}).get("result",[{}])
        if not data: return meta
        d = data[0]
        trend = d.get("recommendationTrend",{}).get("trend",[])
        if trend:
            t0 = trend[0]
            meta["analysts"] = t0.get("strongBuy",0) + t0.get("buy",0) + t0.get("hold",0) + t0.get("sell",0)
        cal = d.get("calendarEvents",{}).get("earnings",{})
        dates = cal.get("earningsDate",[])
        if dates:
            ep = dates[0].get("raw",0)
            if ep:
                ed = datetime.fromtimestamp(ep, tz=ET)
                if timedelta(0) <= (ed - NOW) <= timedelta(days=30):
                    meta["earnings_soon"] = True
    except: pass
    return meta

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\nAttention Scanner — {NOW.strftime('%Y-%m-%d %H:%M ET')}")
    print("="*60)

    # Step 1: Get universe from Reddit + Yahoo
    reddit_mentions = fetch_reddit(days_back=84)
    st_data         = fetch_stocktwits()
    yf_tickers      = fetch_yahoo_trending()

    # Combine all tickers to scan
    universe = (set(reddit_mentions.keys()) | set(st_data.keys()) | yf_tickers)
    universe = {t for t in universe if t not in STOPWORDS and 2 <= len(t) <= 5}
    # Filter to reasonable stocks — skip obvious non-tickers
    universe = {t for t in universe if re.match(r'^[A-Z]{1,5}$', t)}
    print(f"\nUniverse: {len(universe)} unique tickers to score\n")

    # Step 2: Per-ticker deep fetch
    print("Fetching per-ticker data (news, SA, StockTwits)...")
    rows = []
    universe_list = sorted(universe)

    # Google Trends batch
    gt_scores = fetch_google_trends(universe_list[:50])  # limit to top 50 for speed

    for idx, sym in enumerate(universe_list):
        if idx % 20 == 0:
            print(f"  {idx}/{len(universe_list)}...", flush=True)

        r_ts  = reddit_mentions.get(sym, [])
        ynews = fetch_yahoo_news(sym, days_back=84)
        gnews = fetch_google_news(sym, days_back=84)
        sa    = fetch_seekingalpha(sym, days_back=84)
        st_ts = fetch_stocktwits_symbol(sym, days_back=84) if sym in st_data else []
        meta  = fetch_yahoo_meta(sym)

        all_ts = r_ts + ynews + gnews + sa + st_ts

        m4  = in_window(all_ts, 28)
        m8  = in_window(all_ts, 56)
        m12 = in_window(all_ts, 84)

        # Breakdown by source for last 4 weeks
        r4   = in_window(r_ts,   28)
        st4  = in_window(st_ts,  28)
        yn4  = in_window(ynews,  28)
        gn4  = in_window(gnews,  28)
        sa4  = in_window(sa,     28)

        # Weekly rates
        rate_0_4  = m4 / 4
        rate_4_8  = (m8  - m4) / 4
        rate_8_12 = (m12 - m8) / 4

        g1 = (rate_0_4  - rate_4_8)  / (rate_4_8  + 0.5)
        g2 = (rate_4_8  - rate_8_12) / (rate_8_12 + 0.5)
        g3 = rate_0_4 / (rate_8_12 + 0.5)

        attention_score = g1 + g2 + g3
        gt_val = gt_scores.get(sym, 0)

        rows.append({
            "sym":            sym,
            "score":          round(attention_score + gt_val * 0.05, 3),
            "mentions_4wk":   m4,
            "mentions_8wk":   m8,
            "mentions_12wk":  m12,
            "reddit_4wk":     r4,
            "stocktwits_4wk": st4,
            "yahoo_news_4wk": yn4,
            "google_news_4wk":gn4,
            "seekalpha_4wk":  sa4,
            "google_trend":   gt_val,
            "analysts":       meta["analysts"],
            "earnings_soon":  meta["earnings_soon"],
            "st_trending":    sym in st_data,
            "yf_trending":    sym in yf_tickers,
        })
        time.sleep(0.2)

    df = pd.DataFrame(rows)
    df = df[df["mentions_4wk"] >= 3].sort_values("score", ascending=False).reset_index(drop=True)

    # Top 5%
    top = df.head(max(10, int(len(df) * 0.05)))

    print(f"\n{'='*95}")
    print(f"TOP ATTENTION ACCELERATION  |  {NOW.strftime('%Y-%m-%d %H:%M ET')}  |  Top 5% of {len(df)} stocks")
    print(f"{'='*95}")
    print(f"{'#':<3} {'Sym':<6} {'Score':>6} {'4wk':>5} {'8wk':>5} {'12wk':>5} {'Reddit':>7} {'ST':>5} {'YNews':>6} {'GNews':>6} {'SA':>4} {'GTrend':>7} {'Anlst':>6} {'Earn':>5} {'Flags'}")
    print("-"*110)

    for i, row in top.iterrows():
        flags = ""
        if row["earnings_soon"]:  flags += "EARN "
        if row["st_trending"]:    flags += "ST "
        if row["yf_trending"]:    flags += "YF "
        if row["google_trend"] > 20: flags += "GTREND "
        print(
            f"{i+1:<3} {row['sym']:<6} {row['score']:>6.2f} "
            f"{row['mentions_4wk']:>5} {row['mentions_8wk']:>5} {row['mentions_12wk']:>5} "
            f"{row['reddit_4wk']:>7} {row['stocktwits_4wk']:>5} {row['yahoo_news_4wk']:>6} "
            f"{row['google_news_4wk']:>6} {row['seekalpha_4wk']:>4} {row['google_trend']:>7.1f} "
            f"{row['analysts']:>6} {'Y' if row['earnings_soon'] else 'N':>5}  {flags}"
        )

    # Save
    out = f"attention_{NOW.strftime('%Y%m%d_%H%M')}.csv"
    df.to_csv(out, index=False)
    print(f"\nFull results saved to {out}")
