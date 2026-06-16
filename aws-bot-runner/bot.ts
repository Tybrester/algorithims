// ═══════════════════════════════════════════════════════════════════
//  Boof Capital — AWS EC2 Live Bot Runner
//  Deploys to: EC2 t3.nano/t4g.nano in us-east-1 (same AZ as Alpaca)
//  Runtime: Node.js + ts-node + PM2
//  Replaces: Supabase pg_cron + Edge Function cold starts
// ═══════════════════════════════════════════════════════════════════

import * as dotenv from 'dotenv';
dotenv.config();

import { createClient } from '@supabase/supabase-js';
// Polyfill WebSocket for Supabase realtime on Node 20
import WS from 'ws';
if (typeof (globalThis as any).WebSocket === 'undefined') {
  (globalThis as any).WebSocket = WS;
}

import { getBoof22Signal } from './src/signals/boof22';
import { getBoof23Signal } from './src/signals/boof23';
import { getBoof25Signal } from './src/signals/boof25';
import { getBoof55Signal, BOOF55_UNIVERSE } from './src/signals/boof55';

// ─────────────────────────────────────────────
// CLIENTS
// ─────────────────────────────────────────────
const supabase = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_KEY!   // service role key
);

const ALPACA_KEY    = process.env.ALPACA_KEY!;
const ALPACA_SECRET = process.env.ALPACA_SECRET!;
const IS_PAPER      = process.env.ALPACA_PAPER === 'true';

const BASE_URL  = IS_PAPER ? 'https://paper-api.alpaca.markets' : 'https://api.alpaca.markets';
const DATA_URL  = 'https://data.alpaca.markets';

// ─────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────
const SLIPPAGE_BUFFER = 0.02;
const LIMIT_TIMEOUT_MS = 5000;
const R = 0.05;

// Dynamically built from active bot configs after Supabase load
let WATCH_SYMBOLS: string[] = [];

// ─────────────────────────────────────────────
// CANDLE CACHE  (rolling 150-bar window per symbol, 1m bars)
// ─────────────────────────────────────────────
interface Candle {
  time: number; open: number; high: number; low: number; close: number; volume: number;
}
const candleCache: Map<string, Candle[]> = new Map();
const MAX_CANDLES = 150;

// ─────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────
function alpacaHeaders() {
  return {
    'APCA-API-KEY-ID': ALPACA_KEY,
    'APCA-API-SECRET-KEY': ALPACA_SECRET,
    'Content-Type': 'application/json',
  };
}

// ── Smart limit order: mid → mid+25%spread → ask ────────────────────────────
async function placeLimitOrder(symbol: string, qty: number, side: 'buy'|'sell'): Promise<{ ok: boolean; orderId?: string; fillPrice?: number }> {
  const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

  // Fetch live quote
  const qRes = await fetch(`${DATA_URL}/v2/stocks/${symbol}/quotes/latest?feed=iex`, { headers: alpacaHeaders() });
  const qJson: any = await qRes.json();
  const bid = parseFloat(qJson?.quote?.bp ?? qJson?.quote?.bid_price ?? '0');
  const ask = parseFloat(qJson?.quote?.ap ?? qJson?.quote?.ask_price ?? '0');

  if (!bid || !ask || ask <= bid) {
    console.log(`[LimitOrder] ${symbol}: bad quote bid=${bid} ask=${ask}, falling back to market`);
    const mRes = await fetch(`${BASE_URL}/v2/orders`, {
      method: 'POST', headers: alpacaHeaders(),
      body: JSON.stringify({ symbol, qty: String(qty), side, type: 'market', time_in_force: 'day' }),
    });
    return { ok: mRes.ok };
  }

  const spread  = ask - bid;
  const mid     = parseFloat((bid + spread / 2).toFixed(2));
  const midPlus = parseFloat((mid + spread * 0.25).toFixed(2));
  const askLim  = parseFloat(ask.toFixed(2));

  const tryLimit = async (price: number, label: string): Promise<string | null> => {
    console.log(`[LimitOrder] ${symbol}: ${label} limit @ $${price.toFixed(2)} qty=${qty}`);
    const res = await fetch(`${BASE_URL}/v2/orders`, {
      method: 'POST', headers: alpacaHeaders(),
      body: JSON.stringify({ symbol, qty: String(qty), side, type: 'limit', limit_price: price.toFixed(2), time_in_force: 'day', extended_hours: false }),
    });
    const j: any = await res.json();
    if (!res.ok) { console.error(`[LimitOrder] ${symbol}: ${label} rejected:`, j.message); return null; }
    return j.id;
  };

  const cancelOrder = async (id: string) => {
    await fetch(`${BASE_URL}/v2/orders/${id}`, { method: 'DELETE', headers: alpacaHeaders() });
  };

  const checkFilled = async (id: string): Promise<boolean> => {
    const res = await fetch(`${BASE_URL}/v2/orders/${id}`, { headers: alpacaHeaders() });
    const j: any = await res.json();
    return j.status === 'filled' || j.status === 'partially_filled';
  };

  // Step 1: try mid
  let orderId = await tryLimit(mid, 'mid');
  if (!orderId) return { ok: false };
  await sleep(10000); // wait 10s
  if (await checkFilled(orderId)) { console.log(`[LimitOrder] ${symbol}: filled at mid $${mid}`); return { ok: true, orderId, fillPrice: mid }; }

  // Step 2: cancel and try mid + 25% spread
  await cancelOrder(orderId);
  await sleep(500);
  orderId = await tryLimit(midPlus, 'mid+25%');
  if (!orderId) return { ok: false };
  await sleep(20000); // wait 20s
  if (await checkFilled(orderId)) { console.log(`[LimitOrder] ${symbol}: filled at mid+25% $${midPlus}`); return { ok: true, orderId, fillPrice: midPlus }; }

  // Step 3: cancel and go ask
  await cancelOrder(orderId);
  await sleep(500);
  orderId = await tryLimit(askLim, 'ask');
  if (!orderId) return { ok: false };
  console.log(`[LimitOrder] ${symbol}: last resort ask $${askLim}`);
  return { ok: true, orderId, fillPrice: askLim };
}

async function fetchCandles(symbol: string, timeframe: string, limit = 150): Promise<Candle[]> {
  const tf = timeframe.replace(/^(\d+)m$/, '$1Min').replace(/^(\d+)h$/, '$1Hour');
  const url = `${DATA_URL}/v2/stocks/${symbol}/bars?timeframe=${tf}&limit=${limit}&adjustment=raw&feed=sip`;
  const res = await fetch(url, { headers: alpacaHeaders() });
  if (!res.ok) return [];
  const json: any = await res.json();
  return (json.bars || []).map((b: any) => ({
    time: new Date(b.t).getTime(), open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v,
  }));
}

async function fetchInitialCandles(symbol: string): Promise<void> {
  const url = `${DATA_URL}/v2/stocks/${symbol}/bars?timeframe=1Min&limit=${MAX_CANDLES}&adjustment=raw&feed=sip`;
  const res = await fetch(url, { headers: alpacaHeaders() });
  if (!res.ok) { console.error(`[Init] Failed to fetch candles for ${symbol}: ${res.status}`); return; }
  const json: any = await res.json();
  const bars: Candle[] = (json.bars || []).map((b: any) => ({
    time: new Date(b.t).getTime(), open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v,
  }));
  candleCache.set(symbol, bars);
  console.log(`[Init] Loaded ${bars.length} candles for ${symbol}`);
}

function pushCandle(symbol: string, c: Candle): void {
  const arr = candleCache.get(symbol) ?? [];
  arr.push(c);
  if (arr.length > MAX_CANDLES) arr.shift();
  candleCache.set(symbol, arr);
}

function formatOptionSymbol(symbol: string, expDate: string, type: 'call'|'put', strike: number): string {
  const d = new Date(expDate);
  const yy = String(d.getUTCFullYear()).slice(2);
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(d.getUTCDate()).padStart(2, '0');
  const K = String(Math.round(strike * 1000)).padStart(8, '0');
  const formatted = `${symbol}${yy}${mm}${dd}${type === 'call' ? 'C' : 'P'}${K}`;
  console.log(`[FormatSymbol] Input: ${symbol} ${expDate} ${type} $${strike} → Output: ${formatted}`);
  return formatted;
}

function nearestFriday(): string {
  const et = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }));
  const day = et.getDay();
  const daysUntilFri = (5 - day + 7) % 7 || 7;
  et.setDate(et.getDate() + daysUntilFri);
  return et.toISOString().slice(0, 10);
}

function nextTradingDay(): string {
  const et = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }));
  et.setDate(et.getDate() + 1);
  // Skip Saturday (6) -> Monday, Sunday (0) -> Monday
  if (et.getDay() === 6) et.setDate(et.getDate() + 2);
  if (et.getDay() === 0) et.setDate(et.getDate() + 1);
  return et.toISOString().slice(0, 10);
}

function thirdFriday(): string {
  const et = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }));
  const year = et.getFullYear();
  const month = et.getMonth();
  // Find first Friday of month
  const firstDay = new Date(year, month, 1);
  let firstFriday = 1 + ((5 - firstDay.getDay() + 7) % 7);
  // Third Friday is first Friday + 14 days
  const thirdFriday = firstFriday + 14;
  const expDate = new Date(year, month, thirdFriday);
  return expDate.toISOString().slice(0, 10);
}

function pickStrike(spot: number, type: 'call'|'put', atr: number): number {
  // Start ATM — round spot to nearest strike interval
  // Only walk OTM later if ATM is too expensive for budget
  const rawStrike = spot;
  // Round to valid strike intervals
  // - Stocks > $500: $5 intervals (LLY, etc)
  // - Stocks $50-$500: $2.50 intervals (AAPL, MSFT, etc)
  // - Stocks < $50: $1 intervals
  let interval: number;
  if (spot > 500) interval = 5;
  else if (spot > 50) interval = 2.5;
  else interval = 1;
  const rounded = Math.round(rawStrike / interval) * interval;
  return rounded;
}

function blackScholes(S: number, K: number, T: number, r: number, sigma: number, type: 'call'|'put'): number {
  if (T <= 0 || sigma <= 0) return Math.max(0.01, type === 'call' ? S - K : K - S);
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T));
  const d2 = d1 - sigma * Math.sqrt(T);
  const N = (x: number) => {
    const a1=0.254829592, a2=-0.284496736, a3=1.421413741, a4=-1.453152027, a5=1.061405429, p=0.3275911;
    const sign = x < 0 ? -1 : 1; const ax = Math.abs(x);
    const t = 1 / (1 + p * ax);
    return 0.5 * (1 + sign * (1 - (((((a5*t+a4)*t)+a3)*t+a2)*t+a1)*t*Math.exp(-ax*ax/2)));
  };
  return type === 'call'
    ? S * N(d1) - K * Math.exp(-r * T) * N(d2)
    : K * Math.exp(-r * T) * N(-d2) - S * N(-d1);
}

function calcADX(candles: Candle[], period = 14): number {
  if (candles.length < period + 1) return 25;
  const trueRanges: number[] = [];
  const plusDM:  number[] = [];
  const minusDM: number[] = [];
  for (let i = 1; i < candles.length; i++) {
    const high = candles[i].high, low = candles[i].low;
    const prevHigh = candles[i-1].high, prevLow = candles[i-1].low, prevClose = candles[i-1].close;
    trueRanges.push(Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose)));
    const upMove = high - prevHigh;
    const downMove = prevLow - low;
    plusDM.push(upMove > downMove && upMove > 0 ? upMove : 0);
    minusDM.push(downMove > upMove && downMove > 0 ? downMove : 0);
  }
  const smooth = (arr: number[]) => {
    let val = arr.slice(0, period).reduce((a, b) => a + b, 0);
    const out = [val];
    for (let i = period; i < arr.length; i++) { val = val - val / period + arr[i]; out.push(val); }
    return out;
  };
  const atrS = smooth(trueRanges);
  const pS   = smooth(plusDM);
  const mS   = smooth(minusDM);
  const dxArr: number[] = [];
  for (let i = 0; i < atrS.length; i++) {
    if (atrS[i] === 0) continue;
    const pdi = 100 * pS[i] / atrS[i];
    const mdi = 100 * mS[i] / atrS[i];
    const sum = pdi + mdi;
    dxArr.push(sum === 0 ? 0 : 100 * Math.abs(pdi - mdi) / sum);
  }
  if (dxArr.length < period) return 25;
  return dxArr.slice(-period).reduce((a, b) => a + b, 0) / period;
}

function isChoppy(candles: Candle[]): boolean {
  return calcADX(candles) < 20;
}

function calcHistVol(closes: number[]): number {
  if (closes.length < 21) return 0.3;
  const slice = closes.slice(-21);
  const rets = slice.slice(1).map((c, i) => Math.log(c / slice[i]));
  const mean = rets.reduce((a, b) => a + b) / rets.length;
  const variance = rets.reduce((a, b) => a + (b - mean) ** 2, 0) / rets.length;
  return Math.sqrt(variance * 252); // daily-scale annualised vol
}

function isMarketOpen(): boolean {
  const et = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }));
  const d = et.getDay(), h = et.getHours(), m = et.getMinutes();
  const weekend = d === 0 || d === 6;
  const open = (h > 9 || (h === 9 && m >= 30)) && (h < 15 || (h === 15 && m <= 55));
  return !weekend && open;
}

// ─────────────────────────────────────────────
// ORDER PLACEMENT  (mid → mid+25% → market)
// ─────────────────────────────────────────────
async function placeProtectedOrder(
  optSymbol: string, side: 'buy'|'sell', qty: number, midPrice: number,
  blindAsk?: number, botId?: string, userId?: string, forceFill = false
): Promise<{ orderId: string; fillPrice: number | null; status: string } | null> {
  const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

  const bid = blindAsk ? blindAsk - (blindAsk - midPrice) * 2 : midPrice * 0.95;
  const ask = blindAsk ?? midPrice * 1.05;
  const spread = ask - bid;
  const mid25  = parseFloat((midPrice + spread * 0.25).toFixed(2));

  const cancelOrder = async (id: string) => {
    try { await fetch(`${BASE_URL}/v2/orders/${id}`, { method: 'DELETE', headers: alpacaHeaders() }); } catch {}
  };

  const pollFill = async (id: string, waitMs: number): Promise<number | null> => {
    const end = Date.now() + waitMs;
    while (Date.now() < end) {
      await sleep(500);
      const r = await fetch(`${BASE_URL}/v2/orders/${id}`, { headers: alpacaHeaders() });
      const o: any = await r.json();
      if (o.filled_avg_price) return Number(o.filled_avg_price);
    }
    return null;
  };

  const submitLimit = async (price: number, label: string): Promise<string | null> => {
    console.log(`[Order] ${side.toUpperCase()} ${qty}x ${optSymbol} limit @ $${price.toFixed(2)} [${label}]`);
    const res = await fetch(`${BASE_URL}/v2/orders`, {
      method: 'POST', headers: alpacaHeaders(),
      body: JSON.stringify({
        symbol: optSymbol, qty: String(qty), side,
        type: 'limit', limit_price: price.toFixed(2), time_in_force: 'day',
        position_effect: side === 'buy' ? 'open' : 'close',
      }),
    });
    const o: any = await res.json();
    if (!res.ok) { console.error(`[Order] Limit ${label} rejected:`, o.message); (placeProtectedOrder as any)._lastError = o.message; return null; }
    return o.id;
  };

  // Step 1: try mid, wait 5s
  let orderId = await submitLimit(midPrice, 'mid');
  if (orderId) {
    const fill = await pollFill(orderId, 5000);
    if (fill) { console.log(`[Order] Filled at mid $${fill}`); return { orderId, fillPrice: fill, status: 'filled' }; }
    await cancelOrder(orderId);
    await sleep(300);
  }

  // Step 2: try mid+25%, wait 25s
  orderId = await submitLimit(mid25, 'mid+25%');
  if (orderId) {
    const fill = await pollFill(orderId, 25000);
    if (fill) { console.log(`[Order] Filled at mid+25% $${fill}`); return { orderId, fillPrice: fill, status: 'filled' }; }
    await cancelOrder(orderId);
    await sleep(300);
  }

  // Step 3: market order fallback
  console.log(`[Order] ${side.toUpperCase()} ${qty}x ${optSymbol} MARKET fallback`);
  const mRes = await fetch(`${BASE_URL}/v2/orders`, {
    method: 'POST', headers: alpacaHeaders(),
    body: JSON.stringify({ symbol: optSymbol, qty: String(qty), side, type: 'market', time_in_force: 'day', position_effect: side === 'buy' ? 'open' : 'close' }),
  });
  const mOrder: any = await mRes.json();
  if (!mRes.ok) { console.error(`[Order] Market fallback failed:`, mOrder.message); (placeProtectedOrder as any)._lastError = mOrder.message; return null; }

  console.log(`[Order] Market ${side} ${qty}x ${optSymbol} → ${mOrder.id}`);

  for (let i = 0; i < 30; i++) {
    await sleep(200);
    const pollRes = await fetch(`${BASE_URL}/v2/orders/${mOrder.id}`, { headers: alpacaHeaders() });
    const polled: any = await pollRes.json();

    if (polled.filled_avg_price) {
      const fillPrice = Number(polled.filled_avg_price);
      const spreadPaid = blindAsk ? (fillPrice - blindAsk) * 100 * qty : 0;
      console.log(`[Order] Filled @ $${fillPrice} | vs ask: $${spreadPaid.toFixed(2)}`);

      // Log fill metrics async
      supabase.from('slippage_logs').insert({
        symbol:               optSymbol,
        order_id:             mOrder.id,
        bot_id:               botId ?? null,
        user_id:              userId ?? null,
        blind_ask_price:      blindAsk ?? midPrice,
        target_mid_price:     midPrice,
        actual_filled_price:  fillPrice,
        mid_slippage_pennies: Math.round((fillPrice - midPrice) * 100),
        qty,
        timestamp:            new Date().toISOString(),
      }).then(() => {}, (e: any) => console.error('[Slippage] Log failed:', e.message));

      return { orderId: mOrder.id, fillPrice, status: polled.status };
    }
  }

  console.log(`[Order] Market order not filled after 3s — skipping`);
  return null;
}

// ─────────────────────────────────────────────
// LOAD ENABLED BOTS FROM SUPABASE
// ─────────────────────────────────────────────
interface BotRow {
  id: string; user_id: string; name: string; broker: string;
  bot_signal: string; bot_symbol: string; bot_scan_mode: string; bot_interval: string;
  take_profit_pct: number; stop_loss_pct: number;
  paper_balance: number; contracts: number; amount_per_trade: number;
  bot_dollar_amount: number | null; neutral_chop_amount: number | null; neutral_trend_amount: number | null;
  max_daily_trades: number | null; daily_trade_count: number;
  option_type: string; bot_expiry_type: string;
  consecutive_losses: number | null; max_consecutive_losses: number | null; cooldown_minutes: number | null; cooldown_until: string | null;
}

let activeBots: BotRow[] = [];
const openPositions = new Set<string>(); // "botId:symbol" — in-memory guard against race conditions

async function reloadBots(): Promise<void> {
  const { data, error } = await supabase
    .from('options_bots')
    .select('*')
    .eq('enabled', true)
    .eq('auto_submit', true);
  if (error) { console.error('[Bots] Reload failed:', error.message); return; }
  activeBots = (data || []) as BotRow[];
  // Rebuild watch list from all active bot scan lists
  const symSet = new Set<string>();
  for (const bot of activeBots) {
    const scanList = getScanList(bot.bot_scan_mode);
    const syms = scanList.length > 0
      ? scanList
      : (bot.bot_symbol || '').split(',').map((s: string) => s.trim().toUpperCase()).filter(Boolean);
    syms.forEach((s: string) => symSet.add(s));
  }
  const newSymbols = Array.from(symSet);
  const changed = newSymbols.length !== WATCH_SYMBOLS.length || newSymbols.some(s => !WATCH_SYMBOLS.includes(s));
  WATCH_SYMBOLS = newSymbols;
  console.log(`[Bots] Loaded ${activeBots.length}: ${activeBots.map(b => b.name).join(', ')}`);
  console.log(`[Bots] Watching ${WATCH_SYMBOLS.length} symbols: ${WATCH_SYMBOLS.join(', ')}`);
  if (changed && activeWs?.readyState === 1) {
    activeWs.send(JSON.stringify({ action: 'subscribe', bars: WATCH_SYMBOLS }));
    console.log(`[WS] Re-subscribed to updated symbol list`);
  }
}

// ─────────────────────────────────────────────
// CORE SIGNAL EVALUATION
// Called once per 1m bar close per underlying symbol
// ─────────────────────────────────────────────
async function onBar(symbol: string, candles: Candle[]): Promise<void> {
  console.log(`[onBar] ${symbol}: ${candles.length} bars, marketOpen=${isMarketOpen()}`);
  if (!isMarketOpen()) { console.log(`[onBar] ${symbol}: market closed, returning`); return; }

  const botsForSymbol = activeBots.filter(b => {
    const scanList = getScanList(b.bot_scan_mode);
    const symList = scanList.length > 0
      ? scanList
      : (b.bot_symbol || '').split(',').map((s: string) => s.trim().toUpperCase()).filter(Boolean);
    return symList.includes(symbol);
  });

  if (!botsForSymbol.length) return;

  for (const bot of botsForSymbol) {
    try {
      if (bot.bot_signal !== 'boof55' && bot.max_daily_trades && bot.daily_trade_count >= bot.max_daily_trades) {
        console.log(`[TradeLimit] ${bot.name}: Hit daily limit ${bot.daily_trade_count}/${bot.max_daily_trades}`);
        continue;
      }

      // Interval gate: only evaluate on the correct bar boundary
      const interval = bot.bot_interval || '1m';
      const intervalMins = interval === '15m' ? 15 : interval === '5m' ? 5 : 1;
      if (intervalMins > 1) {
        const etNow = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }));
        if (etNow.getMinutes() % intervalMins !== 0) continue;
      }

      // In-memory guard first (prevents race conditions)
      const posKey = `${bot.id}:${symbol}`;
      if (openPositions.has(posKey)) {
        console.log(`[PositionLock] ${bot.name} ${symbol}: Blocked by in-memory lock (size=${openPositions.size})`);
        continue;
      }

      // DB check as secondary guard
      const { data: openTrades } = await supabase
        .from('options_trades')
        .select('id')
        .eq('bot_id', bot.id)
        .eq('symbol', symbol)
        .eq('status', 'open')
        .limit(1);
      if (openTrades && openTrades.length > 0) {
        openPositions.add(posKey); // sync in-memory with DB
        continue;
      }

      // Block new 0DTE entries after 12pm MST (18:00 UTC)
      if (bot.bot_expiry_type === '0dte') {
        const utcH = new Date().getUTCHours(), utcM = new Date().getUTCMinutes();
        if (utcH > 18 || (utcH === 18 && utcM >= 0)) {
          console.log(`[Gate] ${bot.name} ${symbol}: skipping 0DTE entry — past 12pm MST`);
          continue;
        }
      }

      const tpPct = Number(bot.take_profit_pct ?? 40) / 100;
      const slPct = Math.abs(Number(bot.stop_loss_pct ?? 15)) / 100;
      const sig   = bot.bot_signal;

      // ── FETCH CORRECT TIMEFRAME CANDLES FOR SIGNAL ──
      const sigCandles = intervalMins > 1
        ? await fetchCandles(symbol, interval, 150)
        : candles;
      if (sigCandles.length < 50) continue;

      // ── ADX CHOP DETECTION (for .5 variants) ──
      const choppy = isChoppy(sigCandles as any);
      const isHalfVariant = sig === 'boof22_5' || sig === 'boof23_5';
      if (isHalfVariant && choppy) {
        console.log(`[Chop] ${bot.name} ${symbol}: ADX<20 chop detected — using chop sizing`);
      }

      // ── BOOF55: Stock gap breakout — separate execution path (no options) ──
      if (sig === 'boof55') {
        const b55 = getBoof55Signal(sigCandles as any);
        console.log(`[SignalDebug] ${bot.name} ${symbol}: signal=${b55.signal}, reason=${b55.reason}`);
        if (b55.signal !== 'buy') continue;

        // Position guard
        if (openPositions.has(posKey)) continue;
        const { data: openTrades55 } = await supabase
          .from('options_trades')
          .select('id')
          .eq('bot_id', bot.id)
          .eq('symbol', symbol)
          .eq('status', 'open')
          .limit(1);
        if (openTrades55 && openTrades55.length > 0) { openPositions.add(posKey); continue; }

        // Size: 5% equity for stock, fixed $750 for option leg
        const acctRes = await fetch(`${BASE_URL}/v2/account`, { headers: alpacaHeaders() });
        const acct: any = await acctRes.json();
        const equity     = parseFloat(acct.equity ?? acct.paper_balance ?? '3000');
        const stockRisk  = equity * 0.05;
        const shares     = Math.max(1, Math.floor(stockRisk / b55.price));
        const OPT_BUDGET = 750; // fixed $750 option leg budget

        console.log(`[BOOF55] ${symbol}: equity=$${equity.toFixed(0)} stockRisk=$${stockRisk.toFixed(0)} shares=${shares} @ $${b55.price.toFixed(2)} | ${b55.reason}`);

        openPositions.add(posKey);

        // ── LEG 1: Stock — EOD exit ──
        const stockOrder = await placeLimitOrder(symbol, shares, 'buy');
        if (!stockOrder.ok) {
          console.error(`[BOOF55] Stock order failed ${symbol}`);
          openPositions.delete(posKey); continue;
        }
        const entryPrice = b55.price;
        await supabase.from('options_trades').insert({
          bot_id: bot.id, user_id: bot.user_id, symbol,
          option_type: 'stock', strike: entryPrice,
          expiration_date: new Date().toISOString().slice(0, 10),
          premium_per_contract: entryPrice, entry_price: entryPrice,
          total_cost: entryPrice * shares, contracts: shares,
          status: 'open', created_at: new Date().toISOString(),
          reason: b55.reason, entry_slack: 1, signal_version: 'boof55',
          broker: bot.broker || 'alpaca_paper',
          mode: `gap=${b55.gapPct.toFixed(2)}%_rvol=${b55.rvol.toFixed(2)}x_${b55.level}`,
          signal: 'buy', take_profit_pct: null, stop_loss_pct: null,
        });
        console.log(`[BOOF55] Stock leg: ${symbol} ${shares}sh @ $${entryPrice.toFixed(2)} — EOD exit`);

        // ── LEG 2: ATM Call — $750 budget, walk OTM if too expensive, max contracts ──
        {
          const spot      = b55.price;
          const strikeInt = spot > 500 ? 5 : spot > 50 ? 2.5 : 1;
          const atmStrike = Math.round(spot / strikeInt) * strikeInt;
          const optExpDate = nearestFriday();
          const exitAt30min = Date.now() + 30 * 60 * 1000;

          // Start at ATM, walk OTM up to 5 strikes if too expensive
          let chosenStrike = atmStrike;
          let chosenQty    = 1;
          let chosenQ: any = null;
          let chosenSym    = '';

          // Walk OTM if 1-contract cost > budget
          for (let otmStep = 0; otmStep <= 5; otmStep++) {
            const testStrike = atmStrike + (otmStep * strikeInt); // 0=ATM, 1=1OTM...
            const testSym    = formatOptionSymbol(symbol, optExpDate, 'call', testStrike);
            const q          = await fetchLiveQuote(testSym);
            if (!q || q.mid <= 0) continue;
            const costPer = q.ask * 100; // cost for 1 contract
            if (costPer <= OPT_BUDGET) {
              chosenStrike = testStrike;
              chosenQ      = q;
              chosenSym    = testSym;
              // How many contracts fit in budget?
              chosenQty = Math.max(1, Math.floor(OPT_BUDGET / costPer));
              // Cap at 10 contracts
              chosenQty = Math.min(chosenQty, 10);
              break;
            }
          }

          if (chosenQ && chosenQ.mid > 0) {
            const optOrder = await fetch(`${BASE_URL}/v2/orders`, {
              method: 'POST', headers: alpacaHeaders(),
              body: JSON.stringify({
                symbol: chosenSym, qty: String(chosenQty), side: 'buy',
                type: 'limit', limit_price: chosenQ.ask.toFixed(2),
                time_in_force: 'day',
              }),
            });
            if (optOrder.ok) {
              await supabase.from('options_trades').insert({
                bot_id: bot.id, user_id: bot.user_id, symbol,
                option_type: 'call', strike: chosenStrike,
                expiration_date: optExpDate,
                premium_per_contract: chosenQ.mid, entry_price: chosenQ.mid,
                total_cost: chosenQ.mid * chosenQty * 100, contracts: chosenQty,
                status: 'open', created_at: new Date().toISOString(),
                reason: `${b55.reason} [call 30min $${OPT_BUDGET}]`, entry_slack: 1,
                signal_version: 'boof55_call', broker: bot.broker || 'alpaca_paper',
                mode: `gap=${b55.gapPct.toFixed(2)}%_rvol=${b55.rvol.toFixed(2)}x_${b55.level}`,
                signal: 'buy',
                take_profit_pct: exitAt30min, // unix ms — 30min exit deadline
                stop_loss_pct: -50,           // -50% disaster stop
              });
              const itmLabel = chosenStrike < atmStrike ? `${((atmStrike - chosenStrike)/strikeInt).toFixed(0)}-ITM` : chosenStrike === atmStrike ? 'ATM' : `${((chosenStrike-atmStrike)/strikeInt).toFixed(0)}-OTM`;
              console.log(`[BOOF55] Call leg (${itmLabel}): ${chosenSym} ${chosenQty}x @ $${chosenQ.mid.toFixed(2)} cost=$${(chosenQ.ask*chosenQty*100).toFixed(0)} — 30min exit`);
            } else {
              const e: any = await optOrder.json();
              console.error(`[BOOF55] Call order failed ${chosenSym}:`, e.message);
            }
          } else {
            console.log(`[BOOF55] No viable call quote for ${symbol} within budget — skipping call leg`);
          }
        }

        bot.daily_trade_count = (bot.daily_trade_count ?? 0) + 1;
        continue;  // skip options logic below
      }

      // ── RUN BOOF22 / BOOF23 / BOOF25 SIGNAL MATH ──
      let result: any = null;
      if (sig === 'boof22' || sig === 'boof22_5') {
        result = getBoof22Signal(sigCandles as any, symbol, tpPct, slPct);
      } else if (sig === 'boof23' || sig === 'boof23_5') {
        result = getBoof23Signal(sigCandles as any, symbol, tpPct, slPct);
      } else if (sig === 'boof25') {
        result = getBoof25Signal(sigCandles as any, symbol, tpPct, slPct);
      }

      // DEBUG: Log ALL signal results
      console.log(`[SignalDebug] ${bot.name} ${symbol}: signal=${result?.signal}, reason=${result?.reason || 'no result'}`);
      
      if (!result || result.signal === 'none') {
        continue;
      }

      const signal    = result.signal as 'buy' | 'sell';
      const optType: 'call'|'put' = signal === 'buy' ? 'call' : 'put';
      if (bot.option_type === 'call' && optType !== 'call') continue;
      if (bot.option_type === 'put'  && optType !== 'put')  continue;

      // ── CHECK FOR EXISTING OPEN POSITION ──
      const { data: existingPos } = await supabase.from('options_trades')
        .select('*')
        .eq('symbol', symbol)
        .eq('status', 'open')
        .eq('bot_id', bot.id)
        .gte('created_at', new Date(Date.now() - 10 * 60 * 1000).toISOString()) // Within last 10 mins
        .limit(1);
      
      if (existingPos && existingPos.length > 0) {
        console.log(`[SignalSkip] ${bot.name} ${symbol}: Already have open position from ${existingPos[0].created_at}`);
        continue;
      }

      const spot    = sigCandles[sigCandles.length - 1].close;
      const closes  = sigCandles.map(c => c.close);
      const sigma   = calcHistVol(closes);
      const highs   = sigCandles.map(c => c.high);
      const lows    = sigCandles.map(c => c.low);
      const atrVals = sigCandles.map((c, i) => i === 0 ? c.high - c.low :
        Math.max(c.high - c.low, Math.abs(c.high - sigCandles[i-1].close), Math.abs(c.low - sigCandles[i-1].close)));
      const atr     = atrVals.slice(-14).reduce((a, b) => a + b) / 14;

      const expDate   = nextTradingDay(); // 1DTE — next trading day expiration
      const T         = Math.max(0, (new Date(expDate).getTime() - Date.now()) / (365 * 24 * 3600 * 1000));
      const strikeInterval = spot > 500 ? 5 : spot > 50 ? 2.5 : 1;

      // ── TRADE SIZING: symbol slack score → tier amount ──
      // Daily decay: move halfway back toward neutral (100) each new trading day
      const { data: slackRow } = await supabase
        .from('symbol_slack_scores')
        .select('slack_score, total_trades, last_decayed')
        .eq('bot_id', bot.id)
        .eq('symbol', symbol)
        .maybeSingle();
      
      const rawSlack = slackRow?.slack_score ?? 100;
      const lastDecay = slackRow?.last_decayed ? new Date(slackRow.last_decayed).toDateString() : null;
      const todayStr = new Date().toDateString();
      
      // Apply half-life decay if this is a new day
      let symbolSlack = rawSlack;
      if (lastDecay !== todayStr) {
        symbolSlack = Math.round((rawSlack + 100) / 2); // Halfway back to neutral
        // Update decayed score back to DB
        supabase.from('symbol_slack_scores').upsert({
          bot_id: bot.id,
          symbol: symbol,
          slack_score: symbolSlack,
          last_decayed: new Date().toISOString(),
          updated_at: new Date().toISOString()
        }).then(() => {}, (e: any) => console.error('[SlackDecay] Update failed:', e.message));
        console.log(`[SlackDecay] ${symbol}: ${rawSlack} → ${symbolSlack} (daily decay to neutral)`);
      }
      
      const hasHistory  = (slackRow?.total_trades ?? 0) >= 5;

      // Discrete slack tier amounts: High=$500, Normal=$250, Low=$150
      const isTieredSignal = ['boof22','boof22_5','boof23','boof23_5'].includes(bot.bot_signal);
      let amount: number;
      if (isTieredSignal) {
        if (hasHistory && symbolSlack >= 120)  amount = 500;  // High slack
        else if (!hasHistory)                   amount = 250;  // New symbol = normal size
        else if (symbolSlack >= 80)            amount = 250;  // Normal slack
        else                                    amount = 150;  // Low slack (<80)
      } else if (isHalfVariant && choppy && bot.neutral_chop_amount) {
        amount = Number(bot.neutral_chop_amount);
      } else if (isHalfVariant && !choppy && bot.neutral_trend_amount) {
        amount = Number(bot.neutral_trend_amount);
      } else {
        amount = Number(bot.bot_dollar_amount ?? bot.amount_per_trade ?? 250);
      }
      // ── SUPABASE RISK MANAGEMENT: Signal slack + Daily P&L filtering ──
      // Get today's trades for daily P&L calculation
      const today = new Date().toISOString().slice(0, 10);
      const { data: dailyTrades } = await supabase
        .from('options_trades')
        .select('pnl')
        .eq('bot_id', bot.id)
        .gte('created_at', today);
      const dailyPnL = (dailyTrades || []).reduce((sum: number, t: any) => sum + (t.pnl || 0), 0);
      const baseAmountForR = bot.bot_dollar_amount || 250;
      const dailyR = dailyPnL / baseAmountForR;

      // Signal slack from the signal result
      const signalSlack = result.slack ?? 0;

      // Symbol slack multiplier (like Supabase)
      let symbolSlackMultiplier = 1.0;
      let slackStatus = 'normal';
      if (hasHistory) {
        if (symbolSlack < 50) {
          symbolSlackMultiplier = 0.25;
          slackStatus = 'min-size';
        } else if (symbolSlack < 100) {
          symbolSlackMultiplier = 0.5;
          slackStatus = 'reduced';
        }
      }

      // Risk overlays (from Supabase)
      const isLosingStreak = dailyR < -2.0;  // Down more than 2R today
      const isVeryLowSlack = signalSlack < 0.3; // No confidence
      const riskOff = isLosingStreak || isVeryLowSlack;

      // Core signal detection (from Supabase)
      const isCore = signalSlack >= 0.8 && !riskOff;
      const signalMultiplier = riskOff ? 0.5 : (isCore ? 2.0 : 1.0);
      const tieredTier = riskOff ? 'reduced' : (isCore ? 'core' : 'expanded');

      // Combined multiplier (signal * symbol slack)
      const combinedMultiplier = signalMultiplier * symbolSlackMultiplier;

      // Apply multiplier to amount
      const finalAmount = Math.round(amount * combinedMultiplier);

      console.log(`[RiskMgmt] ${bot.name} ${symbol}: signalSlack=${signalSlack.toFixed(2)}, symbolSlack=${symbolSlack.toFixed(1)} [${slackStatus}], dailyR=${dailyR.toFixed(2)}, riskOff=${riskOff}, tier=${tieredTier}, combinedMult=${combinedMultiplier.toFixed(2)}x, ${amount}→${finalAmount}`);

      // Update amount for rest of logic
      amount = finalAmount;

      // Start ATM, always buy 1 contract, walk ITM if needed
      let strike = pickStrike(spot, optType, atr);
      const qty = 1;
      const p = blackScholes(spot, strike, T, R, sigma, optType);
      let midPrice = p < 0.05 ? 0.05 : p;
      const optSymbol = formatOptionSymbol(symbol, expDate, optType, strike);

      console.log(`[Signal] ${bot.name} → ${signal.toUpperCase()} ${symbol} ${optType} $${strike} exp=${expDate} mid=$${midPrice.toFixed(2)} qty=${qty} | ${result.reason}`);

      // ── FETCH LIVE QUOTE SNAPSHOT FOR REAL MID-PRICE ──
      let blindAsk: number | undefined;
      const TARGET_MIN = 1.00;  // Allow cheaper options (was 1.50)
      const TARGET_MAX = 3.00;  // Cap at $3.00 max (was 4.00) - prevents expensive options

      async function fetchLiveQuote(sym: string): Promise<{ mid: number; ask: number } | null> {
        // Use batch snapshots endpoint with feed parameter (like working Supabase version)
        for (const feed of ['opra', 'indicative']) {
          const url = `${DATA_URL}/v1beta1/options/snapshots?symbols=${encodeURIComponent(sym)}&feed=${feed}`;
          const r = await fetch(url, { headers: alpacaHeaders() });
          if (!r.ok) continue; // Try next feed
          const j: any = await r.json();
          const snap = j?.snapshots?.[sym];
          const bid = snap?.latestQuote?.bp;
          const ask = snap?.latestQuote?.ap;
          if (bid > 0 && ask > 0) {
            const mid = Math.round(((bid + ask) / 2) * 100) / 100;
            console.log(`[Quote] Got ${feed} quote for ${sym}: bid=$${bid} ask=$${ask} mid=$${mid}`);
            return { mid, ask };
          }
          const lastTrade = snap?.latestTrade?.p;
          if (lastTrade > 0) {
            console.log(`[Quote] Got ${feed} last trade for ${sym}: $${lastTrade}`);
            return { mid: lastTrade, ask: lastTrade };
          }
        }
        console.log(`[Quote] No valid quote for ${sym} from any feed`);
        return null;
      }

      // Initial quote
      // Dynamic targets based on stock price - expensive stocks need pricier options
      const dynamicMin = Math.max(TARGET_MIN, spot * 0.001); // 0.1% of stock price, min $0.25
      const dynamicMax = Math.min(TARGET_MAX, spot * 0.005); // 0.5% of stock price, max $4.00
      
      let liveQ = await fetchLiveQuote(optSymbol);
      
      // Fallback: if no quote at ATM, walk ITM only until we get a valid quote
      if (!liveQ) {
        console.log(`[Quote] ATM strike ${strike} no quote, walking ITM...`);
        for (let offset = 1; offset <= 20; offset++) {
          const itmStrike = strike + (optType === 'call' ? -offset * strikeInterval : offset * strikeInterval);
          const itmSym = formatOptionSymbol(symbol, expDate, optType, itmStrike);
          const itmQ = await fetchLiveQuote(itmSym);
          if (itmQ && itmQ.mid > 0) {
            console.log(`[Quote] Found ITM strike ${itmStrike} mid=$${itmQ.mid} (walk=${offset})`);
            liveQ = itmQ;
            strike = itmStrike;
            break;
          }
        }
      }
      
      if (liveQ) {
        blindAsk = liveQ.ask;
        midPrice = liveQ.mid;
        console.log(`[Quote] Initial ask=$${blindAsk} mid=$${midPrice} for ${optSymbol}, targets=[$${dynamicMin.toFixed(2)}-$${dynamicMax.toFixed(2)}]`);

        // If no valid price, walk ITM until we get a liquid quote
        if (midPrice < 0.10) {
          let walkStrike = strike;
          for (let w = 0; w < 20; w++) {
            walkStrike = optType === 'call' ? walkStrike - strikeInterval : walkStrike + strikeInterval;
            const walkSym = formatOptionSymbol(symbol, expDate, optType, walkStrike);
            const wq = await fetchLiveQuote(walkSym);
            if (!wq) continue;
            console.log(`[QuoteWalk ITM] strike=${walkStrike} mid=$${wq.mid}`);
            if (wq.mid > 0.10) {
              strike = walkStrike;
              midPrice = wq.mid;
              blindAsk = wq.ask;
              break;
            }
          }
        }
        
        // Final check: reject if still too cheap (illiquid/junk option)
        if (midPrice < 1.00) {
          console.log(`[Quote] Rejecting ${symbol} - best price $${midPrice} too cheap (min $1.00)`);
          continue;
        }
      }

      // Reject if price still too cheap after quote walking (or if no live quote)
      if (midPrice < 1.00) {
        console.log(`[Order] Rejecting ${symbol} - final price $${midPrice} too cheap (min $1.00), no liquid options found`);
        continue;
      }

      // ── BOOF55-style sizing: $750 budget, ATM start, walk OTM if too expensive, max contracts ──
      const OPT_BUDGET_23 = 750;
      let finalStrike  = strike;
      let finalMid     = midPrice;
      let finalAsk     = blindAsk ?? midPrice;
      let finalOptSymbol = formatOptionSymbol(symbol, expDate, optType, strike);

      // Walk OTM up to 5 strikes until 1 contract fits in budget
      if (finalAsk * 100 > OPT_BUDGET_23) {
        let found = false;
        for (let step = 1; step <= 5; step++) {
          const otmStrike = optType === 'call'
            ? finalStrike + step * strikeInterval
            : finalStrike - step * strikeInterval;
          const otmSym = formatOptionSymbol(symbol, expDate, optType, otmStrike);
          const otmQ   = await fetchLiveQuote(otmSym);
          if (!otmQ || otmQ.mid < 1.00) continue;
          if (otmQ.ask * 100 <= OPT_BUDGET_23) {
            finalStrike    = otmStrike;
            finalMid       = otmQ.mid;
            finalAsk       = otmQ.ask;
            finalOptSymbol = otmSym;
            found = true;
            console.log(`[OTMWalk] ${symbol}: walked ${step} OTM to $${otmStrike} mid=$${finalMid.toFixed(2)}`);
            break;
          }
        }
        if (!found) {
          console.log(`[OTMWalk] ${symbol}: no strike fits $${OPT_BUDGET_23} budget — skipping`);
          continue;
        }
      }

      // How many contracts fit in budget (cap at 10)
      const finalQty = Math.min(10, Math.max(1, Math.floor(OPT_BUDGET_23 / (finalAsk * 100))));
      console.log(`[Order] Final: ${finalOptSymbol} strike=${finalStrike} ${optType} exp=${expDate} mid=$${finalMid.toFixed(2)} qty=${finalQty} cost=$${(finalAsk*finalQty*100).toFixed(0)} budget=$${OPT_BUDGET_23}`);
      console.log(`[OrderDebug] About to place order: symbol=${symbol} optType=${optType} strike=${finalStrike} expDate=${expDate} finalOptSymbol=${finalOptSymbol}`);

      // ── GLOBAL POSITION LIMIT: Max 3 simultaneous positions per bot ──
      const globalOpenCount = Array.from(openPositions).filter(k => k.startsWith(`${bot.id}:`)).length;
      if (globalOpenCount >= 3) {
        console.log(`[GlobalLimit] ${bot.name}: Already has ${globalOpenCount} positions open (max 3)`);
        continue;
      }

      // ── FIRE LIMIT ORDER AT MID (better fill than ask) ──
      openPositions.add(posKey); // lock immediately before order fires
      const orderResult = await placeProtectedOrder(finalOptSymbol, 'buy', finalQty, finalMid, finalAsk, bot.id, bot.user_id);
      if (!orderResult) { openPositions.delete(posKey); continue; }

      const fillPremium = orderResult.fillPrice ?? finalMid;
      const totalCost   = fillPremium * finalQty * 100;

      // ── LOG TO SUPABASE ──
      try {
        const { error: insertErr } = await supabase.from('options_trades').insert({
          bot_id:               bot.id,
          user_id:              bot.user_id,
          symbol,
          option_type:          optType,
          strike:               finalStrike,
          expiration_date:      expDate,
          premium_per_contract: fillPremium,
          entry_price:          fillPremium,
          total_cost:           totalCost,
          contracts:            finalQty,
          status:               'open',
          created_at:           new Date().toISOString(),
          reason:               result.reason,
          entry_slack:          result.slack ?? 1,
          signal_version:       bot.bot_signal,
          broker:               bot.broker || 'alpaca_paper',
          mode:                 result.tier === 'core' ? 'core' : (choppy ? 'chop' : 'trend'),
          signal:               signal,
        });
        if (insertErr) {
          console.error(`[DB] INSERT FAILED for ${bot.name} ${symbol}:`, insertErr.message);
        } else {
          console.log(`[DB] Trade logged for ${bot.name} ${symbol}: optType=${optType} strike=${strike} finalQty=${finalQty} fillPremium=${fillPremium}`);
        }
      } catch (e: any) {
        console.error(`[DB] INSERT EXCEPTION for ${bot.name} ${symbol}:`, e.message);
      }

      // Update paper balance async
      supabase.from('options_bots').update({
        paper_balance:    Math.max(0, Number(bot.paper_balance) - totalCost),
        daily_trade_count: (bot.daily_trade_count ?? 0) + 1,
        last_run_at:      new Date().toISOString(),
      }).eq('id', bot.id).then();

      bot.daily_trade_count = (bot.daily_trade_count ?? 0) + 1;

    } catch (err: any) {
      console.error(`[Bot:${bot.name}] Error on ${symbol}:`, err.message);
    }
  }
}

function getScanList(mode: string): string[] {
  const lists: Record<string, string[]> = {
    scan_boof5_22:          ['NVDA','AAPL','META','GOOG','MSFT','AMZN','AMD'],
    scan_boof5_with_etf_22: ['NVDA','AAPL','META','GOOG','MSFT','AMZN','AMD','QQQ','SPY'],
    scan_boof5_23:          ['NVDA','AAPL','META','GOOG','AMD'],
    scan_boof5_with_etf_23: ['NVDA','AAPL','META','GOOG','AMD','QQQ','SPY'],
    scan_boof5:             ['NVDA','AAPL','META','GOOG','MSFT','AMZN','AMD'],
    scan_boof5_with_etf:    ['NVDA','AAPL','META','GOOG','MSFT','AMZN','AMD','QQQ','SPY'],
    scan_boofinator:        ['SPY','QQQ','TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOG'],
    scan_boofinator_stocks: ['TSLA','NVDA','COIN','PLTR','AMD','AAPL','AMZN','META','GOOG'],
    scan_boof55:            [...BOOF55_UNIVERSE],
    scan_boof24:            ['NVDA','AAPL','META','MSFT','AMZN','GOOG','AVGO','TSLA','LLY','PLTR'],
    scan_boof_noetf:        ['NVDA','AAPL','MSFT','AMZN','GOOG','AVGO','META','TSLA','LLY'],
    scan_boof_etf:          ['NVDA','AAPL','MSFT','AMZN','GOOG','AVGO','META','TSLA','LLY','QQQ','SPY'],
    scan_boof_duo:          ['SPY','QQQ'],
    scan_duo:               ['SPY','QQQ'],
    scan_boof:              ['QQQ','SPY','TSLA','NVDA','AMD','AAPL','MSFT','AMZN'],
    scan_top10:             ['SMCI','TSLA','NVDA','COIN','PLTR','AMD','MRNA','MSTY','ENPH','VKTX','CCL'],
    scan_9_backtest:        ['TSLA','NVDA','COIN','PLTR','TSM','AAPL','AMZN','META','GOOG'],
  };
  return lists[mode] ?? [];
}

// ─────────────────────────────────────────────
// TP/SL DAEMON — checks all open trades every 30s
// Same formulas as old Edge Function tpsl_daemon
// ─────────────────────────────────────────────
async function fetchRealOptionPrice(
  symbol: string, strike: number, expiration: string,
  optionType: string, candles: Candle[]
): Promise<number> {
  // Use same symbol formatting as entry logic to ensure consistency
  const alpacaSymbol = formatOptionSymbol(symbol, expiration, optionType.toLowerCase() as 'call'|'put', strike);
  try {
    // Use batch snapshots endpoint with feed parameter (like working Supabase version)
    for (const feed of ['opra', 'indicative']) {
      const snapUrl = `${DATA_URL}/v1beta1/options/snapshots?symbols=${encodeURIComponent(alpacaSymbol)}&feed=${feed}`;
      const snapRes = await fetch(snapUrl, { headers: alpacaHeaders() });
      if (!snapRes.ok) continue;
      const snapJson: any = await snapRes.json();
      const snap = snapJson?.snapshots?.[alpacaSymbol];
      const bid = snap?.latestQuote?.bp;
      const ask = snap?.latestQuote?.ap;
      if (bid > 0 && ask > 0) {
        const mid = Math.round(((bid + ask) / 2) * 100) / 100;
        console.log(`[TPSL Price] ${alpacaSymbol} ${feed}: bid=$${bid} ask=$${ask} mid=$${mid}`);
        return mid;
      }
      const lastTrade = snap?.latestTrade?.p;
      if (lastTrade > 0) {
        console.log(`[TPSL Price] ${alpacaSymbol} ${feed} last trade: $${lastTrade}`);
        return lastTrade;
      }
    }
  } catch (_) {}

  // Fall back to Black-Scholes only if Alpaca quote unavailable
  if (!candles.length) return 0;
  const spotPrice = candles[candles.length - 1].close;
  const etfs = ['SPY','QQQ','IWM','DIA','GLD','TLT','XLF','XLE','XLK','XLV','EEM','VXX'];
  const highVol = ['TSLA','NVDA','AMD','MSTR','COIN','PLTR','GME','AMC','RIVN','LCID'];
  let baseIv = etfs.includes(symbol) ? 0.18 : highVol.includes(symbol) ? 0.55 : 0.30;
  const closes = candles.map(c => c.close);
  const histVol = calcHistVol(closes);
  if (histVol > 0.01 && histVol < 5) baseIv = baseIv * 0.6 + histVol * 0.4;
  const now = new Date();
  const expMs = new Date(expiration).getTime() - now.getTime();
  const T = Math.max(0.0001, expMs / (1000 * 60 * 60 * 24 * 365));
  console.log(`[TPSL Price] ${symbol} $${strike} ${optionType} — no Alpaca quote, using Black-Scholes`);
  const price = blackScholes(spotPrice, strike, T, R, baseIv, optionType.toLowerCase() as 'call'|'put');
  return Math.max(0.01, price);
}

async function runTpSlDaemon(): Promise<void> {
  if (!isMarketOpen()) { console.log('[TPSL] Market closed, skipping'); return; }

  console.log('[TPSL] Checking open trades...');
  const { data: openTrades, error } = await supabase
    .from('options_trades')
    .select('*, options_bots!inner(take_profit_pct, stop_loss_pct, broker, name, bot_signal, bot_expiry_type)')
    .eq('status', 'open');

  if (error) { console.error('[TPSL] DB error:', error); return; }
  if (!openTrades || openTrades.length === 0) { console.log('[TPSL] No open trades found'); return; }
  console.log(`[TPSL] Found ${openTrades.length} open trades to check`);

  const now = new Date();
  const todayStr = now.toISOString().slice(0, 10);
  const tomorrowStr = new Date(Date.now() + 86400000).toISOString().slice(0, 10);

  for (const open of openTrades) {
    try {
      const bot = (open as any).options_bots;
      const botSignal = bot?.bot_signal || 'boof23';

      // ── BOOF55 EXIT (stock = EOD, call = 30min) ──
      if (botSignal === 'boof55' || botSignal === 'boof55_call' || (open as any).option_type === 'stock') {
        const isCallLeg   = (open as any).signal_version === 'boof55_call';
        const candles     = candleCache.get(open.symbol) ?? [];
        const currPrice   = candles.length ? candles[candles.length - 1].close : 0;
        if (!currPrice) continue;

        const entryPrice  = Number(open.entry_price ?? open.premium_per_contract);
        const contracts   = Number(open.contracts);
        const utcH = now.getUTCHours(), utcM = now.getUTCMinutes();
        const isEOD = (utcH === 20 && utcM >= 59) || utcH > 20 || (utcH === 19 && utcM >= 59);

        let shouldExit = false;
        let exitReason = 'eod_close';
        let pnl = 0;
        let exitSymbol = open.symbol;

        if (isCallLeg) {
          // Call leg: exit at 30min deadline or -50% SL
          const exitDeadline = Number(open.take_profit_pct);
          const is30min = exitDeadline > 0 && Date.now() >= exitDeadline;
          const optPrice = await fetchRealOptionPrice(open.symbol, open.strike, open.expiration_date, open.option_type, candles);
          const totalCost = Number(open.total_cost) || (entryPrice * contracts * 100);
          pnl = optPrice ? (optPrice * contracts * 100) - totalCost : 0;
          const pctChange = totalCost > 0 ? (pnl / totalCost) * 100 : 0;
          const slThreshold = Number(open.stop_loss_pct || -50);
          const isSL = pctChange <= slThreshold;
          shouldExit = is30min || isSL || isEOD;
          exitReason = isSL ? 'stop_loss' : is30min ? '30min_exit' : 'eod_close';
          exitSymbol = formatOptionSymbol(open.symbol, open.expiration_date?.slice(0,10), 'call', Number(open.strike));
          console.log(`[BOOF55 CALL] ${open.symbol}: optPrice=$${(optPrice||0).toFixed(2)} pct=${pctChange.toFixed(1)}% sl=${slThreshold}% is30min=${is30min} isSL=${isSL} isEOD=${isEOD}`);
        } else {
          // Stock leg: EOD only
          const shares = contracts;
          pnl = (currPrice - entryPrice) * shares;
          shouldExit = isEOD;
          console.log(`[BOOF55 STK] ${open.symbol}: price=$${currPrice.toFixed(2)} entry=$${entryPrice.toFixed(2)} pct=${((currPrice-entryPrice)/entryPrice*100).toFixed(2)}% isEOD=${isEOD}`);
        }

        if (!shouldExit) continue;

        console.log(`[BOOF55] ✓ CLOSING ${exitSymbol}: ${exitReason} pnl=$${pnl.toFixed(2)}`);
        const orderSym = isCallLeg ? exitSymbol : open.symbol;
        const orderQty = isCallLeg ? String(contracts) : String(contracts);
        const sellRes = await fetch(`${BASE_URL}/v2/orders`, {
          method: 'POST', headers: alpacaHeaders(),
          body: JSON.stringify({ symbol: orderSym, qty: orderQty, side: 'sell', type: 'market', time_in_force: 'day' }),
        });
        if (!sellRes.ok) {
          const e: any = await sellRes.json();
          console.error(`[BOOF55] Sell failed ${open.symbol}:`, e.message);
          continue;
        }
        openPositions.delete(`${open.bot_id}:${open.symbol}`);
        await supabase.from('options_trades').update({
          status: 'closed', pnl, exit_price: currPrice,
          closed_at: now.toISOString(), exit_reason: exitReason, exit_type: exitReason,
        }).eq('id', open.id);
        console.log(`[BOOF55] Closed ${open.symbol} @ $${currPrice.toFixed(2)} pnl=$${pnl.toFixed(2)}`);
        continue;
      }

      // Use per-trade ATR TP/SL for boof22, else bot-level settings
      // For 22.5/23.5 bots in CHOP mode: use tighter -8% stop loss
      const isHalfVariant = ['boof22_5', 'boof23_5'].includes(botSignal);
      const tradeMode = (open as any).mode;
      const isChopTrade = isHalfVariant && tradeMode === 'chop';
      
      const tradeHasAtrTpSl = botSignal === 'boof22' && (open as any).take_profit_pct != null && (open as any).stop_loss_pct != null;
      let takeProfitPct = tradeHasAtrTpSl ? Number((open as any).take_profit_pct) : Number(bot?.take_profit_pct ?? 35);
      let stopLossPct   = tradeHasAtrTpSl ? Number((open as any).stop_loss_pct)   : Number(bot?.stop_loss_pct ?? -25);
      
      // Override for chop trades: tighter stop loss
      if (isChopTrade) {
        stopLossPct = -8;  // Tighter stop for chop conditions
        console.log(`[TPSL] ${open.symbol}: CHOP mode detected - using -8% stop loss`);
      }
      
      const slThreshold   = stopLossPct < 0 ? stopLossPct : -Math.abs(stopLossPct);

      const symbolCandles = candleCache.get(open.symbol) ?? [];
      const optionPrice = await fetchRealOptionPrice(open.symbol, open.strike, open.expiration_date, open.option_type, symbolCandles);
      console.log(`[TPSL Debug] ${open.symbol} ${open.option_type} $${open.strike}: optPrice=$${optionPrice}, entry=$${open.premium_per_contract}, qty=${open.contracts}, totalCost=$${open.total_cost}`);
      if (!optionPrice || optionPrice <= 0) {
        console.log(`[TPSL Debug] ${open.symbol}: SKIP — no option price`);
        continue;
      }

      const totalCost   = Number(open.total_cost) || (Number(open.premium_per_contract) * open.contracts * 100);
      const currentValue = optionPrice * open.contracts * 100;
      const pnl          = currentValue - totalCost;
      const pctChange    = (pnl / totalCost) * 100;
      console.log(`[TPSL Debug] ${open.symbol}: totalCost=$${totalCost}, curValue=$${currentValue}, pnl=$${pnl}, pct=${pctChange.toFixed(2)}%, slThreshold=${slThreshold}%`);

      // EOD exit logic — same as Edge Function
      const expDateStr   = open.expiration_date?.slice(0, 10) || open.expiration_date;
      const botExpiryType = bot?.bot_expiry_type ?? 'weekly';
      const is0dte = botExpiryType === '0dte' || expDateStr === todayStr;
      const is1dte = botExpiryType === '1dte' || expDateStr === tomorrowStr;
      const utcHour   = now.getUTCHours();
      const utcMinute = now.getUTCMinutes();
      const shouldEOD_0dte = is0dte && (utcHour > 18 || (utcHour === 18 && utcMinute >= 0));
      const shouldEOD_1dte = is1dte && (utcHour === 19 && utcMinute >= 59);
      // Universal EOD: close ALL trades by 15:55 ET (20:55 UTC EST / 19:55 UTC EDT)
      const shouldEOD_universal = (utcHour === 20 && utcMinute >= 55) || utcHour > 20 || (utcHour === 19 && utcMinute >= 55);
      const entryTime  = new Date(open.created_at || now);
      const minutesHeld = (now.getTime() - entryTime.getTime()) / (1000 * 60);
      const tradeCandles = candleCache.get(open.symbol) ?? [];
      const tradeInChop = isChoppy(tradeCandles);
      const timeExitMins = tradeInChop ? 20 : 30;
      const shouldTimeExit1DTE = is1dte && minutesHeld >= timeExitMins;
      const shouldTimeExit0DTE = is0dte && minutesHeld >= 20; // 20-min max hold for 0DTEs
      const shouldEOD = shouldEOD_0dte || shouldEOD_1dte || shouldTimeExit1DTE || shouldTimeExit0DTE || shouldEOD_universal;

      const shouldTP = pctChange >= takeProfitPct;
      const shouldSL = pctChange <= slThreshold;
      const isPaper  = bot?.broker === 'paper' || IS_PAPER;

      console.log(`[TPSL] ${open.symbol} ${open.option_type} $${open.strike}: cur=$${optionPrice.toFixed(2)} pct=${pctChange.toFixed(1)}% tp=${takeProfitPct}% sl=${slThreshold}% minsHeld=${minutesHeld.toFixed(1)} shouldTP=${shouldTP} shouldSL=${shouldSL} timeExit0DTE=${shouldTimeExit0DTE} eod=${shouldEOD}`);

      if (!shouldTP && !shouldSL && !shouldEOD) continue;

      const exitType   = shouldTP ? 'tp' : shouldSL ? 'sl' : (shouldTimeExit1DTE || shouldTimeExit0DTE) ? 'time_exit' : 'eod';
      const exitReason = shouldEOD ? 'eod_close' : shouldTP ? 'take_profit' : 'stop_loss';
      const exactPnl   = isPaper && !shouldEOD
        ? Math.round(totalCost * (shouldTP ? takeProfitPct : slThreshold) / 100 * 100) / 100
        : pnl;

      console.log(`[TPSL] ✓ CLOSING ${open.symbol} ${open.option_type} $${open.strike}: ${exitReason} pnl=$${exactPnl.toFixed(2)}`);

      // Fire Alpaca sell order FIRST — only close DB if we have confirmed fill
      const closeOptSym = formatOptionSymbol(open.symbol, open.expiration_date, open.option_type, open.strike);
      const sellResult = await placeProtectedOrder(closeOptSym, 'sell', open.contracts, optionPrice, undefined, open.bot_id, open.user_id, true);
      
      if (!sellResult || !sellResult.fillPrice) {
        console.warn(`[TPSL] Sell order failed or no fill for ${closeOptSym}`);
        // Check if this is a "position doesn't exist" error (cash-secured put margin requirement)
        // If Alpaca thinks we need cash-secured put buying power, it means we don't have the long position
        // In this case, mark the trade as closed in DB to fix sync issue
        const isMissingPositionError = (placeProtectedOrder as any)._lastError?.includes?.('cash-secured put') || 
                                       (placeProtectedOrder as any)._lastError?.includes?.('buying power');
        if (isMissingPositionError) {
          console.warn(`[TPSL] Position ${closeOptSym} doesn't exist in Alpaca - marking as closed in DB to fix sync`);
          await supabase.from('options_trades')
            .update({ status: 'closed', exit_price: 0, pnl: -open.total_cost, closed_at: new Date().toISOString(), close_reason: 'sync_fix_missing_position' })
            .eq('id', open.id);
          openPositions.delete(`${open.bot_id}:${open.symbol}`);
          continue;
        }
        // Otherwise retry next cycle
        continue;
      }
      
      console.log(`[TPSL] Sell order filled for ${closeOptSym} @ $${sellResult.fillPrice}`);

      // Clear in-memory lock so bot can re-enter this symbol
      const lockKey = `${open.bot_id}:${open.symbol}`;
      openPositions.delete(lockKey);
      console.log(`[PositionLock] Cleared lock for ${lockKey}, size=${openPositions.size}`);

      // Step 1 — close status + pnl
      await supabase.from('options_trades').update({ status: 'closed', pnl: exactPnl }).eq('id', open.id);
      // Step 2 — exit details (triggers slack score recalculation via Postgres trigger)
      await supabase.from('options_trades').update({
        exit_price: optionPrice, closed_at: now.toISOString(),
        exit_reason: exitReason, exit_type: exitType,
      }).eq('id', open.id);

      // Update paper balance
      if (isPaper) {
        const { data: bRow } = await supabase.from('options_bots').select('paper_balance').eq('id', open.bot_id).single();
        const bal = Number(bRow?.paper_balance ?? 100000);
        await supabase.from('options_bots').update({ paper_balance: bal + totalCost + exactPnl }).eq('id', open.bot_id);
      }
      // Note: consecutive_loss tracking disabled — columns don't exist in DB
    } catch (err: any) {
      console.error(`[TPSL] Error on trade ${open.id}:`, err.message);
    }
  }
}

// ─────────────────────────────────────────────
// WEBSOCKET STREAM — SIP feed, auto-reconnect
// ─────────────────────────────────────────────
let activeWs: InstanceType<typeof WS> | null = null;

function connectStream(symbols: string[]): void {
  const WS_URL = IS_PAPER ? 'wss://stream.data.alpaca.markets/v2/iex' : 'wss://stream.data.alpaca.markets/v2/sip';
  const ws = new WS(WS_URL);
  activeWs = ws;

  ws.on('open', () => {
    ws.send(JSON.stringify({ action: 'auth', key: ALPACA_KEY, secret: ALPACA_SECRET }));
  });

  ws.on('message', async (raw: Buffer) => {
    const msgs: any[] = JSON.parse(raw.toString());
    for (const msg of msgs) {

      if (msg.T === 'success' && msg.msg === 'authenticated') {
        console.log('[WS] Authenticated to Alpaca SIP stream');
        ws.send(JSON.stringify({ action: 'subscribe', bars: symbols }));
        console.log(`[WS] Subscribed to 1m bars: ${symbols.join(', ')}`);
      }

      if (msg.T === 'b') {
        const symbol = msg.S as string;
        const newBar: Candle = {
          time: new Date(msg.t).getTime(),
          open: msg.o, high: msg.h, low: msg.l, close: msg.c, volume: msg.v,
        };
        pushCandle(symbol, newBar);
        const candles = candleCache.get(symbol) ?? [];
        console.log(`[Bar] ${symbol} @ ${newBar.close} | cache=${candles.length} bars`);
        if (candles.length >= 50) {
          await onBar(symbol, candles);
        } else {
          console.log(`[Bar] ${symbol}: waiting for 50 bars, have ${candles.length}`);
        }
      }

      if (msg.T === 'error') {
        console.error('[WS] Stream error:', msg.code, msg.msg);
      }
    }
  });

  ws.on('close', (code: number) => {
    console.warn(`[WS] Connection closed (code ${code}), reconnecting in 5s...`);
    setTimeout(() => connectStream(symbols), 5000);
  });

  ws.on('error', (err: Error) => {
    console.error('[WS] WebSocket error:', err.message);
  });
}

// ─────────────────────────────────────────────
// ENTRY POINT
// ─────────────────────────────────────────────
async function main(): Promise<void> {
  console.log('═══════════════════════════════════════════════════');
  console.log(' Boof Capital — AWS EC2 Bot Runner  [us-east-1]');
  console.log(`  Paper mode: ${IS_PAPER}`);
  console.log(`  Supabase:   ${process.env.SUPABASE_URL}`);
  console.log('═══════════════════════════════════════════════════');

  // 1. Load all enabled bots from Supabase
  await reloadBots();

  // 2. Pre-load candle history for all watched symbols
  console.log('[Init] Pre-loading candle history...');
  await Promise.all(WATCH_SYMBOLS.map(fetchInitialCandles));

  // 3. Reload bot configs every 60s
  setInterval(reloadBots, 60_000);

  // 4. Connect WebSocket — bars arrive instantly on close
  connectStream(WATCH_SYMBOLS);

  // 5. TP/SL daemon — checks all open trades every 5s for fast exits
  setInterval(() => { runTpSlDaemon().catch(e => console.error('[TPSL] Daemon error:', e.message)); }, 5_000);
  console.log('[TPSL] Daemon started — checking open trades every 5s');
  // Force first run immediately
  setTimeout(() => runTpSlDaemon().catch(e => console.error('[TPSL] Daemon error:', e.message)), 2000);

  // 6. Position lock sync — clear in-memory locks for closed positions every 30s
  setInterval(async () => {
    try {
      const { data: openTrades } = await supabase.from('options_trades').select('bot_id, symbol').eq('status', 'open');
      const validLocks = new Set((openTrades || []).map(t => `${t.bot_id}:${t.symbol}`));
      let cleared = 0;
      for (const lock of openPositions) {
        if (!validLocks.has(lock)) {
          openPositions.delete(lock);
          cleared++;
        }
      }
      if (cleared > 0) console.log(`[LockSync] Cleared ${cleared} stale position locks`);
    } catch (e) {
      console.error('[LockSync] Error:', e);
    }
  }, 30_000);
  console.log('[LockSync] Started — clearing stale locks every 30s');

  console.log('[Runner] Live. Waiting for next 1m bar...');
}

main().catch(err => {
  console.error('[Fatal]', err);
  process.exit(1);
});
