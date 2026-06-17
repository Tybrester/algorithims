with open("boof51_live.py", "r") as f:
    src = f.read()

old = '''def _close_put(s: SymState, reason: str):
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
        s.opt_position = None'''

new = '''def _close_put(s: SymState, reason: str):
    """Market-sell the put to close options leg. Falls back to limit if market rejected."""
    if s.opt_position is None:
        return
    opt_sym = s.opt_position["opt_sym"]
    qty     = s.opt_position["qty"]
    closed  = False
    try:
        api.submit_order(symbol=opt_sym, qty=qty, side="sell", type="market", time_in_force="day")
        log.info(f"OPT {s.sym}: CLOSE PUT {opt_sym} MARKET  reason={reason}")
        closed = True
    except Exception as e:
        log.warning(f"OPT {s.sym}: market close failed ({e}) -- trying limit fallback")
    if not closed:
        try:
            api.submit_order(symbol=opt_sym, qty=qty, side="sell", type="limit",
                             limit_price="0.01", time_in_force="day")
            log.info(f"OPT {s.sym}: CLOSE PUT {opt_sym} LIMIT $0.01  reason={reason}")
        except Exception as e2:
            log.error(f"OPT {s.sym}: put close FAILED both methods -- {e2}")
    with _lock:
        s.opt_position = None'''

if old in src:
    src = src.replace(old, new)
    with open("boof51_live.py", "w") as f:
        f.write(src)
    print("PATCHED OK")
else:
    print("NOT FOUND")
