import ccxt
import time
import os
import pandas as pd
from notifier import send_telegram

# ==============================================================================
# ⚙️ SECTION 1: GLOBAL & STRATEGY CONFIGURATION
# ==============================================================================
SYMBOL = 'BTC/USDT'              # 'BTC/USDT' or 'PAXG/USDT'
TIMEFRAME = '15m'                # Execution Timeframe
RISK_PERCENT = 0.02              # 2% Risk per trade
LEVERAGE = 20                    # Exchange Leverage
USE_DEMO_TRADING = True          # True = Binance Demo/Testnet, False = Real Live Account

# 🛡️ OPERATIONAL SAFETY GUARDS (DO NOT LOWER THESE)
MAX_NOTIONAL_MULT = 4.0          # Max Position Size = 4x of Account Balance (Prevents $80 Fee Burn)
MIN_SL_DISTANCE_PCT = 0.0018     # Min SL distance = 0.18% (~$150 on BTC) to avoid 1-sec spread hits
EMERGENCY_SL_PCT = 0.0100        # 1% Emergency SL if a naked position is ever detected
FEE_BUFFER_PCT = 0.0012          # 0.12% buffer added to 1:1 Break-Even to cover Binance Taker Fees

# 🎯 STRATEGY PARAMETERS (V7.4 Harmonic)
PRICE_RANGE_FILTER = 150         # 150 for BTC, 15 for PAXG
DIVISOR = 1.2                    # 83.3% Pullback
SL_MULTIPLIER = 0.90             # Tight Stop Loss Multiplier
MIN_RR = 2.0                     # Minimum Theoretical RR
MIN_LIVE_EXECUTION_RR = 1.6      # Minimum Real RR at Live Market Price after candle close
MAX_RR = 10.0                    # Maximum RR Cap
LOOKBACK = 40                    # Swing Lookback Candles

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
# 🧠 SECTION 3: PLUG-AND-PLAY STRATEGY LOGIC (ONLY CHANGE THIS FOR NEW STRATEGIES)
# ==============================================================================
def generate_strategy_signal(df):
    """
    Evaluates ONLY the last fully CLOSED candle (df.iloc[-2]) so Live matches Backtest 100%.
    Returns: dict {'side': 'long'/'short', 'sl': float, 'tp': float, 'candle_ts': int} or None
    """
    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()

    # Window of 40 candles PRIOR to the just-closed candle (df.iloc[-2])
    window = df.iloc[-LOOKBACK-2:-2]
    signal_candle = df.iloc[-2]          # 🔒 100% Closed 15m Candle (No Intra-Candle Repainting!)
    current_ema = float(signal_candle['EMA_200'])
    candle_ts = int(signal_candle['Timestamp'])

    swing_low = float(window['Low'].min())
    swing_high = float(window['High'].max())
    swing_low_idx = window['Low'].idxmin()
    swing_high_idx = window['High'].idxmax()
    price_range = swing_high - swing_low

    if price_range < PRICE_RANGE_FILTER:
        return None

    # --- BULLISH SETUP ---
    if swing_low_idx < swing_high_idx:
        if float(signal_candle['Close']) < current_ema:
            return None

        entry_level = swing_high - (price_range / DIVISOR)
        sl_level = swing_high - (price_range * SL_MULTIPLIER)

        # Closed-candle rejection check + Intra-candle SL survival check
        if float(signal_candle['Low']) <= entry_level and float(signal_candle['Close']) > entry_level and float(signal_candle['Low']) > sl_level:
            risk_per_coin = entry_level - sl_level
            if risk_per_coin > 0:
                geo_target = (swing_high * entry_level) / swing_low
                raw_rr = (geo_target - entry_level) / risk_per_coin
                if raw_rr >= MIN_RR:
                    applied_rr = min(raw_rr, MAX_RR)
                    tp_level = entry_level + (risk_per_coin * applied_rr)
                    return {
                        'side': 'long',
                        'ref_entry': float(entry_level),
                        'sl': float(sl_level),
                        'tp': float(tp_level),
                        'candle_ts': candle_ts
                    }

    # --- BEARISH SETUP ---
    elif swing_high_idx < swing_low_idx:
        if float(signal_candle['Close']) > current_ema:
            return None

        entry_level = swing_low + (price_range / DIVISOR)
        sl_level = swing_low + (price_range * SL_MULTIPLIER)

        # Closed-candle rejection check + Intra-candle SL survival check
        if float(signal_candle['High']) >= entry_level and float(signal_candle['Close']) < entry_level and float(signal_candle['High']) < sl_level:
            risk_per_coin = sl_level - entry_level
            if risk_per_coin > 0:
                geo_target = (swing_low * entry_level) / swing_high
                raw_rr = (entry_level - geo_target) / risk_per_coin
                if raw_rr >= MIN_RR:
                    applied_rr = min(raw_rr, MAX_RR)
                    tp_level = entry_level - (risk_per_coin * applied_rr)
                    return {
                        'side': 'short',
                        'ref_entry': float(entry_level),
                        'sl': float(sl_level),
                        'tp': float(tp_level),
                        'candle_ts': candle_ts
                    }

    return None

# ==============================================================================
# 🛡️ SECTION 4: IMMUTABLE OPERATIONAL CORE (NEVER MODIFY BELOW THIS LINE)
# ==============================================================================
def get_raw_symbol():
    return SYMBOL.replace('/', '').replace(':', '')

def get_active_position():
    """Returns (pos_amt, entry_price) from Binance Futures"""
    positions = exchange.fetch_positions()
    raw_sym = get_raw_symbol()
    for p in positions:
        if p['info'].get('symbol') == raw_sym or p.get('symbol') == SYMBOL:
            amt = float(p['info'].get('positionAmt', 0))
            entry = float(p['info'].get('entryPrice', 0))
            return amt, entry
    return 0.0, 0.0

def fetch_all_open_orders_combined():
    """Fetches both Basic and Conditional/Stop open orders"""
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

    # Layer 1: Direct Binance Raw Endpoints (Fastest Bulk Nuke)
    for raw_method in ['fapiPrivateDeleteAllOpenOrders', 'fapiPrivateDeleteAlgoOpenOrders']:
        if hasattr(exchange, raw_method):
            try:
                getattr(exchange, raw_method)({'symbol': raw_sym})
            except Exception:
                pass

    # Layer 2: CCXT Unified Bulk Cancel (Normal + Stop + Trigger)
    for params in [{}, {'stop': True}, {'trigger': True}]:
        try:
            exchange.cancel_all_orders(SYMBOL, params=params)
        except Exception:
            pass

    # Layer 3: Individual Order ID / AlgoID Sniper Verification
    remaining_orders = fetch_all_open_orders_combined()
    for o in remaining_orders:
        oid = o.get('id')
        algo_id = o.get('info', {}).get('algoId')
        # Try standard cancel, stop cancel, and trigger cancel
        for p in [{}, {'stop': True}, {'trigger': True}]:
            try:
                exchange.cancel_order(oid, SYMBOL, params=p)
                killed += 1
                break
            except Exception:
                pass
        # Try direct Algo order delete if algoId exists
        if algo_id and hasattr(exchange, 'fapiPrivateDeleteAlgoOrder'):
            try:
                exchange.fapiPrivateDeleteAlgoOrder({'symbol': raw_sym, 'algoId': algo_id})
                killed += 1
            except Exception:
                pass

    return killed

def cleanup_ghost_orders():
    """🧹 Ensures 0 leftover conditional orders when position is flat"""
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
    """Places MARK_PRICE triggered reduceOnly Stop-Loss and Take-Profit orders"""
    close_side = 'sell' if side == 'long' else 'buy'
    sl_rounded = float(exchange.price_to_precision(SYMBOL, sl_price))
    tp_rounded = float(exchange.price_to_precision(SYMBOL, tp_price))
    amt_rounded = float(exchange.amount_to_precision(SYMBOL, abs(amount)))

    # 🛡️ workingType='MARK_PRICE' prevents fake Testnet orderbook spread stop-outs
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
    """🧲 Cancels old SL/TP and places updated Trailing SL + TP"""
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
    🔄 Self-Healing State Recovery:
    1. Rebuilds active_trade_state if container restarted mid-trade.
    2. Places Emergency SL/TP if a naked position (no SL on exchange) is detected.
    """
    side = 'long' if pos_amt > 0 else 'short'
    open_orders = fetch_all_open_orders_combined()

    sl_order_price = None
    tp_order_price = None
    for o in open_orders:
        otype = str(o.get('type', '')).upper()
        raw_type = str(o.get('info', {}).get('type', '')).upper()
        stop_p = float(o.get('stopPrice') or o.get('triggerPrice') or o.get('info', {}).get('stopPrice') or 0)
        if stop_p > 0:
            if 'STOP' in otype or 'STOP' in raw_type:
                sl_order_price = stop_p
            elif 'PROFIT' in otype or 'PROFIT' in raw_type:
                tp_order_price = stop_p

    # 🚨 NAKED POSITION SHIELD: If position has no SL on Binance, place one immediately!
    if sl_order_price is None:
        print("🚨 WARNING: Naked Position Detected (Missing SL)! Placing Protective SL/TP...")
        if active_trade_state is not None:
            sl_order_price = active_trade_state['initial_sl']
            tp_order_price = active_trade_state['tp']
        else:
            sl_order_price = entry_price * (1.0 - EMERGENCY_SL_PCT) if side == 'long' else entry_price * (1.0 + EMERGENCY_SL_PCT)
            tp_order_price = entry_price * (1.0 + EMERGENCY_SL_PCT * 3.0) if side == 'long' else entry_price * (1.0 - EMERGENCY_SL_PCT * 3.0)
        kill_all_active_orders()
        place_sl_tp_orders(sl_order_price, tp_order_price, pos_amt, side)

    # 🔄 RECOVER MEMORY AFTER CONTAINER RESTART
    if active_trade_state is None:
        fallback_tp = tp_order_price if tp_order_price else (entry_price * 1.03 if side == 'long' else entry_price * 0.97)
        # Estimate initial risk distance (at least MIN_SL_DISTANCE_PCT)
        est_initial_sl = sl_order_price
        if (side == 'long' and sl_order_price >= entry_price) or (side == 'short' and sl_order_price <= entry_price):
            # Already trailed to BE or profit!
            est_initial_sl = entry_price * (1.0 - MIN_SL_DISTANCE_PCT * 2) if side == 'long' else entry_price * (1.0 + MIN_SL_DISTANCE_PCT * 2)
            locked_lvl = 1
        else:
            locked_lvl = 0

        active_trade_state = {
            'side': side,
            'entry': entry_price,
            'initial_sl': est_initial_sl,
            'tp': fallback_tp,
            'locked_level': locked_lvl
        }
        print(f"🔄 Recovered Active Trade State after restart: {active_trade_state}")

    return active_trade_state

def calculate_safe_trade_size(usdt_balance, entry_price, sl_price):
    """🛡️ Calculates Risk-Based Size with Minimum SL Distance & Max Notional Fee Capper"""
    risk_amount = usdt_balance * RISK_PERCENT
    risk_per_coin = abs(entry_price - sl_price)
    min_sl_dist = entry_price * MIN_SL_DISTANCE_PCT

    # Reject micro-stops that would get wiped out by normal spread/fees
    if risk_per_coin < min_sl_dist:
        print(f"🛡️ Trade Skipped: SL distance ({risk_per_coin:.2f}) is smaller than safe minimum ({min_sl_dist:.2f}).")
        return 0.0, 0.0

    ideal_size = risk_amount / risk_per_coin
    notional_value = ideal_size * entry_price

    # Cap max position notional to 4x balance so fees never eat the account
    max_safe_notional = min(usdt_balance * LEVERAGE * 0.85, usdt_balance * MAX_NOTIONAL_MULT)

    if notional_value > max_safe_notional:
        capped_size = max_safe_notional / entry_price
        print(f"⚠️ Size Capped for Fee Safety: {ideal_size:.4f} -> {capped_size:.4f}")
        final_size = capped_size
    else:
        final_size = ideal_size

    actual_risk = final_size * risk_per_coin
    return float(exchange.amount_to_precision(SYMBOL, final_size)), actual_risk

def run_master_engine():
    print("=" * 70)
    print(f"🚀 MASTER ENGINE V7.4 (BULLETPROOF CORE) | {SYMBOL} ({TIMEFRAME})")
    print("=" * 70)

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
                # Use Mark Price if available, fallback to last price
                current_price = float(ticker.get('info', {}).get('markPrice') or ticker['last'])
                entry = active_trade_state['entry']
                initial_sl = active_trade_state['initial_sl']
                risk_dist = abs(entry - initial_sl)

                if risk_dist > 0:
                    if active_trade_state['side'] == 'long':
                        current_rr = (current_price - entry) / risk_dist
                        if current_rr >= 4.0 and active_trade_state['locked_level'] < 2:
                            new_sl = entry + (risk_dist * 2.0)
                            if update_trailing_sl(new_sl, active_trade_state['tp'], pos_amt, 'long'):
                                active_trade_state['locked_level'] = 2
                                print(f"🔒 [LONG] 1:4 Hit! Locked 1:2 Profit at {new_sl:.2f}")
                                send_telegram(f"🔒 {SYMBOL} 1:4 Hit! Profit Locked at {new_sl:.2f}")
                        elif current_rr >= 1.0 and active_trade_state['locked_level'] < 1:
                            # Fee-Adjusted Break-Even (+0.12% above entry)
                            new_sl = max(entry * (1.0 + FEE_BUFFER_PCT), entry + (risk_dist * 0.15))
                            if update_trailing_sl(new_sl, active_trade_state['tp'], pos_amt, 'long'):
                                active_trade_state['locked_level'] = 1
                                print(f"🛡️ [LONG] 1:1 Hit! Fee-Safe Break-Even Secured at {new_sl:.2f}")
                                send_telegram(f"🛡️ {SYMBOL} Fee-Safe Break-Even Secured at {new_sl:.2f}")

                    elif active_trade_state['side'] == 'short':
                        current_rr = (entry - current_price) / risk_dist
                        if current_rr >= 4.0 and active_trade_state['locked_level'] < 2:
                            new_sl = entry - (risk_dist * 2.0)
                            if update_trailing_sl(new_sl, active_trade_state['tp'], pos_amt, 'short'):
                                active_trade_state['locked_level'] = 2
                                print(f"🔒 [SHORT] 1:4 Hit! Locked 1:2 Profit at {new_sl:.2f}")
                                send_telegram(f"🔒 {SYMBOL} 1:4 Hit! Profit Locked at {new_sl:.2f}")
                        elif current_rr >= 1.0 and active_trade_state['locked_level'] < 1:
                            # Fee-Adjusted Break-Even (-0.12% below entry)
                            new_sl = min(entry * (1.0 - FEE_BUFFER_PCT), entry - (risk_dist * 0.15))
                            if update_trailing_sl(new_sl, active_trade_state['tp'], pos_amt, 'short'):
                                active_trade_state['locked_level'] = 1
                                print(f"🛡️ [SHORT] 1:1 Hit! Fee-Safe Break-Even Secured at {new_sl:.2f}")
                                send_telegram(f"🛡️ {SYMBOL} Fee-Safe Break-Even Secured at {new_sl:.2f}")

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

                # 🔒 2. Live Price & Real Execution RR Verification
                ticker = exchange.fetch_ticker(SYMBOL)
                live_price = float(ticker.get('info', {}).get('markPrice') or ticker['last'])
                sl_price = signal['sl']
                tp_price = signal['tp']

                if signal['side'] == 'long':
                    if live_price <= sl_price or live_price >= tp_price:
                        last_traded_candle_ts = signal['candle_ts']
                        continue
                    live_rr = (tp_price - live_price) / (live_price - sl_price)
                else:
                    if live_price >= sl_price or live_price <= tp_price:
                        last_traded_candle_ts = signal['candle_ts']
                        continue
                    live_rr = (live_price - tp_price) / (sl_price - live_price)

                if live_rr < MIN_LIVE_EXECUTION_RR:
                    print(f"⏸️ Signal Skipped: Live RR ({live_rr:.2f}) moved below minimum ({MIN_LIVE_EXECUTION_RR}).")
                    last_traded_candle_ts = signal['candle_ts']
                    continue

                # 🔒 3. Balance & Safe Size Calculation
                balance_data = exchange.fetch_balance()
                usdt_balance = float(balance_data['USDT']['free'])
                if usdt_balance < 20:
                    print("⚠️ Low balance (< $20). Sleeping 5m...")
                    time.sleep(300)
                    continue

                trade_size, actual_risk = calculate_safe_trade_size(usdt_balance, live_price, sl_price)
                if trade_size <= 0:
                    last_traded_candle_ts = signal['candle_ts']
                    time.sleep(30)
                    continue

                # 🔒 4. Clean Slate -> Execute Entry -> Place MARK_PRICE SL/TP
                kill_all_active_orders()

                if signal['side'] == 'long':
                    order = exchange.create_market_buy_order(SYMBOL, trade_size)
                else:
                    order = exchange.create_market_sell_order(SYMBOL, trade_size)

                actual_entry = float(order.get('average') or live_price)
                place_sl_tp_orders(sl_price, tp_price, trade_size, signal['side'])

                active_trade_state = {
                    'side': signal['side'],
                    'entry': actual_entry,
                    'initial_sl': sl_price,
                    'tp': tp_price,
                    'locked_level': 0
                }
                last_traded_candle_ts = signal['candle_ts']

                emoji = "🚀" if signal['side'] == 'long' else "📉"
                msg = (
                    f"{emoji} {SYMBOL} {signal['side'].upper()} (V7.4 MASTER)\n"
                    f"Entry: {actual_entry:.2f}\n"
                    f"Target: {tp_price:.2f}\n"
                    f"SL (Mark): {sl_price:.2f}\n"
                    f"Live RR: 1:{live_rr:.2f}\n"
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
