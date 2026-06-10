// =========================================================
// BOOF 19.0 V2 - 0DTE SCALPING FOR SPY/QQQ
// Event-Driven High-Quality System
// =========================================================

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface Boof19V2Result {
  signal: 'buy' | 'sell' | 'none';
  price: number;
  reason: string;
  setupType: string;
  regime: string;
  trendScore: number;
}

// =========================================================
// PARAMETERS
// =========================================================

const TARGET_SYMBOLS = ['SPY', 'QQQ'];

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

// Dynamic TP based on regime (Chop Specialist - always use chop TP)
const TP_CHOP = 0.20;
const TP_TREND = 0.20; // Same as chop since we only trade chop

// Multi-Candle Acceptance (disabled for more trades)
const CONTINUATION_CANDLES = 0;
const CONTINUATION_THRESHOLD = 0.0001;

// Distance Filters (relaxed for more trades)
const MAX_DISTANCE_FROM_VWAP = 0.015;
const MAX_DISTANCE_FROM_EMA = 0.012;
const MAX_DISTANCE_FROM_ORB = 0.025;

// =========================================================
// SYMBOL-SPECIFIC PROFILES
// =========================================================

const SPY_PROFILE = {
  mode: "mean_reversion",
  orbBreakoutPct: 0.003,        // 0.3%
  liquidityGrabPct: 0.003,     // 0.3%
  vwapDistance: 0.015,          // 1.5%
  takeProfitPct: 0.40,          // 40%
  stopLossPct: -0.15,           // -15%
  maxHoldMin: 6,                // 6 min
  requireChopRegime: true,
  trendTradesAllowed: false,
  name: "SPY_CHOP_ENGINE",
  exitLogic: "quick_scalp"     // SPY: quick profit or time exit
};

const QQQ_PROFILE = {
  mode: "momentum",
  orbBreakoutPct: 0.004,        // 0.4%
  liquidityGrabPct: 0.003,     // 0.3%
  vwapDistance: 0.02,          // 2.0%
  takeProfitPct: 0.40,          // 40%
  stopLossPct: -0.15,           // -15%
  maxHoldMin: 15,               // 15 min hold for trend
  requireChopRegime: false,
  trendTradesAllowed: true,
  name: "QQQ_MOMENTUM_ENGINE",
  exitLogic: "trend_follow",   // QQQ: hold if trend valid, exit if momentum breaks
  useTrailingStop: false,      // Disabled for now
  minHoldBeforeExit: 5         // Don't exit on first weakness (min 5 min hold)
};

function getProfile(symbol: string): any {
  return symbol === 'SPY' ? SPY_PROFILE : QQQ_PROFILE;
}

// Reversal Logic thresholds (defaults, overridden by profile)
const FAILED_BREAKDOWN_THRESHOLD = 0.002;
const FAILED_BREAKOUT_THRESHOLD = 0.002;
const LIQUIDITY_GRAB_THRESHOLD = 0.003;
const VWAP_RECLAIM_REVERSAL = true;

// Exit Engine
const UNDERLYING_TP_PCT = 0.012;
const UNDERLYING_SL_PCT = -0.004;
const VWAP_STOP_LOSS = true;
const ATR_TP_MULTIPLIER = 0.5;
const ATR_SL_MULTIPLIER = 0.3;
const MAX_HOLD_MINUTES = 15;  // Increased from 5 to 15 for structural moves
const FAST_STOP_MINUTES = 5;  // Increased from 2 to 5

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
    return true; // Always return true if no continuation required
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
  
  // Previous day high/low (simplified - use last 100 candles)
  const prevHigh = Math.max(...candles.slice(idx - 100, idx).map(c => c.high));
  const prevLow = Math.min(...candles.slice(idx - 100, idx).map(c => c.low));
  
  // Opening range (first 15 candles of current day - simplified)
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

export function generateSignalBoof19V2(candles: Candle[], symbol: string, tradeDirection: string = 'both'): Boof19V2Result {
  const profile = getProfile(symbol);
  
  if (candles.length < 50) {
    return { signal: 'none', price: candles[candles.length - 1].close, reason: 'Not enough data', setupType: 'none', regime: 'chop', trendScore: 0 };
  }
  
  if (!TARGET_SYMBOLS.includes(symbol)) {
    return { signal: 'none', price: candles[candles.length - 1].close, reason: 'Symbol not in target list (SPY/QQQ only)', setupType: 'none', regime: 'chop', trendScore: 0 };
  }
  
  const currentCandle = candles[candles.length - 1];
  const currentIndex = candles.length - 1;
  
  if (!isInTradeWindow(currentCandle.time)) {
    return { signal: 'none', price: currentCandle.close, reason: 'Outside trade window', setupType: 'none', regime: 'chop', trendScore: 0 };
  }
  
  // Detect regime
  const { regime, trendScore, reason: regimeReason } = detectRegime(candles, currentIndex);
  
  // Symbol-specific regime filter
  if (profile.requireChopRegime && regime !== 'chop') {
    return { signal: 'none', price: currentCandle.close, reason: `Filter: ${regime} regime (chop only)`, setupType: 'none', regime, trendScore };
  }
  if (!profile.trendTradesAllowed && (regime === 'strong_trend' || regime === 'weak_trend')) {
    return { signal: 'none', price: currentCandle.close, reason: `Filter: ${regime} regime (trend disabled)`, setupType: 'none', regime, trendScore };
  }
  
  // Calculate structural levels
  const levels = calculateStructuralLevels(candles, currentIndex);
  
  // Distance Filters (profile-driven)
  const { ok: distanceOk, reason: distanceReason } = checkDistanceFilters(candles, currentIndex, levels, profile.vwapDistance);
  if (!distanceOk) {
    return { signal: 'none', price: currentCandle.close, reason: distanceReason, setupType: 'none', regime, trendScore };
  }
  
  // Reversal-Based Logic
  const vwapValues = vwap(candles);
  const currentVwap = vwapValues[currentIndex];
  
  // Failed breakdown reversal (long) - symbol-specific threshold
  if (detectFailedBreakdown(candles, currentIndex, levels.prevLow, profile.liquidityGrabPct)) {
    if (checkMultiCandleContinuation(candles, currentIndex, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
      if (tradeDirection === 'both' || tradeDirection === 'long') {
        return { signal: 'buy', price: currentCandle.close, reason: `Failed breakdown reversal (prev low) - ${regime}`, setupType: 'reversal', regime, trendScore };
      }
    }
  }
  
  // Failed breakout reversal (short) - symbol-specific threshold
  if (detectFailedBreakout(candles, currentIndex, levels.prevHigh, profile.liquidityGrabPct)) {
    if (checkMultiCandleContinuation(candles, currentIndex, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
      if (tradeDirection === 'both' || tradeDirection === 'short') {
        return { signal: 'sell', price: currentCandle.close, reason: `Failed breakout reversal (prev high) - ${regime}`, setupType: 'reversal', regime, trendScore };
      }
    }
  }
  
  // Liquidity grab reversal - symbol-specific threshold
  if (detectLiquidityGrab(candles, currentIndex, levels.orHigh, profile.liquidityGrabPct)) {
    if (checkMultiCandleContinuation(candles, currentIndex, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
      if (tradeDirection === 'both' || tradeDirection === 'short') {
        return { signal: 'sell', price: currentCandle.close, reason: `Liquidity grab reversal (OR high) - ${regime}`, setupType: 'reversal', regime, trendScore };
      }
    }
  }
  
  if (detectLiquidityGrab(candles, currentIndex, levels.orLow, profile.liquidityGrabPct)) {
    if (checkMultiCandleContinuation(candles, currentIndex, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
      if (tradeDirection === 'both' || tradeDirection === 'long') {
        return { signal: 'buy', price: currentCandle.close, reason: `Liquidity grab reversal (OR low) - ${regime}`, setupType: 'reversal', regime, trendScore };
      }
    }
  }
  
  // VWAP reclaim reversal (SPY only - mean reversion)
  if (profile.mode === 'mean_reversion' && VWAP_RECLAIM_REVERSAL) {
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
  
  // Structural level breakout with continuation (symbol-specific threshold)
  if (currentCandle.close > levels.orHigh * (1 + profile.orbBreakoutPct)) {
    if (checkMultiCandleContinuation(candles, currentIndex, 'buy', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
      if (tradeDirection === 'both' || tradeDirection === 'long') {
        return { signal: 'buy', price: currentCandle.close, reason: `OR breakout - ${regime}`, setupType: 'breakout', regime, trendScore };
      }
    }
  }
  
  if (currentCandle.close < levels.orLow * (1 - profile.orbBreakoutPct)) {
    if (checkMultiCandleContinuation(candles, currentIndex, 'sell', CONTINUATION_CANDLES, CONTINUATION_THRESHOLD)) {
      if (tradeDirection === 'both' || tradeDirection === 'short') {
        return { signal: 'sell', price: currentCandle.close, reason: `OR breakdown - ${regime}`, setupType: 'breakout', regime, trendScore };
      }
    }
  }
  
  return { signal: 'none', price: currentCandle.close, reason: 'No high-quality setup', setupType: 'none', regime, trendScore };
}

// =========================================================
// PROFILE-DRIVEN EXIT LOGIC
// =========================================================

export interface ExitResult {
  shouldExit: boolean;
  exitPrice: number;
  exitReason: string;
}

export function generateExitBoof19V2(
  candles: Candle[],
  symbol: string,
  positionDirection: 'LONG' | 'SHORT',
  entryPrice: number,
  entryTime: number,
  maxFavorableMove: number = 0
): ExitResult {
  const profile = getProfile(symbol);
  const currentCandle = candles[candles.length - 1];
  const currentPrice = currentCandle.close;
  const now = currentCandle.time;
  const holdMinutes = (now - entryTime) / 60000; // Convert to minutes
  const underlyingMove = (currentPrice - entryPrice) / entryPrice;
  
  // Detect current regime for trend-following logic
  const { regime } = detectRegime(candles, candles.length - 1);
  
  if (profile.exitLogic === 'quick_scalp') {
    // SPY: quick profit or time exit
    if (positionDirection === 'LONG' && underlyingMove >= profile.takeProfitPct) {
      return { shouldExit: true, exitPrice: currentPrice, exitReason: `Quick TP (${(underlyingMove * 100).toFixed(2)}%)` };
    }
    if (positionDirection === 'SHORT' && Math.abs(underlyingMove) >= profile.takeProfitPct) {
      return { shouldExit: true, exitPrice: currentPrice, exitReason: `Quick TP (${(Math.abs(underlyingMove) * 100).toFixed(2)}%)` };
    }
    if (holdMinutes >= profile.maxHoldMin) {
      return { shouldExit: true, exitPrice: currentPrice, exitReason: `Time exit (${holdMinutes.toFixed(1)} min)` };
    }
    if (positionDirection === 'LONG' && underlyingMove <= profile.stopLossPct) {
      return { shouldExit: true, exitPrice: currentPrice, exitReason: `SL hit (${(underlyingMove * 100).toFixed(2)}%)` };
    }
    if (positionDirection === 'SHORT' && Math.abs(underlyingMove) <= Math.abs(profile.stopLossPct)) {
      return { shouldExit: true, exitPrice: currentPrice, exitReason: `SL hit (${(Math.abs(underlyingMove) * 100).toFixed(2)}%)` };
    }
  } else if (profile.exitLogic === 'trend_follow') {
    // QQQ: hold if trend valid, exit if momentum breaks
    const trendStillValid = regime === 'strong_trend' || regime === 'weak_trend';
    
    // Track max favorable move for trailing stop
    let currentMaxFavorable = maxFavorableMove;
    if (positionDirection === 'LONG') {
      currentMaxFavorable = Math.max(currentMaxFavorable, underlyingMove);
    } else {
      currentMaxFavorable = Math.max(currentMaxFavorable, Math.abs(underlyingMove));
    }
    
    // Trailing stop logic (protect winners)
    if (profile.useTrailingStop && holdMinutes > 3) {
      const trailingStopThreshold = currentMaxFavorable - profile.trailingStopPct;
      if (positionDirection === 'LONG' && underlyingMove < trailingStopThreshold) {
        return { shouldExit: true, exitPrice: currentPrice, exitReason: `Trailing stop (${(underlyingMove * 100).toFixed(2)}%)` };
      }
      if (positionDirection === 'SHORT' && Math.abs(underlyingMove) < trailingStopThreshold) {
        return { shouldExit: true, exitPrice: currentPrice, exitReason: `Trailing stop (${(Math.abs(underlyingMove) * 100).toFixed(2)}%)` };
      }
    }
    
    // Don't exit on first weakness (min hold time)
    const minHold = profile.minHoldBeforeExit || 0;
    
    if (positionDirection === 'LONG' && underlyingMove >= profile.takeProfitPct) {
      return { shouldExit: true, exitPrice: currentPrice, exitReason: `Trend TP (${(underlyingMove * 100).toFixed(2)}%)` };
    }
    if (positionDirection === 'SHORT' && Math.abs(underlyingMove) >= profile.takeProfitPct) {
      return { shouldExit: true, exitPrice: currentPrice, exitReason: `Trend TP (${(Math.abs(underlyingMove) * 100).toFixed(2)}%)` };
    }
    if (!trendStillValid && holdMinutes > minHold) {
      return { shouldExit: true, exitPrice: currentPrice, exitReason: `Trend broken (${regime})` };
    }
    if (holdMinutes >= profile.maxHoldMin) {
      return { shouldExit: true, exitPrice: currentPrice, exitReason: `Max time exit (${holdMinutes.toFixed(1)} min)` };
    }
    if (positionDirection === 'LONG' && underlyingMove <= profile.stopLossPct) {
      return { shouldExit: true, exitPrice: currentPrice, exitReason: `SL hit (${(underlyingMove * 100).toFixed(2)}%)` };
    }
    if (positionDirection === 'SHORT' && Math.abs(underlyingMove) <= Math.abs(profile.stopLossPct)) {
      return { shouldExit: true, exitPrice: currentPrice, exitReason: `SL hit (${(Math.abs(underlyingMove) * 100).toFixed(2)}%)` };
    }
  }
  
  return { shouldExit: false, exitPrice: currentPrice, exitReason: 'hold' };
}
