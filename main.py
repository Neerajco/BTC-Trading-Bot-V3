import ccxt
import time
import os
import pandas as pd
from notifier import send_telegram

# ==============================================================================
# ⚙️ SECTION 1: GLOBAL & STRATEGY CONFIGURATION (CHAMPION: 0.03, 700, 1.3, 0.95)
# ==============================================================================
SYMBOL = 'BTC/USDT'              # Asset ('BTC/USDT' or 'PAXG/USDT')
TIMEFRAME = '15m'                # Execution Timeframe
RISK_PERCENT = 0.03              # 🏆 3% Risk per trade (0.03)
LEVERAGE = 20                    # Exchange Leverage
USE_DEMO_TRADING = True          # True = Binance Demo/Testnet, False = Real Live Account

# 🛡️ OPERATIONAL & FEE GUARDS (MATCHES BACKTESTER 100%)
MAX_NOTIONAL_MULT = 10.0         # Max Position Size = 10x of Balance (Safe inside 20x Leverage)
EMERGENCY_SL_PCT = 0.0100        # 1% Emergency SL if a naked position is ever detected

# 🎯 CHAMPION STRATEGY PARAMETERS: (0.03, 700, 1.3, 0.95)
PRICE_RANGE_FILTER = 700         # 🏆 700 Minimum Swing Range Filter for BTC
DIVISOR = 1.3                    # 🏆 76.92% Pullback Entry
SL_MULTIPLIER = 0.95             # 🏆 95.0% Wide Stop-Loss (18.08% Cushion)
MIN_RR = 2.0                     # Minimum Theoretical Reward-to-Risk
MAX_RR = 10.0                    # Maximum Reward-to-Risk Cap
LOOKBACK = 40                    # 40-Candle Swing Lookback Window

# 🧲 MULTI-TIER TRAILING SL PARAMETERS: (0.25R BE, 4.0R -> 2.2R)
BE_TRIGGER_RR = 1.0              # Trigger Break-Even at 1.0R
BE_LOCK_RR = 0.25                # Lock +0.25R at Break-Even (Covers Binance Fees + Net Profit)
TRAIL_TRIGGER_RR = 4.0           # Trigger Profit Lock at 4.0R
TRAIL_LOCK_RR = 2.2              # Lock +2.2R Profit when 4.0R is reached

# ==============================================================================
# 🔌 SECTION 2: EXCHANGE INITIALIZATION (IMMUTABLE)
# ==============================================================================
exchange_config = {
    'apiKey': os.environ.get('BINANCE_API_KEY', '').strip(),
    'secret': os.environ.get('BINANCE_SECRET_KEY', '').strip(),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
    }
}
exchange = ccxt.binance(exchange_config)
if USE_DEMO_TRADING:
    exchange.enable_demo_trading(True)

exchange.load_markets()

try:
    exchange.set_leverage(LEVERAGE, SYMBOL)
    print(f"✅ Leverage successfully locked at {LEVERAGE}x for {SYMBOL}")
except Exception as e:
    print(f"⚠️ Leverage note: {e}")

# ==============================================================================
# 🧠 SECTION 3: PLUG-AND-PLAY STRATEGY LOGIC (100% IDENTICAL TO BACKTESTER)
# ==============================================================================
def generate_strategy_signal(df):
    """
    Evaluates the 40-candle swing window and checks for V7.5 Harmonic Sniper Entry.
    """
    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()

    window = df.iloc[-LOOKBACK-1:-1]
    current_candle = df.iloc[-1]
    current_ema = float(current_candle['EMA_200'])
    candle_ts = int(current_candle['Timestamp'])

    swing_low = float(window['Low'].min())
    swing_high = float(window['High'].max())
    swing_low_idx = window['Low'].idxmin()
    swing_high_idx = window['High'].idxmax()
    price_range = swing_high - swing_low

    if price_range < PRICE_RANGE_FILTER:
        return None

    # --- BULLISH SETUP ---
    if swing_low_idx < swing_high_idx:
        if float(current_candle['Close']) < current_ema:
            return None

        entry_level = swing_high - (price_range / DIVISOR)
        sl_level = swing_high - (price_range * SL_MULTIPLIER)

        if float(current_candle['Low']) <= entry_level and float(current_candle['Close']) > entry_level and float(current_candle['Low']) > sl_level:
            risk_per_coin = entry_level - sl_level
            if risk_per_coin > 0:
                geo_target = (swing_high * entry_level) / swing_low
                raw_rr = (geo_target - entry_level) / risk_per_coin
                if raw_rr >= MIN_RR:
                    applied_rr = min(raw_rr, MAX_RR)
                    tp_level = entry_level + (risk_per_coin * applied_rr)
                    return {
                        'side': 'long',
                        'sniper_entry': float(entry_level),
                        'sl': float(sl_level),
                        'tp': float(tp_level),
                        'sniper_risk_dist': float(risk_per_coin),
                        'candle_ts': candle_ts
                    }

    # --- BEARISH SETUP ---
    elif swing_high_idx < swing_low_idx:
        if float(current_candle['Close']) > current_ema:
            return None

        entry_level = swing_low + (price_range / DIVISOR)
        sl_level = swing_low + (price_range * SL_MULTIPLIER)

        if float(current_candle['High']) >= entry_level and float(current_candle['Close']) < entry_level and float(current_candle['High']) < sl_level:
            risk_per_coin = sl_level - entry_level
            if risk_per_coin > 0:
                geo_target = (swing_low * entry_level) / swing_high
                raw_rr = (entry_level - geo_target) / risk_per_coin
                if raw_rr >= MIN_RR:
                    applied_rr = min(raw_rr, MAX_RR)
                    tp_level = entry_level - (risk_per_coin * applied_rr)
                    return {
                        'side': 'short',
                        'sniper_entry': float(entry_level),
                        'sl': float(sl_level),
                        'tp': float(tp_level),
                        'sniper_risk_dist': float(risk_per_coin),
                        'candle_ts': candle_ts
                    }

    return None

# ==============================================================================
# 🛡️ SECTION 4: IMMUTABLE OPERATIONAL CORE (NEVER MODIFY BELOW THIS LINE)
# ==============================================================================
def get_raw_symbol():
    return SYMBOL.replace('/', '').replace(':', '')

def get_active_position():
    positions = exchange.fetch_positions()
    raw_sym = get_raw_symbol()
    for p in positions:
        if p['info'].get('symbol') == raw_sym or p.get('symbol') == SYMBOL:
            amt = float(p['info'].get('positionAmt', 0))
            entry = float(p['info'].get('entryPrice', 0))
            return amt, entry
    return 0.0, 0.0

def fetch_all_open_orders_combined():
    all_orders = []
    seen_ids = set()
    for params in [{}, {'stop': True}, {'trigger': True}]:
        try:
            orders = exchange.fetch_open_orders(SYMBOL, params=params)
            for o in orders:
                oid = str(o.get('id') or o.get('info', {}).get('algoId') or o.get('info', {}).get('orderId'))
                if oid not in seen_ids:
                    seen_ids.add(oid)
                    all_orders.append(o)
        except Exception:
            pass
    return all_orders

def kill_all_active_orders():
    """🔫 4-Layer Nuclear + Sniper Order Killer (Basic + Conditional + Algo Orders)"""
    raw_sym = get_raw_symbol()
    killed = 0

    for raw_method in ['fapiPrivateDeleteAllOpenOrders', 'fapiPrivateDeleteAlgoOpenOrders']:
        if hasattr(exchange, raw_method):
            try:
                getattr(exchange, raw_method)({'symbol': raw_sym})
            except Exception:
                pass

    for params in [{}, {'stop': True}, {'trigger': True}]:
        try:
            exchange.cancel_all_orders(SYMBOL, params=params)
        except Exception:
            pass

    remaining_orders = fetch_all_open_orders_combined()
    for o in remaining_orders:
        oid = o.get('id')
        algo_id = o.get('info', {}).get('algoId')
        for p in [{}, {'stop': True}, {'trigger': True}]:
            try:
                exchange.cancel_order(oid, SYMBOL, params=p)
                killed += 1
                break
            except Exception:
                pass
        if algo_id and hasattr(exchange, 'fapiPrivateDeleteAlgoOrder'):
            try:
                exchange.fapiPrivateDeleteAlgoOrder({'symbol': raw_sym, 'algoId': algo_id})
                killed += 1
            except Exception:
                pass

    return killed

def cleanup_ghost_orders():
    try:
        pos_amt, _ = get_active_position()
        if pos_amt == 0.0:
            open_orders = fetch_all_open_orders_combined()
            if len(open_orders) > 0:
                print(f"🧹 Detected {len(open_orders)} Ghost Orders! Engaging 4-Layer Sniper...")
                kill_all_active_orders()
                time.sleep(1)
                leftover = fetch_all_open_orders_combined()
                print(f"✅ Ghost Order Cleanup Complete. Remaining Orders: {len(leftover)}")
    except Exception as e:
        print(f"⚠️ Cleanup Warning: {e}")

def place_sl_tp_orders(sl_price, tp_price, amount, side):
    close_side = 'sell' if side == 'long' else 'buy'
    sl_rounded = float(exchange.price_to_precision(SYMBOL, sl_price))
    tp_rounded = float(exchange.price_to_precision(SYMBOL, tp_price))
    amt_rounded = float(exchange.amount_to_precision(SYMBOL, abs(amount)))

    exchange.create_order(SYMBOL, 'STOP_MARKET', close_side, amt_rounded, None, params={
        'stopPrice': sl_rounded,
        'reduceOnly': True,
        'workingType': 'MARK_PRICE'
    })
    exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', close_side, amt_rounded, None, params={
        'stopPrice': tp_rounded,
        'reduceOnly': True,
        'workingType': 'MARK_PRICE'
    })

def update_trailing_sl(new_sl, tp_price, amount, side):
    try:
        kill_all_active_orders()
        time.sleep(1)
        place_sl_tp_orders(new_sl, tp_price, amount, side)
        return True
    except Exception as e:
        print(f"⚠️ Error updating Trailing SL: {e}")
        return False

def sync_and_protect_active_position(pos_amt, entry_price, active_trade_state):
    """
    🔄 Accurately detects Binance Algo/Conditional SL & TP orders and preserves Trailed SLs.
    """
    side = 'long' if pos_amt > 0 else 'short'
    open_orders = fetch_all_open_orders_combined()

    sl_order_price = None
    tp_order_price = None
    trigger_prices = []

    for o in open_orders:
        info = o.get('info', {})
        combined_type = f"{o.get('type', '')} {info.get('type', '')} {info.get('orderType', '')} {info.get('origType', '')}".upper()
        stop_p = float(
            o.get('stopPrice') or
            o.get('triggerPrice') or
            info.get('stopPrice') or
            info.get('triggerPrice') or
            info.get('activatePrice') or
            o.get('price') or 0
        )
        if stop_p > 0:
            trigger_prices.append(stop_p)
            if 'STOP' in combined_type:
                sl_order_price = stop_p
            elif 'PROFIT' in combined_type:
                tp_order_price = stop_p

    # Geometry Fallback: If Binance Algo orders didn't label 'STOP'/'PROFIT', infer from trigger prices
    if sl_order_price is None and len(trigger_prices) >= 2:
        if side == 'long':
            sl_order_price = min(trigger_prices)
            tp_order_price = max(trigger_prices)
        else:
            sl_order_price = max(trigger_prices)
            tp_order_price = min(trigger_prices)
    elif sl_order_price is None and len(trigger_prices) == 1 and active_trade_state is not None:
        # Check if the single order is closer to current_sl than tp
        p = trigger_prices[0]
        if abs(p - active_trade_state['current_sl']) <= abs(p - active_trade_state['tp']):
            sl_order_price = p

    # 🚨 Place Protective SL/TP ONLY if SL is genuinely missing on Binance
    if sl_order_price is None:
        print("🚨 WARNING: Naked Position Detected (Missing SL)! Placing Protective SL/TP...")
        if active_trade_state is not None:
            sl_order_price = active_trade_state['current_sl']  # Preserves Trailed SL!
            tp_order_price = active_trade_state['tp']
        else:
            sl_order_price = entry_price * (1.0 - EMERGENCY_SL_PCT) if side == 'long' else entry_price * (1.0 + EMERGENCY_SL_PCT)
            tp_order_price = entry_price * (1.0 + EMERGENCY_SL_PCT * 3.0) if side == 'long' else entry_price * (1.0 - EMERGENCY_SL_PCT * 3.0)
        kill_all_active_orders()
        place_sl_tp_orders(sl_order_price, tp_order_price, pos_amt, side)

    # 🔄 Recover Memory After Container Restart
    if active_trade_state is None:
        fallback_tp = tp_order_price if tp_order_price else (entry_price * 1.03 if side == 'long' else entry_price * 0.97)
        est_risk_dist = abs(entry_price - sl_order_price)
        if (side == 'long' and sl_order_price >= entry_price) or (side == 'short' and sl_order_price <= entry_price):
            est_risk_dist = entry_price * 0.0025
            locked_lvl = 1
        else:
            locked_lvl = 0

        active_trade_state = {
            'side': side,
            'entry': entry_price,
            'initial_sl': sl_order_price,
            'current_sl': sl_order_price,
            'sniper_risk_dist': est_risk_dist,
            'tp': fallback_tp,
            'locked_level': locked_lvl
        }
        print(f"🔄 Recovered Active Trade State after restart: {active_trade_state}")

    return active_trade_state

def calculate_safe_trade_size(usdt_balance, sniper_entry, sl_price):
    """Calculates position size with 10x Notional Capper"""
    risk_amount = usdt_balance * RISK_PERCENT
    risk_per_coin = abs(sniper_entry - sl_price)
    if risk_per_coin <= 0:
        return 0.0, 0.0

    ideal_size = risk_amount / risk_per_coin
    notional_value = ideal_size * sniper_entry
    max_safe_notional = min(usdt_balance * LEVERAGE * 0.90, usdt_balance * MAX_NOTIONAL_MULT)

    if notional_value > max_safe_notional:
        final_size = max_safe_notional / sniper_entry
        print(f"⚠️ Size Capped at {MAX_NOTIONAL_MULT}x Notional: {ideal_size:.4f} -> {final_size:.4f}")
    else:
        final_size = ideal_size

    actual_risk = final_size * risk_per_coin
    return float(exchange.amount_to_precision(SYMBOL, final_size)), actual_risk

def run_master_engine():
    print("=" * 78)
    print(f"🚀 MASTER ENGINE V7.5 | {SYMBOL} ({TIMEFRAME}) | CFG: ({RISK_PERCENT}, {PRICE_RANGE_FILTER}, {DIVISOR}, {SL_MULTIPLIER})")
    print(f"🧲 TRAILING PROFILE   | BE: {BE_TRIGGER_RR}R -> +{BE_LOCK_RR}R | TRAIL: {TRAIL_TRIGGER_RR}R -> +{TRAIL_LOCK_RR}R")
    print("=" * 78)

    cleanup_ghost_orders()
    active_trade_state = None
    last_traded_candle_ts = None

    while True:
        try:
            pos_amt, pos_entry = get_active_position()

            # ==========================================
            # 1. ACTIVE POSITION MANAGEMENT (TRAILING SL)
            # ==========================================
            if pos_amt != 0.0:
                active_trade_state = sync_and_protect_active_position(pos_amt, pos_entry, active_trade_state)

                ticker = exchange.fetch_ticker(SYMBOL)
                current_price = float(ticker.get('info', {}).get('markPrice') or ticker['last'])
                entry = active_trade_state['entry']
                risk_dist = active_trade_state['sniper_risk_dist']

                if risk_dist > 0:
                    if active_trade_state['side'] == 'long':
                        current_rr = (current_price - entry) / risk_dist
                        if current_rr >= TRAIL_TRIGGER_RR and active_trade_state['locked_level'] < 2:
                            new_sl = entry + (risk_dist * TRAIL_LOCK_RR)
                            if update_trailing_sl(new_sl, active_trade_state['tp'], pos_amt, 'long'):
                                active_trade_state['locked_level'] = 2
                                active_trade_state['current_sl'] = new_sl
                                print(f"🔒 [LONG] {TRAIL_TRIGGER_RR}R Hit! Locked +{TRAIL_LOCK_RR}R Profit at {new_sl:.2f}")
                                send_telegram(f"🔒 {SYMBOL} {TRAIL_TRIGGER_RR}R Hit! Locked +{TRAIL_LOCK_RR}R at {new_sl:.2f}")
                        elif current_rr >= BE_TRIGGER_RR and active_trade_state['locked_level'] < 1:
                            new_sl = entry + (risk_dist * BE_LOCK_RR)
                            if update_trailing_sl(new_sl, active_trade_state['tp'], pos_amt, 'long'):
                                active_trade_state['locked_level'] = 1
                                active_trade_state['current_sl'] = new_sl
                                print(f"🛡️ [LONG] {BE_TRIGGER_RR}R Hit! Locked +{BE_LOCK_RR}R Fee-Safe BE at {new_sl:.2f}")
                                send_telegram(f"🛡️ {SYMBOL} Fee-Safe BE (+{BE_LOCK_RR}R) Secured at {new_sl:.2f}")

                    elif active_trade_state['side'] == 'short':
                        current_rr = (entry - current_price) / risk_dist
                        if current_rr >= TRAIL_TRIGGER_RR and active_trade_state['locked_level'] < 2:
                            new_sl = entry - (risk_dist * TRAIL_LOCK_RR)
                            if update_trailing_sl(new_sl, active_trade_state['tp'], pos_amt, 'short'):
                                active_trade_state['locked_level'] = 2
                                active_trade_state['current_sl'] = new_sl
                                print(f"🔒 [SHORT] {TRAIL_TRIGGER_RR}R Hit! Locked +{TRAIL_LOCK_RR}R Profit at {new_sl:.2f}")
                                send_telegram(f"🔒 {SYMBOL} {TRAIL_TRIGGER_RR}R Hit! Locked +{TRAIL_LOCK_RR}R at {new_sl:.2f}")
                        elif current_rr >= BE_TRIGGER_RR and active_trade_state['locked_level'] < 1:
                            new_sl = entry - (risk_dist * BE_LOCK_RR)
                            if update_trailing_sl(new_sl, active_trade_state['tp'], pos_amt, 'short'):
                                active_trade_state['locked_level'] = 1
                                active_trade_state['current_sl'] = new_sl
                                print(f"🛡️ [SHORT] {BE_TRIGGER_RR}R Hit! Locked +{BE_LOCK_RR}R Fee-Safe BE at {new_sl:.2f}")
                                send_telegram(f"🛡️ {SYMBOL} Fee-Safe BE (+{BE_LOCK_RR}R) Secured at {new_sl:.2f}")

                time.sleep(20)
                continue

            # ==========================================
            # 2. FLAT STATE: CLEANUP & SCANNING
            # ==========================================
            if active_trade_state is not None:
                print("🔄 Position Closed. Executing Post-Trade Ghost Order Sweep...")
                active_trade_state = None

            cleanup_ghost_orders()
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 📡 Scanning Market {SYMBOL}...")

            bars = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=250)
            if not bars or len(bars) < 210:
                time.sleep(30)
                continue

            df = pd.DataFrame(bars, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
            signal = generate_strategy_signal(df)

            if signal is not None:
                # 🔒 1. One-Trade-Per-Candle Lock
                if last_traded_candle_ts == signal['candle_ts']:
                    time.sleep(30)
                    continue

                ticker = exchange.fetch_ticker(SYMBOL)
                live_price = float(ticker.get('info', {}).get('markPrice') or ticker['last'])
                sl_price = signal['sl']
                tp_price = signal['tp']

                # Verify live price is inside valid SL/TP boundaries
                if signal['side'] == 'long' and (live_price <= sl_price or live_price >= tp_price):
                    continue
                if signal['side'] == 'short' and (live_price >= sl_price or live_price <= tp_price):
                    continue

                balance_data = exchange.fetch_balance()
                usdt_balance = float(balance_data['USDT']['free'])
                if usdt_balance < 20:
                    print("⚠️ Low balance (< $20). Sleeping 5m...")
                    time.sleep(300)
                    continue

                trade_size, actual_risk = calculate_safe_trade_size(usdt_balance, signal['sniper_entry'], sl_price)
                if trade_size <= 0:
                    time.sleep(30)
                    continue

                # 🔒 2. Clean Slate -> Execute Market Order -> Place MARK_PRICE SL/TP
                kill_all_active_orders()

                if signal['side'] == 'long':
                    order = exchange.create_market_buy_order(SYMBOL, trade_size)
                else:
                    order = exchange.create_market_sell_order(SYMBOL, trade_size)

                actual_entry = float(order.get('average') or live_price)
                place_sl_tp_orders(sl_price, tp_price, trade_size, signal['side'])

                active_trade_state = {
                    'side': signal['side'],
                    'entry': signal['sniper_entry'],
                    'actual_fill': actual_entry,
                    'initial_sl': sl_price,
                    'current_sl': sl_price,
                    'sniper_risk_dist': signal['sniper_risk_dist'],
                    'tp': tp_price,
                    'locked_level': 0
                }
                last_traded_candle_ts = signal['candle_ts']

                emoji = "🚀" if signal['side'] == 'long' else "📉"
                msg = (
                    f"{emoji} {SYMBOL} {signal['side'].upper()} (V7.5 CHAMPION)\n"
                    f"Fill: {actual_entry:.2f} (Ref: {signal['sniper_entry']:.2f})\n"
                    f"Target: {tp_price:.2f}\n"
                    f"SL (Mark): {sl_price:.2f}\n"
                    f"Size: {trade_size} | Risk: ${actual_risk:.2f}"
                )
                print(msg)
                send_telegram(msg)

            time.sleep(30)

        except ccxt.NetworkError:
            print("📡 Network Error. Sleeping 30s...")
            time.sleep(30)
        except Exception as e:
            print(f"❌ Main Loop Error: {e}")
            time.sleep(15)

if __name__ == '__main__':
    run_master_engine()
