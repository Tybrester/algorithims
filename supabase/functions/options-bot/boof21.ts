// =========================================================
// BOOF 21.0 — Volume Cluster S/R MTF Retest Engine
// 10-min levels · 1-min entry · both directions
// =========================================================

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface Boof21Result {
  signal: 'buy' | 'sell' | 'none';
  price: number;
  reason: string;
  setupType: string;
  level: number;
  levelStrength: number;
  direction: 'LONG' | 'SHORT' | 'none';
  slack: number;  // Signal quality metric (levelStrength-based)
}

// ─────────────────────────────────────────────
// CONFIG (mirrors backtest_boof21.py)
// ─────────────────────────────────────────────

const CFG = {
  // Level building
  LOOKBACK:        39,
  VOL_THRESHOLD:   1.3,
  CLUSTER_PCT:     0.2,   // % of price for clustering zone
  MIN_TOUCHES:     3,
  MIN_LEVEL_STR:   8.0,

  // Entry
  RVOL_MIN:        80,    // percentile — use raw ratio > 1.3 as proxy
  RETEST_PCT:      0.002,
  CHOP_THRESH:     0.05,
  EMA_FAST:        20,
  EMA_SLOW:        50,

  // Cooldown
  COOLDOWN_BARS:   15,
  COOLDOWN_PCT:    0.0015,

  // Per-symbol
  SPY: { stopMult: 1.8, tpMult: 3.0, longsOnly: false, allowBreakout: false },
  QQQ: { stopMult: 1.5, tpMult: 3.0, longsOnly: false, allowBreakout: true  },
};

// ─────────────────────────────────────────────
// MATH HELPERS
// ─────────────────────────────────────────────

function ema(data: number[], period: number): number[] {
  const k = 2 / (period + 1);
  const out = new Array(data.length).fill(0);
  out[0] = data[0];
  for (let i = 1; i < data.length; i++) out[i] = data[i] * k + out[i - 1] * (1 - k);
  return out;
}

function atr(highs: number[], lows: number[], closes: number[], period = 14): number[] {
  const tr = highs.map((h, i) =>
    i === 0 ? h - lows[i] : Math.max(h - lows[i], Math.abs(h - closes[i-1]), Math.abs(lows[i] - closes[i-1]))
  );
  const out = new Array(tr.length).fill(0);
  out[period - 1] = tr.slice(0, period).reduce((a, b) => a + b) / period;
  for (let i = period; i < tr.length; i++) out[i] = (out[i-1] * (period - 1) + tr[i]) / period;
  return out;
}

function vwap(candles: Candle[]): number[] {
  let cumTPV = 0, cumVol = 0;
  return candles.map(c => {
    const tp = (c.high + c.low + c.close) / 3;
    cumTPV += tp * (c.volume || 1);
    cumVol += (c.volume || 1);
    return cumTPV / cumVol;
  });
}

// ─────────────────────────────────────────────
// RESAMPLE 1-MIN → 10-MIN
// ─────────────────────────────────────────────

function resample10m(candles: Candle[]): Candle[] {
  const buckets: Map<number, Candle[]> = new Map();
  for (const c of candles) {
    const bucket = Math.floor(c.time / 600) * 600;
    if (!buckets.has(bucket)) buckets.set(bucket, []);
    buckets.get(bucket)!.push(c);
  }
  const result: Candle[] = [];
  for (const [time, bars] of Array.from(buckets.entries()).sort((a, b) => a[0] - b[0])) {
    result.push({
      time,
      open:   bars[0].open,
      high:   Math.max(...bars.map(b => b.high)),
      low:    Math.min(...bars.map(b => b.low)),
      close:  bars[bars.length - 1].close,
      volume: bars.reduce((s, b) => s + (b.volume || 0), 0),
    });
  }
  return result;
}

// ─────────────────────────────────────────────
// BUILD VOLUME CLUSTER S/R LEVELS
// ─────────────────────────────────────────────

interface Level {
  price: number;
  isSupport: boolean;
  touches: number;
  levelStrength: number;
}

function buildLevels(bars: Candle[], currentClose: number): Level[] {
  if (bars.length < 5) return [];

  // Typical prices of high-vol bars (vol > 1.3x avg)
  const vols = bars.map(b => b.volume || 0);
  const avgVol = vols.reduce((a, b) => a + b, 0) / vols.length;
  const highVolBars = bars.filter(b => (b.volume || 0) > avgVol * CFG.VOL_THRESHOLD);
  if (highVolBars.length === 0) return [];

  const typicals = highVolBars.map(b => (b.high + b.low + b.close) / 3);

  // Cluster by proximity (CLUSTER_PCT)
  const clusters: number[][] = [];
  for (const tp of typicals) {
    let placed = false;
    for (const cl of clusters) {
      const center = cl.reduce((a, b) => a + b) / cl.length;
      if (Math.abs(tp - center) / center < CFG.CLUSTER_PCT / 100) {
        cl.push(tp); placed = true; break;
      }
    }
    if (!placed) clusters.push([tp]);
  }

  const levels: Level[] = [];
  for (const cl of clusters) {
    const price = cl.reduce((a, b) => a + b) / cl.length;

    // Count touches (bar high/low spans the cluster price)
    let touches = 0, totalVol = 0;
    for (const b of bars) {
      if (b.low <= price && price <= b.high) {
        touches++;
        totalVol += (b.volume || 0);
      }
    }
    if (touches < CFG.MIN_TOUCHES) continue;

    const strength = (touches * 2) + ((totalVol / avgVol) * 3);
    if (strength < CFG.MIN_LEVEL_STR) continue;

    levels.push({
      price,
      isSupport: price < currentClose,
      touches,
      levelStrength: strength,
    });
  }

  return levels.sort((a, b) => b.levelStrength - a.levelStrength);
}

// ─────────────────────────────────────────────
// RETEST SIGNAL (Pine port)
// retestLong  = isSupport  and close within 0.2% of price and close > price
// retestShort = !isSupport and close within 0.2% of price and close < price
// ─────────────────────────────────────────────

function retestSignal(close: number, levels: Level[], retestPct = 0.002): { long: Level | null; short: Level | null } {
  let long: Level | null = null, short: Level | null = null;
  for (const lvl of levels) {
    const prox = Math.abs(close - lvl.price) / lvl.price;
    if (prox >= retestPct) continue;
    if (lvl.isSupport  && close > lvl.price && !long)  long  = lvl;
    if (!lvl.isSupport && close < lvl.price && !short) short = lvl;
  }
  return { long, short };
}

// ─────────────────────────────────────────────
// MAIN SIGNAL GENERATOR
// ─────────────────────────────────────────────

export function generateSignalBoof21(
  candles: Candle[],   // 1-min bars, most recent last
  symbol: string,
  tpPct = 0.35,
  slPct = 0.15
): Boof21Result {

  const none: Boof21Result = { signal: 'none', price: 0, reason: 'no signal', setupType: 'none', level: 0, levelStrength: 0, direction: 'none', slack: 0 };

  if (candles.length < 200) return { ...none, reason: 'insufficient bars' };

  const sym = symbol.toUpperCase();
  const symCfg = sym === 'SPY' ? CFG.SPY : sym === 'QQQ' ? CFG.QQQ : CFG.QQQ;

  const n = candles.length;
  const closes  = candles.map(c => c.close);
  const highs   = candles.map(c => c.high);
  const lows    = candles.map(c => c.low);
  const volumes = candles.map(c => c.volume || 0);
  const opens   = candles.map(c => c.open);

  // Current bar (use bar[-2] as signal bar, bar[-1] as confirmation)
  const i = n - 2;
  const price     = closes[i];
  const pricePrev = closes[i - 1];

  // ── VWAP ──
  const vwapVals = vwap(candles);
  const aboveVwap = price > vwapVals[i];

  // ── Regime: EMA20/50 ──
  const ema20 = ema(closes, CFG.EMA_FAST);
  const ema50 = ema(closes, CFG.EMA_SLOW);
  const trendVal = ema20[i] - ema50[i];
  const emaBullish = ema20[i] > ema50[i];
  const emaBearish = ema20[i] < ema50[i];

  // ── RVOL (use ratio vs 100-bar avg as proxy for percentile) ──
  const volSlice = volumes.slice(i - 100, i);
  const avgVol100 = volSlice.reduce((a, b) => a + b, 0) / volSlice.length;
  const rvolRatio = avgVol100 > 0 ? (volumes[i] / avgVol100) * 100 : 0;
  if (rvolRatio < CFG.RVOL_MIN) return { ...none, reason: `rvol too low: ${rvolRatio.toFixed(0)}` };

  // ── Build 10-min levels (use last LOOKBACK 10-min bars) ──
  const bars10m = resample10m(candles);
  const window10m = bars10m.slice(-CFG.LOOKBACK);
  const levels = buildLevels(window10m, price);
  if (levels.length === 0) return { ...none, reason: 'no quality levels' };

  // ── Retest signal ──
  const { long: rtLong, short: rtShort } = retestSignal(price, levels);

  // ── Direction logic ──
  let direction: 'LONG' | 'SHORT' | null = null;
  let lvlUsed: Level | null = null;

  if (rtLong && aboveVwap && emaBullish) {
    direction = 'LONG';
    lvlUsed   = rtLong;
  } else if (rtShort && !symCfg.longsOnly && !aboveVwap && emaBearish) {
    direction = 'SHORT';
    lvlUsed   = rtShort;
  }

  if (!direction || !lvlUsed) return { ...none, reason: 'no retest signal' };

  // ── Use provided TP/SL percentages ──
  const stopDistPct = Math.abs(slPct) * 100;
  const tpDistPct   = tpPct * 100;

  const signal: 'buy' | 'sell' = direction === 'LONG' ? 'buy' : 'sell';
  const reason = `Boof21 ${sym} ${direction} RETEST @ ${lvlUsed.price.toFixed(2)} | str=${lvlUsed.levelStrength.toFixed(1)} | stop=-${stopDistPct.toFixed(0)}% tp=+${tpDistPct.toFixed(0)}% | rvol=${rvolRatio.toFixed(0)}`;

  // Calculate slack based on level strength and volume ratio
  // Higher levelStrength and rvolRatio = stronger signal = higher slack
  const slack = (lvlUsed.levelStrength / 10) * Math.min(rvolRatio / 100, 2.0);

  return {
    signal,
    price,
    reason,
    setupType: 'RETEST',
    level: lvlUsed.price,
    levelStrength: lvlUsed.levelStrength,
    direction,
    slack,
  };
}
