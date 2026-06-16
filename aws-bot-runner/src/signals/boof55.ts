// =========================================================
//  BOOF55 — Gap Breakout (Stocks Only)
//  Signal: Gap >1% open + RVOL >=1.5 + close above PDH or PMH
//  Window: 09:30 – 10:00 ET only
//  Exit:   2-hour fixed hold OR -1% hard stop
//  Universe: 28 frozen symbols from walk-forward test 2022-2024
//  Validated: WR 71.4% | EV +1.25% | PF 2.99 (out-of-sample 2025-2026)
// =========================================================

export interface Candle {
  time: number; open: number; high: number; low: number; close: number; volume: number;
}

export interface Boof55Result {
  signal:       'buy' | 'none';
  price:        number;
  reason:       string;
  gapPct:       number;
  rvol:         number;
  level:        'PDH' | 'PMH' | 'none';
  stopPrice:    number;
  holdUntil:    number;   // unix ms — entry time + 2hrs
}

// ── Frozen universe ──────────────────────────────────────────────────────────
export const BOOF55_UNIVERSE = [
  'AAPL','AMZN','APP','ARM','AVGO','AXP','BLK','CAT','CVX','ENPH',
  'FANG','FCX','HD','IBM','LCID','LRCX','MDT','MRNA','MS','MSFT',
  'MU','ORCL','PANW','PLTR','RBLX','RIVN','SMCI','TTWO',
] as const;

// ── Config ───────────────────────────────────────────────────────────────────
const CFG = {
  GAP_MIN:      0.01,   // >1% gap
  RVOL_MIN:     1.5,    // >=1.5x relative volume
  STOP_PCT:     0.01,   // -1% hard stop
  HOLD_MS:      120 * 60 * 1000,  // 2 hours in ms
  RVOL_WINDOW:  20,     // trading days for avg volume baseline
  SIGNAL_START: { h: 9,  m: 30 },
  SIGNAL_END:   { h: 10, m: 0  },
};

// ── Helpers ──────────────────────────────────────────────────────────────────
function etTime(ts: number): { h: number; m: number } {
  const d = new Date(ts > 1e12 ? ts : ts * 1000);
  const et = new Date(d.toLocaleString('en-US', { timeZone: 'America/New_York' }));
  return { h: et.getHours(), m: et.getMinutes() };
}

function inSignalWindow(ts: number): boolean {
  const { h, m } = etTime(ts);
  const mins = h * 60 + m;
  const start = CFG.SIGNAL_START.h * 60 + CFG.SIGNAL_START.m;
  const end   = CFG.SIGNAL_END.h   * 60 + CFG.SIGNAL_END.m;
  return mins >= start && mins <= end;
}

function isToday(ts: number): boolean {
  const barDate = new Date(ts > 1e12 ? ts : ts * 1000).toDateString();
  return barDate === new Date().toDateString();
}

// ── Main signal function ─────────────────────────────────────────────────────
export function getBoof55Signal(candles: Candle[]): Boof55Result {
  const NONE: Boof55Result = {
    signal: 'none', price: 0, reason: 'no signal',
    gapPct: 0, rvol: 0, level: 'none', stopPrice: 0, holdUntil: 0,
  };

  if (candles.length < CFG.RVOL_WINDOW + 5) return { ...NONE, reason: 'not enough bars' };

  const curr = candles[candles.length - 1];
  const prev = candles[candles.length - 2];

  // ── Gate 1: signal window 09:30–10:00 ET ─────────────────────────────────
  if (!inSignalWindow(curr.time)) return { ...NONE, reason: 'outside signal window' };

  // ── Gate 2: today's bars only ─────────────────────────────────────────────
  if (!isToday(curr.time)) return { ...NONE, reason: 'stale bar' };

  // ── Identify today's first bar (09:30) for open + gap ────────────────────
  const todayBars = candles.filter(c => isToday(c.time));
  if (todayBars.length === 0) return { ...NONE, reason: 'no today bars' };
  const openBar   = todayBars[0];
  const openPrice = openBar.open;

  // ── Previous day close — last bar from yesterday ──────────────────────────
  const prevDayBars = candles.filter(c => !isToday(c.time));
  if (prevDayBars.length === 0) return { ...NONE, reason: 'no prev day bars' };
  const prevClose = prevDayBars[prevDayBars.length - 1].close;

  // ── Gate 3: gap > 1% ─────────────────────────────────────────────────────
  const gapPct = (openPrice - prevClose) / prevClose;
  if (gapPct <= CFG.GAP_MIN) {
    return { ...NONE, reason: `gap too small: ${(gapPct * 100).toFixed(2)}%` };
  }

  // ── Gate 4: RVOL >= 1.5 ──────────────────────────────────────────────────
  // Use last RVOL_WINDOW days' worth of first-bar volume as baseline
  // Approximate: sum today's volume so far vs avg bar volume over past window
  const histBars   = candles.filter(c => !isToday(c.time));
  const windowBars = histBars.slice(-CFG.RVOL_WINDOW * 390); // approx 20 days of 1m bars
  const avgVol     = windowBars.length > 0
    ? windowBars.reduce((s, c) => s + c.volume, 0) / windowBars.length
    : 0;
  const todayVol   = todayBars.reduce((s, c) => s + c.volume, 0);
  const todayAvgPerBar = todayBars.length > 0 ? todayVol / todayBars.length : 0;
  const rvol = avgVol > 0 ? todayAvgPerBar / avgVol : 0;

  if (rvol < CFG.RVOL_MIN) {
    return { ...NONE, reason: `RVOL too low: ${rvol.toFixed(2)}x`, gapPct: gapPct * 100, rvol };
  }

  // ── PDH: previous day high ────────────────────────────────────────────────
  const pdh = prevDayBars.length > 0
    ? Math.max(...prevDayBars.slice(-390).map(c => c.high))  // last ~1 day
    : null;

  // ── PMH: pre-market high (bars between 04:00–09:29 today) ────────────────
  const pmBars = candles.filter(c => {
    const { h, m } = etTime(c.time);
    return isToday(c.time) && (h < 9 || (h === 9 && m < 30));
  });
  const pmh = pmBars.length > 0 ? Math.max(...pmBars.map(c => c.high)) : null;

  // ── Gate 5: curr bar closes above PDH or PMH (breakout) ──────────────────
  const brokePDH = pdh !== null && prev.close <= pdh && curr.close > pdh;
  const brokePMH = pmh !== null && prev.close <= pmh && curr.close > pmh;

  if (!brokePDH && !brokePMH) {
    return {
      ...NONE,
      reason: `no PDH/PMH break (curr=${curr.close.toFixed(2)} PDH=${pdh?.toFixed(2)} PMH=${pmh?.toFixed(2)})`,
      gapPct: gapPct * 100, rvol,
    };
  }

  const level: 'PDH' | 'PMH' = brokePDH ? 'PDH' : 'PMH';
  const levelPrice = brokePDH ? pdh! : pmh!;
  const stopPrice  = parseFloat((curr.close * (1 - CFG.STOP_PCT)).toFixed(4));
  const holdUntil  = Date.now() + CFG.HOLD_MS;

  return {
    signal:    'buy',
    price:     curr.close,
    reason:    `BOOF55: gap=${(gapPct*100).toFixed(2)}% rvol=${rvol.toFixed(2)}x broke ${level}@${levelPrice.toFixed(2)} close=${curr.close.toFixed(2)}`,
    gapPct:    parseFloat((gapPct * 100).toFixed(3)),
    rvol:      parseFloat(rvol.toFixed(3)),
    level,
    stopPrice,
    holdUntil,
  };
}
