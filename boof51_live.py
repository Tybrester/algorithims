"""
BOOF51 Live Trading Bot
========================
Strategy : BUY PUTS on gap-up > 0.5% days (NO stock shorts)
Entry     : Fresh 1st touch of routed level + bounce >= 0.15% + +1 bar confirmation
            → Buy 1DTE put, delta 0.40-0.60, highest open interest ATM strike
Exit      : Stock price hits TP (down 0.50% from entry) → sell put at market
            Stock price hits SL (up 0.25% from entry)   → sell put at market
            Max hold 60 bars                             → sell put at market
Universe  : 20 symbols, each routed to its optimal level (PMH/PDH/pivot TF)

Routing:
  PMH   : UPST, APP, SMCI, HIMS, GOOGL
  PDH   : META, AFRM
  10m   : TSLA, CLSK, HOOD
  30m   : ADBE, PANW, MU, AMD, COIN, NVDA
  2H    : MRVL, AVGO
  4H    : PLTR
  Daily : CRM

Kill switches:
  - Gap-up > 0.5% required — flat/gap-down days skipped
  - Max 5 open put positions at once
  - Max 2 consecutive losses per symbol → pause rest of day
  - Max 8 daily losses total → stop bot for the day
  - No new entries after 15:00 ET
  - Force-close all puts at 15:55 ET

Paste your paper API key/secret below before running.
"""

import time
import threading
import logging
import requests as _requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

import alpaca_trade_api as tradeapi
from alpaca_trade_api.stream import Stream

# ── CONFIG ──────────────────────────────────────────────────────────────────────

API_KEY    = "PK7QIKE4PJOJMAG23KEIZ2P6JF"
API_SECRET = "AaiSUex556PSJGXagrSLkF7Ykti6qSZbYDBs2Ctd4uy8"
PAPER      = True

BASE_URL = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"

# Shares per trade (1 share = minimal risk for paper testing)
QTY = 1

# Options config
OPT_BUDGET     = 300        # target spend per option trade in dollars
OPT_DELTA_MIN  = 0.40       # minimum delta for put selection
OPT_DELTA_MAX  = 0.60       # maximum delta for put selection
OPT_DTE        = 1          # 1 DTE expiry
TRADE_OPTIONS  = True       # set False to disable options leg

TP_PCT    = 0.0050   # 0.50% profit target
SL_PCT    = 0.0025   # 0.25% stop loss
MAX_BARS  = 60       # max hold in 1m bars

GAP_MIN   = 0.005    # gap-up minimum 0.5%
BOUNCE    = 0.0015   # bounce >= 0.15% off level
NEAR_PCT  = 0.0015   # within 0.15% = "touching" level

MAX_POSITIONS  = 10      # max 10 concurrent open positions
MAX_CONSEC_SYM = 2   # consecutive losses before pausing symbol
MAX_DAILY_LOSS = 8   # daily loss count before stopping bot

TZ = ZoneInfo("America/New_York")

# ── ROUTING TABLE ───────────────────────────────────────────────────────────────
# Each symbol: (type, lookback_bars, wing)
# type: PMH | PDH | PIV
# PIV lookback: 10m=10, 30m=30, 2H=120, 4H=240, Daily=390

ROUTING = {
    # PMH group
    "UPST":  ("PMH", None, None),
    "APP":   ("PMH", None, None),
    "SMCI":  ("PMH", None, None),
    "HIMS":  ("PMH", None, None),
    "GOOGL": ("PMH", None, None),
    # PDH group
    "META":  ("PDH", None, None),
    "AFRM":  ("PDH", None, None),
    # 10m pivot
    "TSLA":  ("PIV", 10,  2),
    "CLSK":  ("PIV", 10,  2),
    "HOOD":  ("PIV", 10,  2),
    # 30m pivot
    "ADBE":  ("PIV", 30,  3),
    "PANW":  ("PIV", 30,  3),
    "MU":    ("PIV", 30,  3),
    "AMD":   ("PIV", 30,  3),
    "COIN":  ("PIV", 30,  3),
    "NVDA":  ("PIV", 30,  3),
    # 2H pivot
    "MRVL":  ("PIV", 120, 4),
    "AVGO":  ("PIV", 120, 4),
    # 4H pivot
    "PLTR":  ("PIV", 240, 5),
    # Daily pivot
    "CRM":   ("PIV", 390, 5),
}

SYMBOLS = list(ROUTING.keys())

# ── LOGGING ─────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("BOOF51")

# ── SUPABASE ────────────────────────────────────────────────────────────────────

SUPABASE_URL = "https://isanhutzyctcjygjhzbn.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"
_SB_HDR = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
}

def sb_push(payload: list):
    try:
        _requests.post(
            f"{SUPABASE_URL}/rest/v1/bot_status",
            headers=_SB_HDR, json=payload, timeout=5,
        )
    except Exception as e:
        log.debug(f"Supabase push failed: {e}")

# ── ALPACA CLIENT ────────────────────────────────────────────────────────────────

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version="v2")

# ── SYMBOL STATE ─────────────────────────────────────────────────────────────────

class SymState:
    def __init__(self, sym):
        self.sym         = sym
        self.rtype, self.lb, self.wing = ROUTING[sym]

        # premarket / daily tracking
        self.pm_high     = None    # premarket high (reset each day)
        self.prev_close  = None    # prior RTH close
        self.pdh         = None    # previous day high
        self.pdl         = None    # previous day low
        self.rth_open    = None    # today's RTH open
        self.gap_pct     = None    # gap % today
        self.gap_ok      = False   # True if gap > 0.5%

        # pivot levels computed each morning
        self.levels      = []      # list of float price levels to watch

        # bar history for pivot building
        self.rth_bars    = []      # all RTH bars (accumulated across days)
        self.today_bars  = []      # today's RTH bars only

        # entry state machine per level
        # key: level price (rounded), val: dict{state, extreme, touch_num, bars_in}
        self.level_states = {}
        self.pending_entry = False  # True when SM fired, waiting for next bar open

        # active put position
        self.position     = None   # dict: {entry, tp, sl, opt_sym, qty, order_id, opened_at}
        self.bars_held    = 0
        self.opt_position = None   # same as position — kept for _close_put compatibility

        # kill switch
        self.consec_loss = 0
        self.paused      = False

    def reset_day(self):
        self.pm_high       = None
        self.rth_open      = None
        self.gap_pct       = None
        self.gap_ok        = False
        self.levels        = []
        self.today_bars    = []
        self.level_states  = {}
        self.pending_entry  = False
        self.position      = None
        self.bars_held     = 0
        self.opt_position  = None
        self.pending_entry = False

    def reset_daily_kill(self):
        self.consec_loss = 0
        self.paused      = False


# ── GLOBAL STATE ─────────────────────────────────────────────────────────────────

state       = {sym: SymState(sym) for sym in SYMBOLS}
daily_losses = 0
bot_stopped  = False
_lock        = threading.Lock()

# ── PIVOT BUILDER ─────────────────────────────────────────────────────────────────

OVERLAP = 0.002

def build_pivot_levels(bars, lookback, wing):
    """
    bars: list of dicts with 'h' key. Uses last `lookback` bars.
    Returns clustered list of pivot high levels.
    """
    hist = bars[-lookback:] if len(bars) >= lookback else bars
    if len(hist) < wing + 1:
        return []
    H = [b["h"] for b in hist]
    raw = []
    for i in range(wing, len(hist)):
        if H[i] == max(H[i-wing:i+1]):
            raw.append(H[i])
    if not raw:
        return []
    raw = sorted(raw)
    clustered = [raw[0]]
    for lv in raw[1:]:
        if abs(lv - clustered[-1]) / clustered[-1] < OVERLAP:
            clustered[-1] = (clustered[-1] + lv) / 2
        else:
            clustered.append(lv)
    return clustered


# ── LEVEL SCAN STATE MACHINE ──────────────────────────────────────────────────────

def update_level_sm(s: SymState, level: float, bar: dict):
    """
    Run the fresh-1st-touch + bounce state machine for one level on one bar.
    Returns True if entry signal fires (caller opens trade).
    """
    key = round(level, 4)
    if key not in s.level_states:
        s.level_states[key] = {"state": "IDLE", "extreme": None, "touch_num": 0}
    sm = s.level_states[key]

    high = bar["h"]; close = bar["c"]
    touching = high >= level * (1 - NEAR_PCT)

    if sm["state"] == "IDLE":
        if touching:
            sm["state"]    = "IN"
            sm["extreme"]  = close
            sm["touch_num"] += 1

    elif sm["state"] == "IN":
        if touching:
            sm["extreme"] = min(sm["extreme"], close)
        else:
            # left the zone — check bounce
            bounced = (sm["extreme"] is not None and
                       (level - sm["extreme"]) / level >= BOUNCE)
            if bounced and sm["touch_num"] == 1:
                # signal fires — next bar open is entry
                sm["state"] = "FIRED"
                return True
            # no valid bounce or repeat touch → invalidate this level
            sm["state"]    = "DEAD"
    # FIRED / DEAD: no further signals

    return False


# ── OPTIONS LEG ─────────────────────────────────────────────────────────────────

def _get_1dte_expiry() -> str:
    """Return next trading day's date as YYYYMMDD (Alpaca option symbol format)."""
    now = datetime.now(TZ)
    exp = now + timedelta(days=1)
    while exp.weekday() >= 5:   # skip Saturday(5) and Sunday(6)
        exp += timedelta(days=1)
    return exp.strftime("%Y-%m-%d")


def _select_put(sym: str, underlying_px: float):
    """
    Fetch 1DTE put chain for sym.
    Walk from ATM outward (descending strike) and pick the strike where:
      - 1 contract ask*100 is closest to $300, OR
      - 2 contracts ask*100*2 is closest to $300 (i.e. ask*100 ~$150)
    Whichever combo gets closest to OPT_BUDGET wins.
    Returns dict: {opt_sym, strike, bid, ask, mid, delta, oi, qty} or None.
    """
    expiry = _get_1dte_expiry()
    try:
        contracts = api.get_option_contracts(
            underlying_symbol=sym,
            expiration_date=expiry,
            option_type="put",
            limit=100,
        )
        if not contracts:
            log.warning(f"OPT {sym}: no put contracts found for {expiry}")
            return None

        # Build full chain with quotes, sorted by strike descending (ATM first)
        chain = []
        for c in contracts:
            try:
                snap  = api.get_option_snapshot(c.symbol)
                if not snap: continue
                greeks = snap.greeks
                quote  = snap.latest_quote
                if not greeks or not quote: continue
                bid = quote.bid_price or 0
                ask = quote.ask_price or 0
                if bid <= 0 or ask <= 0: continue
                mid   = (bid + ask) / 2
                delta = abs(greeks.delta) if greeks.delta else 0
                oi    = snap.open_interest or 0
                chain.append({
                    "opt_sym": c.symbol,
                    "strike":  float(c.strike_price),
                    "bid":     bid,
                    "ask":     ask,
                    "mid":     mid,
                    "delta":   delta,
                    "oi":      oi,
                })
            except Exception:
                continue

        if not chain:
            log.warning(f"OPT {sym}: no tradeable puts found for {expiry}")
            return None

        # Sort by distance from underlying (ATM first), puts are below so sort desc
        chain.sort(key=lambda x: abs(x["strike"] - underlying_px))

        best = None
        best_diff = float("inf")

        for c in chain:
            ask_total_1 = c["ask"] * 100 * 1   # cost of 1 contract
            ask_total_2 = c["ask"] * 100 * 2   # cost of 2 contracts

            diff_1 = abs(ask_total_1 - OPT_BUDGET)
            diff_2 = abs(ask_total_2 - OPT_BUDGET)

            if diff_1 <= diff_2:
                qty  = 1
                diff = diff_1
            else:
                qty  = 2
                diff = diff_2

            if diff < best_diff:
                best_diff = diff
                best = dict(c)
                best["qty"] = qty

        if best is None:
            return None

        log.info(f"OPT {sym}: selected {best['opt_sym']}  strike={best['strike']}  "
                 f"ask={best['ask']:.2f}  qty={best['qty']}  "
                 f"cost~${best['ask']*100*best['qty']:.0f}  delta={best['delta']:.2f}")
        return best

    except Exception as e:
        log.error(f"OPT {sym}: chain fetch failed — {e}")
        return None


def _buy_put(s: SymState):
    """
    Buy 1DTE ATM put alongside stock short signal.
    Uses adaptive limit: mid -> mid+25% spread -> mid+50% spread (ask).
    """
    if not TRADE_OPTIONS:
        return
    if s.position is None:
        return  # stock short must already be open

    entry_px = s.position["entry"]
    put = _select_put(s.sym, entry_px)
    if put is None:
        return

    opt_sym = put["opt_sym"]
    spread  = put["ask"] - put["bid"]
    prices  = [
        round(put["mid"], 2),
        round(put["mid"] + 0.25 * spread, 2),
        round(put["ask"], 2),
    ]

    order_id = None
    for attempt, limit_px in enumerate(prices):
        try:
            if order_id:
                try: api.cancel_order(order_id)
                except Exception: pass
            # qty determined by _select_put (1 contract ~$300 or 2 contracts ~$150 each)
            contracts = put.get("qty", 1)
            order = api.submit_order(
                symbol        = opt_sym,
                qty           = contracts,
                side          = "buy",
                type          = "limit",
                time_in_force = "day",
                limit_price   = str(limit_px),
            )
            order_id = order.id
            log.info(f"OPT {s.sym}: BUY PUT {opt_sym} x{contracts} @ {limit_px:.2f}  (~${contracts*limit_px*100:.0f})  attempt {attempt+1}")
            time.sleep(7)
            o = api.get_order(order_id)
            if o.status == "filled":
                fill = float(o.filled_avg_price)
                log.info(f"OPT {s.sym}: PUT FILLED {opt_sym} @ {fill:.2f}")
                with _lock:
                    s.opt_position = {
                        "opt_sym":   opt_sym,
                        "qty":       contracts,
                        "entry_fill": fill,
                        "order_id":  order_id,
                    }
                return
        except Exception as e:
            log.error(f"OPT {s.sym}: put entry error attempt {attempt+1} — {e}")
            return

    # cancel if still unfilled after all attempts
    if order_id:
        try: api.cancel_order(order_id)
        except Exception: pass
    log.warning(f"OPT {s.sym}: put unfilled after 3 attempts — skipped")


def _close_put(s: SymState, reason: str):
    """Market-sell the put to close options leg."""
    if s.opt_position is None:
        return
    opt_sym = s.opt_position["opt_sym"]
    qty     = s.opt_position["qty"]
    try:
        api.submit_order(
            symbol        = opt_sym,
            qty           = qty,
            side          = "sell",
            type          = "market",
            time_in_force = "day",
        )
        log.info(f"OPT {s.sym}: CLOSE PUT {opt_sym}  reason={reason}")
    except Exception as e:
        log.error(f"OPT {s.sym}: put close failed — {e}")
    with _lock:
        s.opt_position = None


# ── TRADE MANAGEMENT (PUTS ONLY — no stock shorts) ───────────────────────────────

def open_trade(s: SymState, entry_px: float):
    """Signal fired — buy a 1DTE put. No stock short."""
    with _lock:
        open_count = sum(1 for ss in state.values() if ss.position is not None)
        if open_count >= MAX_POSITIONS:
            log.info(f"{s.sym}: max positions ({MAX_POSITIONS}) — skip")
            s.pending_entry = False
            return
        if s.position is not None:
            s.pending_entry = False
            return
        if not s.gap_ok:
            s.pending_entry = False
            return

    tp_px = round(entry_px * (1 - TP_PCT), 4)  # stock price target for TP
    sl_px = round(entry_px * (1 + SL_PCT), 4)  # stock price level for SL
    log.info(f"SIGNAL {s.sym}  stock_entry~{entry_px:.4f}  TP_level={tp_px:.4f}  SL_level={sl_px:.4f}")

    # Record position first so _buy_put can reference it
    with _lock:
        s.position = {
            "entry":     entry_px,
            "tp":        tp_px,
            "sl":        sl_px,
            "opened_at": datetime.now(TZ),
        }
        s.bars_held     = 0
        s.pending_entry = False

    # Buy the put (runs in thread, fills asynchronously)
    threading.Thread(target=_buy_put, args=(s,), daemon=True).start()
    _sb_update(s)


def close_trade(s: SymState, reason: str):
    """Sell put at market and clear position."""
    _close_put(s, reason)
    with _lock:
        s.position = None
        s.bars_held = 0


def on_exit_fill(s: SymState, won: bool, fill_px: float, reason: str):
    """Called when stock price hits TP or SL level — sell put immediately."""
    global daily_losses, bot_stopped
    _close_put(s, reason)
    with _lock:
        s.position  = None
        s.bars_held = 0
        if won:
            s.consec_loss = 0
            log.info(f"WIN    {s.sym}  {reason}  stock_px={fill_px:.4f}")
        else:
            s.consec_loss += 1
            daily_losses  += 1
            log.info(f"LOSS   {s.sym}  {reason}  stock_px={fill_px:.4f}  streak={s.consec_loss}")
            if s.consec_loss >= MAX_CONSEC_SYM:
                s.paused = True
                log.warning(f"PAUSE  {s.sym} — {MAX_CONSEC_SYM} consecutive losses")
            if daily_losses >= MAX_DAILY_LOSS:
                bot_stopped = True
                log.warning(f"KILL   Bot stopped — {MAX_DAILY_LOSS} daily losses")
    _sb_update(s)


# ── BAR HANDLER ───────────────────────────────────────────────────────────────────

def handle_pm_bar(s: SymState, bar: dict):
    """Process premarket bar — track PM high."""
    if s.pm_high is None or bar["h"] > s.pm_high:
        s.pm_high = bar["h"]


def handle_rth_bar(s: SymState, bar: dict):
    """Process RTH bar — gap check, level compute, entry logic, exit management."""
    now_et = datetime.now(TZ)
    hm     = now_et.strftime("%H:%M")

    # ── First bar of day (09:30) ──────────────────────────────────────────────
    if hm == "09:30":
        s.rth_open = bar["o"]
        if s.prev_close and s.rth_open:
            s.gap_pct = (s.rth_open - s.prev_close) / s.prev_close
            s.gap_ok  = s.gap_pct > GAP_MIN
            log.info(f"{s.sym}: gap={s.gap_pct*100:.2f}%  {'GO' if s.gap_ok else 'SKIP'}")
        if not s.gap_ok:
            return

        # Build levels for today
        rtype = s.rtype
        if rtype == "PMH":
            if s.pm_high:
                s.levels = [s.pm_high]
                log.info(f"{s.sym}: PMH level={s.pm_high:.4f}")
        elif rtype == "PDH":
            if s.pdh:
                s.levels = [s.pdh]
                log.info(f"{s.sym}: PDH level={s.pdh:.4f}")
        elif rtype == "PIV":
            s.levels = build_pivot_levels(s.rth_bars, s.lb, s.wing)
            log.info(f"{s.sym}: {len(s.levels)} pivot levels from {s.lb}-bar window")

    # ── Always append bar ─────────────────────────────────────────────────────
    s.today_bars.append(bar)
    s.rth_bars.append(bar)

    if not s.gap_ok:
        return

    # ── Kill switch checks ────────────────────────────────────────────────────
    if bot_stopped or s.paused:
        return
    if hm >= "15:00" and s.position is None:
        return  # no new entries after 15:00

    # ── Force close at 15:55 ─────────────────────────────────────────────────
    if hm >= "15:55" and s.position is not None:
        close_trade(s, "EOD")
        return

    # ── Manage open position ──────────────────────────────────────────────────
    if s.position is not None:
        s.bars_held += 1
        pos = s.position
        # check TP/SL manually (OCO should handle, but belt+suspenders)
        if bar["l"] <= pos["tp"]:
            on_exit_fill(s, True,  pos["tp"], "TP")
            return
        if bar["h"] >= pos["sl"]:
            on_exit_fill(s, False, pos["sl"], "SL")
            return
        if s.bars_held >= MAX_BARS:
            close_trade(s, "TIMEOUT")
            return
        _sb_update(s)
        return

    # ── +1 bar confirmation entry logic ──────────────────────────────────────
    # Step 1: if prev bar's SM fired (pending_entry=True), enter on THIS bar's open
    if s.pending_entry:
        entry_px = bar["o"]  # open of the bar AFTER the signal bar
        log.info(f"ENTRY  {s.sym}  +1bar open={entry_px:.4f}  TP={entry_px*(1-TP_PCT):.4f}  SL={entry_px*(1+SL_PCT):.4f}")
        threading.Thread(
            target=open_trade, args=(s, entry_px), daemon=True
        ).start()
        _sb_update(s)
        return  # don't scan new signals on same bar we're entering

    # Step 2: run SM on current bar — if fires, set pending_entry for NEXT bar
    for level in s.levels:
        if update_level_sm(s, level, bar):
            s.pending_entry = True
            log.info(f"SIGNAL {s.sym}  level={level:.4f}  — entering next bar open")
            break  # one signal per symbol per bar

    _sb_update(s)


def handle_bar(sym: str, bar: dict, is_pm: bool):
    s = state[sym]
    if is_pm:
        handle_pm_bar(s, bar)
    else:
        handle_rth_bar(s, bar)


# ── SUPABASE STATUS PUSH ──────────────────────────────────────────────────────────

def _sb_update(s: SymState):
    now = datetime.now(TZ)
    pos_str = ""
    if s.position:
        held = s.bars_held
        pos_str = f" | PUT open @ stock={s.position['entry']:.2f} ({held}b held)"
    # setup_close = level touched, state machine in bounce phase (signal imminent)
    touched    = any(v.get("state") == "touch"  for v in s.level_states.values())
    bouncing   = any(v.get("state") == "bounce" for v in s.level_states.values())
    metrics = (f"gap={s.gap_pct*100:.2f}% | "
               f"levels={len(s.levels)} | "
               f"gap_ok={s.gap_ok}"
               f"{pos_str}")
    threading.Thread(target=sb_push, args=([{
        "bot":            "BOOF51",
        "symbol":         s.sym,
        "setup_active":   s.opt_position is not None,
        "setup_close":    s.gap_ok and s.opt_position is None and bouncing,
        "setup_watching": s.gap_ok and s.opt_position is None and bool(s.levels) and not touched and not bouncing,
        "setup_touched":  s.gap_ok and s.opt_position is None and touched and not bouncing,
        "metrics":        metrics,
        "updated_at":     now.isoformat(),
    }],), daemon=True).start()


# ── STREAM HANDLERS ───────────────────────────────────────────────────────────────

async def on_bar(bar):
    sym = bar.symbol
    if sym not in state:
        return
    hm = bar.timestamp.astimezone(TZ).strftime("%H:%M")
    is_pm = hm < "09:30"
    handle_bar(sym, {
        "o": bar.open, "h": bar.high,
        "l": bar.low,  "c": bar.close, "v": bar.volume,
    }, is_pm)


async def on_trade_update(update):
    """Track fills to update kill switches."""
    if update.event not in ("fill", "partial_fill"):
        return
    order = update.order
    sym   = order.get("symbol", "") if isinstance(update.order, dict) else getattr(update.order, "symbol", "")
    if sym not in state:
        return
    s = state[sym]
    if s.position is None:
        return
    fill = float(order.get("filled_avg_price", 0) if isinstance(update.order, dict) else getattr(update.order, "filled_avg_price", 0) or 0)
    otype = (order.get("type", "") if isinstance(update.order, dict) else getattr(update.order, "type", ""))
    side  = (order.get("side", "") if isinstance(update.order, dict) else getattr(update.order, "side", ""))
    # buy fill = closing the short
    if side == "buy":
        won = (otype == "limit")  # limit = TP | stop = SL
        reason = "TP" if won else "SL"
        on_exit_fill(s, won, fill, reason)


# ── HEARTBEAT ─────────────────────────────────────────────────────────────────────

def heartbeat():
    """Log bot status every 5 minutes so it's visible in console/logs."""
    import os
    while True:
        time.sleep(300)  # every 5 minutes
        try:
            now_et   = datetime.now(TZ).strftime("%H:%M ET")
            open_pos = [(s.sym, s.position["entry"]) for s in state.values() if s.position]
            paused   = [s.sym for s in state.values() if s.paused]
            mem_mb   = 0
            try:
                with open(f"/proc/{os.getpid()}/status") as f:
                    for line in f:
                        if line.startswith("VmRSS"):
                            mem_mb = int(line.split()[1]) // 1024
                            break
            except Exception:
                pass
            pos_str    = ", ".join(f"{sym}@{px:.2f}" for sym, px in open_pos) or "none"
            paused_str = ", ".join(paused) or "none"
            log.info(
                f"HEARTBEAT  {now_et}  "
                f"positions={len(open_pos)}/5 [{pos_str}]  "
                f"daily_losses={daily_losses}/{MAX_DAILY_LOSS}  "
                f"paused=[{paused_str}]  "
                f"stopped={bot_stopped}  "
                f"mem={mem_mb}MB"
            )
        except Exception as e:
            log.warning(f"HEARTBEAT error: {e}")


# ── DAILY RESET + CLOSE TRACKER ──────────────────────────────────────────────────

def end_of_day_reset():
    global daily_losses, bot_stopped
    with _lock:
        daily_losses = 0
        bot_stopped  = False
        for s in state.values():
            # save today's close as prev_close for tomorrow
            if s.today_bars:
                s.prev_close = s.today_bars[-1]["c"]
            # save today's high/low as PDH/PDL for tomorrow
            if s.today_bars:
                s.pdh = max(b["h"] for b in s.today_bars)
                s.pdl = min(b["l"] for b in s.today_bars)
            s.reset_day()
            s.reset_daily_kill()
    log.info("RESET  End-of-day state cleared, prev_close and PDH saved")


def schedule_eod_reset():
    """Sleep until 16:05 ET then trigger reset."""
    while True:
        now = datetime.now(TZ)
        target = now.replace(hour=16, minute=5, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        sleep_s = (target - now).total_seconds()
        log.info(f"EOD reset scheduled in {sleep_s/3600:.1f}h")
        time.sleep(sleep_s)
        end_of_day_reset()


# ── STARTUP PRE-SEED (fetch yesterday's daily bar at boot) ─────────────────────────

def preseed_daily_data():
    """
    Called once at startup — before the stream starts.
    Fetches the most recent completed daily bar for each symbol and seeds:
      prev_close = yesterday.close
      pdh        = yesterday.high
      pdl        = yesterday.low
    This ensures the bot is ready immediately on Monday morning or after any restart.
    """
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    import datetime as _dt

    log.info("Pre-seeding prev_close / PDH / PDL from last daily bar...")
    try:
        client = StockHistoricalDataClient(API_KEY, API_SECRET)
        now_et = datetime.now(TZ)
        # fetch last 5 calendar days to guarantee we get at least 1 trading day
        start  = (now_et - timedelta(days=5)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        end    = now_et
        req = StockBarsRequest(
            symbol_or_symbols=SYMBOLS,
            timeframe=TimeFrame(1, TimeFrameUnit.Day),
            start=start, end=end,
        )
        bars_df = client.get_stock_bars(req).df
        if bars_df.empty:
            log.warning("Pre-seed: no daily bars returned")
            return
        # keep only the most recent completed bar per symbol (not today's partial)
        today_date = now_et.date()
        for sym in SYMBOLS:
            if sym not in state:
                continue
            try:
                sym_bars = bars_df.xs(sym, level="symbol") if "symbol" in bars_df.index.names else bars_df[bars_df.index.get_level_values(0)==sym]
                # filter out today's partial bar
                sym_bars = sym_bars[
                    sym_bars.index.get_level_values(-1).date < today_date
                    if hasattr(sym_bars.index.get_level_values(-1)[0], 'date')
                    else [ts.date() < today_date for ts in sym_bars.index.get_level_values(-1)]
                ]
                if sym_bars.empty:
                    log.warning(f"  {sym}: no prior daily bar found")
                    continue
                last = sym_bars.iloc[-1]
                s = state[sym]
                s.prev_close = float(last["close"])
                s.pdh        = float(last["high"])
                s.pdl        = float(last["low"])
                log.info(f"  {sym}: prev_close={s.prev_close:.4f}  PDH={s.pdh:.4f}  PDL={s.pdl:.4f}")
            except Exception as e:
                log.warning(f"  {sym}: pre-seed failed — {e}")
    except Exception as e:
        log.error(f"Pre-seed daily data failed: {e}")


# ── PREMARKET DATA FETCH (REST snapshot for PM high at 09:25) ─────────────────────

def fetch_pm_snapshots():
    """
    At 09:25 ET pull latest quotes to get PM high approximation
    and prior close for gap calculation.
    Run once per day in a background thread.
    """
    while True:
        now = datetime.now(TZ)
        target = now.replace(hour=9, minute=25, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        sleep_s = (target - now).total_seconds()
        time.sleep(sleep_s)

        log.info("Fetching PM snapshots...")
        try:
            snaps = api.get_snapshots(SYMBOLS)
            for sym, snap in snaps.items():
                if sym not in state:
                    continue
                s = state[sym]
                # prev close from daily bar
                if snap.prev_daily_bar:
                    s.prev_close = snap.prev_daily_bar.close
                # PM high from minute bars — use latest trade as proxy if no PM bar
                if snap.minute_bar:
                    mb = snap.minute_bar
                    if s.pm_high is None or mb.high > s.pm_high:
                        s.pm_high = mb.high
                log.info(f"  {sym}: prev_close={s.prev_close}  pm_high={s.pm_high}")
        except Exception as e:
            log.error(f"Snapshot fetch failed: {e}")


# ── MAIN ──────────────────────────────────────────────────────────────────────────

def main():
    log.info(f"BOOF51 Live Bot  {'[PAPER]' if PAPER else '[LIVE]'}")
    log.info(f"Universe ({len(SYMBOLS)}): {', '.join(SYMBOLS)}")
    log.info(f"--- Strategy checks ---")
    log.info(f"[OK] Routing    : Version H — PMH/PDH/10m/30m/2H/4H/Daily per symbol")
    log.info(f"[OK] Direction  : PUTS ONLY — no stock shorts, buys 1DTE put on every signal")
    log.info(f"[OK] Options    : 1DTE put  delta {OPT_DELTA_MIN}-{OPT_DELTA_MAX}  highest OI strike")
    log.info(f"[OK] Gap gate   : gap-up > {GAP_MIN*100:.1f}% required each day per symbol")
    log.info(f"[OK] Entry      : fresh 1st touch + bounce >= {BOUNCE*100:.2f}% + +1 bar confirmation")
    log.info(f"[OK] TP/SL      : TP={TP_PCT*100:.2f}% below entry  SL={SL_PCT*100:.2f}% above entry")
    log.info(f"[OK] Max hold   : {MAX_BARS} bars then force-close")
    log.info(f"MaxPos={MAX_POSITIONS}  MaxConsecSym={MAX_CONSEC_SYM}  DailyStop={MAX_DAILY_LOSS}")

    if "YOUR_PAPER" in API_KEY:
        log.error("API keys not set — edit API_KEY and API_SECRET before running")
        return

    # Pre-seed prev_close / PDH / PDL before stream starts
    preseed_daily_data()

    # Start background threads
    threading.Thread(target=schedule_eod_reset,  daemon=True).start()
    threading.Thread(target=fetch_pm_snapshots,  daemon=True).start()
    threading.Thread(target=heartbeat,           daemon=True).start()

    # Stream using proven alpaca_trade_api library (same as boof50)
    log.info("Streaming started — waiting for bars...")
    backoff = 5
    while True:
        try:
            stream = Stream(API_KEY, API_SECRET, base_url=BASE_URL, data_feed="sip")
            stream.subscribe_bars(on_bar, *SYMBOLS)
            stream.subscribe_updated_bars(on_bar, *SYMBOLS)
            stream.subscribe_trade_updates(on_trade_update)
            stream.run()
        except Exception as e:
            log.error(f"Stream error: {e} — reconnecting in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
        else:
            backoff = 5


if __name__ == "__main__":
    main()
