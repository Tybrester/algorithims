"""
BOOF55 Live Trading Bot — Gap Breakout (Stocks)
================================================
Universe  : 28 frozen symbols from walk-forward validation (2022-2024 train)
Signal    : Gap >1% open + RVOL >=1.5 + first 1-min close above PDH or PMH
            Only fires 09:30-10:00 ET
Entry     : Market order on signal bar close
Exit      : 2-hour fixed hold OR -1% hard stop (whichever comes first)
Sizing    : 10% of equity risk per trade, 4x intraday margin
            position_size = min(equity * 0.10 / 0.01, equity * 4)
Kill sw.  : Max 3 concurrent positions | Max 5 daily losses | Stop after 3 consec losses/sym
"""

import time, threading, logging, requests as _requests
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import alpaca_trade_api as tradeapi
from alpaca_trade_api.stream import Stream

# ── Config ─────────────────────────────────────────────────────────────────────

API_KEY    = "PKKPME54QJA3KBPAJ3QZZOJXDF"
API_SECRET = "J4GMmrbXWozxgx5FoY6kZmeNj9tCG6kmDGmyEvnXrb1Y"
PAPER      = True

BASE_URL = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"

SYMBOLS = [
    "AAPL","AMZN","APP","ARM","AVGO","AXP","BLK","CAT","CVX","ENPH",
    "FANG","FCX","HD","IBM","LCID","LRCX","MDT","MRNA","MS","MSFT",
    "MU","ORCL","PANW","PLTR","RBLX","RIVN","SMCI","TTWO"
]

RVOL_MIN       = 1.5
GAP_MIN        = 0.01     # 1%
STOP_PCT       = 0.01     # -1% hard stop
HOLD_MINUTES   = 120      # 2hr fixed hold
RISK_PCT       = 0.10     # 10% of equity per trade
MARGIN_MULT    = 4        # 4x intraday margin
MAX_POSITIONS  = 3
MAX_LOSSES_SYM = 3
MAX_DAILY_LOSS = 5
RVOL_WINDOW    = 20       # trading days for avg volume
TZ             = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("BOOF55")

# ── Supabase ───────────────────────────────────────────────────────────────────

SUPABASE_URL = "https://isanhutzyctcjygjhzbn.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"
_SB_HEADERS  = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

def sb_push_status(payload: list):
    try:
        _requests.post(
            f"{SUPABASE_URL}/rest/v1/bot_status",
            headers=_SB_HEADERS,
            json=payload,
            timeout=5,
        )
    except Exception as e:
        log.debug(f"Supabase push failed: {e}")

# ── Alpaca client ──────────────────────────────────────────────────────────────

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version="v2")

# ── Per-symbol state ───────────────────────────────────────────────────────────

class SymbolState:
    def __init__(self):
        self.prev_day_high  = None    # PDH fetched pre-market
        self.premarket_high = None    # PMH fetched pre-market
        self.prev_close     = None    # previous day close
        self.open_price     = None    # today's open
        self.gap_pct        = None
        self.rvol           = None
        self.daily_volume   = 0
        self.avg_volume     = None    # 20-day avg
        self.broke_level    = False   # signal already fired today
        self.position       = None    # dict when in trade
        self.consec_loss    = 0
        self.stopped        = False
        self.bars_today     = []      # intraday 1-min bars (09:30-10:00 for signal)

state        = {sym: SymbolState() for sym in SYMBOLS}
daily_losses = 0
bot_stopped  = False
_lock        = threading.Lock()

# ── Pre-market setup ───────────────────────────────────────────────────────────

def fetch_premarket_levels():
    """Fetch PDH, PMH, prev_close, avg_volume for all symbols before market open."""
    log.info("Fetching pre-market levels...")
    today = date.today().isoformat()

    for sym in SYMBOLS:
        s = state[sym]
        try:
            # Get last 22 daily bars (prev day + 20 for RVOL + buffer)
            bars = api.get_bars(sym, "1Day", limit=25, adjustment="all").df
            if len(bars) < 2:
                log.warning(f"{sym}: not enough daily bars")
                continue

            # Previous day OHLC (last completed day)
            prev_bar      = bars.iloc[-2]
            s.prev_close  = float(prev_bar["close"])
            s.prev_day_high = float(prev_bar["high"])

            # 20-day avg volume (excluding today)
            s.avg_volume  = float(bars["volume"].iloc[-RVOL_WINDOW-1:-1].mean())

            # Pre-market high — fetch 1-min bars from 04:00 to 09:29
            pm_bars = api.get_bars(
                sym, "1Min",
                start=f"{today}T04:00:00-05:00",
                end=f"{today}T09:29:00-05:00",
                feed="sip"
            ).df
            s.premarket_high = float(pm_bars["high"].max()) if len(pm_bars) else None

            log.info(
                f"{sym:<6} PDH={s.prev_day_high:.2f}  PMH={s.premarket_high:.2f if s.premarket_high else 'N/A'}"
                f"  PrevClose={s.prev_close:.2f}  AvgVol={s.avg_volume:,.0f}"
            )
        except Exception as e:
            log.error(f"{sym} pre-market fetch error: {e}")

# ── Position sizing ────────────────────────────────────────────────────────────

def get_position_size(price: float) -> int:
    """Shares to buy: risk 10% of equity, stop at -1%, max 4x equity."""
    try:
        account   = api.get_account()
        equity    = float(account.equity)
        risk_usd  = equity * RISK_PCT         # e.g. $300 on $3K account
        max_usd   = equity * MARGIN_MULT      # e.g. $12K buying power
        # position = risk / stop_pct
        pos_usd   = min(risk_usd / STOP_PCT, max_usd)
        shares    = int(pos_usd / price)
        return max(shares, 1)
    except Exception as e:
        log.error(f"Sizing error: {e}")
        return 1

# ── Entry ──────────────────────────────────────────────────────────────────────

def place_entry(sym: str, price: float, level: str):
    global daily_losses, bot_stopped
    if bot_stopped:
        log.warning("Bot stopped — skipping entry"); return
    s = state[sym]
    if s.stopped:
        log.warning(f"{sym} stopped — skipping"); return
    with _lock:
        open_count = sum(1 for st in state.values() if st.position)
        if open_count >= MAX_POSITIONS:
            log.info(f"Max positions ({MAX_POSITIONS}) reached — skipping {sym}"); return
        if s.position:
            log.info(f"{sym} already in position — skipping"); return

    shares = get_position_size(price)
    log.info(f"ENTRY  {sym:<6}  {shares} shares @ ~{price:.2f}  level={level}  gap={s.gap_pct:.2f}%  rvol={s.rvol:.2f}x")
    try:
        order = api.submit_order(
            symbol=sym, qty=shares, side="buy",
            type="market", time_in_force="day"
        )
        fill_price = price  # approximate until confirmed
        with _lock:
            s.position = {
                "shares":    shares,
                "entry":     fill_price,
                "stop":      round(fill_price * (1 - STOP_PCT), 4),
                "opened_at": datetime.now(TZ),
                "order_id":  order.id,
                "level":     level,
            }
        log.info(f"  Order placed: {order.id}  stop={s.position['stop']:.2f}")
    except Exception as e:
        log.error(f"Entry order failed {sym}: {e}")

# ── Exit ───────────────────────────────────────────────────────────────────────

def place_exit(sym: str, reason: str, current_price: float):
    global daily_losses, bot_stopped
    s = state[sym]
    if not s.position:
        return
    pos = s.position
    shares = pos["shares"]
    entry  = pos["entry"]
    pnl_pct = (current_price - entry) / entry * 100

    log.info(f"EXIT   {sym:<6}  {reason}  shares={shares}  entry={entry:.2f}  "
             f"exit~{current_price:.2f}  pnl={pnl_pct:+.2f}%")
    try:
        api.submit_order(
            symbol=sym, qty=shares, side="sell",
            type="market", time_in_force="day"
        )
    except Exception as e:
        log.error(f"Exit order failed {sym}: {e}")

    won = pnl_pct > 0
    with _lock:
        s.position = None
        if won:
            s.consec_loss = 0
        else:
            s.consec_loss += 1
            daily_losses  += 1
            if s.consec_loss >= MAX_LOSSES_SYM:
                s.stopped = True
                log.warning(f"KILL   {sym} stopped ({MAX_LOSSES_SYM} consec losses)")
            if daily_losses >= MAX_DAILY_LOSS:
                bot_stopped = True
                log.warning(f"KILL   Bot stopped — {MAX_DAILY_LOSS} daily losses")

# ── Bar handler ────────────────────────────────────────────────────────────────

def handle_bar(sym: str, bar: dict):
    now_et = datetime.now(TZ)
    t      = now_et.strftime("%H:%M")
    s      = state[sym]

    # Accumulate daily volume for RVOL
    s.daily_volume += bar["v"]

    # Record open price from first bar
    if t == "09:30" and s.open_price is None:
        s.open_price = bar["o"]
        if s.prev_close and s.open_price:
            s.gap_pct = (s.open_price - s.prev_close) / s.prev_close * 100
        if s.avg_volume and s.avg_volume > 0:
            s.rvol = s.daily_volume / s.avg_volume
        log.info(f"{sym:<6} open={s.open_price:.2f}  gap={s.gap_pct:.2f}%  rvol={s.rvol:.2f}x")

    # ── SIGNAL WINDOW: 09:30-10:00 only ──────────────────────────────────────
    in_signal_window = "09:30" <= t <= "10:00"

    if in_signal_window and not s.broke_level and not s.position:
        s.bars_today.append(bar)

        # Gate checks
        if s.gap_pct is None or s.gap_pct <= GAP_MIN * 100:
            pass  # gap not met
        elif s.rvol is None or s.rvol < RVOL_MIN:
            pass  # RVOL not met
        else:
            # Update RVOL with latest volume each bar
            if s.avg_volume and s.avg_volume > 0:
                s.rvol = s.daily_volume / s.avg_volume

            prev_c = s.bars_today[-2]["c"] if len(s.bars_today) >= 2 else None
            curr_c = bar["c"]

            if prev_c is not None:
                broke_pdh = s.prev_day_high and prev_c <= s.prev_day_high and curr_c > s.prev_day_high
                broke_pmh = s.premarket_high and prev_c <= s.premarket_high and curr_c > s.premarket_high

                if broke_pdh or broke_pmh:
                    level = "PDH" if broke_pdh else "PMH"
                    log.info(f"SIGNAL {sym:<6}  {level} break @ {curr_c:.2f}  {t}")
                    s.broke_level = True
                    threading.Thread(
                        target=place_entry,
                        args=(sym, curr_c, level),
                        daemon=True
                    ).start()

    # ── POSITION MANAGEMENT ───────────────────────────────────────────────────
    if s.position:
        pos     = s.position
        curr_px = bar["c"]
        age_min = (now_et - pos["opened_at"]).total_seconds() / 60

        # Hard stop
        if curr_px <= pos["stop"]:
            log.info(f"STOP   {sym:<6}  price={curr_px:.2f} <= stop={pos['stop']:.2f}")
            threading.Thread(target=place_exit, args=(sym, "STOP", curr_px), daemon=True).start()
            return

        # 2hr time exit
        if age_min >= HOLD_MINUTES:
            log.info(f"TIME   {sym:<6}  {age_min:.0f}min hold complete  price={curr_px:.2f}")
            threading.Thread(target=place_exit, args=(sym, "2HR_HOLD", curr_px), daemon=True).start()
            return

        # EOD force close
        if t >= "15:54":
            log.info(f"EOD    {sym:<6}  force close  price={curr_px:.2f}")
            threading.Thread(target=place_exit, args=(sym, "EOD", curr_px), daemon=True).start()
            return

    # ── SUPABASE STATUS PUSH ──────────────────────────────────────────────────
    setup_active   = s.position is not None
    setup_watching = in_signal_window and not s.broke_level and s.gap_pct and s.gap_pct > GAP_MIN * 100
    setup_close    = setup_watching and s.rvol and s.rvol >= RVOL_MIN

    metrics_parts = []
    if s.gap_pct is not None:
        metrics_parts.append(f"gap={s.gap_pct:.2f}%")
    if s.rvol is not None:
        metrics_parts.append(f"rvol={s.rvol:.2f}x")
    if s.prev_day_high:
        metrics_parts.append(f"PDH={s.prev_day_high:.2f}")
    if s.premarket_high:
        metrics_parts.append(f"PMH={s.premarket_high:.2f}")
    if s.position:
        pos = s.position
        age = (now_et - pos["opened_at"]).total_seconds() / 60
        pnl = (bar["c"] - pos["entry"]) / pos["entry"] * 100
        metrics_parts.append(f"pos={pos['shares']}sh@{pos['entry']:.2f} pnl={pnl:+.2f}% age={age:.0f}m")

    threading.Thread(target=sb_push_status, args=([{
        "bot":           "BOOF55",
        "symbol":        sym,
        "setup_active":  setup_active,
        "setup_close":   setup_close,
        "setup_watching": setup_watching,
        "metrics":       " | ".join(metrics_parts),
        "updated_at":    now_et.isoformat(),
    }],), daemon=True).start()

# ── Stream handlers ────────────────────────────────────────────────────────────

async def on_minute_bar(bar):
    sym = bar.symbol
    if sym in state:
        handle_bar(sym, {
            "o": bar.open, "h": bar.high,
            "l": bar.low,  "c": bar.close,
            "v": bar.volume
        })

# ── Daily reset ────────────────────────────────────────────────────────────────

def reset_daily():
    global daily_losses, bot_stopped
    with _lock:
        daily_losses = 0
        bot_stopped  = False
        for s in state.values():
            s.stopped        = False
            s.consec_loss    = 0
            s.broke_level    = False
            s.open_price     = None
            s.gap_pct        = None
            s.rvol           = None
            s.daily_volume   = 0
            s.bars_today     = []
            s.position       = None
    log.info("RESET  Daily state cleared")

def _daily_reset_scheduler():
    """Reset at 04:00 ET each morning, then re-fetch pre-market levels at 09:15."""
    while True:
        now = datetime.now(TZ)
        # Next 04:00
        target = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        time.sleep((target - now).total_seconds())
        reset_daily()
        # Wait until 09:15 to fetch levels
        now = datetime.now(TZ)
        pm_fetch = now.replace(hour=9, minute=15, second=0, microsecond=0)
        if now < pm_fetch:
            time.sleep((pm_fetch - now).total_seconds())
        fetch_premarket_levels()

# ── EOD force-close scheduler ──────────────────────────────────────────────────

def _eod_close_all():
    while True:
        now    = datetime.now(TZ)
        target = now.replace(hour=15, minute=54, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        time.sleep((target - now).total_seconds())
        log.info("EOD CLOSE — force-closing all positions")
        for sym, s in list(state.items()):
            if s.position:
                try:
                    api.submit_order(sym, s.position["shares"], "sell", "market", "day")
                    log.info(f"EOD closed {sym}")
                except Exception as e:
                    log.error(f"EOD close failed {sym}: {e}")
                with _lock:
                    s.position = None

# ── Reconcile open positions on restart ───────────────────────────────────────

def reconcile_positions():
    try:
        positions = api.list_positions()
        for p in positions:
            sym = p.symbol
            if sym not in state:
                continue
            entry = float(p.avg_entry_price)
            shares = int(float(p.qty))
            with _lock:
                state[sym].position = {
                    "shares":    shares,
                    "entry":     entry,
                    "stop":      round(entry * (1 - STOP_PCT), 4),
                    "opened_at": datetime.now(TZ),
                    "order_id":  None,
                    "level":     "RECONCILED",
                }
                state[sym].broke_level = True
            log.info(f"RECONCILE {sym}  {shares}sh @ {entry:.2f}  stop={state[sym].position['stop']:.2f}")
    except Exception as e:
        log.error(f"Reconcile error: {e}")

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    log.info(f"BOOF55 Gap Breakout Bot  {'[PAPER]' if PAPER else '[LIVE]'}")
    log.info(f"Universe : {', '.join(SYMBOLS)}")
    log.info(f"Filters  : Gap>{GAP_MIN*100:.0f}%  RVOL>={RVOL_MIN}x  Window=09:30-10:00 ET")
    log.info(f"Exit     : 2hr hold OR -{STOP_PCT*100:.0f}% stop")
    log.info(f"Sizing   : {RISK_PCT*100:.0f}% risk / {MARGIN_MULT}x margin")
    log.info(f"Kill sw. : MaxPos={MAX_POSITIONS}  MaxLoss/sym={MAX_LOSSES_SYM}  DailyStop={MAX_DAILY_LOSS}")

    fetch_premarket_levels()
    reconcile_positions()

    threading.Thread(target=_daily_reset_scheduler, daemon=True).start()
    threading.Thread(target=_eod_close_all, daemon=True).start()

    while True:
        try:
            stream = Stream(API_KEY, API_SECRET, base_url=BASE_URL, data_feed="sip")
            stream.subscribe_bars(on_minute_bar, *SYMBOLS)
            stream.subscribe_updated_bars(on_minute_bar, *SYMBOLS)
            log.info("Streaming — waiting for bars...")
            stream.run()
        except Exception as e:
            log.error(f"Stream error: {e} — reconnecting in 60s")
            time.sleep(60)

if __name__ == "__main__":
    main()
