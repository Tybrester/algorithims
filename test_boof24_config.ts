/**
 * Test BOOF 24 Configuration
 */
import { 
  BOOF24_1M_SYMBOL_LIST,
  BOOF24_5M_SYMBOL_LIST,
  BOOF24_ALL_SYMBOLS,
  getStockType, 
  getMaxTrades, 
  shouldUseBreakout, 
  boofRouter,
  Boof24TradeTracker,
  getBoof24Summary,
  BOOF24_STOCKS 
} from './boof24_config';

// Test 1: Verify stock lists
console.log('=== BOOF 24 1M Symbol List ===');
console.log(BOOF24_1M_SYMBOL_LIST.join(', '));
console.log(`Total: ${BOOF24_1M_SYMBOL_LIST.length} symbols\n`);

console.log('=== BOOF 24 5M Symbol List ===');
console.log(BOOF24_5M_SYMBOL_LIST.join(', '));
console.log(`Total: ${BOOF24_5M_SYMBOL_LIST.length} symbols\n`);

console.log(`Combined: ${BOOF24_ALL_SYMBOLS.length} symbols\n`);

// Test 2: Classification summary
console.log(getBoof24Summary());

// Test 3: Individual lookups
console.log('=== Individual Stock Lookups ===');
const testSymbols = ['BABA', 'AAPL', 'PLTR', 'MSFT', 'AMD', 'NVDA', 'SPY'];
for (const sym of testSymbols) {
  const stock = BOOF24_STOCKS[sym];
  if (stock) {
    console.log(`${sym}: ${stock.type} | Max: ${stock.maxTradesPerDay}/day | Breakout: ${shouldUseBreakout(sym)}`);
  }
}

// Test 4: Strategy Router
console.log('\n=== Strategy Router Tests ===');
const tracker = new Boof24TradeTracker();

// Test scenarios
const scenarios: Array<{ symbol: string; signal: { breakoutCondition: boolean; baselineCondition: boolean; volZ: number; vwapAligned: boolean; direction: 'long' | 'short' }; tradesToday: number }> = [
  // Breakout stock with breakout signal
  { symbol: 'BABA', signal: { breakoutCondition: true, baselineCondition: false, volZ: 2.1, vwapAligned: true, direction: 'long' }, tradesToday: 0 },
  // Impulse stock with baseline signal  
  { symbol: 'AAPL', signal: { breakoutCondition: false, baselineCondition: true, volZ: 2.0, vwapAligned: true, direction: 'long' }, tradesToday: 0 },
  // Breakout stock without breakout condition
  { symbol: 'PLTR', signal: { breakoutCondition: false, baselineCondition: true, volZ: 2.0, vwapAligned: true, direction: 'long' }, tradesToday: 0 },
  // Skip stock
  { symbol: 'MSFT', signal: { breakoutCondition: true, baselineCondition: true, volZ: 2.5, vwapAligned: true, direction: 'long' }, tradesToday: 0 },
  // Max trades reached
  { symbol: 'AMD', signal: { breakoutCondition: true, baselineCondition: false, volZ: 2.2, vwapAligned: true, direction: 'long' }, tradesToday: 3 },
  // Vol Z too low
  { symbol: 'BABA', signal: { breakoutCondition: true, baselineCondition: false, volZ: 1.5, vwapAligned: true, direction: 'long' }, tradesToday: 0 },
];

for (const scenario of scenarios) {
  const result = boofRouter(scenario.symbol, scenario.signal, scenario.tradesToday);
  console.log(`${scenario.symbol} (tradesToday=${scenario.tradesToday}): ${result.action} | ${result.config || '-'} | ${result.reason}`);
}

// Test 5: Trade tracker
console.log('\n=== Trade Tracker Tests ===');
console.log(`BABA remaining: ${tracker.getRemaining('BABA')}`);
tracker.recordTrade('BABA');
tracker.recordTrade('BABA');
console.log(`BABA after 2 trades: ${tracker.getRemaining('BABA')}`);
console.log(`Can trade BABA? ${tracker.canTrade('BABA')}`);
tracker.recordTrade('BABA');
console.log(`BABA after 3 trades (max): ${tracker.getRemaining('BABA')}`);
console.log(`Can trade BABA? ${tracker.canTrade('BABA')}`);

console.log('\n=== All Tests Complete ===');
