// Boof 24.0 — Market Structure Break + Retest
// Step 1: ATR-based swing highs/lows
// Step 2: Market structure (HH/HL or LL/LH)
// Step 3: Structure break detection
// Step 4: Volume confirmation (1.25x avg)
// Step 5: Retest entry
// Step 6: Context filters (ATR > 40%, VWAP)
// Step 7: 2R/3R exits

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface Boof24Result {
  signal: 'buy' | 'sell' | 'none';
  price: number;
  reason: string;
  direction: 'LONG' | 'SHORT' | 'none';
  tpPct: number;
  slPct: number;
  slack: number;
  tier: 'core' | 'expanded';
  swingHigh?: number;
  swingLow?: number;
  trend?: 'bullish' | 'bearish' | 'neutral';
  msbPrice?: number;
  retestPrice?: number;
}

// Config
const CFG = {
  ATR_LEN: 14,
  VOL_LEN: 50,
  ATR_REV_MULT: 1.0,      // ATR reversal multiplier for swing detection
  VOL_MULT: 1.25,         // Volume confirmation multiplier
  ATR_PERCENTILE_MIN: 40, // Min ATR percentile for context filter
  RETEST_BARS: 5,         // How many bars to wait for retest
  TP_R: 2.0,              // Take profit at 2R
  SL_R: 1.0,              // Stop loss at 1R
};

// Compute ATR
function computeATR(candles: Candle[], period: number): number[] {
  const atr: number[] = new Array(candles.length).fill(0);
  for (let i = 1; i < candles.length; i++) {
    const high = candles[i].high;
    const low = candles[i].low;
    const prevClose = candles[i - 1].close;
    const tr = Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose));
    atr[i] = tr;
  }
  for (let i = period; i < candles.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += atr[j];
    atr[i] = sum / period;
  }
  return atr;
}

// Compute Volume SMA
function computeVolSMA(candles: Candle[], period: number): number[] {
  const vol = candles.map(c => c.volume ?? 0);
  const sma: number[] = new Array(candles.length).fill(0);
  for (let i = period - 1; i < candles.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += vol[j];
    sma[i] = sum / period;
  }
  return sma;
}

// Compute VWAP
function computeVWAP(candles: Candle[]): number[] {
  const vwap: number[] = new Array(candles.length).fill(0);
  let cumTPV = 0;
  let cumVol = 0;
  for (let i = 0; i < candles.length; i++) {
    const typicalPrice = (candles[i].high + candles[i].low + candles[i].close) / 3;
    const vol = candles[i].volume ?? 0;
    cumTPV += typicalPrice * vol;
    cumVol += vol;
    vwap[i] = cumVol > 0 ? cumTPV / cumVol : typicalPrice;
  }
  return vwap;
}

// ATR percentile (for context filter)
function computeATRPercentile(atr: number[], lookback = 50): number[] {
  const pct: number[] = new Array(atr.length).fill(0);
  for (let i = lookback; i < atr.length; i++) {
    const window = atr.slice(i - lookback, i + 1);
    const current = atr[i];
    const below = window.filter(v => v < current).length;
    pct[i] = (below / window.length) * 100;
  }
  return pct;
}

// Step 1: Find swing highs/lows using ATR reversal
interface Swing {
  index: number;
  price: number;
  type: 'high' | 'low';
}

function findSwings(candles: Candle[], atr: number[], atrMult = CFG.ATR_REV_MULT): Swing[] {
  const swings: Swing[] = [];
  let lastHigh = { index: 0, price: candles[0].high };
  let lastLow = { index: 0, price: candles[0].low };
  let direction: 'up' | 'down' | '' = '';

  for (let i = 1; i < candles.length; i++) {
    const c = candles[i];
    const currentATR = atr[i] || atr[i - 1] || 0.01;
    const revThreshold = currentATR * atrMult;

    // Check for swing high
    if (c.high > lastHigh.price) {
      lastHigh = { index: i, price: c.high };
    }
    // Check for swing low  
    if (c.low < lastLow.price) {
      lastLow = { index: i, price: c.low };
    }

    // Detect swing high confirmation (price reverses > 1 ATR from high)
    if (direction === 'up' && lastHigh.price - c.close > revThreshold) {
      swings.push({ index: lastHigh.index, price: lastHigh.price, type: 'high' });
      direction = 'down';
      lastLow = { index: i, price: c.low };
    }
    // Detect swing low confirmation (price reverses > 1 ATR from low)
    else if (direction === 'down' && c.close - lastLow.price > revThreshold) {
      swings.push({ index: lastLow.index, price: lastLow.price, type: 'low' });
      direction = 'up';
      lastHigh = { index: i, price: c.high };
    }
    // Initial direction
    else if (direction === '') {
      if (c.close > candles[0].high + revThreshold) direction = 'up';
      else if (c.close < candles[0].low - revThreshold) direction = 'down';
    }
  }

  return swings;
}

// Step 2 & 3: Build market structure and detect MSB
interface MarketStructure {
  trend: 'bullish' | 'bearish' | 'neutral';
  lastSwingHigh: number;
  lastSwingLow: number;
  lastSwingHighIdx: number;
  lastSwingLowIdx: number;
  msbBullish: boolean;
  msbBearish: boolean;
  msbPrice: number;
  recentHighs: number[];
  recentLows: number[];
}

function analyzeMarketStructure(candles: Candle[], swings: Swing[], minSwings = 4): MarketStructure {
  const n = candles.length;
  const recentSwings = swings.slice(-minSwings);
  
  if (recentSwings.length < minSwings) {
    return {
      trend: 'neutral',
      lastSwingHigh: candles[n - 1].high,
      lastSwingLow: candles[n - 1].low,
      lastSwingHighIdx: n - 1,
      lastSwingLowIdx: n - 1,
      msbBullish: false,
      msbBearish: false,
      msbPrice: 0,
      recentHighs: [],
      recentLows: [],
    };
  }

  const highs = recentSwings.filter(s => s.type === 'high').map(s => s.price);
  const lows = recentSwings.filter(s => s.type === 'low').map(s => s.price);
  
  const lastHigh = recentSwings.filter(s => s.type === 'high').pop();
  const lastLow = recentSwings.filter(s => s.type === 'low').pop();

  // Determine trend
  let trend: 'bullish' | 'bearish' | 'neutral' = 'neutral';
  if (highs.length >= 2 && lows.length >= 2) {
    const higherHighs = highs[highs.length - 1] > highs[highs.length - 2];
    const higherLows = lows[lows.length - 1] > lows[lows.length - 2];
    const lowerHighs = highs[highs.length - 1] < highs[highs.length - 2];
    const lowerLows = lows[lows.length - 1] < lows[lows.length - 2];

    if (higherHighs && higherLows) trend = 'bullish';
    else if (lowerHighs && lowerLows) trend = 'bearish';
  }

  // Check for MSB
  const currentClose = candles[n - 1].close;
  let msbBullish = false;
  let msbBearish = false;
  let msbPrice = 0;

  // Bullish MSB: Close above last lower high (in bearish structure)
  if (trend === 'bearish' && lastHigh) {
    const resistance = lastHigh.price;
    if (currentClose > resistance) {
      msbBullish = true;
      msbPrice = resistance;
    }
  }
  // Bearish MSB: Close below last higher low (in bullish structure)
  else if (trend === 'bullish' && lastLow) {
    const support = lastLow.price;
    if (currentClose < support) {
      msbBearish = true;
      msbPrice = support;
    }
  }

  return {
    trend,
    lastSwingHigh: lastHigh?.price || candles[n - 1].high,
    lastSwingLow: lastLow?.price || candles[n - 1].low,
    lastSwingHighIdx: lastHigh?.index || n - 1,
    lastSwingLowIdx: lastLow?.index || n - 1,
    msbBullish,
    msbBearish,
    msbPrice,
    recentHighs: highs.slice(-3),
    recentLows: lows.slice(-3),
  };
}

// Step 4: Volume confirmation
function checkVolumeConfirmation(candles: Candle[], idx: number): boolean {
  const volSMA = computeVolSMA(candles, CFG.VOL_LEN);
  const currentVol = candles[idx].volume ?? 0;
  const avgVol = volSMA[idx] || 1;
  return currentVol > avgVol * CFG.VOL_MULT;
}

// Step 5: Check for retest
interface RetestResult {
  valid: boolean;
  price: number;
  direction: 'LONG' | 'SHORT' | 'none';
}

function checkRetest(
  candles: Candle[], 
  msbPrice: number, 
  direction: 'LONG' | 'SHORT',
  barsToCheck = CFG.RETEST_BARS
): RetestResult {
  const n = candles.length;
  const startIdx = Math.max(0, n - barsToCheck - 5);
  
  if (direction === 'LONG') {
    // Look for pullback to retest broken resistance (now support)
    for (let i = startIdx; i < n; i++) {
      const low = candles[i].low;
      const close = candles[i].close;
      // Price came near the MSB level and bounced
      if (low <= msbPrice * 1.005 && close > msbPrice) {
        return { valid: true, price: msbPrice, direction: 'LONG' };
      }
    }
  } else {
    // Look for rally to retest broken support (now resistance)
    for (let i = startIdx; i < n; i++) {
      const high = candles[i].high;
      const close = candles[i].close;
      // Price came near the MSB level and rejected
      if (high >= msbPrice * 0.995 && close < msbPrice) {
        return { valid: true, price: msbPrice, direction: 'SHORT' };
      }
    }
  }
  
  return { valid: false, price: 0, direction: 'none' };
}

// Step 6: Context filters
function checkContextFilters(
  candles: Candle[], 
  atr: number[], 
  vwap: number[], 
  direction: 'LONG' | 'SHORT',
  idx: number
): { passed: boolean; reason: string } {
  // ATR percentile filter
  const atrPct = computeATRPercentile(atr);
  if (atrPct[idx] < CFG.ATR_PERCENTILE_MIN) {
    return { passed: false, reason: `ATR percentile ${atrPct[idx].toFixed(1)}% < ${CFG.ATR_PERCENTILE_MIN}%` };
  }

  // VWAP filter
  const currentClose = candles[idx].close;
  const currentVWAP = vwap[idx];
  
  if (direction === 'LONG' && currentClose < currentVWAP) {
    return { passed: false, reason: 'Price below VWAP' };
  }
  if (direction === 'SHORT' && currentClose > currentVWAP) {
    return { passed: false, reason: 'Price above VWAP' };
  }

  return { passed: true, reason: 'Context OK' };
}

// MAIN SIGNAL FUNCTION
export function getBoof24Signal(
  candles: Candle[], 
  symbol = 'NVDA', 
  tpPct = 0.35, 
  slPct = 0.15
): Boof24Result {
  const NONE: Boof24Result = {
    signal: 'none',
    price: 0,
    reason: 'no signal',
    direction: 'none',
    tpPct,
    slPct,
    slack: 0,
    tier: 'expanded',
  };

  const n = candles.length;
  if (n < 100) return { ...NONE, reason: 'not enough bars' };

  // Compute indicators
  const atr = computeATR(candles, CFG.ATR_LEN);
  const vwap = computeVWAP(candles);

  // Step 1: Find swings
  const swings = findSwings(candles, atr);
  if (swings.length < 6) return { ...NONE, reason: 'not enough swings' };

  // Step 2 & 3: Analyze structure
  const ms = analyzeMarketStructure(candles, swings);

  // Check for MSB
  if (!msb.ms && !msb.msbBearish) {
    return { ...NONE, reason: `no MSB (trend: ${ms.trend})` };
  }

  // Step 4: Volume confirmation
  if (!checkVolumeConfirmation(candles, n - 1)) {
    return { ...NONE, reason: 'volume too low' };
  }

  // Step 5: Check retest
  const direction = ms.msbBullish ? 'LONG' : 'SHORT';
  const retest = checkRetest(candles, ms.msbPrice, direction);
  if (!retest.valid) {
    return { ...NONE, reason: 'waiting for retest' };
  }

  // Step 6: Context filters
  const context = checkContextFilters(candles, atr, vwap, direction, n - 1);
  if (!context.passed) {
    return { ...NONE, reason: context.reason };
  }

  // Calculate entry price and risk
  const entryPrice = candles[n - 1].close;
  const currentATR = atr[n - 1] || 0.01;
  
  // Stop loss: Below swing low for longs, above swing high for shorts
  let stopDistance = 0;
  if (direction === 'LONG') {
    stopDistance = entryPrice - ms.lastSwingLow;
  } else {
    stopDistance = ms.lastSwingHigh - entryPrice;
  }
  
  // Ensure minimum stop distance (ATR-based floor)
  stopDistance = Math.max(stopDistance, currentATR * 0.5);

  // Calculate TP/SL percentages based on R-multiples
  const slPctCalc = (stopDistance / entryPrice) * 100;
  const tpPctCalc = slPctCalc * CFG.TP_R;

  // Calculate slack (quality score based on MSB strength)
  const msbStrength = ms.msbBullish 
    ? (entryPrice - ms.msbPrice) / currentATR 
    : (ms.msbPrice - entryPrice) / currentATR;
  const slack = Math.max(0, msbStrength);

  return {
    signal: direction === 'LONG' ? 'buy' : 'sell',
    price: entryPrice,
    reason: `B24 MSB ${direction} @ ${ms.msbPrice.toFixed(2)}, retest valid, trend: ${ms.trend}`,
    direction,
    tpPct: tpPctCalc / 100,
    slPct: -slPctCalc / 100,
    slack,
    tier: slack >= 1.0 ? 'core' : 'expanded',
    swingHigh: ms.lastSwingHigh,
    swingLow: ms.lastSwingLow,
    trend: ms.trend,
    msbPrice: ms.msbPrice,
    retestPrice: retest.price,
  };
}
