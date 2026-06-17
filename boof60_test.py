"""
BOOF60 dry-run backtest — no API calls, no orders placed.
Uses yfinance 1-min data to replay last 5 days and count signals.
"""
import yfinance as yf
import pandas as pd
import pytz
from datetime import timedelta

ET = pytz.timezone('America/New_York')

SYMBOLS = [
    'AAPL','AMZN','APP','AVGO','AMD','NVDA','TSLA','META','MSFT','PLTR',
    'HOOD','COIN','MSTR','SMCI','UPST','MU','MRVL','CRM','PANW','GOOGL',
    'AFRM','HIMS','CLSK','ADBE','ARM','CRWD','SNOW','UBER','NFLX','RBLX'
]

GAP_UP_MIN   = 1.0
PDH_NEAR_PCT = 0.8
REJECT_PCT   = 0.50
MAX_POS      = 5
TP_PCT       = 35.0
SL_PCT       = 30.0
MAX_BARS     = 60
BUDGET       = 750.0

print("Fetching data...")
data = {}
for sym in SYMBOLS + ['SPY']:
    t = yf.Ticker(sym)
    h = t.history(period='5d', interval='1m', prepost=True)
    if h.empty:
        data[sym] = h
        continue
    if not hasattr(h.index, 'tz') or h.index.tz is None:
        h.index = h.index.tz_localize('UTC')
    h.index = h.index.tz_convert(ET)
    data[sym] = h

daily_data = {}
for sym in SYMBOLS:
    t = yf.Ticker(sym)
    h = t.history(period='30d', interval='1d')
    daily_data[sym] = h

# Get unique trading days
all_dates = sorted(set(data['SPY'].index.date))[-5:]
print(f"Simulating {len(all_dates)} days: {all_dates}\n")

total_signals = 0
total_long    = 0
total_short   = 0
total_tp      = 0
total_sl      = 0
total_timeout = 0
all_trades    = []

for day in all_dates:
    print(f"\n{'='*55}")
    print(f"DATE: {day}")
    print(f"{'='*55}")

    day_signals = 0
    open_positions = {}  # sym -> {direction, entry_bar_idx, entry_price, opt_entry_est}
    pdh_broken  = set()
    pdh_touched = set()
    spy_bars_day = []
    regime = "neutral"

    for sym in SYMBOLS:
        dh = daily_data[sym]
        # find prev day close and high
        prev_rows = dh[dh.index.date < day]
        if len(prev_rows) < 1:
            continue

        prev_close = float(prev_rows['Close'].iloc[-1])
        pdh        = float(prev_rows['High'].iloc[-1])

        sym_bars = data[sym]
        day_bars = sym_bars[sym_bars.index.date == day]
        rth_bars = day_bars.between_time('09:30', '16:00')
        pm_bars  = day_bars.between_time('04:00', '09:29')

        if rth_bars.empty:
            continue

        day_open = float(rth_bars['Open'].iloc[0])
        gap_pct  = (day_open - prev_close) / prev_close * 100
        gap_ok   = gap_pct > GAP_UP_MIN

        confirm_long  = False
        confirm_short = False

        for i, (ts, bar) in enumerate(rth_bars.iterrows()):
            hm    = ts.strftime('%H:%M')
            price = float(bar['Close'])
            o_px  = float(bar['Open'])

            if hm >= '15:30':
                break

            # Update SPY regime
            spy_day = data['SPY']
            spy_rth = spy_day[spy_day.index.date == day].between_time('09:30','16:00')
            if i < len(spy_rth):
                spy_bars_day.append(float(spy_rth.iloc[min(i, len(spy_rth)-1)]['Close']))
                if len(spy_bars_day) > 5: spy_bars_day.pop(0)
                if len(spy_bars_day) >= 3:
                    if spy_bars_day[-1] > spy_bars_day[0] * 1.001:
                        regime = "bull"
                    elif spy_bars_day[-1] < spy_bars_day[0] * 0.999:
                        regime = "bear"
                    else:
                        regime = "neutral"

            # Check exits
            if sym in open_positions:
                pos = open_positions[sym]
                pos['bars_held'] += 1
                # Estimate option move: delta ~0.5 for 1DTE ATM
                stock_move_pct = (price - pos['entry_price']) / pos['entry_price'] * 100
                if pos['direction'] == 'short':
                    stock_move_pct = -stock_move_pct
                opt_pct = stock_move_pct * 5  # ~5x leverage on 1DTE ATM

                if opt_pct >= TP_PCT:
                    result = 'TP'
                    total_tp += 1
                elif opt_pct <= -SL_PCT:
                    result = 'SL'
                    total_sl += 1
                elif pos['bars_held'] >= MAX_BARS:
                    result = 'TIMEOUT'
                    total_timeout += 1
                    opt_pct = stock_move_pct * 5
                else:
                    continue

                cost    = pos['opt_cost']
                pnl_est = cost * opt_pct / 100
                all_trades.append({
                    'date': day, 'sym': sym, 'dir': pos['direction'],
                    'entry': pos['entry_price'], 'exit': price,
                    'opt_pct': round(opt_pct,1), 'pnl_est': round(pnl_est,2),
                    'result': result, 'bars': pos['bars_held']
                })
                del open_positions[sym]
                continue

            if sym in open_positions or len(open_positions) >= MAX_POS:
                continue
            if sym in pdh_broken or sym in pdh_touched:
                continue

            # LONG signal
            if gap_ok and price > pdh and sym not in pdh_broken:
                if not confirm_long:
                    confirm_long = True
                    continue
                if regime in ('bull', 'neutral'):
                    pdh_broken.add(sym)
                    qty      = min(10, int(BUDGET / (max(0.50, abs(price - pdh)) * 100)))
                    qty      = max(1, qty)
                    opt_cost = BUDGET
                    open_positions[sym] = {
                        'direction': 'long', 'entry_price': price,
                        'bars_held': 0, 'opt_cost': opt_cost
                    }
                    day_signals += 1
                    total_long  += 1
                    print(f"  {hm} LONG  {sym:<6} ${price:.2f}  gap={gap_pct:+.1f}%  pdh=${pdh:.2f}  regime={regime}")

            # SHORT signal — skip if gap-up long already fired on this sym
            near_pdh = abs(price - pdh) / pdh < (PDH_NEAR_PCT / 100)
            reject   = o_px > 0 and price < o_px * (1 - REJECT_PCT / 100)
            already_long = sym in pdh_broken
            if near_pdh and reject and sym not in pdh_touched and not already_long and not gap_ok:
                if regime in ('bear', 'neutral'):
                    pdh_touched.add(sym)
                    opt_cost = BUDGET
                    open_positions[sym] = {
                        'direction': 'short', 'entry_price': price,
                        'bars_held': 0, 'opt_cost': opt_cost
                    }
                    day_signals += 1
                    total_short += 1
                    print(f"  {hm} SHORT {sym:<6} ${price:.2f}  near_pdh=${pdh:.2f}  regime={regime}")

    # EOD close remaining
    for sym, pos in open_positions.items():
        rth = data[sym][data[sym].index.date == day].between_time('09:30','16:00')
        exit_price = float(rth['Close'].iloc[-1]) if not rth.empty else pos['entry_price']
        stock_move_pct = (exit_price - pos['entry_price']) / pos['entry_price'] * 100
        if pos['direction'] == 'short':
            stock_move_pct = -stock_move_pct
        opt_pct = stock_move_pct * 5
        pnl_est = pos['opt_cost'] * opt_pct / 100
        all_trades.append({
            'date': day, 'sym': sym, 'dir': pos['direction'],
            'entry': pos['entry_price'], 'exit': exit_price,
            'opt_pct': round(opt_pct,1), 'pnl_est': round(pnl_est,2),
            'result': 'EOD', 'bars': pos['bars_held']
        })

    total_signals += day_signals
    print(f"  Day signals: {day_signals}")

# ── SUMMARY ──────────────────────────────────────────────────────────────────
print(f"\n{'='*55}")
print(f"BOOF60 5-DAY BACKTEST SUMMARY")
print(f"{'='*55}")
df = pd.DataFrame(all_trades)
if df.empty:
    print("No trades fired.")
else:
    wins   = df[df['opt_pct'] > 0]
    losses = df[df['opt_pct'] <= 0]
    print(f"Total trades:    {len(df)}")
    print(f"  Long:          {total_long}")
    print(f"  Short:         {total_short}")
    print(f"  Avg/day:       {len(df)/len(all_dates):.1f}")
    print(f"Winners:         {len(wins)}  ({len(wins)/len(df)*100:.0f}%)")
    print(f"Losers:          {len(losses)}")
    print(f"Exits: TP={total_tp}  SL={total_sl}  Timeout={total_timeout}  EOD={len(df)-total_tp-total_sl-total_timeout}")
    print(f"\nEst. P&L per trade (avg): ${df['pnl_est'].mean():.2f}")
    print(f"Est. P&L total:           ${df['pnl_est'].sum():.2f}")
    print(f"Best trade:               ${df['pnl_est'].max():.2f}")
    print(f"Worst trade:              ${df['pnl_est'].min():.2f}")
    print(f"\nBy result:")
    print(df.groupby('result')['pnl_est'].agg(['count','sum','mean']).round(2).to_string())
    print(f"\nBy direction:")
    print(df.groupby('dir')['pnl_est'].agg(['count','sum','mean']).round(2).to_string())
