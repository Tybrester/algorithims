// =========================================================
// BOOF 24.0 — ICT/MSB Swing Break + Retest Strategy
// Based on backtest: 0.75x ATR + Retest + 1.25x Volume + VWAP
// Target: 0.156 R/T
// =========================================================
// Architecture:
//   Step 1: ATR-based swing detection
//   Step 2: Market structure analysis (HH/HL/LH/LL)
//   Step 3: MSB (Market Structure Break) detection
//   Step 4: Volume confirmation (1.25x SMA)
//   Step 5: Retest check (price returns to broken level)
//   Step 6: Context filters (ATR percentile > 40%, VWAP)
//   Entry: 2:1 R/R (TP=2R, SL=1R)
// =========================================================

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Boof24Result {
  signal: 'buy' | 'sell' | 'none';
  price: number;
  reason: string;
  direction: 'LONG' | 'SHORT' | 'none';
  tpPct: number;
  slPct: number;
  entryPrice?: number;
  stopLoss?: number;
  takeProfit?: number;
  msbType?: string;
  rMultiple?: number;
}

// ── CONFIG ──────────────────────────────────────────
const CFG = {
  ATR_LEN: 14,
  VOL_LEN: 50,
  ATR_REV_MULT: 0.75,      // Swing detection threshold
  VOL_MULT: 1.25,          // Volume confirmation
  ATR_PERCENTILE_MIN: 40,  // ATR must be > 40th percentile
  RETEST_BARS: 5,          // Lookback for retest
  TP_R: 2.0,               // 2:1 R/R
  SL_R: 1.0,
  MIN_SWINGS: 6,           // Need at least 6 swings
};

// ── ATR Calculation ─────────────────────────────────
function computeATR(candles: Candle[], period: number): number[] {
  const tr: number[] = [];
  tr.push(candles[0].high - candles[0].low);
  for (let i = 1; i < candles.length; i++) {
    const tr1 = candles[i].high - candles[i].low;
    const tr2 = Math.abs(candles[i].high - candles[i - 1].close);
    const tr3 = Math.abs(candles[i].low - candles[i - 1].close);
    tr.push(Math.max(tr1, tr2, tr3));
  }
  // Simple moving average for ATR
  const atr: number[] = [];
  for (let i = 0; i < tr.length; i++) {
    if (i < period - 1) {
      atr.push(tr[i]);
    } else {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) sum += tr[j];
      atr.push(sum / period);
    }
  }
  return atr;
}

// ── VWAP Calculation ────────────────────────────────
function computeVWAP(candles: Candle[]): number[] {
  let cumTPVol = 0;
  let cumVol = 0;
  const vwap: number[] = [];
  for (const c of candles) {
    const tp = (c.high + c.low + c.close) / 3;
    cumTPVol += tp * c.volume;
    cumVol += c.volume;
    vwap.push(cumVol > 0 ? cumTPVol / cumVol : c.close);
  }
  return vwap;
}

// ── ATR Percentile ──────────────────────────────────
function computeATRPercentile(atr: number[], lookback: number): number[] {
  const result: number[] = [];
  for (let i = 0; i < atr.length; i++) {
    if (i < lookback) {
      result.push(50);
      continue;
    }
    let count = 0;
    for (let j = i - lookback + 1; j <= i; j++) {
      if (atr[j] < atr[i]) count++;
    }
    result.push((count / lookback) * 100);
  }
  return result;
}

// ── Swing Detection (ATR-based) ────────────────────
interface Swing { idx: number; price: number; type: 'high' | 'low'; }

function findSwings(candles: Candle[], atr: number[]): Swing[] {
  const swings: Swing[] = [];
  if (candles.length < 2) return swings;

  let lastHigh = { idx: 0, price: candles[0].high };
  let lastLow = { idx: 0, price: candles[0].low };
  let direction: 'up' | 'down' | '' = '';

  for (let i = 1; i < candles.length; i++) {
    const currentATR = atr[i] || 0.01;
    const threshold = currentATR * CFG.ATR_REV_MULT;

    if (candles[i].high > lastHigh.price) {
      lastHigh = { idx: i, price: candles[i].high };
    }
    if (candles[i].low < lastLow.price) {
      lastLow = { idx: i, price: candles[i].low };
    }

    const close = candles[i].close;

    if (direction === 'up' && lastHigh.price - close > threshold) {
      swings.push({ idx: lastHigh.idx, price: lastHigh.price, type: 'high' });
      direction = 'down';
      lastLow = { idx: i, price: candles[i].low };
    } else if (direction === 'down' && close - lastLow.price > threshold) {
      swings.push({ idx: lastLow.idx, price: lastLow.price, type: 'low' });
      direction = 'up';
      lastHigh = { idx: i, price: candles[i].high };
    } else if (direction === '') {
      if (close > candles[0].high + threshold) direction = 'up';
      else if (close < candles[0].low - threshold) direction = 'down';
    }
  }
  return swings;
}

// ── Market Structure Analysis ─────────────────────
interface MarketStructure {
  trend: 'bullish' | 'bearish' | 'neutral';
  msbBull: boolean;
  msbBear: boolean;
  msbPrice: number;
  lastHigh: number;
  lastLow: number;
}

function analyzeStructure(candles: Candle[], swings: Swing[]): MarketStructure | null {
  if (swings.length < 4) return null;

  const recent = swings.slice(-4);
  const highs = recent.filter(s => s.type === 'high');
  const lows = recent.filter(s => s.type === 'low');

  if (highs.length < 2 || lows.length < 2) return null;

  // Trend detection
  let trend: 'bullish' | 'bearish' | 'neutral' = 'neutral';
  const hh = highs[highs.length - 1].price > highs[highs.length - 2].price;
  const hl = lows[lows.length - 1].price > lows[lows.length - 2].price;
  const lh = highs[highs.length - 1].price < highs[highs.length - 2].price;
  const ll = lows[lows.length - 1].price < lows[lows.length - 2].price;

  if (hh && hl) trend = 'bullish';
  else if (lh && ll) trend = 'bearish';

  // MSB detection
  const close = candles[candles.length - 1].close;
  let msbBull = false;
  let msbBear = false;
  let msbPrice = 0;

  if (trend === 'bearish' && highs.length > 0) {
    const lastHighPrice = highs[highs.length - 1].price;
    if (close > lastHighPrice) {
      msbBull = true;
      msbPrice = lastHighPrice;
    }
  } else if (trend === 'bullish' && lows.length > 0) {
    const lastLowPrice = lows[lows.length - 1].price;
    if (close < lastLowPrice) {
      msbBear = true;
      msbPrice = lastLowPrice;
    }
  }

  return {
    trend,
    msbBull,
    msbBear,
    msbPrice,
    lastHigh: highs[highs.length - 1]?.price || candles[candles.length - 1].high,
    lastLow: lows[lows.length - 1]?.price || candles[candles.length - 1].low,
  };
}

// ── Volume Confirmation ─────────────────────────────
function checkVolume(candles: Candle[], idx: number, volSMA: number[]): boolean {
  if (idx < CFG.VOL_LEN) return false;
  return candles[idx].volume > volSMA[idx] * CFG.VOL_MULT;
}

// ── Retest Check ────────────────────────────────────
function checkRetest(candles: Candle[], msbPrice: number, direction: 'LONG' | 'SHORT'): boolean {
  const n = candles.length;
  const start = Math.max(0, n - CFG.RETEST_BARS - 5);
  
  for (let i = start; i < n; i++) {
    if (direction === 'LONG') {
      // Price touched below MSB then closed above
      if (candles[i].low <= msbPrice * 1.005 && candles[i].close > msbPrice) {
        return true;
      }
    } else {
      // Price touched above MSB then closed below
      if (candles[i].high >= msbPrice * 0.995 && candles[i].close < msbPrice) {
        return true;
      }
    }
  }
  return false;
}

// ── Volume SMA ─────────────────────────────────────
function computeVolSMA(candles: Candle[], period: number): number[] {
  const result: number[] = [];
  for (let i = 0; i < candles.length; i++) {
    if (i < period - 1) {
      result.push(candles[i].volume);
    } else {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) {
        sum += candles[j].volume;
      }
      result.push(sum / period);
    }
  }
  return result;
}

// ── MAIN BOOF 24 SIGNAL ─────────────────────────────
export function getBoof24Signal(
  candles: Candle[],
  symbol = 'NVDA',
  _spyCandles?: Candle[]
): Boof24Result {
  const n = candles.length;
  const minLen = Math.max(CFG.ATR_LEN, CFG.VOL_LEN) + 100;
  
  if (n < minLen) {
    return { signal: 'none', price: candles[n - 1]?.close || 0, reason: 'Need more data', direction: 'none', tpPct: 0, slPct: 0 };
  }

  const atr = computeATR(candles, CFG.ATR_LEN);
  const vwap = computeVWAP(candles);
  const atrPct = computeATRPercentile(atr, 50);
  const volSMA = computeVolSMA(candles, CFG.VOL_LEN);

  const i = n - 1;
  const currentATR = atr[i];
  const currentVWAP = vwap[i];
  const currentATRPct = atrPct[i];
  const close = candles[i].close;

  // Step 1: Find swings
  const swings = findSwings(candles, atr);
  if (swings.length < CFG.MIN_SWINGS) {
    return { signal: 'none', price: close, reason: 'Insufficient swings', direction: 'none', tpPct: 0, slPct: 0 };
  }

  // Step 2 & 3: Structure + MSB
  const ms = analyzeStructure(candles, swings);
  if (!ms || (!ms.msbBull && !ms.msbBear)) {
    return { signal: 'none', price: close, reason: 'No MSB', direction: 'none', tpPct: 0, slPct: 0 };
  }

  const direction: 'LONG' | 'SHORT' = ms.msbBull ? 'LONG' : 'SHORT';

  // Step 4: Volume confirmation
  if (!checkVolume(candles, i, volSMA)) {
    return { signal: 'none', price: close, reason: 'Volume check failed', direction: 'none', tpPct: 0, slPct: 0, msbType: direction };
  }

  // Step 5: Retest check
  if (!checkRetest(candles, ms.msbPrice, direction)) {
    return { signal: 'none', price: close, reason: 'No retest', direction: 'none', tpPct: 0, slPct: 0, msbType: direction };
  }

  // Step 6: Context filters
  if (currentATRPct < CFG.ATR_PERCENTILE_MIN) {
    return { signal: 'none', price: close, reason: 'ATR percentile too low', direction: 'none', tpPct: 0, slPct: 0, msbType: direction };
  }

  if (direction === 'LONG' && close < currentVWAP) {
    return { signal: 'none', price: close, reason: 'Below VWAP', direction: 'none', tpPct: 0, slPct: 0, msbType: direction };
  }
  if (direction === 'SHORT' && close > currentVWAP) {
    return { signal: 'none', price: close, reason: 'Above VWAP', direction: 'none', tpPct: 0, slPct: 0, msbType: direction };
  }

  // Calculate entry, SL, TP
  const entry = close;
  let sl: number, tp: number;
  
  if (direction === 'LONG') {
    sl = entry - currentATR * CFG.SL_R;
    tp = entry + currentATR * CFG.TP_R;
  } else {
    sl = entry + currentATR * CFG.SL_R;
    tp = entry - currentATR * CFG.TP_R;
  }

  const signal: 'buy' | 'sell' = direction === 'LONG' ? 'buy' : 'sell';
  const tpPct = (tp - entry) / entry;
  const slPct = Math.abs(sl - entry) / entry;

  return {
    signal,
    price: entry,
    reason: `B24 MSB ${direction}: trend=${ms.trend}, MSB=${ms.msbPrice.toFixed(2)}, ATRpct=${currentATRPct.toFixed(1)}`,
    direction,
    tpPct,
    slPct,
    entryPrice: entry,
    stopLoss: sl,
    takeProfit: tp,
    msbType: ms.trend,
    rMultiple: CFG.TP_R / CFG.SL_R,
  };
}
