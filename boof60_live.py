# ═══════════════════════════════════════════════════════════════════
#  BOOF60 — Multi-Level Breakout Bot (Live)
#  Matches backtest: boof60_combined.py + boof60_walkforward.py
#
#  LONG  (SPY+QQQ both up day + stock gap-up >0.5%):
#    Breaks above PDH / PWH / P10H / P20H / PMH  → buy call
#
#  SHORT (SPY+QQQ both down day + stock gap-down >0.5%):
#    Breaks below PDL / PWL / P10L / P20L / PML  → buy put
#
#  Entry  : +1 bar confirmation after breakout
#  Cutoff : no new entries after 10:30 ET
#  Exit   : TP=25% | SL=-10% | flat 20 bars | EOD 15:55
#  Budget : $750/trade | Max 5 simultaneous | 60 symbols
# ═══════════════════════════════════════════════════════════════════

import threading
import time
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import alpaca_trade_api as tradeapi
from alpaca_trade_api.stream import Stream

# ── CONFIG ────────────────────────────────────────────────────────────────────
API_KEY    = "PKTAPRDPBBOKTQYZGNBDZJ6XJZ"
API_SECRET = "6tzye8uezFRCV13EwhUqft4BNV6cg47kC77WgRVVZrpi"
PAPER      = True

BASE_URL   = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"
DATA_URL   = "https://data.alpaca.markets"

SYMBOLS = [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX',
    'SOFI','IONQ','RGTI','QUBT','ACHR','JOBY','LUNR','RDDT','CAVA','DUOL',
    'CELH','DKNG','MELI','SHOP','PYPL','SPOT','PINS','SNAP','LYFT','RIVN',
    'LCID','CHWY','SOUN','BBAI','AI','ASTS','RKLB','IREN','CORZ',
]

BUDGET          = 750.0    # max $ per trade
MAX_POSITIONS   = 5        # simultaneous open trades
MAX_DAILY_LOSS  = 10       # daily stop after N losses
MAX_CONSEC_SYM  = 3        # pause symbol after N consecutive losses
TP_PCT          = 25.0     # take profit % — matched to backtest
SL_PCT          = 10.0     # stop loss %  — matched to backtest
FLAT_BARS       = 20       # bars before flat exit check
FLAT_THRESH     = 3.0      # flat exit if |pct| < this after FLAT_BARS
MAX_BARS        = 60       # max hold in 5-min bars
GAP_MIN         = 0.5      # min gap % (both directions)
ENTRY_CUTOFF    = "10:30"  # no new entries after this time
BRK_THRESH      = 0.001    # must close 0.1% beyond level to confirm break

TZ = ZoneInfo("America/New_York")

# ── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("boof60")

# ── ALPACA CLIENT ─────────────────────────────────────────────────────────────
api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version="v2")

# ── STATE ────────────────────────────────────────────────────────────────────
_lock        = threading.Lock()
daily_losses = 0
bot_stopped  = False

class SymState:
    def __init__(self, sym):
        self.sym           = sym
        self.prev_close    = None
        self.pdh           = None   # prev day high
        self.pdl           = None   # prev day low
        self.pwh           = None   # prev week high (5d)
        self.pwl           = None   # prev week low  (5d)
        self.p10h          = None   # 10-day high
        self.p10l          = None   # 10-day low
        self.p20h          = None   # 20-day high
        self.p20l          = None   # 20-day low
        self.pmh           = None   # premarket high
        self.pml           = None   # premarket low
        self.day_open      = None
        self.last_close    = None
        self.gap_pct       = 0.0
        self.gap_ok_long   = False  # gap up >0.5%
        self.gap_ok_short  = False  # gap dn >0.5%
        # breakout tracking: {level_name: broken_bool}
        self.brk_broken    = set()
        self.brk_confirm   = None   # level name pending +1 bar
        self.brk_confirm_price = None
        self.pending_entry = False
        self.position      = None
        self.opt_position  = None
        self.bars_held     = 0
        self.flat_bars     = 0
        self.consec_loss   = 0
        self.paused        = False
        self.fired_today   = False  # one trade per symbol per day
        self.closed_at     = None
        self.close_reason  = None

state = {sym: SymState(sym) for sym in SYMBOLS}

# Regime: track SPY and QQQ daily direction (up = close > open)
spy_day_up   = False
spy_day_dn   = False
qqq_day_up   = False
qqq_day_dn   = False
both_up      = False   # SPY+QQQ both up  → longs valid
both_dn      = False   # SPY+QQQ both dn  → shorts valid

# ── HELPERS ──────────────────────────────────────────────────────────────────
def now_et():
    return datetime.now(TZ)

def market_time():
    n = now_et()
    return n.strftime("%H:%M")

def is_premarket():
    hm = market_time()
    return "04:00" <= hm < "09:30"

def is_rth():
    hm = market_time()
    return "09:30" <= hm < "16:00"

def next_trading_day():
    """Return next trading day date string YYYY-MM-DD (skips weekends)."""
    d = now_et().date() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return str(d)

def format_option_symbol(sym, exp_date, opt_type, strike):
    """OCC option symbol format."""
    d   = datetime.strptime(exp_date, "%Y-%m-%d")
    yy  = d.strftime("%y")
    mm  = d.strftime("%m")
    dd  = d.strftime("%d")
    K   = str(int(round(strike * 1000))).zfill(8)
    t   = "C" if opt_type == "call" else "P"
    return f"{sym}{yy}{mm}{dd}{t}{K}"

def update_regime(sym, open_px, close_px):
    """Called once per day per index bar to set regime."""
    global spy_day_up, spy_day_dn, qqq_day_up, qqq_day_dn, both_up, both_dn
    if sym == 'SPY':
        spy_day_up = close_px > open_px
        spy_day_dn = close_px < open_px
    elif sym == 'QQQ':
        qqq_day_up = close_px > open_px
        qqq_day_dn = close_px < open_px
    both_up = spy_day_up and qqq_day_up
    both_dn = spy_day_dn and qqq_day_dn

# ── OPTION PRICING ────────────────────────────────────────────────────────────
def get_option_quote(opt_sym):
    """Fetch bid/ask for an option symbol."""
    import requests
    headers = {
        "APCA-API-KEY-ID":     API_KEY,
        "APCA-API-SECRET-KEY": API_SECRET,
    }
    url = f"{DATA_URL}/v1beta1/options/quotes/latest?symbols={opt_sym}"
    try:
        r = requests.get(url, headers=headers, timeout=5)
        j = r.json()
        q = j.get("quotes", {}).get(opt_sym, {})
        bid = float(q.get("bp", 0) or 0)
        ask = float(q.get("ap", 0) or 0)
        return bid, ask
    except Exception as e:
        log.warning(f"Option quote error {opt_sym}: {e}")
        return 0, 0

def find_best_strike(sym, direction, stock_price, exp_date):
    """
    Walk from ATM outward up to 5 strikes.
    Finds cheapest strike where $750 buys at least 1 contract.
    Returns (opt_sym, strike, ask, qty) or None.
    """
    import requests
    headers = {
        "APCA-API-KEY-ID":     API_KEY,
        "APCA-API-SECRET-KEY": API_SECRET,
    }
    opt_type = "call" if direction == "long" else "put"
    url = (
        f"{DATA_URL}/v1beta1/options/snapshots/{sym}"
        f"?expiration_date={exp_date}&option_type={opt_type}&limit=50"
    )
    try:
        r = requests.get(url, headers=headers, timeout=5)
        j = r.json()
        snaps = j.get("snapshots", {})
    except Exception as e:
        log.warning(f"Option snapshots error {sym}: {e}")
        return None

    if not snaps:
        return None

    # Sort strikes: for calls ascending from ATM, for puts descending from ATM
    candidates = []
    for osym, snap in snaps.items():
        greeks = snap.get("greeks", {})
        strike = float(snap.get("details", {}).get("strike_price", 0))
        ask    = float((snap.get("latestQuote") or {}).get("ap", 0) or 0)
        delta  = abs(float(greeks.get("delta", 0) or 0))
        if ask <= 0 or strike <= 0:
            continue
        candidates.append((strike, ask, delta, osym))

    if not candidates:
        return None

    # Sort: calls = ascending strike from ATM, puts = descending strike from ATM
    if direction == "long":
        candidates.sort(key=lambda x: x[0])
        atm_idx = min(range(len(candidates)), key=lambda i: abs(candidates[i][0] - stock_price))
        ordered = candidates[atm_idx:]
    else:
        candidates.sort(key=lambda x: -x[0])
        atm_idx = min(range(len(candidates)), key=lambda i: abs(candidates[i][0] - stock_price))
        ordered = candidates[atm_idx:]

    for strike, ask, delta, osym in ordered[:6]:  # ATM + 5 OTM
        qty = min(10, int(BUDGET / (ask * 100)))
        if qty >= 1:
            log.info(f"  {sym} {opt_type} strike=${strike} ask=${ask:.2f} qty={qty} cost=${ask*qty*100:.0f} delta={delta:.2f}")
            return osym, strike, ask, qty

    return None

# ── ORDER PLACEMENT ───────────────────────────────────────────────────────────
def place_option_order(s: SymState, direction: str):
    """Buy option: mid → 5s → mid+25% → 25s → market."""
    exp_date    = next_trading_day()
    stock_price = s.last_close or s.day_open or 0
    if not stock_price:
        log.warning(f"{s.sym}: no stock price for option strike calc")
        return

    result = find_best_strike(s.sym, direction, stock_price, exp_date)
    if not result:
        log.warning(f"{s.sym}: no suitable option found")
        with _lock:
            s.pending_entry = False
        return

    opt_sym, strike, ask, qty = result
    bid, ask2 = get_option_quote(opt_sym)
    if ask2 > 0:
        ask = ask2
    mid    = round((bid + ask) / 2, 2) if bid > 0 else ask
    spread = ask - bid if bid > 0 else ask * 0.10
    mid25  = round(mid + spread * 0.25, 2)

    log.info(f"OPT {s.sym}: {direction} {opt_sym} x{qty}  bid={bid:.2f} ask={ask:.2f} mid={mid:.2f}")

    order_id = None
    filled   = False
    fill_px  = 0.0

    def try_limit(price, label, wait_s):
        nonlocal order_id, filled, fill_px
        try:
            if order_id:
                try: api.cancel_order(order_id)
                except: pass
            o = api.submit_order(
                symbol=opt_sym, qty=qty, side="buy",
                type="limit", limit_price=str(round(price, 2)),
                time_in_force="day",
            )
            order_id = o.id
            log.info(f"OPT {s.sym}: {label} limit @ ${price:.2f} (wait {wait_s}s)")
            time.sleep(wait_s)
            o2 = api.get_order(order_id)
            if o2.status == "filled":
                fill_px = float(o2.filled_avg_price)
                filled  = True
                log.info(f"OPT {s.sym}: FILLED {opt_sym} x{qty} @ ${fill_px:.2f} [{label}]")
        except Exception as e:
            log.error(f"OPT {s.sym}: {label} error — {e}")

    try_limit(mid,   "mid",     5)
    if not filled:
        try_limit(mid25, "mid+25%", 25)

    if not filled:
        # Market fallback
        try:
            if order_id:
                try: api.cancel_order(order_id)
                except: pass
            o = api.submit_order(
                symbol=opt_sym, qty=qty, side="buy",
                type="market", time_in_force="day",
            )
            order_id = o.id
            time.sleep(3)
            o2 = api.get_order(order_id)
            fill_px = float(o2.filled_avg_price or mid)
            filled  = True
            log.info(f"OPT {s.sym}: MARKET FILLED {opt_sym} x{qty} @ ${fill_px:.2f}")
        except Exception as e:
            log.error(f"OPT {s.sym}: market fallback failed — {e}")

    with _lock:
        s.pending_entry = False
        if filled:
            s.opt_position = {
                "opt_sym":    opt_sym,
                "qty":        qty,
                "entry_fill": fill_px,
                "order_id":   order_id,
                "direction":  direction,
            }
        else:
            s.position = None

def close_option(s: SymState, reason: str):
    """Close option position: market first, fallback limit $0.01."""
    if s.opt_position is None:
        return
    opt_sym = s.opt_position["opt_sym"]
    qty     = s.opt_position["qty"]
    closed  = False
    try:
        api.submit_order(symbol=opt_sym, qty=qty, side="sell", type="market", time_in_force="day")
        log.info(f"OPT {s.sym}: CLOSE MARKET {opt_sym} reason={reason}")
        closed = True
    except Exception as e:
        log.warning(f"OPT {s.sym}: market close failed ({e}) — trying limit $0.01")
    if not closed:
        try:
            api.submit_order(symbol=opt_sym, qty=qty, side="sell", type="limit",
                             limit_price="0.01", time_in_force="day")
            log.info(f"OPT {s.sym}: CLOSE LIMIT $0.01 {opt_sym} reason={reason}")
        except Exception as e2:
            log.error(f"OPT {s.sym}: CLOSE FAILED both methods — {e2}")
    with _lock:
        s.opt_position = None

# ── TRADE MANAGEMENT ──────────────────────────────────────────────────────────
def open_trade(s: SymState, direction: str, stock_price: float):
    global daily_losses, bot_stopped
    with _lock:
        if bot_stopped:
            return
        open_count = sum(1 for ss in state.values() if ss.position is not None)
        if open_count >= MAX_POSITIONS:
            log.info(f"{s.sym}: max positions ({MAX_POSITIONS}) reached — skip")
            s.pending_entry = False
            return
        if s.position is not None or s.paused:
            s.pending_entry = False
            return

        s.position = {
            "direction":  direction,
            "entry":      stock_price,
            "opened_at":  datetime.now(TZ),
        }
        s.bars_held     = 0
        s.pending_entry = False

    log.info(f"OPEN {s.sym} {direction.upper()}  stock~${stock_price:.2f}  TP={TP_PCT}%  SL={SL_PCT}%")
    threading.Thread(target=place_option_order, args=(s, direction), daemon=True).start()

def close_trade(s: SymState, reason: str, won: bool = False):
    global daily_losses, bot_stopped
    close_option(s, reason)
    with _lock:
        s.position     = None
        s.bars_held    = 0
        s.closed_at    = datetime.now(TZ)
        s.close_reason = reason
        if won:
            s.consec_loss = 0
            log.info(f"WIN    {s.sym}  {reason}")
        else:
            s.consec_loss += 1
            daily_losses  += 1
            log.info(f"LOSS   {s.sym}  {reason}  streak={s.consec_loss}")
            if s.consec_loss >= MAX_CONSEC_SYM:
                s.paused = True
                log.warning(f"PAUSE  {s.sym} — {MAX_CONSEC_SYM} consecutive losses")
            if daily_losses >= MAX_DAILY_LOSS:
                bot_stopped = True
                log.warning(f"KILL   Bot stopped — {MAX_DAILY_LOSS} daily losses")

# ── BAR HANDLER ──────────────────────────────────────────────────────────────
def handle_bar(s: SymState, bar: dict):
    price   = float(bar.get("c") or 0)
    high    = float(bar.get("h") or price)
    low     = float(bar.get("l") or price)
    o_price = float(bar.get("o") or price)
    if not price:
        return

    hm = market_time()

    # ── Pre-market: capture PMH/PML and day open ──
    if is_premarket():
        if s.pmh is None or high > s.pmh: s.pmh = high
        if s.pml is None or low  < s.pml: s.pml = low
        if s.prev_close and not s.day_open:
            s.day_open    = o_price or price
            s.gap_pct     = (s.day_open - s.prev_close) / s.prev_close * 100
            s.gap_ok_long  = s.gap_pct >  GAP_MIN
            s.gap_ok_short = s.gap_pct < -GAP_MIN
        s.last_close = price
        return

    if not is_rth():
        return

    s.last_close = price

    # ── Manage open option position ──
    if s.opt_position and s.position:
        opt_sym    = s.opt_position["opt_sym"]
        entry_fill = s.opt_position["entry_fill"]

        bid, ask  = get_option_quote(opt_sym)
        cur_price = (bid + ask) / 2 if bid > 0 and ask > 0 else (ask or entry_fill)
        pct_chg   = (cur_price - entry_fill) / entry_fill * 100 if entry_fill > 0 else 0

        s.bars_held += 1
        is_tp      = pct_chg >= TP_PCT
        is_sl      = pct_chg <= -SL_PCT
        is_timeout = s.bars_held >= MAX_BARS
        is_eod     = hm >= "15:55"
        # Flat exit: after FLAT_BARS bars, if barely moving close it out
        if s.bars_held >= FLAT_BARS and abs(pct_chg) < FLAT_THRESH:
            s.flat_bars += 1
        else:
            s.flat_bars = 0
        is_flat = s.flat_bars >= 2

        if is_tp or is_sl or is_timeout or is_eod or is_flat:
            reason = "tp" if is_tp else "sl" if is_sl else "eod" if is_eod else "flat" if is_flat else "timeout"
            close_trade(s, reason, won=is_tp)
        return

    # ── Gate checks ──
    if bot_stopped or s.paused or s.pending_entry or s.position or s.fired_today:
        return
    if hm > ENTRY_CUTOFF:
        return
    if not s.prev_close or not s.pdh:
        return

    direction = None
    level_hit = None

    # ── LONG breakout: SPY+QQQ both up, stock gapped up ──
    if both_up and s.gap_ok_long:
        levels = {}
        if s.pdh  and s.pdh  > s.day_open: levels['PDH']  = s.pdh
        if s.pwh  and s.pwh  > s.day_open: levels['PWH']  = s.pwh
        if s.p10h and s.p10h > s.day_open: levels['P10H'] = s.p10h
        if s.p20h and s.p20h > s.day_open: levels['P20H'] = s.p20h
        if s.pmh  and s.pmh  > s.day_open: levels['PMH']  = s.pmh
        # Check each level for breakout (closest first)
        for lname, lval in sorted(levels.items(), key=lambda x: -x[1]):
            if lname in s.brk_broken: continue
            if price > lval * (1 + BRK_THRESH):
                s.brk_broken.add(lname)
                if s.brk_confirm is None:
                    s.brk_confirm = lname
                    s.brk_confirm_price = price
                    log.info(f"PENDING {s.sym} LONG break {lname}={lval:.2f} @ {price:.2f} — waiting +1 bar")
                else:
                    if price >= s.brk_confirm_price:
                        direction = "long"
                        level_hit = s.brk_confirm
                        log.info(f"SIGNAL {s.sym} LONG confirm {level_hit} gap={s.gap_pct:.1f}% price={price:.2f}")
                break
        # +1 bar confirm already pending
        if direction is None and s.brk_confirm and not direction:
            if price >= s.brk_confirm_price:
                direction = "long"
                level_hit = s.brk_confirm
                log.info(f"SIGNAL {s.sym} LONG +1bar {level_hit} gap={s.gap_pct:.1f}% price={price:.2f}")

    # ── SHORT breakout: SPY+QQQ both dn, stock gapped dn ──
    elif both_dn and s.gap_ok_short:
        levels = {}
        if s.pdl  and s.pdl  < s.day_open: levels['PDL']  = s.pdl
        if s.pwl  and s.pwl  < s.day_open: levels['PWL']  = s.pwl
        if s.p10l and s.p10l < s.day_open: levels['P10L'] = s.p10l
        if s.p20l and s.p20l < s.day_open: levels['P20L'] = s.p20l
        if s.pml  and s.pml  < s.day_open: levels['PML']  = s.pml
        for lname, lval in sorted(levels.items(), key=lambda x: x[1]):
            if lname in s.brk_broken: continue
            if price < lval * (1 - BRK_THRESH):
                s.brk_broken.add(lname)
                if s.brk_confirm is None:
                    s.brk_confirm = lname
                    s.brk_confirm_price = price
                    log.info(f"PENDING {s.sym} SHORT break {lname}={lval:.2f} @ {price:.2f} — waiting +1 bar")
                else:
                    if price <= s.brk_confirm_price:
                        direction = "short"
                        level_hit = s.brk_confirm
                        log.info(f"SIGNAL {s.sym} SHORT confirm {level_hit} gap={s.gap_pct:.1f}% price={price:.2f}")
                break
        if direction is None and s.brk_confirm:
            if price <= s.brk_confirm_price:
                direction = "short"
                level_hit = s.brk_confirm
                log.info(f"SIGNAL {s.sym} SHORT +1bar {level_hit} gap={s.gap_pct:.1f}% price={price:.2f}")

    if direction:
        s.fired_today  = True
        s.brk_confirm  = None
        s.pending_entry = True
        threading.Thread(target=open_trade, args=(s, direction, price), daemon=True).start()

def on_bar(bar):
    sym   = bar.symbol if hasattr(bar, 'symbol') else bar.get('S', '')
    close = float(bar.close if hasattr(bar, 'close') else bar.get('c', 0))
    open_ = float(bar.open  if hasattr(bar, 'open')  else bar.get('o', 0))
    high  = float(bar.high  if hasattr(bar, 'high')  else bar.get('h', close))
    low   = float(bar.low   if hasattr(bar, 'low')   else bar.get('l', close))

    if sym in ('SPY', 'QQQ'):
        update_regime(sym, open_, close)
        return

    s = state.get(sym)
    if s:
        handle_bar(s, {'c': close, 'o': open_, 'h': high, 'l': low})

# ── EOD FORCE CLOSE ───────────────────────────────────────────────────────────
def eod_close():
    while True:
        now = now_et()
        target = now.replace(hour=15, minute=55, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        sleep_s = (target - now).total_seconds()
        log.info(f"EOD close scheduled in {sleep_s/3600:.1f}h")
        time.sleep(sleep_s)
        log.info("EOD CLOSE 15:55 — force-closing all positions")
        for s in state.values():
            if s.position is not None:
                close_trade(s, "eod")

# ── DAILY RESET ───────────────────────────────────────────────────────────────
def daily_reset():
    global daily_losses, bot_stopped
    while True:
        now    = now_et()
        target = now.replace(hour=9, minute=25, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        time.sleep((target - now).total_seconds())
        with _lock:
            daily_losses = 0
            bot_stopped  = False
            for s in state.values():
                s.gap_ok_long  = False
                s.gap_ok_short = False
                s.gap_pct      = 0.0
                s.day_open     = None
                s.pmh          = None
                s.pml          = None
                s.brk_broken   = set()
                s.brk_confirm  = None
                s.brk_confirm_price = None
                s.fired_today  = False
                s.flat_bars    = 0
                s.paused       = False
        log.info("DAILY RESET — counters cleared")

# ── PRE-SEED LEVELS ───────────────────────────────────────────────────────────
def preseed_levels():
    """Fetch prev day bars + rolling 5/10/20 day highs/lows for all symbols."""
    import requests
    headers = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": API_SECRET}
    all_syms = SYMBOLS + ['SPY', 'QQQ']

    # Fetch 25 days of daily bars per symbol to compute rolling levels
    end   = now_et().date()
    start = end - timedelta(days=40)  # extra buffer for weekends/holidays
    for sym in all_syms:
        url = (f"{DATA_URL}/v2/stocks/{sym}/bars"
               f"?timeframe=1Day&start={start}&end={end}&limit=30&feed=iex")
        try:
            r  = requests.get(url, headers=headers, timeout=10)
            bars = r.json().get("bars", [])
            if not bars or len(bars) < 2:
                log.warning(f"  {sym}: not enough daily bars ({len(bars)})")
                continue
            # bars[-1] is today (possibly incomplete), bars[-2] is prev day
            if sym in ('SPY', 'QQQ'):
                prev = bars[-2] if len(bars) >= 2 else bars[-1]
                update_regime(sym, float(prev.get('o', 0)), float(prev.get('c', 0)))
                continue
            s = state[sym]
            # Prev day
            p1          = bars[-2]
            s.prev_close = float(p1.get('c') or 0) or None
            s.pdh        = float(p1.get('h') or 0) or None
            s.pdl        = float(p1.get('l') or 0) or None
            # Rolling windows (exclude today)
            hist = bars[:-1]
            tail5  = hist[-5:]  if len(hist) >= 5  else hist
            tail10 = hist[-10:] if len(hist) >= 10 else hist
            tail20 = hist[-20:] if len(hist) >= 20 else hist
            s.pwh  = max(float(b.get('h', 0)) for b in tail5)
            s.pwl  = min(float(b.get('l', 0)) for b in tail5)
            s.p10h = max(float(b.get('h', 0)) for b in tail10)
            s.p10l = min(float(b.get('l', 0)) for b in tail10)
            s.p20h = max(float(b.get('h', 0)) for b in tail20)
            s.p20l = min(float(b.get('l', 0)) for b in tail20)
            if s.prev_close:
                log.info(f"  {sym}: close={s.prev_close:.2f} PDH={s.pdh:.2f} PDL={s.pdl:.2f} "
                         f"PWH={s.pwh:.2f} PWL={s.pwl:.2f} P10H={s.p10h:.2f} P10L={s.p10l:.2f}")
        except Exception as e:
            log.error(f"Preseed {sym} error: {e}")
    log.info(f"Regime: both_up={both_up} both_dn={both_dn}")

# ── HEARTBEAT ─────────────────────────────────────────────────────────────────
def heartbeat():
    while True:
        time.sleep(300)
        try:
            hm       = now_et().strftime("%H:%M ET")
            open_pos = [(s.sym, s.position["direction"]) for s in state.values() if s.position]
            pos_str  = ", ".join(f"{sym}({d})" for sym, d in open_pos) or "none"
            log.info(
                f"HEARTBEAT {hm}  positions={len(open_pos)}/{MAX_POSITIONS} [{pos_str}]  "
                f"daily_losses={daily_losses}/{MAX_DAILY_LOSS}  "
                f"stopped={bot_stopped}  both_up={both_up}  both_dn={both_dn}"
            )
        except Exception as e:
            log.warning(f"HEARTBEAT error: {e}")

# ── RECONCILE ────────────────────────────────────────────────────────────────
def reconcile_positions():
    try:
        positions  = api.list_positions()
        open_orders = api.list_orders(status='open')
        closing    = {o.symbol for o in open_orders if o.side == 'sell'}
        for p in positions:
            osym = p.symbol
            if osym in closing:
                continue
            underlying = next((s for s in SYMBOLS if osym.startswith(s)), None)
            if not underlying:
                continue
            direction = "long" if "C" in osym[len(underlying):] else "short"
            entry     = float(p.avg_entry_price)
            qty       = int(float(p.qty))
            with _lock:
                ss = state[underlying]
                ss.position    = {"direction": direction, "entry": entry, "opened_at": datetime.now(TZ)}
                ss.opt_position = {"opt_sym": osym, "qty": qty, "entry_fill": entry,
                                   "order_id": None, "direction": direction}
                ss.bars_held   = 0
            log.info(f"RECONCILE {underlying} {direction} {osym} @ {entry}")
    except Exception as e:
        log.error(f"Reconcile error: {e}")

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    log.info(f"BOOF60 Multi-Level Breakout  {'[PAPER]' if PAPER else '[LIVE]'}")
    log.info(f"Universe ({len(SYMBOLS)} syms) | Budget=${BUDGET} | MaxPos={MAX_POSITIONS}")
    log.info(f"TP={TP_PCT}%  SL={SL_PCT}%  FlatBars={FLAT_BARS}  MaxBars={MAX_BARS}  Cutoff={ENTRY_CUTOFF}")
    log.info(f"LONG  : SPY+QQQ both up + gap>{GAP_MIN}% → breaks PDH/PWH/P10H/P20H/PMH")
    log.info(f"SHORT : SPY+QQQ both dn + gap<-{GAP_MIN}% → breaks PDL/PWL/P10L/P20L/PML")

    preseed_levels()
    reconcile_positions()

    threading.Thread(target=eod_close,   daemon=True).start()
    threading.Thread(target=daily_reset, daemon=True).start()
    threading.Thread(target=heartbeat,   daemon=True).start()

    watch = SYMBOLS + ['SPY', 'QQQ']

    while True:
        try:
            stream = Stream(API_KEY, API_SECRET, base_url=BASE_URL, data_feed="iex")
            stream.subscribe_bars(on_bar, *watch)
            stream.subscribe_updated_bars(on_bar, *watch)
            log.info("Streaming — waiting for bars...")
            stream.run()
        except Exception as e:
            log.error(f"Stream error: {e} — reconnecting in 60s")
            time.sleep(60)

if __name__ == "__main__":
    main()
