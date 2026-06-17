with open("boof51_live.py", "r") as f:
    src = f.read()

old = '''    if s.sym in HIGH_VOL_SYMS:
        prices = [
            (round(mid, 2),                15),  # mid, 15s
            (round(mid + 0.50 * spread, 2), 15),  # mid+50%, 15s then cancel
        ]
    else:
        prices = [
            (round(bid + 0.10 * spread, 2), 30),  # near bid, 30s then cancel
        ]'''

new = '''    # mid → 5s → mid+25% → 25s → market
    prices = [
        (round(mid, 2),                        5),   # mid, wait 5s
        (round(mid + 0.25 * spread, 2),       25),   # mid+25%, wait 25s
    ]'''

if old in src:
    src = src.replace(old, new)
    # Also fix the fallback after all attempts to use market order
    old2 = '''    # cancel after all attempts (spread exploded)
    if order_id:
        try: api.cancel_order(order_id)
        except Exception: pass
    log.warning(f"OPT {s.sym}: put unfilled after 15s — cancelled")'''

    new2 = '''    # All limit attempts failed — fall back to market order
    if order_id:
        try: api.cancel_order(order_id)
        except Exception: pass
    log.warning(f"OPT {s.sym}: limits unfilled — falling back to market order")
    try:
        order = api.submit_order(
            symbol=opt_sym, qty=contracts, side="buy",
            type="market", time_in_force="day",
        )
        time.sleep(2)
        o = api.get_order(order.id)
        fill = float(o.filled_avg_price) if o.filled_avg_price else 0
        log.info(f"OPT {s.sym}: PUT MARKET FILLED {opt_sym} x{contracts} @ {fill:.2f}")
        with _lock:
            s.opt_position = {"opt_sym": opt_sym, "qty": contracts, "entry_fill": fill, "order_id": order.id}
    except Exception as e:
        log.error(f"OPT {s.sym}: market fallback failed — {e}")'''

    if old2 in src:
        src = src.replace(old2, new2)
        print("BOTH PATCHES OK")
    else:
        print("PATCH 1 OK, fallback block not found")
    with open("boof51_live.py", "w") as f:
        f.write(src)
else:
    print("PATCH 1 NOT FOUND")
