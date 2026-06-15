"""
BOOF50 Live Trading Bot — 1DTE Options
=======================================
Signal    : VWAP Cross on underlying (5-bar hold confirmation)
Instrument: 1DTE options — call (long signal) / put (short signal)
            Pick the strike whose mid-price is closest to $3.50

Entry fill logic (adaptive limit):
  1. Place buy limit at mid = (bid + ask) / 2
  2. After 7s if unfilled: move to mid + 25% of spread
  3. After another 7s if unfilled: move to mid + 50% of spread (≈ ask)
  4. Cancel if still unfilled

On fill (e.g. $3.04):
  TP = fill * 1.30  → sell limit  $3.95
  SL = fill * 0.85  → sell stop   $2.58
  Submit both as OCO — first fill cancels the other

Kill switches:
  - Max 3 open positions at once
  - Max 1 per symbol per direction
  - Stop symbol after 3 consecutive losses
  - Stop bot after 5 daily losses
  - PAPER = True by default
"""

import time, threading, logging, requests as _requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import alpaca_trade_api as tradeapi
from alpaca_trade_api.stream import Stream

# ── Config ─────────────────────────────────────────────────────────────────────

API_KEY    = "PKUE2IRNMB5ZUCK3ISPE3RIUX4"
API_SECRET = "Cb3rxrN6SNSYkpYEbVn96i7FjM5KCBcpR8bLq7hKRciB"
PAPER      = True

BASE_URL = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"

SYMBOLS = [
    "TSLA","AMD","APP","COIN","HOOD",
    "SMCI","UPST","META","MSFT","NVDA",
    "MSTR","PLTR","CRWD","AAPL","AMZN"
]

OPTION_TARGET  = 3.50    # pick strike whose mid is closest to this
CONTRACTS      = 1
TP_MULT        = 1.30    # +30%
SL_MULT        = 0.85    # -15%
FILL_WAIT_S    = 7       # seconds between limit price bumps
CONFIRM_BARS   = 5
MAX_HOLD_MIN   = 120
MAX_POSITIONS  = 10      # max 10 concurrent open positions
MAX_LOSSES_SYM = 3
MAX_DAILY_LOSS = 8
TZ             = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("BOOF50")

# ── Supabase ───────────────────────────────────────────────────────────────────

SUPABASE_URL     = "https://isanhutzyctcjygjhzbn.supabase.co"
SUPABASE_KEY     = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlzYW5odXR6eWN0Y2p5Z2poemJuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMTYzNDYsImV4cCI6MjA5MTY5MjM0Nn0.L0ATp-IriR708C2n3as_YXDgjHvtn_CWubbzPeSxRi0"
_SB_HEADERS      = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}

def sb_push_status(symbols_payload: list):
    try:
        _requests.post(
            f"{SUPABASE_URL}/rest/v1/bot_status",
            headers=_SB_HEADERS,
            json=symbols_payload,
            timeout=5,
        )
    except Exception as e:
        log.debug(f"Supabase status push failed: {e}")

# ── Alpaca client ──────────────────────────────────────────────────────────────

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version="v2")


# ── State ──────────────────────────────────────────────────────────────────────

class SymbolState:
    def __init__(self):
        self.bars        = []
        self.cum_pv      = 0.0
        self.cum_vol     = 0.0
        self.confirm     = {}   # side -> bar count
        self.position    = {}   # side -> position dict
        self.consec_loss = 0
        self.stopped     = False


state        = {sym: SymbolState() for sym in SYMBOLS}
daily_losses = 0
bot_stopped  = False
_lock        = threading.Lock()


# ── VWAP ───────────────────────────────────────────────────────────────────────

def update_vwap(s: SymbolState, bar: dict) -> float:
    typ       = (bar["h"] + bar["l"] + bar["c"]) / 3
    s.cum_pv  += typ * bar["v"]
    s.cum_vol += bar["v"]
    return s.cum_pv / s.cum_vol if s.cum_vol else bar["c"]


# ── Option contract selection ──────────────────────────────────────────────────

def get_1dte_expiry() -> str:
    """Return next trading day's date as YYYY-MM-DD (1DTE expiry)."""
    now = datetime.now(TZ)
    exp = now + timedelta(days=1)
    # skip weekends
    while exp.weekday() >= 5:
        exp += timedelta(days=1)
    return exp.strftime("%Y-%m-%d")


def select_option(sym: str, side: str, underlying_price: float):
    """
    Fetch option chain for sym, find the strike whose mid is closest
    to OPTION_TARGET. Returns dict with keys: symbol, bid, ask, mid.
    """
    from alpaca.trading.client import TradingClient as _TC
    from alpaca.trading.requests import GetOptionContractsRequest as _GOCR
    from alpaca.data.historical.option import OptionHistoricalDataClient as _OHDC
    from alpaca.data.requests import OptionSnapshotRequest as _OSR
    opt_type = "call" if side == "long" else "put"
    try:
        _tc  = _TC(API_KEY, API_SECRET, paper=True)
        _odc = _OHDC(API_KEY, API_SECRET)
        _now = datetime.now(ZoneInfo("America/New_York"))
        _candidates = [(_now + timedelta(days=i)).strftime("%Y-%m-%d")
                       for i in range(1, 10) if (_now + timedelta(days=i)).weekday() < 5][:7]
        contracts = []; expiry = None
        for candidate in _candidates:
            req = _GOCR(underlying_symbols=[sym], expiration_date=candidate, type=opt_type, limit=50)
            contracts = _tc.get_option_contracts(req).option_contracts
            if contracts: expiry = candidate; break
        if not contracts:
            log.warning(f"No contracts for {sym} {opt_type} in next 7 days")
            return None
        log.info(f"Option expiry {sym}: {expiry} ({len(contracts)} contracts)")
        snaps = _odc.get_option_snapshot(_OSR(symbol_or_symbols=[c.symbol for c in contracts]))
        OPT_BUDGET  = OPTION_TARGET * 100   # $350 total budget
        MAX_COST    = OPT_BUDGET * 1.5      # hard cap $525 per contract
        MAX_STRIKE_DIST = 0.10              # strike must be within 10% of underlying
        chain = []
        for contract in contracts:
            snap = snaps.get(contract.symbol)
            if not snap: continue
            strike = float(contract.strike_price)
            if abs(strike - underlying_price) / underlying_price > MAX_STRIKE_DIST: continue
            bid = snap.latest_quote.bid_price or 0
            ask = snap.latest_quote.ask_price or 0
            if ask <= 0: continue                  # need at least an ask
            if ask * 100 > MAX_COST: continue      # hard cap — no deep ITM
            mid  = (bid + ask) / 2
            cost_1 = ask * 100
            cost_2 = ask * 100 * 2
            diff_1 = abs(cost_1 - OPT_BUDGET)
            diff_2 = abs(cost_2 - OPT_BUDGET)
            qty  = 1 if diff_1 <= diff_2 else 2
            diff = min(diff_1, diff_2)
            chain.append({"symbol": contract.symbol, "bid": bid, "ask": ask,
                          "mid": mid, "qty": qty, "diff": diff})
        if not chain:
            log.warning(f"No contracts within budget for {sym} {opt_type}")
            return None
        chain.sort(key=lambda x: x["diff"])
        best = chain[0]
        log.info(f"  {sym} selected {best['symbol']} ask={best['ask']:.2f} "
                 f"qty={best['qty']} cost=${best['ask']*100*best['qty']:.0f}")
        return best
    except Exception as e:
        log.error(f"Option chain error {sym}: {e}")
        return None


# ── Adaptive limit entry ───────────────────────────────────────────────────────

def place_entry(sym: str, side: str, underlying_price: float):
    """Select option, enter with adaptive limit, then place OCO exits on fill."""
    if bot_stopped:
        log.warning("Bot stopped — skipping"); return
    if state[sym].stopped:
        log.warning(f"{sym} stopped — skipping"); return
    with _lock:
        if sum(len(s.position) for s in state.values()) >= MAX_POSITIONS:
            log.info(f"Max positions reached — skipping {sym} {side}"); return
        if side in state[sym].position:
            log.info(f"{sym} {side} already open — skipping"); return

    contract = select_option(sym, side, underlying_price)
    if not contract:
        log.warning(f"No suitable option found for {sym} {side}"); return

    opt_sym  = contract["symbol"]
    bid      = contract["bid"]
    ask      = contract["ask"]
    spread   = ask - bid
    mid      = contract["mid"]
    qty      = contract.get("qty", CONTRACTS)
    log.info(f"OPTION {sym:5s} {side:5s}  {opt_sym}  bid={bid:.2f} ask={ask:.2f} mid={mid:.2f}  qty={qty}")

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
                qty           = qty,
                side          = "buy",
                type          = "limit",
                time_in_force = "day",
                limit_price   = str(limit_px),
            )
            order_id = order.id
            log.info(f"  Attempt {attempt+1}: BUY LIMIT {opt_sym} @ {limit_px:.2f} (wait {wait}s)")
            time.sleep(wait)
            o = api.get_order(order_id)
            if o.status == "filled":
                fill = float(o.filled_avg_price)
                log.info(f"FILL   {sym:5s} {side:5s}  {opt_sym} @ {fill:.2f}")
                _place_oco_exits(sym, side, opt_sym, fill, qty)
                return
        except Exception as e:
            log.error(f"Entry order error {sym} attempt {attempt+1}: {e}")
            return
    # cancel after all attempts (spread exploded)
    if order_id:
        try: api.cancel_order(order_id)
        except Exception: pass
    log.warning(f"SKIP   {sym} {side} — unfilled after 15s, cancelled")


def _place_oco_exits(sym: str, side: str, opt_sym: str, fill: float, qty: int = 1):
    """Place sell limit (TP) + sell stop (SL) as two separate orders after fill."""
    tp_price = round(fill * TP_MULT, 2)
    sl_price = round(fill * SL_MULT, 2)
    log.info(f"EXIT   {sym:5s} {side:5s}  TP={tp_price:.2f}  SL={sl_price:.2f}")
    tp_id = None; sl_id = None
    try:
        tp_ord = api.submit_order(
            symbol=opt_sym, qty=qty, side="sell",
            type="limit", time_in_force="day",
            limit_price=str(tp_price),
        )
        tp_id = tp_ord.id
        log.info(f"  TP order placed: {tp_id}")
    except Exception as e:
        log.error(f"TP order error {sym}: {e}")
    try:
        sl_ord = api.submit_order(
            symbol=opt_sym, qty=qty, side="sell",
            type="stop", time_in_force="day",
            stop_price=str(sl_price),
        )
        sl_id = sl_ord.id
        log.info(f"  SL order placed: {sl_id}")
    except Exception as e:
        log.error(f"SL order error {sym}: {e}")
    # Always record position so dashboard shows active and monitor loop can manage exits
    with _lock:
        state[sym].position[side] = {
            "opt_sym":   opt_sym,
            "entry":     fill,
            "tp":        tp_price,
            "sl":        sl_price,
            "opened_at": datetime.now(TZ),
            "tp_id":     tp_id,
            "sl_id":     sl_id,
        }


# ── Fill/close tracking ────────────────────────────────────────────────────────

def on_exit_fill(sym: str, side: str, fill: float, won: bool):
    global daily_losses, bot_stopped
    with _lock:
        state[sym].position.pop(side, None)
        if won:
            state[sym].consec_loss = 0
            log.info(f"WIN    {sym:5s} {side:5s}  exit={fill:.2f}")
        else:
            state[sym].consec_loss += 1
            daily_losses           += 1
            log.info(f"LOSS   {sym:5s} {side:5s}  exit={fill:.2f}  streak={state[sym].consec_loss}")
            if state[sym].consec_loss >= MAX_LOSSES_SYM:
                state[sym].stopped = True
                log.warning(f"KILL   {sym} stopped ({MAX_LOSSES_SYM} consec losses)")
            if daily_losses >= MAX_DAILY_LOSS:
                bot_stopped = True
                log.warning(f"KILL   Bot stopped — {MAX_DAILY_LOSS} daily losses reached")


# ── Bar handler ────────────────────────────────────────────────────────────────

def handle_bar(sym: str, bar: dict):
    now_et = datetime.now(TZ)
    t      = now_et.strftime("%H:%M")
    s      = state[sym]

    if t == "09:00":
        s.cum_pv = s.cum_vol = 0.0
        s.bars = []; s.confirm = {}

    vwap        = update_vwap(s, bar)
    bar["vwap"] = vwap
    s.bars.append(bar)

    if bot_stopped or s.stopped:   return
    if len(s.bars) < 6:            return
    if t < "09:30":                return   # no signals before RTH open
    if t >= "15:55" and s.position:         # EOD force close
        try:
            api.submit_order(s.position["opt_sym"], CONTRACTS, "sell", "market", "day")
        except Exception as e:
            log.error(f"EOD close failed {sym}: {e}")
        with _lock:
            s.position.pop("long", None); s.position.pop("short", None)
        return
    if t >= "15:00":               return   # no new entries after 15:00

    prev = s.bars[-2]; curr = s.bars[-1]

    for side in ["long", "short"]:
        crossed = (
            prev["c"] < prev["vwap"] and curr["c"] > curr["vwap"]
        ) if side == "long" else (
            prev["c"] > prev["vwap"] and curr["c"] < curr["vwap"]
        )

        if crossed:
            s.confirm[side] = 1
            log.info(f"CROSS  {sym:5s} {side:5s}  {t}  px={curr['c']:.2f}  vwap={curr['vwap']:.2f}")
            continue

        if side in s.confirm:
            still_holding = (curr["c"] > curr["vwap"]) if side == "long" else (curr["c"] < curr["vwap"])
            if still_holding:
                s.confirm[side] += 1
            else:
                del s.confirm[side]; continue

            if s.confirm[side] >= CONFIRM_BARS:
                log.info(f"SIGNAL {sym:5s} {side:5s}  confirmed @ {curr['c']:.2f}")
                threading.Thread(
                    target=place_entry, args=(sym, side, curr["c"]), daemon=True
                ).start()
                del s.confirm[side]

    # push status to Supabase every bar
    pos_str      = ", ".join(f"{sd}@{p['entry']:.2f}" for sd, p in s.position.items())
    setup_active = len(s.position) > 0
    setup_close  = any(v >= CONFIRM_BARS - 1 for v in s.confirm.values())
    setup_watching = bool(s.confirm) and not setup_close
    metrics = f"VWAP: {curr['vwap']:.2f} | Price: {curr['c']:.2f}"
    if pos_str: metrics += f" | Position: {pos_str}"
    # show signal info if watching/close (confirm in progress)
    if s.confirm:
        sig_side = next(iter(s.confirm))
        sig_cnt  = s.confirm[sig_side]
        metrics += f" | Confirm: {sig_side.upper()} {sig_cnt}/{CONFIRM_BARS} @ {t}"
    threading.Thread(target=sb_push_status, args=([{
        "bot": "BOOF50", "symbol": sym,
        "setup_active": setup_active, "setup_close": setup_close,
        "setup_watching": setup_watching,
        "metrics": metrics, "updated_at": datetime.now(TZ).isoformat(),
    }],), daemon=True).start()

    # time exit
    for side, pos in list(s.position.items()):
        age = (now_et - pos["opened_at"]).seconds / 60
        if age >= MAX_HOLD_MIN:
            log.info(f"TIMEOUT {sym} {side} — market close after {age:.0f} min")
            try:
                api.submit_order(pos["opt_sym"], CONTRACTS, "sell", "market", "day")
            except Exception as e:
                log.error(f"Timeout close failed {sym}: {e}")
            with _lock:
                s.position.pop(side, None)


# ── Stream handlers ────────────────────────────────────────────────────────────

async def on_minute_bar(bar):
    sym = bar.symbol
    if sym in state:
        handle_bar(sym, {"o": bar.open, "h": bar.high, "l": bar.low, "c": bar.close, "v": bar.volume})


async def on_trade_update(update):
    if update.event not in ("fill", "partial_fill"): return
    order  = update.order
    # map option symbol back to underlying
    opt_sym = order["symbol"]
    fill    = float(order.get("filled_avg_price", 0))
    otype   = order.get("type", "")
    for sym, s in state.items():
        for side, pos in list(s.position.items()):
            if pos.get("opt_sym") == opt_sym:
                won = (otype == "limit")  # limit fill = TP hit; stop fill = SL hit
                on_exit_fill(sym, side, fill, won)
                return


# ── Daily reset ────────────────────────────────────────────────────────────────

def reset_daily():
    global daily_losses, bot_stopped
    with _lock:
        daily_losses = 0; bot_stopped = False
        for s in state.values():
            s.stopped = False; s.consec_loss = 0
            s.confirm = {}; s.cum_pv = s.cum_vol = 0.0; s.bars = []
    log.info("RESET  Daily state cleared")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    log.info(f"BOOF50 1DTE Options Bot  {'[PAPER]' if PAPER else '[LIVE]'}")
    log.info(f"Universe : {', '.join(SYMBOLS)}")
    log.info(f"Target premium ~${OPTION_TARGET:.2f}  TP={TP_MULT}x  SL={SL_MULT}x")
    log.info(f"MaxPos={MAX_POSITIONS}  MaxLosses/sym={MAX_LOSSES_SYM}  DailyStop={MAX_DAILY_LOSS}")

    while True:
        try:
            stream = Stream(API_KEY, API_SECRET, base_url=BASE_URL, data_feed="sip")
            stream.subscribe_bars(on_minute_bar, *SYMBOLS)
            stream.subscribe_updated_bars(on_minute_bar, *SYMBOLS)
            stream.subscribe_trade_updates(on_trade_update)
            log.info("Streaming — waiting for bars (incl. pre-market)...")
            stream.run()
        except Exception as e:
            log.error(f"Stream error: {e} — reconnecting in 60s")
            time.sleep(60)


if __name__ == "__main__":
    main()
