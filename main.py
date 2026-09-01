import ccxt
import time
import os
import pandas as pd
from notifier import send_telegram  # Assuming you have your telegram module

# --- 1. CONFIGURATION & V7.2 MATH ---
SYMBOL = 'BTCUSDT'
TIMEFRAME = '15m'
RISK_PERCENT = 0.01

# 🎯 HARMONIC V7.2 PARAMETERS
DIVISOR = 1.2          # 83.3% Deep Pullback
SL_MULTIPLIER = 0.91   # 91.0% Breathing Room
LOOKBACK = 40          # Candles to find the impulse wave

# --- 2. EXCHANGE SETUP ---
exchange = ccxt.binance({
    'apiKey': os.environ.get('BINANCE_API_KEY'),
    'secret': os.environ.get('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})
exchange.set_sandbox_mode(True) # Demo Trading Enabled

def cleanup_ghost_orders():
    """🧹 Forcefully clears leftover TP/SL orders if no active position exists."""
    try:
        positions = exchange.fetch_positions([SYMBOL])
        pos_data = [p for p in positions if p['symbol'] == SYMBOL][0]
        pos_amt = float(pos_data['info']['positionAmt'])
        
        if pos_amt == 0.0:
            open_orders = exchange.fetch_open_orders(SYMBOL)
            if len(open_orders) > 0:
                print(f"🧹 Trade Closed! Clearing {len(open_orders)} Ghost Orders...")
                exchange.cancel_all_orders(SYMBOL)
                # send_telegram(f"🧹 Cleaned up {len(open_orders)} Ghost Orders.")
    except Exception as e:
        print(f"⚠️ Cleanup Error: {e}")

def run_harmonic_v7():
    print(f"🚀 HARMONIC V7.2 ENGINE STARTED | Divisor: {DIVISOR} | SL: {SL_MULTIPLIER}")
    
    while True:
        try:
            # 1. CLEANUP GHOST ORDERS FIRST
            cleanup_ghost_orders()

            # Check active position
            positions = exchange.fetch_positions([SYMBOL])
            pos_data = [p for p in positions if p['symbol'] == SYMBOL][0]
            pos_amt = float(pos_data['info']['positionAmt'])

            if pos_amt != 0.0:
                print(f"⏳ Active Trade Running (Size: {pos_amt}). Waiting...")
                time.sleep(30)
                continue

            # 2. FETCH DATA & FIND IMPULSE
            bars = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=LOOKBACK + 5)
            df = pd.DataFrame(bars, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
            
            window = df.iloc[-LOOKBACK-1:-1] # Ignore currently open candle
            current_candle = df.iloc[-1]
            
            swing_low = window['Low'].min()
            swing_high = window['High'].max()
            swing_low_idx = window['Low'].idxmin()
            swing_high_idx = window['High'].idxmax()
            price_range = swing_high - swing_low

            if price_range < 150: # Ignore flat chop
                time.sleep(30)
                continue

            # 3. HARMONIC MATH & EXECUTION
            balance_data = exchange.fetch_balance()
            usdt_balance = float(balance_data['USDT']['free'])
            risk_amount = usdt_balance * RISK_PERCENT

            # --- BULLISH SETUP ---
            if swing_low_idx < swing_high_idx: 
                sniper_discount = price_range / DIVISOR
                entry_level = swing_high - sniper_discount

                # If price drops into the 83.3% Harmonic Zone
                if current_candle['Low'] <= entry_level and current_candle['Close'] > entry_level:
                    sl_level = swing_high - (price_range * SL_MULTIPLIER)
                    risk_per_coin = entry_level - sl_level
                    
                    if risk_per_coin > 0:
                        geo_target = (swing_high * entry_level) / swing_low
                        trade_size = round(risk_amount / risk_per_coin, 3)

                        print(f"🟢 BULLISH V7.2 TRIGGERED! Entry: {entry_level} | Target: {geo_target}")
                        
                        # Execute Market Order
                        exchange.create_market_buy_order(SYMBOL, trade_size)
                        
                        # Place Conditional SL & TP
                        exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', trade_size, params={'stopPrice': sl_level})
                        exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', trade_size, params={'stopPrice': geo_target})
                        
                        send_telegram(f"🚀 V7.2 LONG Executed!\nEntry: {entry_level}\nTarget: {geo_target}\nSL: {sl_level}")
                        time.sleep(60)

            # --- BEARISH SETUP ---
            elif swing_high_idx < swing_low_idx:  
                sniper_discount = price_range / DIVISOR
                entry_level = swing_low + sniper_discount

                # If price pumps into the 83.3% Harmonic Zone
                if current_candle['High'] >= entry_level and current_candle['Close'] < entry_level:
                    sl_level = swing_low + (price_range * SL_MULTIPLIER)
                    risk_per_coin = sl_level - entry_level
                    
                    if risk_per_coin > 0:
                        geo_target = (swing_low * entry_level) / swing_high
                        trade_size = round(risk_amount / risk_per_coin, 3)

                        print(f"🔴 BEARISH V7.2 TRIGGERED! Entry: {entry_level} | Target: {geo_target}")
                        
                        # Execute Market Order
                        exchange.create_market_sell_order(SYMBOL, trade_size)
                        
                        # Place Conditional SL & TP
                        exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', trade_size, params={'stopPrice': sl_level})
                        exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', trade_size, params={'stopPrice': geo_target})
                        
                        send_telegram(f"📉 V7.2 SHORT Executed!\nEntry: {entry_level}\nTarget: {geo_target}\nSL: {sl_level}")
                        time.sleep(60)

            time.sleep(30) # Loop delay

        except Exception as e:
            print(f"❌ Main Loop Error: {e}")
            time.sleep(10)

if __name__ == '__main__':
    run_harmonic_v7()
