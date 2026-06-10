// =========================================================
// BOOF 19.0 - 0DTE SCALPING FOR SPY/QQQ
// Layered Signal Approach: Regime + ORB + Continuation
// =========================================================

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface Boof19Result {
  signal: 'buy' | 'sell' | 'none';
  price: number;
  reason: string;
  layer: string;
}

// =========================================================
// PARAMETERS
// =========================================================

// Target symbols
const TARGET_SYMBOLS = ['SPY', 'QQQ'];

// LAYER 1 — MARKET REGIME FILTER
const ATR_EXPANSION_MULTIPLIER = 1.1;
const ORB_RANGE_THRESHOLD = 1.0;
const VWAP_DISTANCE_THRESHOLD = 0.002;

// LAYER 2 — PRIMARY ORB ENTRY
const OR_MINUTES = 15;
const COMPRESSION_LOOKBACK = 5;
const COMPRESSION_THRESHOLD = 0.9;
const RANGE_ROLLING_PERIOD = 20;
const VOLUME_SPIKE_MULTIPLIER = 1.1;
const MIN_BODY_MULTIPLIER = 1.1;

// LAYER 3 — CONTINUATION ENTRIES
const EMA9_PERIOD = 9;
const PULLBACK_THRESHOLD = 0.001;
const REJECTION_BODY_RATIO = 0.6;
const RECOMPRESSION_ATR_THRESHOLD = 0.8;
const RECOMPRESSION_LOOKBACK = 10;
const VWAP_RECLAIM_THRESHOLD = 0.001;
const VWAP_LOSS_THRESHOLD = 0.001;

// Trend filter
const EMA_SLOPE_THRESHOLD = 0.0001;
const VWAP_TREND_OFFSET = 0.0005;

// Exit engine
const TAKE_PROFIT_PCT = 0.08;
const STOP_LOSS_PCT = -0.05;
const MAX_HOLD_MINUTES = 10;
const MOMENTUM_STALL_CANDLES = 3;

// Trade windows (UTC)
const TRADE_WINDOWS = [
  { startH: 13, startM: 35, endH: 15, endM: 0 },
  { startH: 17, startM: 30, endH: 19, endM: 0 },
];

// =========================================================
// HELPER FUNCTIONS
// =========================================================

function ema(data: number[], period: number): number[] {
  const result: number[] = [];
  const k = 2 / (period + 1);
  
  for (let i = 0; i < data.length; i++) {
    if (i === 0) {
      result.push(data[i]);
    } else {
      result.push(data[i] * k + result[i - 1] * (1 - k));
    }
  }
  
  return result;
}

function vwap(candles: Candle[]): number[] {
  const result: number[] = [];
  let cumulativeTPV = 0;
  let cumulativeVolume = 0;
  
  for (let i = 0; i < candles.length; i++) {
    const vol = candles[i].volume || 1000000;
    const tp = (candles[i].high + candles[i].low + candles[i].close) / 3;
    cumulativeTPV += tp * vol;
    cumulativeVolume += vol;
    result.push(cumulativeTPV / cumulativeVolume);
  }
  
  return result;
}

function atr(candles: Candle[], period: number): number[] {
  const result: number[] = [];
  const tr: number[] = [];
  
  for (let i = 0; i < candles.length; i++) {
    if (i === 0) {
      tr.push(candles[i].high - candles[i].low);
    } else {
      const hl = candles[i].high - candles[i].low;
      const hc = Math.abs(candles[i].high - candles[i - 1].close);
      const lc = Math.abs(candles[i].low - candles[i - 1].close);
      tr.push(Math.max(hl, hc, lc));
    }
  }
  
  for (let i = 0; i < tr.length; i++) {
    if (i < period - 1) {
      result.push(0);
    } else if (i === period - 1) {
      const sum = tr.slice(0, period).reduce((a, b) => a + b, 0);
      result.push(sum / period);
    } else {
      result.push((result[i - 1] * (period - 1) + tr[i]) / period);
    }
  }
  
  return result;
}

function isInTradeWindow(timestamp: number): boolean {
  const date = new Date(timestamp);
  const hour = date.getUTCHours();
  const minute = date.getUTCMinutes();
  const timeMinutes = hour * 60 + minute;
  
  for (const window of TRADE_WINDOWS) {
    const startMinutes = window.startH * 60 + window.startM;
    const endMinutes = window.endH * 60 + window.endM;
    
    if (startMinutes <= timeMinutes && timeMinutes < endMinutes) {
      return true;
    }
  }
  
  return false;
}

// =========================================================
// LAYER 1: MARKET REGIME FILTER
// =========================================================

function calculateOr(candles: Candle[], minutes: number = 15): {
  orHigh: Map<number, number>;
  orLow: Map<number, number>;
  orRange: Map<number, number>;
} {
  const orHigh = new Map<number, number>();
  const orLow = new Map<number, number>();
  const orRange = new Map<number, number>();
  
  const byDate = new Map<number, Candle[]>();
  for (const candle of candles) {
    const date = new Date(candle.time);
    const dateKey = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
    
    if (!byDate.has(dateKey)) {
      byDate.set(dateKey, []);
    }
    byDate.get(dateKey)!.push(candle);
  }
  
  for (const [dateKey, dayCandles] of byDate) {
    dayCandles.sort((a, b) => a.time - b.time);
    const orCandles = dayCandles.slice(0, minutes);
    
    if (orCandles.length > 0) {
      const high = Math.max(...orCandles.map(c => c.high));
      const low = Math.min(...orCandles.map(c => c.low));
      orHigh.set(dateKey, high);
      orLow.set(dateKey, low);
      orRange.set(dateKey, high - low);
    } else {
      orHigh.set(dateKey, dayCandles[0].high);
      orLow.set(dateKey, dayCandles[0].low);
      orRange.set(dateKey, dayCandles[0].high - dayCandles[0].low);
    }
  }
  
  return { orHigh, orLow, orRange };
}

function calculateAvgOrbRange(orRange: Map<number, number>, period: number = 20): Map<number, number> {
  const avgOrbRange = new Map<number, number>();
  const dates = Array.from(orRange.keys()).sort((a, b) => a - b);
  
  for (let i = 0; i < dates.length; i++) {
    if (i < period - 1) {
      avgOrbRange.set(dates[i], orRange.get(dates[i]) || 0);
    } else {
      const recentRanges = dates.slice(i - period + 1, i + 1).map(d => orRange.get(d) || 0);
      const avg = recentRanges.reduce((a, b) => a + b, 0) / recentRanges.length;
      avgOrbRange.set(dates[i], avg);
    }
  }
  
  return avgOrbRange;
}

function checkExpansionDay(candles: Candle[], idx: number, orRange: Map<number, number>, avgOrbRange: Map<number, number>): {
  isExpansion: boolean;
  reason: string;
} {
  if (idx < 20) {
    return { isExpansion: false, reason: 'Not enough data for regime check' };
  }
  
  const candle = candles[idx];
  const date = Date.UTC(
    new Date(candle.time).getUTCFullYear(),
    new Date(candle.time).getUTCMonth(),
    new Date(candle.time).getUTCDate()
  );
  
  const atrValues = atr(candles, 14);
  const atrAvg = ema(atrValues, 20);
  const atrExpansion = atrValues[idx] > atrAvg[idx] * ATR_EXPANSION_MULTIPLIER;
  
  const orbRange = orRange.get(date) || 0;
  const avgOrb = avgOrbRange.get(date) || 0;
  const orbExpansion = orbRange > avgOrb * ORB_RANGE_THRESHOLD;
  
  const vwapValues = vwap(candles);
  const vwapDistance = Math.abs(candle.close - vwapValues[idx]) / vwapValues[idx];
  const vwapExpansion = vwapDistance > VWAP_DISTANCE_THRESHOLD;
  
  const isExpansion = atrExpansion && orbExpansion && vwapExpansion;
  const reason = `ATR_exp=${atrExpansion}, ORB_exp=${orbExpansion}, VWAP_exp=${vwapExpansion}`;
  
  return { isExpansion, reason };
}

// =========================================================
// LAYER 2: PRIMARY ORB ENTRY
// =========================================================

function detectCompression(candles: Candle[], lookback: number = 5, threshold: number = 0.9): boolean[] {
  const ranges = candles.map(c => c.high - c.low);
  const rangeAvg = ema(ranges, lookback);
  
  return ranges.map((r, i) => r < rangeAvg[i] * threshold);
}

function detectOrbBreakout(candles: Candle[], orHigh: Map<number, number>, orLow: Map<number, number>, threshold: number = 0.002): {
  orbBreakoutLong: boolean[];
  orbBreakoutShort: boolean[];
} {
  const orbBreakoutLong: boolean[] = [];
  const orbBreakoutShort: boolean[] = [];
  
  for (let i = 0; i < candles.length; i++) {
    const candle = candles[i];
    const date = Date.UTC(
      new Date(candle.time).getUTCFullYear(),
      new Date(candle.time).getUTCMonth(),
      new Date(candle.time).getUTCDate()
    );
    
    const orbH = orHigh.get(date);
    const orbL = orLow.get(date);
    
    if (orbH !== undefined && orbL !== undefined) {
      orbBreakoutLong.push(candle.close > orbH * (1 + threshold));
      orbBreakoutShort.push(candle.close < orbL * (1 - threshold));
    } else {
      orbBreakoutLong.push(false);
      orbBreakoutShort.push(false);
    }
  }
  
  return { orbBreakoutLong, orbBreakoutShort };
}

// =========================================================
// LAYER 3: CONTINUATION ENTRIES
// =========================================================

function detectPullbackContinuation(candles: Candle[], emaPeriod: number = 9, pullbackThreshold: number = 0.001, rejectionRatio: number = 0.6): {
  pullbackContinuationLong: boolean[];
  pullbackContinuationShort: boolean[];
} {
  const closes = candles.map(c => c.close);
  const ema9 = ema(closes, emaPeriod);
  const vwapValues = vwap(candles);
  
  const pullbackEma = closes.map((c, i) => Math.abs(c - ema9[i]) / ema9[i] < pullbackThreshold);
  
  const bodies = candles.map(c => Math.abs(c.close - c.open));
  const ranges = candles.map(c => c.high - c.low);
  const bullishRejection = bodies.map((b, i) => (b / ranges[i] > rejectionRatio) && (candles[i].close > candles[i].open));
  const bearishRejection = bodies.map((b, i) => (b / ranges[i] > rejectionRatio) && (candles[i].close < candles[i].open));
  
  const pullbackContinuationLong = pullbackEma.map((p, i) => p && bullishRejection[i]);
  const pullbackContinuationShort = pullbackEma.map((p, i) => p && bearishRejection[i]);
  
  return { pullbackContinuationLong, pullbackContinuationShort };
}

function detectRecompressionBreak(candles: Candle[], atrThreshold: number = 0.8, lookback: number = 10): {
  recompressionBreakLong: boolean[];
  recompressionBreakShort: boolean[];
} {
  const atrValues = atr(candles, 14);
  const atrAvg = ema(atrValues, 20);
  const recompression = atrValues.map((a, i) => a < atrAvg[i] * atrThreshold);
  
  const highs = candles.map(c => c.high);
  const recentBreakout = highs.map((h, i) => i >= lookback ? h > Math.max(...highs.slice(i - lookback, i)) : false);
  
  const recompressionBreakLong = recompression.map((r, i) => i > 0 ? r && recentBreakout[i] && candles[i].close > candles[i].open : false);
  const recompressionBreakShort = recompression.map((r, i) => i > 0 ? r && recentBreakout[i] && candles[i].close < candles[i].open : false);
  
  return { recompressionBreakLong, recompressionBreakShort };
}

function detectVwapReclaim(candles: Candle[], reclaimThreshold: number = 0.001, lossThreshold: number = 0.001): boolean[] {
  const vwapValues = vwap(candles);
  const vwapDistance = candles.map((c, i) => (c.close - vwapValues[i]) / vwapValues[i]);
  const aboveVwap = vwapDistance.map(d => d > 0);
  
  const vwapLoss = aboveVwap.map((a, i) => i > 0 ? !a && aboveVwap[i - 1] : false);
  const vwapReclaim = aboveVwap.map((a, i) => i > 1 ? a && !aboveVwap[i - 1] && vwapLoss[i - 1] : false);
  
  return vwapReclaim;
}

function calculateEmaSlope(candles: Candle[], period: number = 9): number[] {
  const closes = candles.map(c => c.close);
  const emaValues = ema(closes, period);
  
  const emaSlope: number[] = [];
  for (let i = 0; i < emaValues.length; i++) {
    if (i === 0) {
      emaSlope.push(0);
    } else {
      emaSlope.push(emaValues[i] - emaValues[i - 1]);
    }
  }
  
  return emaSlope;
}

// =========================================================
// MAIN SIGNAL GENERATION (LAYERED APPROACH)
// =========================================================

export function generateSignalBoof19(candles: Candle[], symbol: string, tradeDirection: string = 'both'): Boof19Result {
  if (candles.length < 50) {
    return { signal: 'none', price: candles[candles.length - 1].close, reason: 'Not enough data', layer: 'none' };
  }
  
  if (!TARGET_SYMBOLS.includes(symbol)) {
    return { signal: 'none', price: candles[candles.length - 1].close, reason: 'Symbol not in target list (SPY/QQQ only)', layer: 'none' };
  }
  
  const currentCandle = candles[candles.length - 1];
  const currentIndex = candles.length - 1;
  
  if (!isInTradeWindow(currentCandle.time)) {
    return { signal: 'none', price: currentCandle.close, reason: 'Outside trade window', layer: 'none' };
  }
  
  const { orHigh, orLow, orRange } = calculateOr(candles, OR_MINUTES);
  const avgOrbRange = calculateAvgOrbRange(orRange, 20);
  
  const { isExpansion, reason: regimeReason } = checkExpansionDay(candles, currentIndex, orRange, avgOrbRange);
  if (!isExpansion) {
    return { signal: 'none', price: currentCandle.close, reason: `Layer 1: Not expansion day (${regimeReason})`, layer: '1' };
  }
  
  const compression = detectCompression(candles, COMPRESSION_LOOKBACK, COMPRESSION_THRESHOLD);
  const { orbBreakoutLong, orbBreakoutShort } = detectOrbBreakout(candles, orHigh, orLow, 0.002);
  
  if (orbBreakoutLong[currentIndex] && compression[currentIndex]) {
    const volumes = candles.map(c => c.volume || 1000000);
    const volumeAvg = ema(volumes, 5);
    const volumeExpansion = (candles[currentIndex].volume || 1000000) > volumeAvg[currentIndex] * VOLUME_SPIKE_MULTIPLIER;
    
    if (volumeExpansion) {
      return { signal: 'buy', price: currentCandle.close, reason: 'Layer 2: ORB breakout with compression and volume', layer: '2' };
    }
  }
  
  if (orbBreakoutShort[currentIndex] && compression[currentIndex]) {
    const volumes = candles.map(c => c.volume || 1000000);
    const volumeAvg = ema(volumes, 5);
    const volumeExpansion = (candles[currentIndex].volume || 1000000) > volumeAvg[currentIndex] * VOLUME_SPIKE_MULTIPLIER;
    
    if (volumeExpansion) {
      return { signal: 'sell', price: currentCandle.close, reason: 'Layer 2: ORB breakout with compression and volume', layer: '2' };
    }
  }
  
  const { pullbackContinuationLong, pullbackContinuationShort } = detectPullbackContinuation(candles, EMA9_PERIOD, PULLBACK_THRESHOLD, REJECTION_BODY_RATIO);
  const { recompressionBreakLong, recompressionBreakShort } = detectRecompressionBreak(candles, RECOMPRESSION_ATR_THRESHOLD, RECOMPRESSION_LOOKBACK);
  const vwapReclaim = detectVwapReclaim(candles, VWAP_RECLAIM_THRESHOLD, VWAP_LOSS_THRESHOLD);
  const emaSlope = calculateEmaSlope(candles, EMA9_PERIOD);
  
  if (pullbackContinuationLong[currentIndex] && (tradeDirection === 'both' || tradeDirection === 'long')) {
    return { signal: 'buy', price: currentCandle.close, reason: 'Layer 3A: Pullback continuation long', layer: '3A' };
  }
  
  if (pullbackContinuationShort[currentIndex] && (tradeDirection === 'both' || tradeDirection === 'short')) {
    return { signal: 'sell', price: currentCandle.close, reason: 'Layer 3A: Pullback continuation short', layer: '3A' };
  }
  
  if (recompressionBreakLong[currentIndex] && (tradeDirection === 'both' || tradeDirection === 'long')) {
    return { signal: 'buy', price: currentCandle.close, reason: 'Layer 3B: Re-compression break long', layer: '3B' };
  }
  
  if (recompressionBreakShort[currentIndex] && (tradeDirection === 'both' || tradeDirection === 'short')) {
    return { signal: 'sell', price: currentCandle.close, reason: 'Layer 3B: Re-compression break short', layer: '3B' };
  }
  
  if (vwapReclaim[currentIndex]) {
    if (emaSlope[currentIndex] > EMA_SLOPE_THRESHOLD && (tradeDirection === 'both' || tradeDirection === 'long')) {
      return { signal: 'buy', price: currentCandle.close, reason: 'Layer 3C: VWAP reclaim with bullish trend', layer: '3C' };
    } else if (emaSlope[currentIndex] < -EMA_SLOPE_THRESHOLD && (tradeDirection === 'both' || tradeDirection === 'short')) {
      return { signal: 'sell', price: currentCandle.close, reason: 'Layer 3C: VWAP reclaim with bearish trend', layer: '3C' };
    }
  }
  
  return { signal: 'none', price: currentCandle.close, reason: 'No signal (all layers checked)', layer: 'none' };
}
