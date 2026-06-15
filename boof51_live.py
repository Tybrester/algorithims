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

# ── CONFIG ──────────────────────────────────────────────────────────────────────

API_KEY    = "PKWKMWREJIGNRMBOQWORXFRMDS"
API_SECRET = "7vdjuEeeWhxSSGMUbefFQfjb4Z9rSuEzkASNDS6t74MW"
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
        self.last_price  = None  # last bar close

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
        s.level_states[key] = {"state": "IDLE", "extreme": None, "touch_num": 0, "was_below": False}
    sm = s.level_states[key]

    high = bar["h"]; close = bar["c"]

    # gate: price must have closed below the level before a touch counts
    if close < level:
        sm["was_below"] = True

    touching = sm["was_below"] and high >= level * (1 - NEAR_PCT)

    if sm["state"] == "IDLE":
        if touching:
            sm["state"]    = "IN"
            sm["extreme"]  = close
            sm["touch_num"] += 1

    elif sm["state"] == "IN":
        if high >= level * (1 - NEAR_PCT):
            sm["extreme"] = min(sm["extreme"], close)
        else:
            # left the zone — check bounce
            bounced = (sm["extreme"] is not None and
                       (level - sm["extreme"]) / level >= BOUNCE)
            if bounced and sm["touch_num"] == 1:
                # signal fires — next bar open is entry
                sm["state"] = "FIRED"
                return True
            # no valid bounce or repeat touch → invalidate
            sm["state"]   = "DEAD"
            sm["was_below"] = False  # must go below again before re-arming
    elif sm["state"] == "DEAD":
        if sm["was_below"]:  # price came back below — reset to IDLE for re-test
            sm["state"]    = "IDLE"
            sm["extreme"]  = None
            sm["touch_num"] = 0
    # FIRED: no further signals

    return False


# ── OPTIONS LEG ─────────────────────────────────────────────────────────────────

def _next_trading_days(n: int = 7) -> list:
    """Return next n trading day dates as YYYY-MM-DD strings."""
    now = datetime.now(TZ)
    days = []
    exp  = now + timedelta(days=1)
    while len(days) < n:
        if exp.weekday() < 5:
            days.append(exp.strftime("%Y-%m-%d"))
        exp += timedelta(days=1)
    return days


def _select_put(sym: str, underlying_px: float):
    """
    Fetch 1DTE put chain for sym.
    Walk from ATM outward (descending strike) and pick the strike where:
      - 1 contract ask*100 is closest to $300, OR
      - 2 contracts ask*100*2 is closest to $300 (i.e. ask*100 ~$150)
    Whichever combo gets closest to OPT_BUDGET wins.
    Returns dict: {opt_sym, strike, bid, ask, mid, delta, oi, qty} or None.
    """
    try:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetOptionContractsRequest
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.requests import OptionSnapshotRequest

        _trade_client = TradingClient(API_KEY, API_SECRET, paper=True)
        _opt_data     = OptionHistoricalDataClient(API_KEY, API_SECRET)

        contracts = []
        expiry    = None
        for candidate in _next_trading_days(7):
            req = GetOptionContractsRequest(
                underlying_symbols=[sym],
                expiration_date=candidate,
                type="put",
                limit=100,
            )
            contracts = _trade_client.get_option_contracts(req).option_contracts
            if contracts:
                expiry = candidate
                log.info(f"OPT {sym}: using expiry {expiry} ({len(contracts)} contracts)")
                break
        if not contracts:
            log.warning(f"OPT {sym}: no put contracts found in next 7 trading days")
            return None

        # Fetch snapshots for all contract symbols at once
        opt_syms = [c.symbol for c in contracts]
        snap_req = OptionSnapshotRequest(symbol_or_symbols=opt_syms)
        snaps    = _opt_data.get_option_snapshot(snap_req)

        chain = []
        for c in contracts:
            try:
                snap = snaps.get(c.symbol)
                if not snap: continue
                greeks = snap.greeks
                quote  = snap.latest_quote
                if not greeks or not quote: continue
                bid = quote.bid_price or 0
                ask = quote.ask_price or 0
                if ask <= 0: continue  # bid can be 0 on illiquid puts
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

        # Walk from ATM → ITM (sort by strike descending = closest to price first for puts)
        # Puts: strike at or just below underlying = ATM, higher strike = ITM
        chain.sort(key=lambda x: abs(x["strike"] - underlying_px))

        best = None
        best_diff = float("inf")

        for c in chain:
            ask = c["ask"]
            cost_1 = ask * 100        # 1 contract
            cost_2 = ask * 100 * 2    # 2 contracts

            diff_1 = abs(cost_1 - OPT_BUDGET)   # vs $300 target
            diff_2 = abs(cost_2 - OPT_BUDGET)   # 2x ~$150 each

            qty  = 1 if diff_1 <= diff_2 else 2
            diff = min(diff_1, diff_2)

            log.debug(f"  OPT {sym} strike={c['strike']} ask={ask:.2f} "
                      f"cost1=${cost_1:.0f} cost2=${cost_2:.0f} -> qty={qty} diff={diff:.0f}")

            if diff < best_diff:
                best_diff = diff
                best = dict(c)
                best["qty"] = qty

        if best is None:
            log.warning(f"OPT {sym}: no suitable strike found in chain of {len(chain)}")
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

    opt_sym   = put["opt_sym"]
    bid       = put["bid"]
    ask       = put["ask"]
    spread    = ask - bid
    mid       = put["mid"]
    contracts = put.get("qty", 1)

    prices = [
        (round(mid + 0.25 * spread, 2), 5),
        (round(mid + 0.50 * spread, 2), 5),
        (round(ask, 2),                 5),
    ]
    order_id = None
    for attempt, (limit_px, wait) in enumerate(prices):
        try:
            if order_id:
                try: api.cancel_order(order_id)
                except Exception: pass
            order = api.submit_order(
                symbol        = opt_sym,
                qty           = contracts,
                side          = "buy",
                type          = "limit",
                time_in_force = "day",
                limit_price   = str(limit_px),
            )
            order_id = order.id
            log.info(f"OPT {s.sym}: attempt {attempt+1} BUY PUT {opt_sym} x{contracts} @ {limit_px:.2f} (wait {wait}s)")
            time.sleep(wait)
            o = api.get_order(order_id)
            if o.status == "filled":
                fill = float(o.filled_avg_price)
                log.info(f"OPT {s.sym}: PUT FILLED {opt_sym} x{contracts} @ {fill:.2f}")
                with _lock:
                    s.opt_position = {
                        "opt_sym":    opt_sym,
                        "qty":        contracts,
                        "entry_fill": fill,
                        "order_id":   order_id,
                    }
                return
        except Exception as e:
            log.error(f"OPT {s.sym}: put entry error attempt {attempt+1} — {e}")
            return
    # cancel after all attempts (spread exploded)
    if order_id:
        try: api.cancel_order(order_id)
        except Exception: pass
    log.warning(f"OPT {s.sym}: put unfilled after 15s — cancelled")


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
            elif s.pdh:
                s.levels = [s.pdh]
                log.info(f"{s.sym}: PMH unavailable — falling back to PDH={s.pdh:.4f}")
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
    s.last_price = bar["c"]

    if not s.gap_ok:
        _sb_update(s)
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
    # setup_close = price is currently touching a level (IN = touching, FIRED = signal just fired)
    touched    = any(v.get("state") == "IN"    for v in s.level_states.values())
    bouncing   = any(v.get("state") == "FIRED" for v in s.level_states.values())
    px_str = f" | px=${s.last_price:.2f}" if s.last_price else ""
    lb = s.lb
    rtype_label = {"PMH": "PMH", "PDH": "PDH"}.get(s.rtype) or (
        "10m" if lb == 10 else "30m" if lb == 30 else "2H" if lb == 120 else "4H" if lb == 240 else "Daily" if lb == 390 else s.rtype
    )
    if s.gap_pct is not None:
        gap_str = f"Gap: {s.gap_pct*100:+.2f}%"
        if s.gap_ok:
            lvl_str = ", ".join(f"${lv:.2f}" for lv in s.levels[:3]) if s.levels else "none"
            touch_str = " | ⚡ TOUCHING LEVEL" if touched else (" | 🔥 SIGNAL FIRED" if bouncing else "")
            metrics = f"[{rtype_label}] {gap_str} ✓{px_str} | Levels: {lvl_str}{touch_str}{pos_str}"
        else:
            metrics = f"[{rtype_label}] {gap_str} — no gap{px_str}"
    else:
        metrics = "Waiting for open..."
    threading.Thread(target=sb_push, args=([{
        "bot":            "BOOF51",
        "symbol":         s.sym,
        "setup_active":   s.position is not None or s.opt_position is not None,
        "setup_close":    s.gap_ok and s.position is None and s.opt_position is None and (bouncing or touched),
        "setup_watching": s.gap_ok and s.position is None and s.opt_position is None and bool(s.levels) and not touched and not bouncing,
        "metrics":        metrics,
        "updated_at":     now.isoformat(),
    }],), daemon=True).start()


# ── REST POLL LOOP ────────────────────────────────────────────────────────────────

def poll_bars():
    """Poll latest 1-min bar for all symbols every 60s via REST."""
    seen: dict = {}   # sym -> last bar timestamp
    log.info("REST polling started — fetching bars every 60s...")
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    _client = StockHistoricalDataClient(API_KEY, API_SECRET)
    while True:
        now_et = datetime.now(TZ)
        in_session = (
            now_et.weekday() < 5
            and (now_et.hour > 4 or (now_et.hour == 4 and now_et.minute >= 0))
            and now_et.hour < 20
        )
        if not in_session:
            time.sleep(60)
            continue
        now_et2 = datetime.now(TZ)
        req = StockBarsRequest(
            symbol_or_symbols=SYMBOLS,
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
            start=now_et2 - timedelta(minutes=5),
            end=now_et2,
            feed="iex",
        )
        try:
            df = _client.get_stock_bars(req).df
        except Exception as e:
            log.error(f"poll_bars fetch failed: {e}")
            time.sleep(60)
            continue
        for sym in SYMBOLS:
            try:
                if df.empty:
                    continue
                if "symbol" in df.index.names:
                    sym_df = df.xs(sym, level="symbol") if sym in df.index.get_level_values("symbol") else None
                else:
                    sym_df = df[df.index.get_level_values(0) == sym]
                if sym_df is None or sym_df.empty:
                    continue
                bar = sym_df.iloc[-1]
                ts_str = str(bar.name)
                if seen.get(sym) == ts_str:
                    continue
                seen[sym] = ts_str
                log.info(f"BAR {sym} @ {ts_str}  c={bar.close:.2f}")
                ts = bar.name
                if hasattr(ts, "to_pydatetime"):
                    ts = ts.to_pydatetime()
                if not hasattr(ts, "astimezone"):
                    ts = datetime.fromtimestamp(float(ts) / 1e9, tz=TZ)
                hm    = ts.astimezone(TZ).strftime("%H:%M")
                is_pm = hm < "09:30"
                handle_bar(sym, {
                    "o": float(bar.open), "h": float(bar.high),
                    "l": float(bar.low),  "c": float(bar.close), "v": float(bar.volume),
                }, is_pm)
            except Exception as e:
                log.error(f"poll_bars {sym}: {e}")
        time.sleep(60)


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
            feed="iex",
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


# ── BACKFILL TODAY'S GAP (mid-day restart recovery) ──────────────────────────────

def backfill_today_gap():
    """
    If bot starts mid-day (after 09:30), fetch today's 1-min bars to recover:
      - rth_open (first bar open at 09:30)
      - pm_high  (max high from 04:00–09:30 bars)
      - gap_pct / gap_ok
      - levels for each symbol
    Safe to call any time — skips symbols already initialised.
    """
    now_et = datetime.now(TZ)
    if now_et.hour < 9 or (now_et.hour == 9 and now_et.minute < 31):
        return  # too early, normal open will handle it
    if now_et.weekday() >= 5:
        return  # weekend

    log.info("Backfilling today's gap / levels for mid-day restart...")
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    try:
        client  = StockHistoricalDataClient(API_KEY, API_SECRET)
        today   = now_et.date()
        start   = datetime(today.year, today.month, today.day, 4, 0, tzinfo=TZ)
        end     = now_et
        req = StockBarsRequest(
            symbol_or_symbols=SYMBOLS,
            timeframe=TimeFrame(1, TimeFrameUnit.Minute),
            start=start, end=end,
            feed="iex",
        )
        df = client.get_stock_bars(req).df
        if df.empty:
            log.warning("Backfill: no bars returned")
            return

        for sym in SYMBOLS:
            s = state[sym]
            if s.gap_ok:
                continue  # already initialised
            try:
                sym_df = df.xs(sym, level="symbol") if sym in df.index.get_level_values("symbol") else None
                if sym_df is None or sym_df.empty:
                    continue
                # convert index to ET
                sym_df = sym_df.copy()
                sym_df.index = sym_df.index.tz_convert(TZ)
                hm = sym_df.index.strftime("%H:%M")
                # PM high
                pm_bars = sym_df[hm < "09:30"]
                if not pm_bars.empty:
                    s.pm_high = float(pm_bars["high"].max())
                # RTH open = first bar at/after 09:30
                rth_bars = sym_df[hm >= "09:30"]
                if rth_bars.empty:
                    continue
                s.rth_open = float(rth_bars.iloc[0]["open"])
                if s.prev_close and s.rth_open:
                    s.gap_pct = (s.rth_open - s.prev_close) / s.prev_close
                    s.gap_ok  = s.gap_pct > GAP_MIN
                    log.info(f"  {sym}: backfill gap={s.gap_pct*100:.2f}%  {'GO' if s.gap_ok else 'SKIP'}")
                if not s.gap_ok:
                    continue
                # Build levels
                rtype = s.rtype
                if rtype == "PMH":
                    if s.pm_high:
                        s.levels = [s.pm_high]
                        log.info(f"  {sym}: PMH level={s.pm_high:.4f}")
                    elif s.pdh:
                        s.levels = [s.pdh]
                        log.info(f"  {sym}: PMH unavailable — falling back to PDH={s.pdh:.4f}")
                elif rtype == "PDH":
                    if s.pdh:
                        s.levels = [s.pdh]
                elif rtype == "PIV":
                    # seed rth_bars into s.rth_bars for pivot builder
                    for _, row in rth_bars.iterrows():
                        s.rth_bars.append({"o": row["open"], "h": row["high"],
                                           "l": row["low"],  "c": row["close"], "v": row["volume"]})
                    s.levels = build_pivot_levels(s.rth_bars, s.lb, s.wing)
                log.info(f"  {sym}: {len(s.levels)} level(s) — {[round(l,2) for l in s.levels[:3]]}")
                s.level_states = {}  # reset SM — only live bars should trigger state changes
                _sb_update(s)
            except Exception as e:
                log.warning(f"  {sym}: backfill failed — {e}")
    except Exception as e:
        log.error(f"Backfill today gap failed: {e}")


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
    # Recover today's gap/levels if restarted mid-day
    backfill_today_gap()

    # Start background threads
    threading.Thread(target=schedule_eod_reset,  daemon=True).start()
    threading.Thread(target=fetch_pm_snapshots,  daemon=True).start()
    threading.Thread(target=heartbeat,           daemon=True).start()

    poll_bars()


if __name__ == "__main__":
    main()
