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
API_KEY    = "PKOMQ2SP7VX4B7OI3P7O6FUWNV"
API_SECRET = "85MQcXB7nqfrvaXmQidhLKgs9usWgDXnDiubMugArPzb"
PAPER      = True

BASE_URL   = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"
DATA_URL   = "https://data.alpaca.markets"

SYMBOLS = [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX',
    'SOFI','RDDT','CAVA','DUOL','DKNG','MELI','SHOP','PYPL','SPOT','RKLB',
]

BUDGET          = 750.0    # max $ per trade
MAX_CONTRACT_COST = 500.0  # skip if 1 contract costs more than this
MAX_POSITIONS   = 5        # simultaneous open trades
MAX_DAILY_LOSS  = 10       # daily stop after N losses
MAX_CONSEC_SYM  = 3        # pause symbol after N consecutive losses
TP_PCT          = 25.0     # take profit % — 2.5:1 RR on options
SL_PCT          = 10.0     # stop loss %  — cut losers fast
FLAT_BARS       = 20       # bars before flat exit check
FLAT_THRESH     = 3.0      # flat exit if |pct| < this after FLAT_BARS
MAX_BARS        = 60       # max hold in 5-min bars
GAP_MIN         = 0.5      # min gap % (both directions)
ENTRY_CUTOFF    = "10:30"  # no new entries after this time
ENTRY_START     = "09:35"  # no new entries before this time (5-min open buffer)
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
def next_trading_days(n=7):
    """Return next N trading day date strings YYYY-MM-DD."""
    days = []
    exp  = now_et() + timedelta(days=1)
    while len(days) < n:
        if exp.weekday() < 5:
            days.append(exp.strftime("%Y-%m-%d"))
        exp += timedelta(days=1)
    return days

def select_option(sym, direction, underlying_price):
    """Exactly mirrors BOOF23 select_option — uses alpaca-py SDK."""
    if underlying_price < 10:
        log.warning(f"Skipping {sym} — underlying price ${underlying_price:.2f} below $20 min")
        return None
    from alpaca.trading.client import TradingClient as _TC
    from alpaca.trading.requests import GetOptionContractsRequest as _GOCR
    from alpaca.data.historical.option import OptionHistoricalDataClient as _OHDC
    from alpaca.data.requests import OptionSnapshotRequest as _OSR
    opt_type = "call" if direction == "long" else "put"
    try:
        _tc  = _TC(API_KEY, API_SECRET, paper=True)
        _odc = _OHDC(API_KEY, API_SECRET)
        contracts = []; expiry = None
        strike_lo = round(underlying_price * 0.80, 2)
        strike_hi = round(underlying_price * 1.20, 2)
        for candidate in next_trading_days(7):
            req = _GOCR(
                underlying_symbols=[sym], expiration_date=candidate,
                type=opt_type,
                strike_price_gte=str(strike_lo), strike_price_lte=str(strike_hi),
                limit=50
            )
            contracts = _tc.get_option_contracts(req).option_contracts
            if contracts: expiry = candidate; break
        if not contracts:
            log.warning(f"No contracts for {sym} {opt_type} in next 7 days")
            return None
        log.info(f"Option expiry {sym}: {expiry} ({len(contracts)} contracts, strikes {strike_lo}-{strike_hi})")
        snaps = _odc.get_option_snapshot(_OSR(symbol_or_symbols=[c.symbol for c in contracts]))
        TARGET_SPEND = 300.0  # target spend per trade
        # Build chain sorted by strike proximity to underlying (ATM first)
        chain = []
        for contract in contracts:
            snap = snaps.get(contract.symbol)
            if not snap: continue
            strike = float(contract.strike_price)
            bid = snap.latest_quote.bid_price or 0
            ask = snap.latest_quote.ask_price or 0
            if ask < 1.50: continue  # minimum $1.50 ask — skip cheap/worthless contracts
            if bid > 0 and ask > 0 and (ask - bid) / ask > 0.40: continue  # skip spread > 2:1 ratio
            mid = (bid + ask) / 2
            strike_dist = abs(strike - underlying_price)
            chain.append({"symbol": contract.symbol, "bid": bid, "ask": ask,
                          "mid": mid, "strike": strike, "strike_dist": strike_dist})
        if not chain:
            for contract in contracts:
                snap = snaps.get(contract.symbol)
                if not snap: continue
                strike = float(contract.strike_price)
                bid = snap.latest_quote.bid_price or 0
                ask = snap.latest_quote.ask_price or 0
                if ask < 1.50: continue
                if bid > 0 and ask > 0 and (ask - bid) / ask > 0.60: continue
                mid = (bid + ask) / 2
                strike_dist = abs(strike - underlying_price)
                chain.append({"symbol": contract.symbol, "bid": bid, "ask": ask,
                              "mid": mid, "strike": strike, "strike_dist": strike_dist})
            if not chain:
                log.warning(f"No contracts for {sym} {opt_type} even with relaxed spread")
                return None
            log.info(f"  {sym} using relaxed spread filter (60%)")
        # Sort by ITM first: calls -> strike just below price, puts -> strike just above
        if opt_type == "call":
            itm = [c for c in chain if c["strike"] <= underlying_price]
            otm = [c for c in chain if c["strike"] >  underlying_price]
            itm.sort(key=lambda x: underlying_price - x["strike"])  # closest ITM first
        else:
            itm = [c for c in chain if c["strike"] >= underlying_price]
            otm = [c for c in chain if c["strike"] <  underlying_price]
            itm.sort(key=lambda x: x["strike"] - underlying_price)  # closest ITM first
        otm.sort(key=lambda x: x["strike_dist"])
        ordered = itm + otm  # ITM preferred, fall back to ATM/OTM
        # Pick first contract where we can spend ~$500
        best = None
        for c in ordered:
            cost_1 = c["ask"] * 100
            if cost_1 <= 0: continue
            if cost_1 > MAX_CONTRACT_COST:
                log.warning(f"  {sym} skipping {c['symbol']} — 1 contract costs ${cost_1:.0f} > max ${MAX_CONTRACT_COST:.0f}")
                continue
            qty = max(1, round(TARGET_SPEND / cost_1))
            c["qty"] = qty
            best = c
            break
        if not best:
            log.warning(f"  {sym} no contracts under ${MAX_CONTRACT_COST:.0f} — skipping")
            return None
        log.info(f"  {sym} selected {best['symbol']} ask={best['ask']:.2f} "
                 f"qty={best['qty']} cost=${best['ask']*100*best['qty']:.0f}")
        return best
    except Exception as e:
        log.error(f"Option chain error {sym}: {e}")
        return None

def get_option_quote(opt_sym):
    """Fetch current mid price for open position monitoring."""
    from alpaca.data.historical.option import OptionHistoricalDataClient as _OHDC
    from alpaca.data.requests import OptionSnapshotRequest as _OSR
    try:
        _odc = _OHDC(API_KEY, API_SECRET)
        snaps = _odc.get_option_snapshot(_OSR(symbol_or_symbols=[opt_sym]))
        snap  = snaps.get(opt_sym)
        if not snap: return 0, 0
        bid = snap.latest_quote.bid_price or 0
        ask = snap.latest_quote.ask_price or 0
        return bid, ask
    except Exception as e:
        log.warning(f"Option quote error {opt_sym}: {e}")
        return 0, 0

# ── ORDER PLACEMENT ───────────────────────────────────────────────────────────
def place_option_order(s: SymState, direction: str):
    """Mirror BOOF23 place_option_entry exactly: select → limit ladder → TP on fill."""
    stock_price = s.last_close or s.day_open or 0
    if not stock_price:
        log.warning(f"{s.sym}: no stock price for option strike calc")
        with _lock:
            s.position = None
        return

    contract = select_option(s.sym, direction, stock_price)
    if not contract:
        log.warning(f"{s.sym}: no suitable option found")
        with _lock:
            s.position = None
        return

    opt_sym = contract["symbol"]
    bid     = contract["bid"]
    ask     = contract["ask"]
    mid     = contract["mid"]
    qty     = contract["qty"]
    spread  = ask - bid

    log.info(f"OPT {s.sym}: {direction} {opt_sym} x{qty}  bid={bid:.2f} ask={ask:.2f} mid={mid:.2f}")

    order_id = None
    filled   = False
    fill_px  = 0.0
    limit_px = round(ask + 0.05, 2)  # slightly above ask to guarantee fill

    for attempt in range(2):
        try:
            if order_id:
                try: api.cancel_order(order_id)
                except: pass
            if attempt == 0:
                o = api.submit_order(
                    symbol=opt_sym, qty=qty, side="buy",
                    type="limit", time_in_force="day",
                    limit_price=str(limit_px)
                )
                log.info(f"OPT {s.sym}: attempt 1 BUY LIMIT {opt_sym} @ {limit_px:.2f} (wait 20s)")
            else:
                o = api.submit_order(
                    symbol=opt_sym, qty=qty, side="buy",
                    type="market", time_in_force="day"
                )
                log.info(f"OPT {s.sym}: attempt 2 BUY MARKET {opt_sym} (fallback)")
            order_id = o.id
            time.sleep(20)
            o2 = api.get_order(order_id)
            if o2.status == "filled":
                fill_px = float(o2.filled_avg_price)
                filled  = True
                log.info(f"OPT {s.sym}: FILLED {opt_sym} x{qty} @ ${fill_px:.2f}")
                break
        except Exception as e:
            log.error(f"OPT {s.sym}: attempt {attempt+1} error — {e}")
            break

    if not filled:
        if order_id:
            try: api.cancel_order(order_id)
            except: pass
        log.warning(f"OPT {s.sym}: unfilled after all attempts — skipping")
        with _lock:
            s.position = None
        return

    # Place TP limit sell immediately on fill (matches BOOF23)
    tp_price = round(fill_px * (1 + TP_PCT / 100), 2)
    tp_id    = None
    try:
        tp_ord = api.submit_order(
            symbol=opt_sym, qty=qty, side="sell",
            type="limit", time_in_force="day",
            limit_price=str(tp_price)
        )
        tp_id = tp_ord.id
        log.info(f"OPT {s.sym}: TP limit placed @ ${tp_price:.2f} (id={tp_id})")
    except Exception as e:
        log.error(f"OPT {s.sym}: TP order error — {e}")

    with _lock:
        s.opt_position = {
            "opt_sym":    opt_sym,
            "qty":        qty,
            "entry_fill": fill_px,
            "order_id":   order_id,
            "tp_id":      tp_id,
            "direction":  direction,
        }

def close_option(s: SymState, reason: str):
    """Cancel resting TP order then close position at market."""
    if s.opt_position is None:
        return
    opt_sym = s.opt_position["opt_sym"]
    qty     = s.opt_position["qty"]
    tp_id   = s.opt_position.get("tp_id")
    # Cancel resting TP limit first to avoid double-sell
    if tp_id:
        try: api.cancel_order(tp_id)
        except: pass
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

    # ── First RTH bar fallback: set day_open if premarket missed it ──
    if s.prev_close and not s.day_open:
        s.day_open     = o_price or price
        s.gap_pct      = (s.day_open - s.prev_close) / s.prev_close * 100
        s.gap_ok_long  = s.gap_pct >  GAP_MIN
        s.gap_ok_short = s.gap_pct < -GAP_MIN
        log.info(f"{s.sym}: RTH open fallback gap={s.gap_pct:.2f}%")

    # ── Position open but option order still pending fill — count bars, force close if stuck ──
    if s.position and not s.opt_position:
        s.bars_held += 1
        if s.bars_held > 5:  # option never filled after 5 bars — abandon
            log.warning(f"{s.sym}: option never filled after {s.bars_held} bars — abandoning position")
            with _lock:
                s.position  = None
                s.bars_held = 0
                s.fired_today = True
        return

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
    if hm < ENTRY_START or hm > ENTRY_CUTOFF:
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
        # Check each level for breakout (closest to price first = lowest value above open)
        for lname, lval in sorted(levels.items(), key=lambda x: x[1]):
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
        # Check each level for breakdown (closest to price first = highest value below open)
        for lname, lval in sorted(levels.items(), key=lambda x: -x[1]):
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

async def on_bar(bar):
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

    # ── Pull today's premarket bars (4:00–9:29 ET) for PMH/PML/gap ──
    import requests as _req2
    today     = now_et().date()
    pm_start  = f"{today}T04:00:00-04:00"
    pm_end    = f"{today}T09:30:00-04:00"
    chunk     = SYMBOLS[:30]   # batch 1
    chunk2    = SYMBOLS[30:]   # batch 2
    for batch in [chunk, chunk2]:
        syms_param = ",".join(batch)
        url = (f"{DATA_URL}/v2/stocks/bars"
               f"?symbols={syms_param}&timeframe=1Min&start={pm_start}&end={pm_end}"
               f"&limit=500&feed=iex")
        try:
            r  = _req2.get(url, headers=headers, timeout=15)
            bars_map = r.json().get("bars", {})
            for sym, bars in bars_map.items():
                if sym not in state or not bars:
                    continue
                s = state[sym]
                highs  = [float(b.get('h', 0)) for b in bars]
                lows   = [float(b.get('l', 0)) for b in bars]
                opens  = [float(b.get('o', 0)) for b in bars]
                if highs: s.pmh = max(highs)
                if lows:  s.pml = min(lows)
                # day_open = first premarket bar open
                if opens and not s.day_open:
                    s.day_open     = opens[0]
                    if s.prev_close and s.day_open:
                        s.gap_pct      = (s.day_open - s.prev_close) / s.prev_close * 100
                        s.gap_ok_long  = s.gap_pct >  GAP_MIN
                        s.gap_ok_short = s.gap_pct < -GAP_MIN
                log.info(f"  {sym} PM: open={s.day_open} PMH={s.pmh} PML={s.pml} gap={s.gap_pct:.2f}%")
        except Exception as e:
            log.error(f"Premarket preseed error: {e}")

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
            current_px = float(p.current_price or entry)
            with _lock:
                ss = state[underlying]
                ss.position    = {"direction": direction, "entry": entry, "opened_at": datetime.now(TZ)}
                ss.opt_position = {"opt_sym": osym, "qty": qty, "entry_fill": entry,
                                   "order_id": None, "direction": direction,
                                   "peak": current_px}
                ss.bars_held   = 0
            log.info(f"RECONCILE {underlying} {direction} {osym} @ {entry} current={current_px:.2f} peak seeded")
    except Exception as e:
        log.error(f"Reconcile error: {e}")

# ── Real-time SL/TP monitor (polls Alpaca every 15s) ──────────────────────────
def sl_monitor():
    """Background thread: poll Alpaca positions every 15s, fire market sell on SL/TP breach.
    Uses fresh option snapshot quotes — NOT stale p.current_price from positions API."""
    log.info("SL MONITOR started — polling every 15s")
    while True:
        try:
            positions   = api.list_positions()
            open_orders = {o.symbol for o in api.list_orders(status='open') if o.side == 'sell' and o.type == 'market'}
            for p in positions:
                opt_sym = p.symbol
                if opt_sym in open_orders:
                    continue
                underlying = next((s for s in SYMBOLS if opt_sym.startswith(s)), None)
                if not underlying:
                    continue
                ss = state.get(underlying)
                if not ss or not ss.opt_position:
                    continue
                entry_fill = float(ss.opt_position.get("entry_fill") or 0)
                if entry_fill <= 0:
                    continue
                # ── Fetch LIVE quote — don't trust stale p.current_price ──
                bid, ask = get_option_quote(opt_sym)
                if bid <= 0 and ask <= 0:
                    log.warning(f"SL MONITOR {underlying}: no live quote for {opt_sym} — skipping")
                    continue
                current_price = (bid + ask) / 2 if bid > 0 and ask > 0 else (ask or bid)
                pct_chg = (current_price - entry_fill) / entry_fill * 100
                qty     = int(float(p.qty))
                log.info(f"SL MONITOR {underlying} {opt_sym}  entry={entry_fill:.2f}  cur={current_price:.2f}  pct={pct_chg:+.1f}%")

                # ── Ratcheting trailing stop ──────────────────────────────
                opt_pos = ss.opt_position or {}
                if current_price > opt_pos.get("peak", entry_fill):
                    opt_pos["peak"] = current_price
                    ss.opt_position = opt_pos
                peak      = opt_pos.get("peak", entry_fill)
                peak_pct  = (peak - entry_fill) / entry_fill * 100
                if peak_pct >= 25.0:
                    steps           = int((peak_pct - 25.0) / 5.0)
                    trail_floor_pct = 25.0 + steps * 5.0
                    trail_floor     = round(entry_fill * (1 + trail_floor_pct / 100), 2)
                    if current_price <= trail_floor:
                        log.info(f"TRAIL STOP {underlying} {opt_sym} cur={current_price:.2f} <= floor={trail_floor:.2f} "
                                 f"(peak=+{peak_pct:.1f}%, floor=+{trail_floor_pct:.0f}%) — CLOSING")
                        close_option(ss, f"trail_stop(floor=+{trail_floor_pct:.0f}%)")
                        close_trade(ss, "trail_stop", won=True)
                    else:
                        log.info(f"TRAIL {underlying} cur={current_price:.2f} +{pct_chg:.1f}%  peak=+{peak_pct:.1f}%  floor=+{trail_floor_pct:.0f}%")
                    continue  # skip fixed SL/TP once trailing active

                # ── Fixed SL (before +15% threshold) ─────────────────────
                if pct_chg <= -SL_PCT:
                    log.warning(f"SL MONITOR {underlying} {opt_sym} pct={pct_chg:.1f}% <= -{SL_PCT}% — CLOSING")
                    close_option(ss, f"sl_monitor({pct_chg:.1f}%)")
                    close_trade(ss, "sl_monitor", won=False)
                elif pct_chg >= TP_PCT:
                    log.info(f"TP MONITOR {underlying} {opt_sym} pct={pct_chg:.1f}% >= {TP_PCT}% — CLOSING")
                    close_option(ss, f"tp_monitor({pct_chg:.1f}%)")
                    close_trade(ss, "tp_monitor", won=True)
        except Exception as e:
            log.error(f"SL monitor error: {e}")
        time.sleep(15)


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    log.info(f"BOOF60 Multi-Level Breakout  {'[PAPER]' if PAPER else '[LIVE]'}")
    log.info(f"Universe ({len(SYMBOLS)} syms) | Budget=${BUDGET} | MaxPos={MAX_POSITIONS}")
    log.info(f"TP={TP_PCT}%  SL={SL_PCT}%  FlatBars={FLAT_BARS}  MaxBars={MAX_BARS}  Cutoff={ENTRY_CUTOFF}")
    log.info(f"LONG  : SPY+QQQ both up + gap>{GAP_MIN}% → breaks PDH/PWH/P10H/P20H/PMH")
    log.info(f"SHORT : SPY+QQQ both dn + gap<-{GAP_MIN}% → breaks PDL/PWL/P10L/P20L/PML")

    preseed_levels()
    reconcile_positions()

    def premarket_refresh():
        """Re-run preseed at 9:25 ET every day to lock in final PMH/PML before open."""
        while True:
            now    = now_et()
            target = now.replace(hour=9, minute=25, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            time.sleep((target - now).total_seconds())
            log.info("9:25 premarket refresh — updating PMH/PML/gap for all symbols")
            preseed_levels()

    threading.Thread(target=eod_close,        daemon=True).start()
    threading.Thread(target=daily_reset,      daemon=True).start()
    threading.Thread(target=heartbeat,        daemon=True).start()
    threading.Thread(target=premarket_refresh, daemon=True).start()
    threading.Thread(target=sl_monitor,       daemon=True).start()

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
