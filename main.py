import ccxt
import time
import os
import pandas as pd
from notifier import send_telegram  # Make sure your telegram module is active

# ==========================================
# 1. V7.4 CONFIGURATION (THE GOLDEN FORMULA)
# ==========================================
SYMBOL = 'BTC/USDT'      # Asset
TIMEFRAME = '15m'        # The Compounding Timeframe
RISK_PERCENT = 0.02      # 🎯 2% Aggressive Compounding Risk
LEVERAGE = 20            
PRICE_RANGE_FILTER = 150 # 30 for PAXG. Ignores choppy tiny swings

# 🎯 HARMONIC V7.4 MATH
DIVISOR = 1.2          # 83.3% Pullback
SL_MULTIPLIER = 0.90   # Tight Stop Loss
MIN_RR = 2.0           
MAX_RR = 10.0          # Max Cap

# ==========================================
# 2. EXCHANGE SETUP (EU-WEST NATIVE, NO PROXY)
# ==========================================
exchange_config = {
    'apiKey': os.environ.get('BINANCE_API_KEY'),
    'secret': os.environ.get('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
    }
}
exchange = ccxt.binance(exchange_config)
# 🛡️ UNCOMMENT BELOW LINE IF USING TESTNET/DEMO ACCOUNT 
exchange.set_sandbox_mode(True) 

try:
    exchange.set_leverage(LEVERAGE, SYMBOL)
    print(f"✅ Leverage successfully set to {LEVERAGE}x for {SYMBOL}")
except Exception as e:
    print(f"⚠️ Warning: Set leverage manually to {LEVERAGE}x in Binance.")

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def cleanup_ghost_orders():
    """🧹 Clears all leftover orders (The Nuke Method)"""
    try:
        positions = exchange.fetch_positions()
        pos_amt = 0.0
        raw_symbol = SYMBOL.replace('/', '').replace(':', '') 
        for p in positions:
            if p['info'].get('symbol') == raw_symbol or p.get('symbol') == SYMBOL:
                pos_amt = float(p['info'].get('positionAmt', 0))
                break
        
        if pos_amt == 0.0:
            normal_orders = exchange.fetch_open_orders(SYMBOL)
            stop_orders = exchange.fetch_open_orders(SYMBOL, params={'stop': True})
            if len(normal_orders) + len(stop_orders) > 0:
                print("🧹 Cleaning up Ghost Orders...")
                exchange.cancel_all_orders(SYMBOL)
                time.sleep(1)
    except Exception as e:
        pass

def update_trailing_sl(new_sl, tp_price, amount, side):
    """🧲 Cancels old Stop-Loss and places a new one to Lock Profits"""
    try:
        exchange.cancel_all_orders(SYMBOL) # Kill old TP & SL
        time.sleep(1)
        
        close_side = 'sell' if side == 'long' else 'buy'
        
        # Place New SL
        exchange.create_order(SYMBOL, 'STOP_MARKET', close_side, amount, None, params={
            'stopPrice': float(new_sl), 'reduceOnly': True
        })
        # Place Same TP back
        exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', close_side, amount, None, params={
            'stopPrice': float(tp_price), 'reduceOnly': True
        })
        return True
    except Exception as e:
        print(f"⚠️ Error updating Trailing SL: {e}")
        return False

# ==========================================
# 4. THE V7.4 MASTER ENGINE
# ==========================================
def run_v74_engine():
    print("="*60)
    print(f"🚀 V7.4 ENGINE STARTED | RISK: {RISK_PERCENT*100}% | SL: MULTI-TIER")
    print("="*60)
    
    cleanup_ghost_orders()
    active_trade_state = None  # Holds local memory for trailing SL
    
    while True:
        try:
            # --- CHECK POSITION STATE ---
            positions = exchange.fetch_positions()
            pos_amt = 0.0
            raw_symbol = SYMBOL.replace('/', '').replace(':', '')
            for p in positions:
                if p['info'].get('symbol') == raw_symbol or p.get('symbol') == SYMBOL:
                    pos_amt = float(p['info'].get('positionAmt', 0))
                    break

            # 🧲 MULTI-TIER TRAILING SL LOGIC
            if pos_amt != 0.0:
                if active_trade_state is not None:
                    ticker = exchange.fetch_ticker(SYMBOL)
                    current_price = float(ticker['last'])
                    
                    entry = active_trade_state['entry']
                    initial_sl = active_trade_state['initial_sl']
                    risk_dist = abs(entry - initial_sl)
                    
                    if active_trade_state['side'] == 'long':
                        current_rr = (current_price - entry) / risk_dist if risk_dist > 0 else 0
                        
                        if current_rr >= 4.0 and active_trade_state['locked_level'] < 2:
                            new_sl = entry + (risk_dist * 2.0)
                            if update_trailing_sl(new_sl, active_trade_state['tp'], abs(pos_amt), 'long'):
                                active_trade_state['locked_level'] = 2
                                print(f"🔒 [LONG] 1:4 Profit Locked! New SL: {new_sl}")
                                send_telegram(f"🔒 {SYMBOL} 1:4 Profit Locked! Trailing SL moved to {new_sl:.2f}")
                                
                        elif current_rr >= 1.0 and active_trade_state['locked_level'] < 1:
                            new_sl = entry
                            if update_trailing_sl(new_sl, active_trade_state['tp'], abs(pos_amt), 'long'):
                                active_trade_state['locked_level'] = 1
                                print(f"🛡️ [LONG] 1:1 Hit! Break-Even Secured. New SL: {new_sl}")
                                send_telegram(f"🛡️ {SYMBOL} Break-Even Secured at {new_sl:.2f}")

                    elif active_trade_state['side'] == 'short':
                        current_rr = (entry - current_price) / risk_dist if risk_dist > 0 else 0
                        
                        if current_rr >= 4.0 and active_trade_state['locked_level'] < 2:
                            new_sl = entry - (risk_dist * 2.0)
                            if update_trailing_sl(new_sl, active_trade_state['tp'], abs(pos_amt), 'short'):
                                active_trade_state['locked_level'] = 2
                                print(f"🔒 [SHORT] 1:4 Profit Locked! New SL: {new_sl}")
                                send_telegram(f"🔒 {SYMBOL} 1:4 Profit Locked! Trailing SL moved to {new_sl:.2f}")
                                
                        elif current_rr >= 1.0 and active_trade_state['locked_level'] < 1:
                            new_sl = entry
                            if update_trailing_sl(new_sl, active_trade_state['tp'], abs(pos_amt), 'short'):
                                active_trade_state['locked_level'] = 1
                                print(f"🛡️ [SHORT] 1:1 Hit! Break-Even Secured. New SL: {new_sl}")
                                send_telegram(f"🛡️ {SYMBOL} Break-Even Secured at {new_sl:.2f}")

                time.sleep(30)
                continue
                
            else:
                # Flat state, reset memory
                if active_trade_state is not None:
                    print("🔄 Trade Closed. Returning to Scan Mode.")
                    active_trade_state = None
                
                cleanup_ghost_orders()
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 📡 Scanning Market {SYMBOL}...")

            # --- FETCH DATA & EMA 200 ---
            bars = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=250)
            if not bars: continue
            
            df = pd.DataFrame(bars, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()
            
            lookback = 40
            window = df.iloc[-lookback-1:-1]
            current_candle = df.iloc[-1]
            current_ema = current_candle['EMA_200']
            
            swing_low, swing_high = window['Low'].min(), window['High'].max()
            swing_low_idx, swing_high_idx = window['Low'].idxmin(), window['High'].idxmax()
            price_range = swing_high - swing_low

            if price_range < PRICE_RANGE_FILTER: 
                time.sleep(30)
                continue

            balance_data = exchange.fetch_balance()
            usdt_balance = float(balance_data['USDT']['free'])
            if usdt_balance < 20:
                time.sleep(300)
                continue
                
            risk_amount = usdt_balance * RISK_PERCENT

            # ==========================================
            # --- BULLISH SETUP ---
            # ==========================================
            if swing_low_idx < swing_high_idx: 
                if current_candle['Close'] < current_ema: 
                    time.sleep(30)
                    continue 
                
                sniper_discount = price_range / DIVISOR
                entry_level = swing_high - sniper_discount

                if current_candle['Low'] <= entry_level and current_candle['Close'] > entry_level:
                    sl_level = swing_high - (price_range * SL_MULTIPLIER)
                    risk_per_coin = entry_level - sl_level
                    
                    if risk_per_coin > 0:
                        geo_target = (swing_high * entry_level) / swing_low
                        raw_rr = (geo_target - entry_level) / risk_per_coin
                        
                        if raw_rr >= MIN_RR:
                            applied_rr = min(raw_rr, MAX_RR)
                            tp_level = entry_level + (risk_per_coin * applied_rr)
                            
                            # 🛡️ THE MARGIN CAPPER (BULLISH)
                            ideal_trade_size = risk_amount / risk_per_coin
                            notional_value = ideal_trade_size * entry_level
                            margin_required = notional_value / LEVERAGE
                            max_allowed_margin = usdt_balance * 0.90
                            
                            if margin_required > max_allowed_margin:
                                max_notional = max_allowed_margin * LEVERAGE
                                trade_size = round(max_notional / entry_level, 4)
                                print(f"⚠️ Margin Capped! Reduced size from {ideal_trade_size:.4f} to {trade_size:.4f}")
                            else:
                                trade_size = round(ideal_trade_size, 4)

                            exchange.create_market_buy_order(SYMBOL, trade_size)
                            exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', trade_size, None, params={'stopPrice': float(sl_level), 'reduceOnly': True})
                            exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', trade_size, None, params={'stopPrice': float(tp_level), 'reduceOnly': True})
                            
                            active_trade_state = {'side': 'long', 'entry': entry_level, 'initial_sl': sl_level, 'tp': tp_level, 'locked_level': 0}
                            
                            msg = f"🚀 {SYMBOL} LONG (V7.4)\nEntry: {entry_level:.2f}\nTarget: {tp_level:.2f}\nSL: {sl_level:.2f}\nRisk: ${risk_amount:.2f}"
                            send_telegram(msg)
                            time.sleep(60)

            # ==========================================
            # --- BEARISH SETUP ---
            # ==========================================
            elif swing_high_idx < swing_low_idx:  
                if current_candle['Close'] > current_ema:
                    time.sleep(30)
                    continue 

                sniper_discount = price_range / DIVISOR
                entry_level = swing_low + sniper_discount

                if current_candle['High'] >= entry_level and current_candle['Close'] < entry_level:
                    sl_level = swing_low + (price_range * SL_MULTIPLIER)
                    risk_per_coin = sl_level - entry_level
                    
                    if risk_per_coin > 0:
                        geo_target = (swing_low * entry_level) / swing_high
                        raw_rr = (entry_level - geo_target) / risk_per_coin
                        
                        if raw_rr >= MIN_RR:
                            applied_rr = min(raw_rr, MAX_RR)
                            tp_level = entry_level - (risk_per_coin * applied_rr)
                            
                            # 🛡️ THE MARGIN CAPPER (BEARISH)
                            ideal_trade_size = risk_amount / risk_per_coin
                            notional_value = ideal_trade_size * entry_level
                            margin_required = notional_value / LEVERAGE
                            max_allowed_margin = usdt_balance * 0.90
                            
                            if margin_required > max_allowed_margin:
                                max_notional = max_allowed_margin * LEVERAGE
                                trade_size = round(max_notional / entry_level, 4)
                                print(f"⚠️ Margin Capped! Reduced size from {ideal_trade_size:.4f} to {trade_size:.4f}")
                            else:
                                trade_size = round(ideal_trade_size, 4)

                            exchange.create_market_sell_order(SYMBOL, trade_size)
                            exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', trade_size, None, params={'stopPrice': float(sl_level), 'reduceOnly': True})
                            exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', trade_size, None, params={'stopPrice': float(tp_level), 'reduceOnly': True})
                            
                            active_trade_state = {'side': 'short', 'entry': entry_level, 'initial_sl': sl_level, 'tp': tp_level, 'locked_level': 0}
                            
                            msg = f"📉 {SYMBOL} SHORT (V7.4)\nEntry: {entry_level:.2f}\nTarget: {tp_level:.2f}\nSL: {sl_level:.2f}\nRisk: ${risk_amount:.2f}"
                            send_telegram(msg)
                            time.sleep(60)

            time.sleep(60)
            
        except ccxt.NetworkError:
            print("📡 Network Error. Sleeping 60s...")
            time.sleep(60)
        except Exception as e:
            print(f"❌ Main Loop Error: {e}")
            time.sleep(10)

if __name__ == '__main__':
    run_v74_engine()
