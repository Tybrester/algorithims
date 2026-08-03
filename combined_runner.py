"""
Combined runner for ORB + Fade strategies.
One TopstepX login, one WebSocket, both bots run in separate threads.
"""

import os
import sys
import time
import threading
import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from signalrcore.hub_connection_builder import HubConnectionBuilder

from boof_futures_live import BoofBot, TopstepClient, MARKET_HUB, TZ
from fade_scalp_live import FadeScalpBot

log_dir = r"C:\Users\tybre\Desktop\topstep logs"
os.makedirs(log_dir, exist_ok=True)
log_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, f"combined_runner_{log_ts}.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


def _load_credentials():
    if len(sys.argv) >= 3:
        return sys.argv[1], sys.argv[2]
    username = os.environ.get("PROJECT_X_USERNAME", "")
    api_key  = os.environ.get("PROJECT_X_API_KEY", "")
    if not username or not api_key:
        raise ValueError("Missing credentials: pass API_KEY USERNAME or set env vars")
    return api_key, username


class CombinedRunner:
    def __init__(self):
        self.api_key, self.username = _load_credentials()
        self.client = TopstepClient(self.username, self.api_key)
        self.boof = BoofBot(client=self.client, combined_mode=True)
        # Temporarily default disable_fade=True due to live trading issues
        self.disable_fade = os.environ.get("DISABLE_FADE", "true").lower() in ("1", "true", "yes")
        if self.disable_fade:
            log.info("Fade bot DISABLED — set DISABLE_FADE=false to re-enable")
            self.fade = None
        else:
            self.fade = FadeScalpBot(client=self.client, combined_mode=True)
        self._hub = None
        self._running = False
        self._threads = []

    def _setup_callbacks(self, hub):
        def _on_quote(data):
            try:
                self.boof._on_quote(data)
            except Exception as e:
                log.error(f"ORB quote error: {e}")
            if self.fade:
                try:
                    self.fade._on_quote(data)
                except Exception as e:
                    log.error(f"Fade quote error: {e}")

        def _on_logout(data):
            log.warning(f"GatewayLogout: {data}")
            self.boof._ws_closed = True
            if self.fade:
                self.fade._ws_closed = True

        def _on_close():
            log.warning("Shared WebSocket disconnected")
            self.boof._ws_closed = True
            if self.fade:
                self.fade._ws_closed = True

        hub.on("GatewayQuote", _on_quote)
        hub.on("GatewayTrade", _on_quote)
        hub.on("GatewayLogout", _on_logout)
        hub.on_close(_on_close)

    def _subscribe_all(self, hub):
        # ORB subscriptions
        try:
            self.boof._subscribe_contracts(hub)
        except Exception as e:
            log.error(f"ORB subscribe failed: {e}")
        # Fade subscription
        if self.fade:
            try:
                self.fade._subscribe_contract(hub)
            except Exception as e:
                log.error(f"Fade subscribe failed: {e}")

    def _connect_hub(self):
        if self._hub:
            try:
                self._hub.stop()
            except Exception:
                pass
        hub_url = f"{MARKET_HUB}?access_token={self.client.jwt_token}"
        self._hub = HubConnectionBuilder().with_url(hub_url).build()
        self._setup_callbacks(self._hub)
        self._hub.start()
        time.sleep(2)
        self._subscribe_all(self._hub)
        self.boof._ws_closed = False
        self.boof._last_quote_time = time.time()
        if self.fade:
            self.fade._ws_closed = False
            self.fade._last_quote_time = time.time()
        log.info("Shared hub connected and subscribed")

    def _reconnect(self):
        log.warning("[WS] Reconnecting shared market feed...")
        try:
            self.client.authenticate()
            self._connect_hub()
            log.info("[WS] Shared market feed reconnected")
        except Exception as e:
            log.error(f"[WS] Shared reconnect failed: {e}")

    def _bot_loop(self, bot, name):
        try:
            bot.run()
        except Exception as e:
            log.error(f"{name} bot crashed: {e}")

    def run(self):
        log.info("=" * 60)
        log.info("Starting COMBINED ORB + FADE runner")
        log.info("=" * 60)

        # Authenticate once
        self.client.authenticate()

        # Cross-strategy guard: cannot enter opposite direction if either strategy is in a position
        def overall_direction():
            for state in self.boof.states.values():
                if state.in_position:
                    return state.direction
            if self.fade and self.fade.state.trade.in_position:
                return self.fade.state.trade.direction
            return ""

        def can_enter(direction: str) -> bool:
            cur = overall_direction()
            return not cur or cur == direction

        self.boof._external_can_enter = can_enter
        if self.fade:
            self.fade._external_can_enter = can_enter

        # Start bot threads. Each bot does its own setup() and enters its main loop.
        # In combined_mode their websocket setup is a no-op; we provide the shared hub below.
        self._running = True
        t1 = threading.Thread(target=self._bot_loop, args=(self.boof, "ORB"), daemon=True)
        self._threads = [t1]
        t1.start()
        if self.fade:
            t2 = threading.Thread(target=self._bot_loop, args=(self.fade, "Fade"), daemon=True)
            self._threads.append(t2)
            t2.start()

        # Give bots a moment to resolve accounts/contracts
        time.sleep(4)

        # Start shared hub
        self._connect_hub()

        # Monitor and reconnect centrally
        last_heartbeat = 0
        try:
            while self._running:
                time.sleep(2)
                now = time.time()

                # Combined heartbeat every 60s
                if now - last_heartbeat >= 60:
                    last_heartbeat = now
                    orb_conn = "DISCONNECTED" if self.boof._ws_closed else "CONNECTED" if now - self.boof._last_quote_time < 15 else "STALE"

                    orb_pos = "flat"
                    for st in self.boof.states.values():
                        if st.in_position:
                            orb_pos = f"{st.direction.upper()} @ {st.entry_px:.2f}"
                            break
                    orb_pnl = sum(st.daily_pnl for st in self.boof.states.values())
                    orb_trades = sum(st.daily_trades for st in self.boof.states.values())

                    if self.fade:
                        fade_conn = "DISCONNECTED" if self.fade._ws_closed else "CONNECTED" if now - self.fade._last_quote_time < 15 else "STALE"
                        fade_trade = self.fade.state.trade
                        fade_pos = f"{fade_trade.direction.upper()} @ {fade_trade.entry_px:.2f}" if fade_trade.in_position else "flat"
                        fade_pnl = self.fade.state.daily_pnl
                        fade_trades = self.fade.state.daily_trades
                        combined_pnl = orb_pnl + fade_pnl
                        combined_trades = orb_trades + fade_trades
                        log.info(f"[HEARTBEAT] COMBINED pnl=${combined_pnl:+.0f} trades={combined_trades} | "
                                 f"ORB={orb_conn} trading={orb_pos} pnl=${orb_pnl:+.0f} trades={orb_trades} | "
                                 f"FADE={fade_conn} trading={fade_pos} pnl=${fade_pnl:+.0f} trades={fade_trades}")
                    else:
                        log.info(f"[HEARTBEAT] ORB={orb_conn} trading={orb_pos} pnl=${orb_pnl:+.0f} trades={orb_trades} | FADE=DISABLED")

                now_et = datetime.now(TZ)
                is_rth = dtime(9, 0) <= now_et.time() <= dtime(16, 30)

                needs_reconnect = self.boof._ws_closed or (self.fade._ws_closed if self.fade else False)
                if not needs_reconnect and is_rth:
                    stale = False
                    if self.boof._last_quote_time > 0 and time.time() - self.boof._last_quote_time > 120:
                        stale = True
                    if self.fade and self.fade._last_quote_time > 0 and time.time() - self.fade._last_quote_time > 120:
                        stale = True
                    if stale:
                        log.warning("[WS] Stale feed detected")
                        needs_reconnect = True

                if needs_reconnect:
                    self._reconnect()

                # Check thread health
                if not t1.is_alive():
                    log.error("ORB bot thread died")
                    self._running = False
                if self.fade and not t2.is_alive():
                    log.error("Fade bot thread died")
                    self._running = False
        except KeyboardInterrupt:
            log.info("KeyboardInterrupt — shutting down")
        finally:
            self._running = False
            self.boof._running = False
            if self.fade:
                self.fade._running = False
            if self._hub:
                try:
                    self._hub.stop()
                except Exception:
                    pass
            for t in self._threads:
                t.join(timeout=5)
            log.info("Combined runner stopped")


def main():
    runner = CombinedRunner()
    runner.run()


if __name__ == "__main__":
    main()
