// =========================================================
// BOOF 26.0 — Hybrid Strategy
// Layer 1: Boof 22 — Volume Cluster + Fractal Detection
// Layer 2: Boof 23 — ZigZag Regime Filter  
// Layer 3: Boof 24 — MSB Confirmation + Retest
// Result: Fewer, higher-quality trades with multi-layer confirmation
// =========================================================

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Boof26Result {
  signal: 'buy' | 'sell' | 'none';
  price: number;
  reason: string;
  direction: 'LONG' | 'SHORT' | 'none';
  entryPrice?: number;
  stopLoss?: number;
  takeProfit?: number;
  tpPct: number;
  slPct: number;
  tier: 'core' | 'expanded';
  layersPassed: number;
}

// ── CONFIG ─────────────────────────────────────────────
const CFG = {
  // Layer 1 (Boof 22) — Clusters
  ATR_LEN: 14,
  VOL_LEN: 50,
  FRACTAL_BARS: 3,
  ATR_MULT: 0.6,
  CLUSTER_MERGE: 0.5,
  SR_STRENGTH_MIN: 2,
  SR_DIST_MAX: 1.0,
  VOL_MULT: 1.3,
  
  // Layer 2 (Boof 23) — ZigZag
  ZZ_PROX_BARS: 30,
  
  // Layer 3 (Boof 24) — MSB/Retest
  ATR_REV_MULT: 0.75,
  VOL_MULT_MS: 1.25,
  ATR_PERCENTILE_MIN: 40,
  RETEST_BARS: 5,
  
  // R/R (Boof 24 style)
  TP_R: 2.0,
  SL_R: 1.0,
};

interface Cluster { price: number; strength: number; }

// ── ATR ───────────────────────────────────────────────
function computeATR(candles: Candle[], period: number): number[] {
  const atr: number[] = new Array(candles.length).fill(0);
  for (let i = 1; i < candles.length; i++) {
    const tr = Math.max(
      candles[i].high - candles[i].low,
      Math.abs(candles[i].high - candles[i-1].close),
      Math.abs(candles[i].low - candles[i-1].close)
    );
    atr[i] = i < period ? tr : atr[i-1] * (period-1)/period + tr/period;
  }
  return atr;
}

// ── Volume SMA ───────────────────────────────────────
function computeVolSMA(candles: Candle[], period: number): number[] {
  const sma: number[] = new Array(candles.length).fill(0);
  for (let i = period; i < candles.length; i++) {
    let sum = 0;
    for (let j = i - period; j < i; j++) sum += candles[j].volume;
    sma[i] = sum / period;
  }
  return sma;
}

// ── VWAP ─────────────────────────────────────────────
function computeVWAP(candles: Candle[]): number[] {
  let cumTPVol = 0, cumVol = 0;
  return candles.map(c => {
    const tp = (c.high + c.low + c.close) / 3;
    cumTPVol += tp * c.volume;
    cumVol += c.volume;
    return cumVol > 0 ? cumTPVol / cumVol : c.close;
  });
}

// ── ATR Percentile ───────────────────────────────────
function computeATRPercentile(atr: number[], lookback: number): number[] {
  const result: number[] = [];
  for (let i = 0; i < atr.length; i++) {
    if (i < lookback) { result.push(50); continue; }
    let count = 0;
    for (let j = i - lookback + 1; j <= i; j++) {
      if (atr[j] < atr[i]) count++;
    }
    result.push((count / lookback) * 100);
  }
  return result;
}

// ── LAYER 1: Build Volume Clusters (Boof 22) ─────────
function buildClusters(candles: Candle[], atr: number[]): Cluster[] {
  const volSMA = computeVolSMA(candles, CFG.VOL_LEN);
  const avgATR = atr.filter(v => v > 0).reduce((a,b) => a+b, 0) / atr.filter(v => v > 0).length || 1;
  const mergeTol = avgATR * CFG.CLUSTER_MERGE;
  const buckets: Cluster[] = [];
  
  for (let i = CFG.VOL_LEN; i < candles.length; i++) {
    if (candles[i].volume < volSMA[i] * CFG.VOL_MULT) continue;
    const price = (candles[i].high + candles[i].low) / 2;
    let merged = false;
    for (const b of buckets) {
      if (Math.abs(b.price - price) <= mergeTol) {
        b.price = (b.price * b.strength + price) / (b.strength + 1);
        b.strength++;
        merged = true;
        break;
      }
    }
    if (!merged) buckets.push({ price, strength: 1 });
  }
  
  return buckets.filter(b => b.strength >= CFG.SR_STRENGTH_MIN);
}

function nearestCluster(price: number, clusters: Cluster[], atr: number): { dist: number; cluster: Cluster | null } {
  if (!clusters.length || !atr) return { dist: Infinity, cluster: null };
  let best = clusters[0], bestDist = Math.abs(price - best.price) / atr;
  for (const c of clusters) {
    const d = Math.abs(price - c.price) / atr;
    if (d < bestDist) { bestDist = d; best = c; }
  }
  return { dist: bestDist, cluster: best };
}

// ── LAYER 2: ZigZag State (Boof 23) ──────────────────
interface Swing { idx: number; price: number; type: 'high' | 'low'; }
interface ZZState {
  trend: 'up' | 'down' | '';
  zzHighPrice: number;
  zzHighBar: number;
  zzLowPrice: number;
  zzLowBar: number;
}

function updateZigZag(candles: Candle[], atr: number[]): ZZState {
  const n = candles.length;
  if (n < 2) return { trend: '', zzHighPrice: 0, zzHighBar: 0, zzLowPrice: 0, zzLowBar: 0 };
  
  let lastHigh = { idx: 0, price: candles[0].high };
  let lastLow = { idx: 0, price: candles[0].low };
  let trend: 'up' | 'down' | '' = '';
  
  for (let i = 1; i < n; i++) {
    const threshold = atr[i] * CFG.ATR_REV_MULT;
    if (candles[i].high > lastHigh.price) lastHigh = { idx: i, price: candles[i].high };
    if (candles[i].low < lastLow.price) lastLow = { idx: i, price: candles[i].low };
    
    const close = candles[i].close;
    if (trend === 'up' && lastHigh.price - close > threshold) {
      trend = 'down';
      lastLow = { idx: i, price: candles[i].low };
    } else if (trend === 'down' && close - lastLow.price > threshold) {
      trend = 'up';
      lastHigh = { idx: i, price: candles[i].high };
    } else if (trend === '') {
      if (close > candles[0].high + threshold) trend = 'up';
      else if (close < candles[0].low - threshold) trend = 'down';
    }
  }
  
  return {
    trend,
    zzHighPrice: lastHigh.price,
    zzHighBar: lastHigh.idx,
    zzLowPrice: lastLow.price,
    zzLowBar: lastLow.idx
  };
}

// ── LAYER 3: MSB + Retest (Boof 24) ──────────────────
function checkMSB(candles: Candle[], atr: number[], zz: ZZState): { msbBull: boolean; msbBear: boolean; msbPrice: number } {
  const close = candles[candles.length - 1].close;
  let msbBull = false, msbBear = false, msbPrice = 0;
  
  if (zz.trend === 'down' && close > zz.zzHighPrice) {
    msbBull = true;
    msbPrice = zz.zzHighPrice;
  } else if (zz.trend === 'up' && close < zz.zzLowPrice) {
    msbBear = true;
    msbPrice = zz.zzLowPrice;
  }
  
  return { msbBull, msbBear, msbPrice };
}

function checkRetest(candles: Candle[], msbPrice: number, direction: 'LONG' | 'SHORT'): boolean {
  const n = candles.length;
  const start = Math.max(0, n - CFG.RETEST_BARS - 5);
  
  for (let i = start; i < n; i++) {
    if (direction === 'LONG') {
      if (candles[i].low <= msbPrice * 1.005 && candles[i].close > msbPrice) return true;
    } else {
      if (candles[i].high >= msbPrice * 0.995 && candles[i].close < msbPrice) return true;
    }
  }
  return false;
}

// ── MAIN HYBRID SIGNAL ─────────────────────────────
export function getBoof26Signal(candles: Candle[], symbol = 'NVDA'): Boof26Result {
  const n = candles.length;
  const minLen = Math.max(CFG.ATR_LEN, CFG.VOL_LEN) + 100;
  
  if (n < minLen) {
    return { signal: 'none', price: candles[n-1]?.close || 0, reason: 'Insufficient data', direction: 'none', tpPct: 0, slPct: 0, tier: 'expanded', layersPassed: 0 };
  }
  
  const atr = computeATR(candles, CFG.ATR_LEN);
  const vwap = computeVWAP(candles);
  const volSMA = computeVolSMA(candles, CFG.VOL_LEN);
  const atrPct = computeATRPercentile(atr, 50);
  
  const i = n - 1;
  const currentATR = atr[i];
  const currentVWAP = vwap[i];
  const currentATRPct = atrPct[i];
  const close = candles[i].close;
  
  let layersPassed = 0;
  let reasons: string[] = [];
  
  // ── LAYER 1: Boof 22 Cluster + Fractal ─────────────
  const clusters = buildClusters(candles, atr);
  const { dist: clusterDist, cluster: nearestCl } = nearestCluster(close, clusters, currentATR);
  
  if (clusterDist > CFG.SR_DIST_MAX) {
    return { signal: 'none', price: close, reason: 'No cluster nearby', direction: 'none', tpPct: 0, slPct: 0, tier: 'expanded', layersPassed };
  }
  layersPassed++;
  reasons.push(`Cluster ${clusterDist.toFixed(2)}ATR`);
  
  // Check fractal (simplified - look for recent fractal confirmation)
  const fractalLookback = CFG.FRACTAL_BARS + 5;
  let fractalPeak = false, fractalTrough = false;
  
  for (let offset = CFG.FRACTAL_BARS + 2; offset < fractalLookback && offset < n; offset++) {
    const idx = n - 1 - offset;
    if (idx < CFG.FRACTAL_BARS) break;
    
    let isPeak = true, isTrough = true;
    for (let j = 1; j <= CFG.FRACTAL_BARS; j++) {
      if (candles[idx].high <= candles[idx + j].high) isPeak = false;
      if (candles[idx].high <= candles[idx - j].high) isPeak = false;
      if (candles[idx].low >= candles[idx + j].low) isTrough = false;
      if (candles[idx].low >= candles[idx - j].low) isTrough = false;
    }
    if (isPeak) fractalPeak = true;
    if (isTrough) fractalTrough = true;
  }
  
  // ── LAYER 2: Boof 23 ZigZag Regime ─────────────────
  const zz = updateZigZag(candles, atr);
  
  if (!zz.trend) {
    return { signal: 'none', price: close, reason: 'No ZZ trend', direction: 'none', tpPct: 0, slPct: 0, tier: 'expanded', layersPassed };
  }
  
  // Determine direction based on fractal + ZZ trend
  let direction: 'LONG' | 'SHORT' | null = null;
  
  if (fractalPeak && zz.trend === 'up') {
    direction = 'SHORT'; // Fade peak in up-trend
    layersPassed++;
    reasons.push('Peak+ZZup');
  } else if (fractalTrough && zz.trend === 'down') {
    direction = 'LONG'; // Fade trough in down-trend
    layersPassed++;
    reasons.push('Trough+ZZdown');
  }
  
  if (!direction) {
    return { signal: 'none', price: close, reason: 'No fractal/ZZ alignment', direction: 'none', tpPct: 0, slPct: 0, tier: 'expanded', layersPassed };
  }
  
  // ── LAYER 3: Boof 24 MSB + Retest + Context ────────
  const msb = checkMSB(candles, atr, zz);
  
  // Check if MSB aligns with direction
  const msbAligned = (direction === 'LONG' && msb.msbBull) || (direction === 'SHORT' && msb.msbBear);
  if (!msbAligned) {
    return { signal: 'none', price: close, reason: 'MSB not aligned', direction: 'none', tpPct: 0, slPct: 0, tier: 'expanded', layersPassed };
  }
  
  // Retest check
  if (!checkRetest(candles, msb.msbPrice, direction)) {
    return { signal: 'none', price: close, reason: 'No retest', direction: 'none', tpPct: 0, slPct: 0, tier: 'expanded', layersPassed };
  }
  layersPassed++;
  reasons.push('MSB+Retest');
  
  // Volume confirmation
  if (candles[i].volume < volSMA[i] * CFG.VOL_MULT_MS) {
    return { signal: 'none', price: close, reason: 'Volume low', direction: 'none', tpPct: 0, slPct: 0, tier: 'expanded', layersPassed };
  }
  
  // ATR percentile
  if (currentATRPct < CFG.ATR_PERCENTILE_MIN) {
    return { signal: 'none', price: close, reason: 'ATR% low', direction: 'none', tpPct: 0, slPct: 0, tier: 'expanded', layersPassed };
  }
  
  // VWAP alignment
  if (direction === 'LONG' && close < currentVWAP) {
    return { signal: 'none', price: close, reason: 'Below VWAP', direction: 'none', tpPct: 0, slPct: 0, tier: 'expanded', layersPassed };
  }
  if (direction === 'SHORT' && close > currentVWAP) {
    return { signal: 'none', price: close, reason: 'Above VWAP', direction: 'none', tpPct: 0, slPct: 0, tier: 'expanded', layersPassed };
  }
  
  layersPassed++;
  reasons.push('Context OK');
  
  // Calculate entry/TP/SL with Boof 24 style R/R
  const entry = close;
  let sl: number, tp: number;
  
  if (direction === 'LONG') {
    sl = entry - currentATR * CFG.SL_R;
    tp = entry + currentATR * CFG.TP_R;
  } else {
    sl = entry + currentATR * CFG.SL_R;
    tp = entry - currentATR * CFG.TP_R;
  }
  
  // Tier based on cluster quality
  const tier: 'core' | 'expanded' = clusterDist <= 0.8 ? 'core' : 'expanded';
  
  const signal: 'buy' | 'sell' = direction === 'LONG' ? 'buy' : 'sell';
  const tpPct = Math.abs(tp - entry) / entry;
  const slPct = Math.abs(sl - entry) / entry;
  
  return {
    signal,
    price: entry,
    reason: `B26: ${reasons.join(' | ')}`,
    direction,
    entryPrice: entry,
    stopLoss: sl,
    takeProfit: tp,
    tpPct,
    slPct,
    tier,
    layersPassed
  };
}

export const BOOFINGTON26 = ['AAPL', 'NVDA', 'META', 'GOOGL', 'AMD', 'PLTR'] as const;
