"""
fix_daily_pnl.py
────────────────
End-of-day P&L correction script.

For every CLOSED trade today, recalculate P&L using the bot's
configured TP/SL instead of whatever the live exit recorded.

Logic:
  - If exit_type == 'tp'  → pnl = total_cost * (tp_pct / 100)
  - If exit_type == 'sl'  → pnl = total_cost * (sl_pct / 100)   (negative)
  - If exit_type == 'manual' or unknown → skip (can't determine direction)

Usage:
  python fix_daily_pnl.py

Set your Supabase credentials below or use env vars.
"""

import os
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# ─── CONFIG ────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://isanhutzyctcjygjhzbn.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")  # service role key

# Override TP/SL here if you want to force a specific value across ALL trades.
# Set to None to use each trade's stored take_profit_pct / stop_loss_pct from the DB.
OVERRIDE_TP_PCT = None   # e.g. 40  → force +40% TP on all wins
OVERRIDE_SL_PCT = None   # e.g. -10 → force -10% SL on all losses

DRY_RUN = True  # Set to False to actually write to DB
# ────────────────────────────────────────────────────────────


def main():
    if not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_SERVICE_KEY env var or paste it into the script.")
        return

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Fetch all closed trades from today
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end   = today_start + timedelta(days=1)

    print(f"\nFetching closed trades from {today_start.date()} ...")

    resp = supabase.table("options_trades") \
        .select("id, symbol, bot_id, total_cost, entry_price, contracts, premium_per_contract, take_profit_pct, stop_loss_pct, pnl, status, exit_type, closed_at, signal_version") \
        .eq("status", "closed") \
        .gte("closed_at", today_start.isoformat()) \
        .lt("closed_at", today_end.isoformat()) \
        .execute()

    trades = resp.data or []
    print(f"Found {len(trades)} closed trades today.\n")

    if not trades:
        print("Nothing to fix.")
        return

    fixed = 0
    skipped = 0
    updates = []

    for t in trades:
        trade_id    = t["id"]
        symbol      = t["symbol"]
        total_cost  = float(t["total_cost"] or 0)
        old_pnl     = t["pnl"]
        exit_type   = (t.get("exit_type") or "").lower()
        tp_pct      = float(OVERRIDE_TP_PCT if OVERRIDE_TP_PCT is not None else (t.get("take_profit_pct") or 35))
        sl_pct      = float(OVERRIDE_SL_PCT if OVERRIDE_SL_PCT is not None else (t.get("stop_loss_pct") or -10))

        # Ensure sl_pct is negative
        if sl_pct > 0:
            sl_pct = -sl_pct

        if exit_type == "tp":
            new_pnl = round(total_cost * (tp_pct / 100), 2)
        elif exit_type in ("sl", "stop_loss", "stop"):
            new_pnl = round(total_cost * (sl_pct / 100), 2)
        else:
            print(f"  SKIP  {symbol} id={trade_id} — exit_type='{exit_type}' (unknown, skipping)")
            skipped += 1
            continue

        if round(float(old_pnl or 0), 2) == new_pnl:
            print(f"  OK    {symbol} id={trade_id} — pnl already correct: ${new_pnl}")
            continue

        print(f"  FIX   {symbol} id={trade_id} | exit={exit_type} | old_pnl=${old_pnl} → new_pnl=${new_pnl}  (tp={tp_pct}% sl={sl_pct}%)")
        updates.append({"id": trade_id, "pnl": new_pnl})
        fixed += 1

    print(f"\n{'[DRY RUN] ' if DRY_RUN else ''}Summary: {fixed} trades to fix, {skipped} skipped.\n")

    if not DRY_RUN and updates:
        for u in updates:
            supabase.table("options_trades").update({"pnl": u["pnl"]}).eq("id", u["id"]).execute()
            print(f"  Updated trade {u['id']} → pnl=${u['pnl']}")
        print(f"\nDone. {fixed} trades corrected.")
    elif DRY_RUN:
        print("DRY RUN complete — no changes written. Set DRY_RUN = False to apply.")


if __name__ == "__main__":
    main()
