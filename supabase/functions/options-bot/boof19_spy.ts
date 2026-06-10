// =========================================================
// BOOF 19.0 SPY - 0DTE MEAN REVERSION SCALPING
// Chop Specialist - Quick Scalp Exit Logic
// =========================================================

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface Boof19SpyResult {
  signal: 'buy' | 'sell' | 'none';
  price: number;
  reason: string;
  setupType: string;
  regime: string;
  trendScore: number;
}

// =========================================================
// SPY-SPECIFIC PROFILE
// =========================================================

const SPY_PROFILE = {
  mode: "mean_reversion",
  orbBreakoutPct: 0.0035,       // 0.35%
  liquidityGrabPct: 0.0035,    // 0.35%
  vwapDistance: 0.016,          // 1.6%
  takeProfitPct: 0.20,          // 20%
  stopLossPct: -0.10,           // -10%
  maxHoldMin: 6,                // 6 min
  requireChopRegime: true,
  trendTradesAllowed: false,
  name: "SPY_CHOP_ENGINE",
  exitLogic: "quick_scalp"
};

// =========================================================
// PARAMETERS
// =========================================================

const TARGET_SYMBOL = 'SPY';

// Regime Detection
const VWAP_SLOPE_STRONG = 0.0001;
const VWAP_SLOPE_FLAT = 0.00002;
const EMA9_PERIOD = 9;
const EMA21_PERIOD = 21;
const EMA_SPREAD_EXPANDING = 0.0005;
const EMA_SPREAD_COMPRESSING = 0.0001;
const ADX_PROXY_PERIOD = 14;
const ADX_PROXY_HIGH = 0.002;
const ADX_PROXY_LOW = 0.0005;
const HTF_VWAP_DISTANCE = 0.001;

// Multi-Candle Acceptance
const CONTINUATION_CANDLES = 0;
const CONTINUATION_THRESHOLD = 0.0001;

// Distance Filters
const MAX_DISTANCE_FROM_VWAP = 0.015;
const MAX_DISTANCE_FROM_EMA = 0.012;
const MAX_DISTANCE_FROM_ORB = 0.025;

// Reversal Logic thresholds
const FAILED_BREAKDOWN_THRESHOLD = 0.002;
const FAILED_BREAKOUT_THRESHOLD = 0.002;
const LIQUIDITY_GRAB_THRESHOLD = 0.003;
const VWAP_RECLAIM_REVERSAL = true;

// Trade Windows (UTC)
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
// REGIME DETECTION
// =========================================================

function detectRegime(candles: Candle[], idx: number): { regime: string; trendScore: number; reason: string } {
  if (idx < 30) {
    return { regime: 'chop', trendScore: 0, reason: 'Not enough data' };
  }
  
  let trendScore = 0;
  
  // 1. VWAP slope
  const vwapValues = vwap(candles);
  const vwapSlope = (vwapValues[idx] - vwapValues[idx - 10]) / vwapValues[idx - 10];
  if (Math.abs(vwapSlope) >= VWAP_SLOPE_STRONG) {
    trendScore += 30;
  } else if (Math.abs(vwapSlope) <= VWAP_SLOPE_FLAT) {
    trendScore -= 10;
  }
  
  // 2. EMA separation
  const ema9Values = ema(candles.map(c => c.close), EMA9_PERIOD);
  const ema21Values = ema(candles.map(c => c.close), EMA21_PERIOD);
  const emaSpread = Math.abs(ema9Values[idx] - ema21Values[idx]) / ema21Values[idx];
  
  const emaSpreadPrev = Math.abs(ema9Values[idx - 5] - ema21Values[idx - 5]) / ema21Values[idx - 5];
  if (emaSpread > emaSpreadPrev * 1.1 && emaSpread > EMA_SPREAD_EXPANDING) {
    trendScore += 25;
  } else if (emaSpread < EMA_SPREAD_COMPRESSING) {
    trendScore -= 10;
  }
  
  // 3. ADX proxy
  let totalMove = 0;
  let totalRange = 0;
  for (let i = idx - ADX_PROXY_PERIOD; i < idx; i++) {
    if (i >= 0) {
      totalMove += Math.abs(candles[i].close - candles[i].open);
      totalRange += candles[i].high - candles[i].low;
    }
  }
  const adxProxy = totalRange > 0 ? totalMove / totalRange : 0;
  
  if (adxProxy >= ADX_PROXY_HIGH) {
    trendScore += 25;
  } else if (adxProxy <= ADX_PROXY_LOW) {
    trendScore -= 10;
  }
  
  // 4. Higher timeframe alignment
  const priceVsVwap = (candles[idx].close - vwapValues[idx]) / vwapValues[idx];
  const ema9Slope = (ema9Values[idx] - ema9Values[idx - 5]) / ema9Values[idx - 5];
  
  if (priceVsVwap > HTF_VWAP_DISTANCE && ema9Slope > 0) {
    trendScore += 20;
  } else if (priceVsVwap < -HTF_VWAP_DISTANCE && ema9Slope < 0) {
    trendScore += 20;
  } else if (Math.abs(priceVsVwap) < HTF_VWAP_DISTANCE) {
    trendScore -= 10;
  }
  
  // Classify regime
  let regime: string;
  if (trendScore >= 70) {
    regime = 'strong_trend';
  } else if (trendScore >= 40) {
    regime = 'weak_trend';
  } else {
    regime = 'chop';
  }
  
  const reason = `Score=${trendScore}, VWAP_slope=${vwapSlope.toFixed(5)}, EMA_spread=${emaSpread.toFixed(4)}, ADX_proxy=${adxProxy.toFixed(3)}`;
  
  return { regime, trendScore, reason };
}

// =========================================================
// MULTI-CANDLE ACCEPTANCE
// =========================================================

function checkMultiCandleContinuation(candles: Candle[], idx: number, direction: 'buy' | 'sell', numCandles: number = 0, threshold: number = 0.0001): boolean {
  if (numCandles === 0) {
    return true;
  }
  
  if (idx < numCandles) {
    return false;
  }
  
  for (let i = 1; i <= numCandles; i++) {
    const candle = candles[idx - i];
    const prevCandle = candles[idx - i - 1];
    
    if (direction === 'buy') {
      if (candle.close <= prevCandle.close) {
        return false;
      }
      if ((candle.close - prevCandle.close) / prevCandle.close < threshold) {
        return false;
      }
    } else {
      if (candle.close >= prevCandle.close) {
        return false;
      }
      if ((prevCandle.close - candle.close) / prevCandle.close < threshold) {
        return false;
      }
    }
  }
  
  return true;
}

// =========================================================
// STRUCTURAL LEVELS
// =========================================================

function calculateStructuralLevels(candles: Candle[], idx: number): {
  prevHigh: number;
  prevLow: number;
  orHigh: number;
  orLow: number;
} {
  if (idx < 100) {
    return { prevHigh: candles[idx].high, prevLow: candles[idx].low, orHigh: candles[idx].high, orLow: candles[idx].low };
  }
  
  const prevHigh = Math.max(...candles.slice(idx - 100, idx).map(c => c.high));
  const prevLow = Math.min(...candles.slice(idx - 100, idx).map(c => c.low));
  
  const orHigh = Math.max(...candles.slice(Math.max(0, idx - 15), idx).map(c => c.high));
  const orLow = Math.min(...candles.slice(Math.max(0, idx - 15), idx).map(c => c.low));
  
  return { prevHigh, prevLow, orHigh, orLow };
}

// =========================================================
// DISTANCE FILTERS
// =========================================================

function checkDistanceFilters(candles: Candle[], idx: number, levels: any, maxDistanceVwap: number = MAX_DISTANCE_FROM_VWAP): { ok: boolean; reason: string } {
  const candle = candles[idx];
  const vwapValues = vwap(candles);
  const emaValues = ema(candles.map(c => c.close), 9);
  
  const vwapDistance = Math.abs(candle.close - vwapValues[idx]) / vwapValues[idx];
  if (vwapDistance > maxDistanceVwap) {
    return { ok: false, reason: `Too far from VWAP (${(vwapDistance * 100).toFixed(2)}%)` };
  }
  
  const emaDistance = Math.abs(candle.close - emaValues[idx]) / emaValues[idx];
  if (emaDistance > MAX_DISTANCE_FROM_EMA) {
    return { ok: false, reason: `Too far from EMA (${(emaDistance * 100).toFixed(2)}%)` };
  }
  
  const orDistance = Math.abs(candle.close - levels.orHigh) / levels.orHigh;
  if (orDistance > MAX_DISTANCE_FROM_ORB) {
    return { ok: false, reason: `Too far from ORB (${(orDistance * 100).toFixed(2)}%)` };
  }
  
  return { ok: true, reason: 'Distance filters passed' };
}

// =========================================================
// REVERSAL-BASED LOGIC
// =========================================================

function detectFailedBreakdown(candles: Candle[], idx: number, level: number, threshold: number = FAILED_BREAKDOWN_THRESHOLD): boolean {
  if (idx < 5) {
    return false;
  }
  
  const recentLow = Math.min(...candles.slice(idx - 5, idx).map(c => c.low));
  if (recentLow < level * (1 - threshold)) {
    if (candles[idx].close > level) {
      return true;
    }
  }
  return false;
}

function detectFailedBreakout(candles: Candle[], idx: number, level: number, threshold: number = FAILED_BREAKOUT_THRESHOLD): boolean {
  if (idx < 5) {
    return false;
  }
  
  const recentHigh = Math.max(...candles.slice(idx - 5, idx).map(c => c.high));
  if (recentHigh > level * (1 + threshold)) {
    if (candles[idx].close < level) {
      return true;
    }
  }
  return false;
}

function detectLiquidityGrab(candles: Candle[], idx: number, level: number, threshold: number = LIQUIDITY_GRAB_THRESHOLD): boolean {
  if (idx < 3) {
    return false;
  }
  
  if (candles[idx - 1].high > level * (1 + threshold)) {
    if (candles[idx].close < level) {
      return true;
    }
  }
  if (candles[idx - 1].low < level * (1 - threshold)) {
    if (candles[idx].close > level) {
      return true;
    }
  }
  
  return false;
}

// =========================================================
// MAIN SIGNAL GENERATION
// =========================================================

export function generateSignalBoof19Spy(candles: Candle[], symbol: string, tradeDirection: string = 'both'): Boof19SpyResult {
  if (candles.length < 50) {
    return { signal: 'none', price: candles[candles.length - 1].close, reason: 'Not enough data', setupType: 'none', regime: 'chop', trendScore: 0 };
  }
  
  if (symbol !== TARGET_SYMBOL) {
    return { signal: 'none', price: candles[candles.length - 1].close, reason: 'Symbol not SPY', setupType: 'none', regime: 'chop', trendScore: 0 };
  }
  
  const currentCandle = candles[candles.length - 1];
  const currentIndex = candles.length - 1;
  
  if (!isInTradeWindow(currentCandle.time)) {
    return { signal: 'none', price: currentCandle.close, reason: 'Outside trade window', setupType: 'none', regime: 'chop', trendScore: 0 };
  }
  
  // Detect regime
  const { regime, trendScore, reason: regimeReason } = detectRegime(candles, currentIndex);
  
  // SPY: only trade in chop
  if (SPY_PROFILE.requireChopRegime && regime !== 'chop') {
    return { signal: 'none', price: currentCandle.close, reason: `Filter: ${regime} regime (chop only)`, setupType: 'none', regime, trendScore };
  }
  
  // Calculate structural levels
  const levels = calculateStructuralLevels(candles, currentIndex);
  
  // Distance Filters
  const { ok: distanceOk, reason: distanceReason } = checkDistanceFilters(candles, currentIndex, levels, SPY_PROFILE.vwapDistance);
  if (!distanceOk) {
    return { signal: 'none', price: currentCandle.close, reason: distanceReason, setupType: 'none', regime, trendScore };
  }
  
  // Reversal-Based Logic
  const vwapValues = vwap(candles);
  const currentVwap = vwapValues[currentIndex];
  
  // Failed breakdown reversal (long)
  if (detectFailedBreakdown(candles, currentIndex, levels.prevLow, SPY_PROFILE.liquidityGrabPct)) {
    if (checkMultiCandleContinuation(candles, currentIndex, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
      if (tradeDirection === 'both' || tradeDirection === 'long') {
        return { signal: 'buy', price: currentCandle.close, reason: `Failed breakdown reversal - ${regime}`, setupType: 'reversal', regime, trendScore };
      }
    }
  }
  
  // Failed breakout reversal (short)
  if (detectFailedBreakout(candles, currentIndex, levels.prevHigh, SPY_PROFILE.liquidityGrabPct)) {
    if (checkMultiCandleContinuation(candles, currentIndex, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
      if (tradeDirection === 'both' || tradeDirection === 'short') {
        return { signal: 'sell', price: currentCandle.close, reason: `Failed breakout reversal - ${regime}`, setupType: 'reversal', regime, trendScore };
      }
    }
  }
  
  // Liquidity grab reversal
  if (detectLiquidityGrab(candles, currentIndex, levels.orHigh, SPY_PROFILE.liquidityGrabPct)) {
    if (checkMultiCandleContinuation(candles, currentIndex, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
      if (tradeDirection === 'both' || tradeDirection === 'short') {
        return { signal: 'sell', price: currentCandle.close, reason: `Liquidity grab reversal - ${regime}`, setupType: 'reversal', regime, trendScore };
      }
    }
  }
  
  if (detectLiquidityGrab(candles, currentIndex, levels.orLow, SPY_PROFILE.liquidityGrabPct)) {
    if (checkMultiCandleContinuation(candles, currentIndex, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
      if (tradeDirection === 'both' || tradeDirection === 'long') {
        return { signal: 'buy', price: currentCandle.close, reason: `Liquidity grab reversal - ${regime}`, setupType: 'reversal', regime, trendScore };
      }
    }
  }
  
  // VWAP reclaim reversal (mean reversion)
  if (VWAP_RECLAIM_REVERSAL) {
    const vwapDistance = (currentCandle.close - currentVwap) / currentVwap;
    if (Math.abs(vwapDistance) < 0.001 && vwapDistance > 0) {
      if (checkMultiCandleContinuation(candles, currentIndex, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
        if (tradeDirection === 'both' || tradeDirection === 'long') {
          return { signal: 'buy', price: currentCandle.close, reason: `VWAP reclaim reversal - ${regime}`, setupType: 'reversal', regime, trendScore };
        }
      }
    } else if (Math.abs(vwapDistance) < 0.001 && vwapDistance < 0) {
      if (checkMultiCandleContinuation(candles, currentIndex, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
        if (tradeDirection === 'both' || tradeDirection === 'short') {
          return { signal: 'sell', price: currentCandle.close, reason: `VWAP reclaim reversal - ${regime}`, setupType: 'reversal', regime, trendScore };
        }
      }
    }
  }
  
  // Structural level breakout
  if (currentCandle.close > levels.orHigh * (1 + SPY_PROFILE.orbBreakoutPct)) {
    if (checkMultiCandleContinuation(candles, currentIndex, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
      if (tradeDirection === 'both' || tradeDirection === 'long') {
        return { signal: 'buy', price: currentCandle.close, reason: `OR breakout - ${regime}`, setupType: 'breakout', regime, trendScore };
      }
    }
  }
  
  if (currentCandle.close < levels.orLow * (1 - SPY_PROFILE.orbBreakoutPct)) {
    if (checkMultiCandleContinuation(candles, currentIndex, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
      if (tradeDirection === 'both' || tradeDirection === 'short') {
        return { signal: 'sell', price: currentCandle.close, reason: `OR breakdown - ${regime}`, setupType: 'breakout', regime, trendScore };
      }
    }
  }
  
  return { signal: 'none', price: currentCandle.close, reason: 'No high-quality setup', setupType: 'none', regime, trendScore };
}

// =========================================================
// EXIT LOGIC
// =========================================================

export interface ExitResult {
  shouldExit: boolean;
  exitPrice: number;
  exitReason: string;
}

export function generateExitBoof19Spy(
  candles: Candle[],
  symbol: string,
  positionDirection: 'LONG' | 'SHORT',
  entryPrice: number,
  entryTime: number
): ExitResult {
  const currentCandle = candles[candles.length - 1];
  const currentPrice = currentCandle.close;
  const now = currentCandle.time;
  const holdMinutes = (now - entryTime) / 60000;
  const underlyingMove = (currentPrice - entryPrice) / entryPrice;
  
  // SPY: quick profit or time exit
  if (positionDirection === 'LONG' && underlyingMove >= SPY_PROFILE.takeProfitPct) {
    return { shouldExit: true, exitPrice: currentPrice, exitReason: `Quick TP (${(underlyingMove * 100).toFixed(2)}%)` };
  }
  if (positionDirection === 'SHORT' && Math.abs(underlyingMove) >= SPY_PROFILE.takeProfitPct) {
    return { shouldExit: true, exitPrice: currentPrice, exitReason: `Quick TP (${(Math.abs(underlyingMove) * 100).toFixed(2)}%)` };
  }
  if (holdMinutes >= SPY_PROFILE.maxHoldMin) {
    return { shouldExit: true, exitPrice: currentPrice, exitReason: `Time exit (${holdMinutes.toFixed(1)} min)` };
  }
  if (positionDirection === 'LONG' && underlyingMove <= SPY_PROFILE.stopLossPct) {
    return { shouldExit: true, exitPrice: currentPrice, exitReason: `SL hit (${(underlyingMove * 100).toFixed(2)}%)` };
  }
  if (positionDirection === 'SHORT' && Math.abs(underlyingMove) <= Math.abs(SPY_PROFILE.stopLossPct)) {
    return { shouldExit: true, exitPrice: currentPrice, exitReason: `SL hit (${(Math.abs(underlyingMove) * 100).toFixed(2)}%)` };
  }
  
  return { shouldExit: false, exitPrice: currentPrice, exitReason: 'hold' };
}
