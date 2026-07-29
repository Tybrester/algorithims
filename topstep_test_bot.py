"""
TopstepX connection test bot — TEMPORARY, for testing the dashboard's Futures
Bot panel/runner wiring without running the full NQ strategy bot
(boof_futures_live.py).

Authenticates against TopstepX using the same username + API key credential
model as boof_futures_live.py's TopstepClient (POST /api/Auth/loginKey), then
repeats a simple open/close round trip every INTERVAL_SECONDS: open (market
Buy or Sell) -> wait -> close (opposite market order, flat-to-flat) -> wait ->
repeat, alternating direction each round trip. Uses "base qty" contracts by
default; if the round trip that just closed lost money, the NEXT round trip
uses "loss qty" instead (same step-down-after-a-loss idea as
boof_futures_live.py, simplified to 1 trade of memory) — purely to exercise
order placement + live config updates end-to-end.

ALWAYS run this against a TopstepX evaluation/practice account, never a live
funded account, until you're confident in the wiring.

Swap tradovate_bot_server.py's BOT_SCRIPT to boof_futures_live.py (or a
TopstepX-native version of the real strategy) when you're done testing.
"""

import json
import os
import sys
import time

import httpx

API_URL = os.environ.get("PROJECT_X_API_URL", "https://api.topstepx.com")

USERNAME = os.environ.get("PROJECT_X_USERNAME", "")
API_KEY  = os.environ.get("PROJECT_X_API_KEY", "")

# Symbol choices exposed in the dashboard dropdown — searched via TopstepX's
# Contract/search endpoint, which resolves to the current front-month
# contract automatically (no manual roll needed, unlike Tradovate).
CONTRACT_SEARCH = {"NQ": "NQ", "MNQ": "MNQ"}
DEFAULT_SYMBOL_KEY = os.environ.get("TOPSTEP_TEST_SYMBOL", "MNQ")
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
        if raw.get("baseSymbol") in CONTRACT_SEARCH:
            cfg["baseSymbol"] = raw["baseSymbol"]
        cfg["baseQty"] = max(1, int(raw.get("baseQty", DEFAULT_QTY)))
        cfg["lossSymbol"] = raw["lossSymbol"] if raw.get("lossSymbol") in CONTRACT_SEARCH else cfg["baseSymbol"]
        cfg["lossQty"] = max(1, int(raw.get("lossQty", cfg["baseQty"])))
    except Exception:
        pass
    return cfg


def main():
    print("[TEST BOT] Starting TopstepX connection test...", flush=True)

    missing = [k for k, v in {
        "PROJECT_X_USERNAME": USERNAME, "PROJECT_X_API_KEY": API_KEY,
    }.items() if not v]
    if missing:
        print(f"[TEST BOT] Missing required env vars: {', '.join(missing)}", flush=True)
        sys.exit(1)

    client = httpx.Client(timeout=10)

    print("[TEST BOT] Authenticating...", flush=True)
    try:
        resp = client.post(f"{API_URL}/api/Auth/loginKey", json={
            "userName": USERNAME,
            "apiKey":   API_KEY,
        })
        data = resp.json()
    except Exception as e:
        print(f"[TEST BOT] Request failed: {e}", flush=True)
        sys.exit(1)

    if not data.get("success", False):
        print(f"[TEST BOT] Authentication FAILED: {data.get('errorMessage', data)}", flush=True)
        sys.exit(1)

    token = data.get("token")
    if not token:
        print(f"[TEST BOT] Authentication succeeded but no token received: {data}", flush=True)
        sys.exit(1)

    print("[TEST BOT] Authenticated OK", flush=True)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        accts_resp = client.post(f"{API_URL}/api/Account/search", headers=headers,
                                  json={"onlyActiveAccounts": True})
        accounts = accts_resp.json().get("accounts") or []
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

    contract_cache = {}

    def get_contract_id(symbol_key):
        if symbol_key in contract_cache:
            return contract_cache[symbol_key]
        try:
            resp = client.post(f"{API_URL}/api/Contract/search", headers=headers,
                                json={"searchText": CONTRACT_SEARCH.get(symbol_key, symbol_key), "live": False})
            contracts = resp.json().get("contracts") or []
            if not contracts:
                print(f"[TEST BOT] No contract found for: {symbol_key}", flush=True)
                return None
            contract_id = contracts[0]["id"]
            contract_cache[symbol_key] = contract_id
            return contract_id
        except Exception as e:
            print(f"[TEST BOT] Contract search failed for {symbol_key}: {e}", flush=True)
            return None

    def place_order(side, qty, contract_id):
        # side: 0=Buy, 1=Sell (TopstepX convention)
        try:
            resp = client.post(f"{API_URL}/api/Order/place", headers=headers, json={
                "accountId":  account_id,
                "contractId": contract_id,
                "type":       2,   # 2 = Market
                "side":       side,
                "size":       qty,
            })
            data = resp.json() if resp.content else {}
            if resp.status_code != 200 or not data.get("success", True):
                print(f"[TEST BOT] {'Buy' if side == 0 else 'Sell'} x{qty} order FAILED: {data}", flush=True)
                return None
            order_id = data.get("orderId")
            print(f"[TEST BOT] {'Buy' if side == 0 else 'Sell'} x{qty} order placed OK — orderId={order_id}", flush=True)
            return order_id
        except Exception as e:
            print(f"[TEST BOT] Order request error: {e}", flush=True)
            return None

    def get_fill_price(account_id, contract_id, retries=5, delay=1):
        for _ in range(retries):
            try:
                resp = client.post(f"{API_URL}/api/Position/search", headers=headers,
                                    json={"accountId": account_id})
                if resp.status_code == 200:
                    positions = resp.json().get("positions") or []
                    for p in positions:
                        if p.get("contractId") == contract_id:
                            return p.get("averagePrice")
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

    print(f"[TEST BOT] Starting open/close round-trip loop every {INTERVAL_SECONDS}s (Stop to end)...", flush=True)
    cfg = get_config()
    print(f"[TEST BOT] Config: base={cfg['baseQty']}x{cfg['baseSymbol']} loss={cfg['lossQty']}x{cfg['lossSymbol']}", flush=True)

    def log_cfg_change(new_cfg):
        print(f"[TEST BOT] Config updated: base={new_cfg['baseQty']}x{new_cfg['baseSymbol']} loss={new_cfg['lossQty']}x{new_cfg['lossSymbol']}", flush=True)

    side = 0  # 0 = Buy
    next_qty_is_loss = False
    try:
        while True:
            cfg = get_config()
            if next_qty_is_loss:
                symbol_key, qty = cfg["lossSymbol"], cfg["lossQty"]
            else:
                symbol_key, qty = cfg["baseSymbol"], cfg["baseQty"]

            contract_id = get_contract_id(symbol_key)
            if contract_id is None:
                print("[TEST BOT] Skipping round trip — no contract resolved.", flush=True)
                sleep_and_watch(INTERVAL_SECONDS, log_cfg_change)
                continue

            open_order_id = place_order(side, qty, contract_id)
            entry_price = get_fill_price(account_id, contract_id) if open_order_id else None

            sleep_and_watch(INTERVAL_SECONDS, log_cfg_change)

            close_side = 1 if side == 0 else 0
            close_order_id = place_order(close_side, qty, contract_id)
            exit_price = get_fill_price(account_id, contract_id) if close_order_id else None

            if entry_price is not None and exit_price is not None:
                direction = 1 if side == 0 else -1
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
