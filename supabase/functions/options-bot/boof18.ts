// =========================================================
// BOOF 18.0 - ORB + COMPRESSION + REGIME FILTER
// Ported from Python backtest_boof18.py
// =========================================================

interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface Boof18Signal {
  time: number;
  price: number;
  side: 'LONG' | 'SHORT';
  or_high: number;
  or_low: number;
  volume: number;
  atr: number;
  candle_body: number;
  avg_body: number;
  avg_range: number;
  avg_last_5_range: number;
  signal_type: 'orb_compression' | 'vwap_ema_bounce';
  regime: 'EXPANSION' | 'TRANSITION' | 'CHOP';
}

interface Boof18Result {
  signal: 'buy' | 'sell' | 'none';
  price: number;
  reason: string;
  regime: string;
  signal_type: string;
  orb_strength: number;
}

// Constants
const OR_MINUTES = 15;
const COMPRESSION_LOOKBACK = 5;
const COMPRESSION_THRESHOLD = 0.9;
const RANGE_ROLLING_PERIOD = 20;
const VOLUME_SPIKE_MULTIPLIER = 1.1;
const ATR_EXPANSION_THRESHOLD = 1.2;
const ATR_TRANSITION_THRESHOLD = 1.0;
const TREND_CONSISTENCY_THRESHOLD = 0.6;
const TREND_TRANSITION_THRESHOLD = 0.4;
const ORB_BREAKOUT_STRENGTH_THRESHOLD = 0.3;
const SYMBOL_SCORE_THRESHOLD = 60;

// Trade windows (UTC)
const TRADE_WINDOWS = [
  { start: '13:35', end: '15:00' },  // Morning session
  { start: '17:30', end: '19:00' },  // Afternoon session - CUT OFF AT 12PM MST
];

// =========================================================
// UTILITY FUNCTIONS
// =========================================================

function ema(values: number[], period: number): number[] {
  const result: number[] = [];
  const multiplier = 2 / (period + 1);
  
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      result.push(values[i]);
    } else if (i === period - 1) {
      const sum = values.slice(0, period).reduce((a, b) => a + b, 0);
      result.push(sum / period);
    } else {
      result.push((values[i] - result[i - 1]) * multiplier + result[i - 1]);
    }
  }
  
  return result;
}

function atr(candles: Candle[], period: number): number[] {
  const tr: number[] = [];
  
  for (let i = 0; i < candles.length; i++) {
    if (i === 0) {
      tr.push(candles[i].high - candles[i].low);
    } else {
      const highLow = candles[i].high - candles[i].low;
      const highClose = Math.abs(candles[i].high - candles[i - 1].close);
      const lowClose = Math.abs(candles[i].low - candles[i - 1].close);
      tr.push(Math.max(highLow, highClose, lowClose));
    }
  }
  
  return ema(tr, period);
}

function vwap(candles: Candle[]): number[] {
  const result: number[] = [];
  let cumVolume = 0;
  let cumVolumePrice = 0;
  
  for (let i = 0; i < candles.length; i++) {
    const typicalPrice = (candles[i].high + candles[i].low + candles[i].close) / 3;
    cumVolume += candles[i].volume;
    cumVolumePrice += typicalPrice * candles[i].volume;
    result.push(cumVolumePrice / cumVolume);
  }
  
  return result;
}

function isInTradeWindow(timestamp: number): boolean {
  const date = new Date(timestamp);
  const hour = date.getUTCHours();
  const minute = date.getUTCMinutes();
  const timeMinutes = hour * 60 + minute;
  
  for (const window of TRADE_WINDOWS) {
    const [startHour, startMin] = window.start.split(':').map(Number);
    const [endHour, endMin] = window.end.split(':').map(Number);
    const startMinutes = startHour * 60 + startMin;
    const endMinutes = endHour * 60 + endMin;
    
    if (startMinutes <= timeMinutes && timeMinutes <= endMinutes) {
      return true;
    }
  }
  
  return false;
}

function isLunchtime(timestamp: number): boolean {
  const date = new Date(timestamp);
  const hour = date.getUTCHours();
  const minute = date.getUTCMinutes();
  const timeMinutes = hour * 60 + minute;
  return 960 <= timeMinutes && timeMinutes <= 1020;  // 16:00-17:00 UTC
}

// =========================================================
// OPENING RANGE CALCULATION
// =========================================================

interface ORResult {
  or_high: Map<string, number>;
  or_low: Map<string, number>;
}

function calculateOr(candles: Candle[], minutes: number = OR_MINUTES): ORResult {
  const or_high = new Map<string, number>();
  const or_low = new Map<string, number>();
  
  // Group by date
  const byDate = new Map<string, Candle[]>();
  for (const candle of candles) {
    const date = new Date(candle.time);
    const dateKey = date.toISOString().split('T')[0];
    if (!byDate.has(dateKey)) {
      byDate.set(dateKey, []);
    }
    byDate.get(dateKey)!.push(candle);
  }
  
  for (const [date, group] of byDate) {
    const sorted = group.sort((a, b) => a.time - b.time);
    const orCandles = sorted.slice(0, minutes);
    
    if (orCandles.length > 0) {
      or_high.set(date, Math.max(...orCandles.map(c => c.high)));
      or_low.set(date, Math.min(...orCandles.map(c => c.low)));
    } else {
      or_high.set(date, sorted[0].high);
      or_low.set(date, sorted[0].low);
    }
  }
  
  return { or_high, or_low };
}

// =========================================================
// REGIME DETECTION
// =========================================================

function detectRegime(candles: Candle[]): Map<string, 'EXPANSION' | 'TRANSITION' | 'CHOP'> {
  const regimeByDate = new Map<string, 'EXPANSION' | 'TRANSITION' | 'CHOP'>();
  
  // Group by date
  const byDate = new Map<string, Candle[]>();
  for (const candle of candles) {
    const date = new Date(candle.time);
    const dateKey = date.toISOString().split('T')[0];
    if (!byDate.has(dateKey)) {
      byDate.set(dateKey, []);
    }
    byDate.get(dateKey)!.push(candle);
  }
  
  // Calculate ORB ranges for median
  const { or_high, or_low } = calculateOr(candles, OR_MINUTES);
  const orbRanges: number[] = [];
  
  for (const [date] of byDate) {
    const orbH = or_high.get(date) || 0;
    const orbL = or_low.get(date) || 0;
    orbRanges.push(orbH - orbL);
  }
  
  const medianOrbRange = orbRanges.length > 0 
    ? orbRanges.sort((a, b) => a - b)[Math.floor(orbRanges.length / 2)] 
    : 0;
  
  for (const [date, group] of byDate) {
    const sorted = group.sort((a, b) => a.time - b.time);
    
    if (sorted.length < 60) {
      regimeByDate.set(date, 'CHOP');
      continue;
    }
    
    // Calculate ATR
    const atrValues = atr(sorted, 14);
    const dayAtr = atrValues[atrValues.length - 1] || 0;
    const avgAtr = atrValues.length >= 20 ? atrValues[atrValues.length - 1] : dayAtr;
    
    // ATR expansion check
    const atrExpansion = avgAtr > 0 ? dayAtr > (avgAtr * ATR_EXPANSION_THRESHOLD) : false;
    const atrTransition = avgAtr > 0 ? dayAtr > (avgAtr * ATR_TRANSITION_THRESHOLD) : false;
    
    // ORB range check
    const todayOrbRange = (or_high.get(date) || sorted[0].high) - (or_low.get(date) || sorted[0].low);
    const orbExpansion = medianOrbRange > 0 ? todayOrbRange > medianOrbRange : false;
    
    // Trend consistency check
    const firstHour = sorted.slice(0, 60);
    let higherHighs = 0;
    let lowerLows = 0;
    
    if (firstHour.length >= 10) {
      const highs = firstHour.map(c => c.high);
      const lows = firstHour.map(c => c.low);
      
      for (let i = 2; i < highs.length; i++) {
        if (highs[i] > highs[i - 1] && highs[i - 1] > highs[i - 2]) higherHighs++;
        if (lows[i] < lows[i - 1] && lows[i - 1] < lows[i - 2]) lowerLows++;
      }
      
      const totalSwings = higherHighs + lowerLows;
      const trendConsistency = totalSwings > 0 ? Math.max(higherHighs, lowerLows) / totalSwings : 0;
      
      const trendStrong = trendConsistency >= TREND_CONSISTENCY_THRESHOLD;
      const trendMixed = trendConsistency >= TREND_TRANSITION_THRESHOLD;
      
      // VWAP behavior check
      const vwapValues = vwap(sorted).slice(0, 60);
      const closeValues = sorted.slice(0, 60).map(c => c.close);
      
      let crosses = 0;
      for (let i = 1; i < vwapValues.length; i++) {
        const prevAbove = closeValues[i - 1] > vwapValues[i - 1];
        const currAbove = closeValues[i] > vwapValues[i];
        if (prevAbove !== currAbove) crosses++;
      }
      
      const vwapMeanReversion = crosses > 10;
      
      // Classify regime
      if (atrExpansion && orbExpansion && trendStrong) {
        regimeByDate.set(date, 'EXPANSION');
      } else if (atrTransition && trendMixed && !vwapMeanReversion) {
        regimeByDate.set(date, 'TRANSITION');
      } else {
        regimeByDate.set(date, 'CHOP');
      }
    } else {
      regimeByDate.set(date, 'CHOP');
    }
  }
  
  return regimeByDate;
}

// =========================================================
// SIGNAL GENERATION
// =========================================================

function generateSignalBoof18(
  candles: Candle[],
  symbolScore: number = 50
): Boof18Result {
  if (candles.length < 60) {
    return {
      signal: 'none',
      price: candles[candles.length - 1].close,
      reason: 'Not enough candles',
      regime: 'CHOP',
      signal_type: 'none',
      orb_strength: 0
    };
  }
  
  // Calculate indicators
  const atrValues = atr(candles, 14);
  const vwapValues = vwap(candles);
  const ema9Values = ema(candles.map(c => c.close), 9);
  
  // Calculate candle ranges and bodies
  const candleRanges = candles.map(c => c.high - c.low);
  const candleBodies = candles.map(c => Math.abs(c.close - c.open));
  const avgRanges: number[] = [];
  const avgBodies: number[] = [];
  
  for (let i = 0; i < candleRanges.length; i++) {
    const start = Math.max(0, i - RANGE_ROLLING_PERIOD + 1);
    const slice = candleRanges.slice(start, i + 1);
    avgRanges.push(slice.reduce((a, b) => a + b, 0) / slice.length);
    
    const bodySlice = candleBodies.slice(start, i + 1);
    avgBodies.push(bodySlice.reduce((a, b) => a + b, 0) / bodySlice.length);
  }
  
  // Calculate Opening Range
  const { or_high, or_low } = calculateOr(candles, OR_MINUTES);
  
  // Detect regime
  const regimeByDate = detectRegime(candles);
  
  const currentCandle = candles[candles.length - 1];
  const currentDate = new Date(currentCandle.time);
  const currentDateKey = currentDate.toISOString().split('T')[0];
  const regime = regimeByDate.get(currentDateKey) || 'CHOP';
  
  // Trade window check
  if (!isInTradeWindow(currentCandle.time)) {
    return {
      signal: 'none',
      price: currentCandle.close,
      reason: 'Outside trade window',
      regime,
      signal_type: 'none',
      orb_strength: 0
    };
  }
  
  // Skip lunchtime
  if (isLunchtime(currentCandle.time)) {
    return {
      signal: 'none',
      price: currentCandle.close,
      reason: 'Lunchtime chop',
      regime,
      signal_type: 'none',
      orb_strength: 0
    };
  }
  
  // Regime switch - CHOP overrides everything
  if (regime === 'CHOP') {
    return {
      signal: 'none',
      price: currentCandle.close,
      reason: 'CHOP regime - no trades',
      regime,
      signal_type: 'none',
      orb_strength: 0
    };
  }
  
  // Skip if before OR is established (first 15 minutes)
  const hour = currentDate.getUTCHours();
  const minute = currentDate.getUTCMinutes();
  if (hour < 13 || (hour === 13 && minute < 45)) {
    return {
      signal: 'none',
      price: currentCandle.close,
      reason: 'Before OR established',
      regime,
      signal_type: 'none',
      orb_strength: 0
    };
  }
  
  // Get OR for today
  const todayOrHigh = or_high.get(currentDateKey) || currentCandle.high;
  const todayOrLow = or_low.get(currentDateKey) || currentCandle.low;
  const orbRange = todayOrHigh - todayOrLow;
  
  // Check ORB breakout
  const breakoutUp = currentCandle.close > todayOrHigh;
  const breakoutDown = currentCandle.close < todayOrLow;
  
  if (!breakoutUp && !breakoutDown) {
    return {
      signal: 'none',
      price: currentCandle.close,
      reason: 'No ORB breakout',
      regime,
      signal_type: 'none',
      orb_strength: 0
    };
  }
  
  // Calculate ORB breakout strength
  const breakoutStrength = breakoutUp 
    ? (currentCandle.close - todayOrHigh) / (orbRange || 1)
    : (todayOrLow - currentCandle.close) / (orbRange || 1);
  
  // Trade quality filter - ORB breakout strength
  if (breakoutStrength < ORB_BREAKOUT_STRENGTH_THRESHOLD) {
    return {
      signal: 'none',
      price: currentCandle.close,
      reason: 'Weak ORB breakout',
      regime,
      signal_type: 'none',
      orb_strength: breakoutStrength
    };
  }
  
  // Trade quality filter - symbol score
  if (symbolScore < SYMBOL_SCORE_THRESHOLD) {
    return {
      signal: 'none',
      price: currentCandle.close,
      reason: 'Symbol score too low',
      regime,
      signal_type: 'none',
      orb_strength: breakoutStrength
    };
  }
  
  // Check compression filter
  const last5Ranges = candleRanges.slice(-COMPRESSION_LOOKBACK);
  const avgLast5Range = last5Ranges.reduce((a, b) => a + b, 0) / last5Ranges.length;
  const avgRange = avgRanges[avgRanges.length - 1] || 0;
  const compressionMet = avgLast5Range < (avgRange * COMPRESSION_THRESHOLD);
  
  if (!compressionMet) {
    return {
      signal: 'none',
      price: currentCandle.close,
      reason: 'No compression before breakout',
      regime,
      signal_type: 'none',
      orb_strength: breakoutStrength
    };
  }
  
  // Generate signal
  const side = breakoutUp ? 'LONG' : 'SHORT';
  
  return {
    signal: breakoutUp ? 'buy' : 'sell',
    price: currentCandle.close,
    reason: `ORB ${side} breakout with compression filter (${regime} regime)`,
    regime,
    signal_type: 'orb_compression',
    orb_strength: breakoutStrength
  };
}

// =========================================================
// EXPORT
// =========================================================

export { generateSignalBoof18, Boof18Result, Candle };
