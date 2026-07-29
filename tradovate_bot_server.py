#!/usr/bin/env python3
"""
TopstepX Bot Control Server — MULTI-TENANT
--------------------------------------------
Always-on Flask service that the BoofCapital dashboard talks to directly
(NOT through Supabase — Supabase Edge Functions can't hold a long-running
process or WebSocket connection, which the futures bot needs all day).

Each logged-in dashboard user gets their own isolated bot subprocess, runtime
config file, and log stream, keyed by their Supabase user id (`userId`) — so
many people can run the bot at once from the same server without stepping on
each other. TopstepX issues one username + API key per trading account, not
per platform, so each user submits their OWN username and API key from the
dashboard — this server never needs its own.

Deploy this once, anywhere reachable by everyone's browser (a small VPS,
Railway, Render, etc. — NOT your laptop, or it stops working when your PC is
off/asleep):

    pip install flask flask-cors
    python tradovate_bot_server.py

Then point the dashboard's RUNNER_URL (in dashboard.html) at that deployment's
public URL instead of http://localhost:8787.

Endpoints (all take/return JSON; userId is required on every call):
  POST /api/start      {userId, username, apiKey, baseSymbol, baseQty, lossSymbol, lossQty}
  POST /api/stop       {userId}
  POST /api/set-config {userId, baseSymbol, baseQty, lossSymbol, lossQty}  (live update, no restart)
  GET  /api/status?userId=...
  GET  /api/stream?userId=...  (Server-Sent Events — live stdout/stderr for that user's bot)
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# TEMPORARY: pointed at the lightweight connection-test bot while testing the
# dashboard panel. Switch to a TopstepX-native version of boof_futures_live.py
# before going live.
BOT_SCRIPT = os.path.join(BASE_DIR, "topstep_test_bot.py")
# Per-user runtime config files live here — one JSON file per userId so
# concurrent users' live qty/symbol updates never collide.
RUNTIME_CONFIG_DIR = os.path.join(BASE_DIR, "bot_runtime_configs")
os.makedirs(RUNTIME_CONFIG_DIR, exist_ok=True)
MAX_HISTORY = 500

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": [
    "https://boofcapital.com", "https://www.boofcapital.com",
    "http://localhost:3000", "http://127.0.0.1:5500",
    "http://localhost:5500", "http://127.0.0.1:3000",
    # Local dev preview tooling (e.g. IDE proxy ports) — origin varies per
    # session, so allow any localhost/127.0.0.1 port during local testing.
    re.compile(r"^https?://(localhost|127\.0\.0\.1):\d+$"),
]}})

# Optional fallback only — used if a user leaves their own username/API key
# blank (e.g. for the operator's own testing). Real users provide their own
# via the dashboard, since TopstepX issues these per trading account.
PX_USERNAME = os.environ.get("PROJECT_X_USERNAME", "")
PX_API_KEY  = os.environ.get("PROJECT_X_API_KEY", "")

# ── Per-user session state ──────────────────────────────────────────────────
# _sessions[user_id] = {
#   "process": subprocess.Popen | None,
#   "started_at": float | None,
#   "log_lines": [str, ...],
#   "log_lock": threading.Lock,
#   "subscribers": [queue.Queue, ...],
# }
_sessions_lock = threading.Lock()
_sessions = {}


def _safe_filename(user_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id)


def _config_path(user_id: str) -> str:
    return os.path.join(RUNTIME_CONFIG_DIR, f"{_safe_filename(user_id)}.json")


def _get_session(user_id: str) -> dict:
    with _sessions_lock:
        sess = _sessions.get(user_id)
        if sess is None:
            sess = {
                "process": None,
                "started_at": None,
                "log_lines": [],
                "log_lock": threading.Lock(),
                "subscribers": [],
            }
            _sessions[user_id] = sess
        return sess


def _broadcast(sess: dict, line: str):
    with sess["log_lock"]:
        sess["log_lines"].append(line)
        if len(sess["log_lines"]) > MAX_HISTORY:
            del sess["log_lines"][: len(sess["log_lines"]) - MAX_HISTORY]
        dead = []
        for q in sess["subscribers"]:
            try:
                q.put_nowait(line)
            except queue.Full:
                dead.append(q)
        for q in dead:
            sess["subscribers"].remove(q)


def _reader(sess: dict, proc: subprocess.Popen):
    for raw in iter(proc.stdout.readline, b""):
        try:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
        except Exception:
            line = str(raw)
        if line:
            _broadcast(sess, line)
    _broadcast(sess, "[server] Bot process exited.")
    sess["process"] = None


def _require_user_id(source) -> tuple:
    """Returns (user_id, error_response_or_None)."""
    user_id = source.get("userId")
    if not user_id or not isinstance(user_id, str):
        return None, (jsonify({"error": "Missing required field: userId"}), 400)
    return user_id, None


@app.route("/api/start", methods=["POST", "OPTIONS"])
def start_bot():
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(force=True, silent=True) or {}

    user_id, err = _require_user_id(body)
    if err:
        return err

    # TopstepX issues one username + API key per trading account (much
    # simpler than Tradovate's 5-credential model) — each user submits their
    # own from the dashboard. Only fall back to the runner's own env vars
    # (useful for the operator's personal testing) if left blank.
    user_username = body.get("username") or PX_USERNAME
    user_api_key  = body.get("apiKey") or PX_API_KEY
    if not user_username or not user_api_key:
        return jsonify({"error": "Missing TopstepX credentials: username and API key are required (from TopstepX \u2192 Settings \u2192 API Keys)."}), 400

    sess = _get_session(user_id)

    with _sessions_lock:
        if sess["process"] is not None and sess["process"].poll() is None:
            return jsonify({"error": "Bot is already running. Stop it first."}), 409

        env = dict(os.environ)
        env["PROJECT_X_USERNAME"] = user_username
        env["PROJECT_X_API_KEY"]  = user_api_key
        env["PYTHONUNBUFFERED"]   = "1"
        # Tell the bot process which per-user config file to poll.
        env["BOT_RUNTIME_CONFIG_PATH"] = _config_path(user_id)

        try:
            base_qty = max(1, int(body.get("baseQty", 1)))
        except (TypeError, ValueError):
            base_qty = 1
        try:
            loss_qty = max(1, int(body.get("lossQty", base_qty)))
        except (TypeError, ValueError):
            loss_qty = base_qty
        base_symbol = body.get("baseSymbol") if body.get("baseSymbol") in ("NQ", "MNQ") else "MNQ"
        loss_symbol = body.get("lossSymbol") if body.get("lossSymbol") in ("NQ", "MNQ") else base_symbol
        try:
            with open(_config_path(user_id), "w") as f:
                json.dump({
                    "baseSymbol": base_symbol, "baseQty": base_qty,
                    "lossSymbol": loss_symbol, "lossQty": loss_qty,
                }, f)
        except Exception:
            pass

        try:
            proc = subprocess.Popen(
                [sys.executable, BOT_SCRIPT],
                cwd=BASE_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except Exception as e:
            return jsonify({"error": f"Failed to launch bot: {e}"}), 500

        sess["process"] = proc
        sess["started_at"] = time.time()
        with sess["log_lock"]:
            sess["log_lines"].clear()
        _broadcast(sess, f"[server] Bot started pid={proc.pid}")

        t = threading.Thread(target=_reader, args=(sess, proc), daemon=True)
        t.start()

    return jsonify({"status": "started", "pid": proc.pid})


@app.route("/api/stop", methods=["POST", "OPTIONS"])
def stop_bot():
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(force=True, silent=True) or {}
    user_id, err = _require_user_id(body)
    if err:
        return err

    sess = _get_session(user_id)
    proc = sess["process"]
    if proc is None or proc.poll() is not None:
        return jsonify({"status": "not_running"})
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    sess["process"] = None
    _broadcast(sess, "[server] Bot stopped by user.")
    return jsonify({"status": "stopped"})


@app.route("/api/set-config", methods=["POST", "OPTIONS"])
def set_config():
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(force=True, silent=True) or {}
    user_id, err = _require_user_id(body)
    if err:
        return err

    base_symbol = body.get("baseSymbol")
    loss_symbol = body.get("lossSymbol")
    if base_symbol not in ("NQ", "MNQ") or loss_symbol not in ("NQ", "MNQ"):
        return jsonify({"error": "baseSymbol and lossSymbol must each be 'NQ' or 'MNQ'"}), 400
    try:
        base_qty = int(body.get("baseQty"))
        loss_qty = int(body.get("lossQty"))
    except (TypeError, ValueError):
        return jsonify({"error": "baseQty and lossQty must be integers"}), 400
    if base_qty < 1 or loss_qty < 1:
        return jsonify({"error": "baseQty and lossQty must be at least 1"}), 400

    try:
        with open(_config_path(user_id), "w") as f:
            json.dump({
                "baseSymbol": base_symbol, "baseQty": base_qty,
                "lossSymbol": loss_symbol, "lossQty": loss_qty,
            }, f)
    except Exception as e:
        return jsonify({"error": f"Failed to write config: {e}"}), 500
    sess = _get_session(user_id)
    _broadcast(sess, f"[server] Config updated: base={base_qty}x{base_symbol} loss={loss_qty}x{loss_symbol}")
    return jsonify({
        "status": "ok",
        "baseSymbol": base_symbol, "baseQty": base_qty,
        "lossSymbol": loss_symbol, "lossQty": loss_qty,
    })


@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    # No userId required — meant for external uptime pingers (e.g. UptimeRobot)
    # to keep this free-tier Render service from spinning down mid-trade.
    return jsonify({"status": "ok"})


@app.route("/api/status", methods=["GET"])
def status():
    user_id, err = _require_user_id(request.args)
    if err:
        return err
    sess = _get_session(user_id)
    proc = sess["process"]
    running = proc is not None and proc.poll() is None
    pid = proc.pid if running else None
    started_at = sess["started_at"] if running else None
    return jsonify({"running": running, "pid": pid, "started_at": started_at})


@app.route("/api/stream", methods=["GET"])
def stream():
    user_id, err = _require_user_id(request.args)
    if err:
        return err
    sess = _get_session(user_id)

    q = queue.Queue(maxsize=1000)
    with sess["log_lock"]:
        for line in sess["log_lines"]:
            q.put_nowait(line)
        sess["subscribers"].append(q)

    def gen():
        try:
            while True:
                try:
                    line = q.get(timeout=15)
                    yield f"data: {json.dumps(line)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with sess["log_lock"]:
                if q in sess["subscribers"]:
                    sess["subscribers"].remove(q)

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8787))
    print(f"Tradovate bot control server (multi-tenant) on http://0.0.0.0:{port}")
    print(f"Bot script: {BOT_SCRIPT}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
