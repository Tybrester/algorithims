// =========================================================
// BOOF 22.5 — Fractal + ADX Chop Detection
// ADX < 15: Chop regime — tagged in reason, uses bot-configured TP/SL
// ADX >= 15: Trend regime — uses bot-configured TP/SL
// =========================================================

import { Candle, Boof22Result } from './boof22.ts';
import { getBoof22Signal } from './boof22.ts';

// ─────────────────────────────────────────────
// CHOP MODE CONFIG
// ─────────────────────────────────────────────
const CHOP_CFG = {
  ADX_LEN:      14,
  ADX_CHOP_TH:  10,  // ADX < 10 = chop
};

// ─────────────────────────────────────────────
// ADX INDICATOR
// ─────────────────────────────────────────────
function computeADX(candles: Candle[], len: number): number[] {
  const adx: number[] = [];
  const plusDM: number[] = [];
  const minusDM: number[] = [];
  const tr: number[] = [];
  
  for (let i = 0; i < candles.length; i++) {
    const c = candles[i];
    const prev = i > 0 ? candles[i - 1] : c;
    const upMove = c.high - prev.high;
    const downMove = prev.low - c.low;
    plusDM.push((upMove > downMove && upMove > 0) ? upMove : 0);
    minusDM.push((downMove > upMove && downMove > 0) ? downMove : 0);
    const prevClose = i > 0 ? prev.close : c.open;
    tr.push(Math.max(c.high - c.low, Math.abs(c.high - prevClose), Math.abs(c.low - prevClose)));
  }
  
  for (let i = 0; i < candles.length; i++) {
    if (i < len) {
      adx.push(0);
      continue;
    }
    const atrSlice = tr.slice(i - len + 1, i + 1);
    const atrSum = atrSlice.reduce((a, b) => a + b, 0);
    if (atrSum === 0) {
      adx.push(adx[i - 1] || 0);
      continue;
    }
    const plusDI = (plusDM.slice(i - len + 1, i + 1).reduce((a, b) => a + b, 0) / atrSum) * 100;
    const minusDI = (minusDM.slice(i - len + 1, i + 1).reduce((a, b) => a + b, 0) / atrSum) * 100;
    const dx = Math.abs(plusDI - minusDI) / (plusDI + minusDI + 0.0001) * 100;
    if (i === len) adx.push(dx);
    else adx.push((adx[i - 1] * (len - 1) + dx) / len);
  }
  return adx;
}

// ─────────────────────────────────────────────
// MAIN SIGNAL FUNCTION
// ─────────────────────────────────────────────
export function getBoof22v2Signal(candles: Candle[], symbol = 'NVDA', tpPct = 0.35, slPct = 0.15): Boof22Result {
  const minBars = 100;
  if (candles.length < minBars) {
    return { 
      signal: 'none', price: 0, reason: 'not enough bars', direction: 'none', 
      nearestCluster: 0, clusterStrength: 0, atr: 0, tpPct, slPct, slack: 0, tier: 'expanded' 
    };
  }

  const adx = computeADX(candles, CHOP_CFG.ADX_LEN);
  const currentADX = adx[adx.length - 1];
  const isChop = currentADX < CHOP_CFG.ADX_CHOP_TH;

  const result = getBoof22Signal(candles, symbol, tpPct, slPct);

  return {
    ...result,
    reason: result.reason + ` | ADX=${currentADX.toFixed(1)} (${isChop ? 'CHOP MODE' : 'TREND MODE'})`,
  };
}
