"""
Tradovate connection test bot — TEMPORARY, for testing the dashboard's
Futures Bot panel/runner wiring without running the full NQ strategy bot.

Authenticates against Tradovate using the same credentials/env vars as
NQ_Tradovate_Copy.py, then repeats a simple open/close round trip every
INTERVAL_SECONDS: open (market Buy or Sell) -> wait -> close (opposite
market order, flat-to-flat) -> wait -> repeat, alternating direction each
round trip. Uses "base qty" contracts by default; if the round trip that
just closed lost money, the NEXT round trip uses "loss qty" instead (same
step-down-after-a-loss idea as NQ_Tradovate_Copy.py, simplified to 1 trade
of memory) — purely to exercise order placement + live config updates
end-to-end. ALWAYS run this on TRADOVATE_ENV=demo.

Swap tradovate_bot_server.py's BOT_SCRIPT back to NQ_Tradovate_Copy.py
when you're done testing.
"""

import json
import os
import sys
import time

import httpx

TRADOVATE_ENV = os.environ.get("TRADOVATE_ENV", "demo").lower()
API_URL = (
    "https://live.tradovateapi.com/v1"
    if TRADOVATE_ENV == "live"
    else "https://demo.tradovateapi.com/v1"
)

USERNAME    = os.environ.get("TRADOVATE_USERNAME", "")
PASSWORD    = os.environ.get("TRADOVATE_PASSWORD", "")
APP_ID      = os.environ.get("TRADOVATE_APP_ID", "")
APP_VERSION = os.environ.get("TRADOVATE_APP_VERSION", "1.0.0")
CID         = os.environ.get("TRADOVATE_CID", "")
SEC         = os.environ.get("TRADOVATE_SEC", "")
DEVICE_ID   = os.environ.get("TRADOVATE_DEVICE_ID", "test-bot")

# Symbol choices exposed in the dashboard dropdown. Verify these match
# Tradovate's current front-month symbol format (/contract/suggest?t=MNQ or ?t=NQ)
# — futures contract codes roll over quarterly.
CONTRACT_MAP = {"NQ": "NQU26", "MNQ": "MNQU26"}
DEFAULT_SYMBOL_KEY = os.environ.get("TRADOVATE_TEST_SYMBOL", "MNQ")
DEFAULT_QTY = 1
INTERVAL_SECONDS = 5 * 60

# Set by tradovate_bot_server.py to a per-user config file — polled each loop
# iteration so the dashboard's fields can update THIS user's running bot
# without a restart, without colliding with other users' bots.
RUNTIME_CONFIG_PATH = os.environ.get(
    "BOT_RUNTIME_CONFIG_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_runtime_config.json"),
)


def get_config():
    cfg = {
        "baseSymbol": DEFAULT_SYMBOL_KEY, "baseQty": DEFAULT_QTY,
        "lossSymbol": DEFAULT_SYMBOL_KEY, "lossQty": DEFAULT_QTY,
    }
    try:
        with open(RUNTIME_CONFIG_PATH, "r") as f:
            raw = json.load(f)
        if raw.get("baseSymbol") in CONTRACT_MAP:
            cfg["baseSymbol"] = raw["baseSymbol"]
        cfg["baseQty"] = max(1, int(raw.get("baseQty", DEFAULT_QTY)))
        cfg["lossSymbol"] = raw["lossSymbol"] if raw.get("lossSymbol") in CONTRACT_MAP else cfg["baseSymbol"]
        cfg["lossQty"] = max(1, int(raw.get("lossQty", cfg["baseQty"])))
    except Exception:
        pass
    return cfg


def main():
    print(f"[TEST BOT] Starting Tradovate connection test ({TRADOVATE_ENV})...", flush=True)

    missing = [k for k, v in {
        "TRADOVATE_USERNAME": USERNAME, "TRADOVATE_PASSWORD": PASSWORD,
        "TRADOVATE_APP_ID": APP_ID, "TRADOVATE_CID": CID, "TRADOVATE_SEC": SEC,
    }.items() if not v]
    if missing:
        print(f"[TEST BOT] Missing required env vars: {', '.join(missing)}", flush=True)
        sys.exit(1)

    client = httpx.Client(timeout=10)

    print("[TEST BOT] Authenticating...", flush=True)
    try:
        resp = client.post(f"{API_URL}/auth/accesstokenrequest", json={
            "name":       USERNAME,
            "password":   PASSWORD,
            "appId":      APP_ID,
            "appVersion": APP_VERSION,
            "cid":        CID,
            "sec":        SEC,
            "deviceId":   DEVICE_ID,
        })
        data = resp.json()
    except Exception as e:
        print(f"[TEST BOT] Request failed: {e}", flush=True)
        sys.exit(1)

    token = data.get("accessToken")
    if not token:
        print(f"[TEST BOT] Authentication FAILED: {data}", flush=True)
        sys.exit(1)

    print(f"[TEST BOT] Authenticated OK — userId={data.get('userId')}", flush=True)

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        accts_resp = client.get(f"{API_URL}/account/list", headers=headers)
        accounts = accts_resp.json() or []
        print(f"[TEST BOT] Found {len(accounts)} account(s):", flush=True)
        for a in accounts:
            print(f"[TEST BOT]   - id={a.get('id')} name={a.get('name')}", flush=True)
    except Exception as e:
        print(f"[TEST BOT] Failed to fetch accounts: {e}", flush=True)
        sys.exit(1)

    if not accounts:
        print("[TEST BOT] No accounts found — cannot place orders.", flush=True)
        sys.exit(1)
    account_id = accounts[0]["id"]
    account_name = accounts[0].get("name", USERNAME)

    def place_order(action, qty, symbol):
        try:
            resp = client.post(f"{API_URL}/order/placeorder", headers=headers, json={
                "accountSpec": account_name,
                "accountId":   account_id,
                "action":      action,
                "symbol":      symbol,
                "orderQty":    qty,
                "orderType":   "Market",
                "isAutomated": True,
            })
            data = resp.json() if resp.content else {}
            if resp.status_code != 200 or data.get("failureReason"):
                print(f"[TEST BOT] {action} x{qty} {symbol} order FAILED: {data.get('failureText') or data.get('failureReason') or resp.status_code}", flush=True)
                return None
            order_id = data.get("orderId")
            print(f"[TEST BOT] {action} x{qty} {symbol} order placed OK — orderId={order_id}", flush=True)
            return order_id
        except Exception as e:
            print(f"[TEST BOT] {action} x{qty} {symbol} order request error: {e}", flush=True)
            return None

    def get_fill_price(order_id, retries=5, delay=1):
        if order_id is None:
            return None
        for _ in range(retries):
            try:
                resp = client.get(f"{API_URL}/fill/list", headers=headers)
                fills = [f for f in (resp.json() or []) if f.get("orderId") == order_id]
                if fills:
                    total_qty = sum(f.get("qty", 0) for f in fills) or 1
                    return sum(f.get("price", 0) * f.get("qty", 0) for f in fills) / total_qty
            except Exception:
                pass
            time.sleep(delay)
        return None

    def sleep_and_watch(seconds, on_change):
        """Sleep in small chunks, calling on_change(new_cfg) whenever config changes."""
        cfg_before = get_config()
        slept = 0
        while slept < seconds:
            time.sleep(min(10, seconds - slept))
            slept += 10
            cfg_now = get_config()
            if cfg_now != cfg_before:
                on_change(cfg_now)
                cfg_before = cfg_now

    print(f"[TEST BOT] Starting open/close round-trip loop every {INTERVAL_SECONDS}s (Ctrl+C / Stop to end)...", flush=True)
    cfg = get_config()
    print(f"[TEST BOT] Config: base={cfg['baseQty']}x{cfg['baseSymbol']} loss={cfg['lossQty']}x{cfg['lossSymbol']}", flush=True)

    def log_cfg_change(new_cfg):
        print(f"[TEST BOT] Config updated: base={new_cfg['baseQty']}x{new_cfg['baseSymbol']} loss={new_cfg['lossQty']}x{new_cfg['lossSymbol']}", flush=True)

    side = "Buy"
    next_qty_is_loss = False
    try:
        while True:
            cfg = get_config()
            if next_qty_is_loss:
                symbol = CONTRACT_MAP.get(cfg["lossSymbol"], CONTRACT_MAP["MNQ"])
                qty = cfg["lossQty"]
            else:
                symbol = CONTRACT_MAP.get(cfg["baseSymbol"], CONTRACT_MAP["MNQ"])
                qty = cfg["baseQty"]

            open_order_id = place_order(side, qty, symbol)
            entry_price = get_fill_price(open_order_id)

            sleep_and_watch(INTERVAL_SECONDS, log_cfg_change)

            close_side = "Sell" if side == "Buy" else "Buy"
            close_order_id = place_order(close_side, qty, symbol)
            exit_price = get_fill_price(close_order_id)

            if entry_price is not None and exit_price is not None:
                direction = 1 if side == "Buy" else -1
                pnl = (exit_price - entry_price) * direction * qty
                result = "LOSS" if pnl < 0 else "WIN"
                print(f"[TEST BOT] Round trip {result}: entry={entry_price} exit={exit_price} pnl={pnl:.2f}", flush=True)
                next_qty_is_loss = pnl < 0
            else:
                print("[TEST BOT] Could not determine fill prices for this round trip — using base qty next.", flush=True)
                next_qty_is_loss = False

            side = close_side
            sleep_and_watch(INTERVAL_SECONDS, log_cfg_change)
    except KeyboardInterrupt:
        print("[TEST BOT] Stopped.", flush=True)


if __name__ == "__main__":
    main()
