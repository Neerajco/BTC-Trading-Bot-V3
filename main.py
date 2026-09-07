import ccxt
import time
import os
import pandas as pd
from notifier import send_telegram  # Assuming you have your telegram module

# --- 1. CONFIGURATION & V7.2 MATH (BTC) ---
SYMBOL = 'BTC/USDT'      # 🏆 Primary Asset
TIMEFRAME = '15m'
RISK_PERCENT = 0.01      # 1% Risk per trade
LEVERAGE = 20            # 🛡️ Force Leverage to prevent Insufficient Balance

# 🎯 HARMONIC V7.2 PARAMETERS
DIVISOR = 1.2          # 83.3% Deep Pullback
SL_MULTIPLIER = 0.91   # 91.0% Breathing Room
MIN_RR = 2.0           # Minimum acceptable Risk-to-Reward
MAX_RR = 7.0           # Strict 1:7 RR cap
LOOKBACK = 40          # Candles to find the impulse wave

# --- 2. EXCHANGE SETUP ---
exchange_config = {
    'apiKey': os.environ.get('BINANCE_API_KEY'),
    'secret': os.environ.get('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
    }
}

# (Optional) DevOps Proxy Guardrail - Won't do anything if variable doesn't exist
proxy_url = os.environ.get('MY_CUSTOM_PROXY')
if proxy_url:
    exchange_config['httpProxy'] = proxy_url

exchange = ccxt.binance(exchange_config)

# ✅ THE FINAL FIX: Official method for Demo Trading
exchange.enable_demo_trading(True)

# 🛡️ INIT: FORCE LEVERAGE (Fixes Insufficient Margin Error)
try:
    exchange.set_leverage(LEVERAGE, SYMBOL)
    print(f"✅ Leverage successfully set to {LEVERAGE}x for {SYMBOL}")
except Exception as e:
    print(f"⚠️ Warning: Could not set leverage automatically: {e}. Please ensure it is set to 20x manually in Binance.")

def cleanup_ghost_orders():
    """🧹 Forcefully clears leftover TP/SL orders if no active position exists."""
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
            
            all_ghosts = normal_orders + stop_orders
            total_ghosts = len(all_ghosts)
            
            if total_ghosts > 0:
                print(f"🧹 Trade Closed! Clearing {total_ghosts} Ghost Orders for {SYMBOL}...")
                
                # Method 1: Ask Binance nicely
                try:
                    exchange.cancel_all_orders(SYMBOL)
                except:
                    pass
                
                # Method 2: TARGETED SNIPING (The Bulletproof Fix)
                for order in all_ghosts:
                    try:
                        exchange.cancel_order(order['id'], SYMBOL)
                        print(f"🔫 Successfully sniped ghost order ID: {order['id']}")
                    except Exception as e:
                        pass
                
                time.sleep(2) # Give Binance 2 seconds to update its database
                
    except Exception as e:
        print(f"⚠️ Cleanup Error: {e}")

def check_recent_pnl():
    """Fetches the last trade from Binance and prints the Realized PNL."""
    try:
        trades = exchange.fetch_my_trades(SYMBOL, limit=2)
        if trades:
            last_trade = trades[-1]
            price = last_trade['price']
            realized_pnl = float(last_trade['info'].get('realizedPnl', '0'))
            
            if realized_pnl > 0:
                print(f"🏆 PNL REPORT: TRADE CLOSED IN PROFIT! Exit Price: {price} | Profit: +${realized_pnl:.2f}")
                send_telegram(f"🏆 PROFIT BOOKED!\nExit Price: {price}\nProfit: +${realized_pnl:.2f}")
            elif realized_pnl < 0:
                print(f"🛡️ PNL REPORT: TRADE CLOSED IN LOSS! Exit Price: {price} | Loss: ${realized_pnl:.2f}")
                send_telegram(f"🛡️ STOP LOSS HIT\nExit Price: {price}\nLoss: ${realized_pnl:.2f}")
    except Exception as e:
        print(f"⚠️ Could not fetch PNL history: {e}")

def run_harmonic_v7_btc():
    print("="*60)
    print(f"🚀 BTC HARMONIC V7.2 ENGINE STARTED")
    print(f"⚙️ Divisor: {DIVISOR} | Target RR: {MIN_RR} to {MAX_RR}")
    print("="*60)
    
    was_in_trade = False  
    last_executed_candle_time = None  # 🧠 NAYA MEMORY VARIABLE: Tracks last traded candle
    
    while True:
        try:
            # 1. CLEANUP GHOST ORDERS FIRST
            cleanup_ghost_orders()

            # Check active position safely
            positions = exchange.fetch_positions()
            pos_amt = 0.0
            
            raw_symbol = SYMBOL.replace('/', '').replace(':', '')
            for p in positions:
                if p['info'].get('symbol') == raw_symbol or p.get('symbol') == SYMBOL:
                    pos_amt = float(p['info'].get('positionAmt', 0))
                    break

            # --- STATE LOGIC ---
            if pos_amt != 0.0:
                print(f"⏳ Active Trade Running (Size: {pos_amt}). Waiting for TP/SL...")
                was_in_trade = True
                time.sleep(30)
                continue
            else:
                if was_in_trade:
                    print("\n" + "="*50)
                    print("🔄 TRADE CLOSED! No active position detected.")
                    check_recent_pnl()
                    print("📡 Returning to Scanning Mode...")
                    print("="*50 + "\n")
                    was_in_trade = False
                
                current_time = time.strftime('%Y-%m-%d %H:%M:%S')
                print(f"[{current_time}] 📡 Scanning Market {SYMBOL} for 83.3% Pullback...")

            # 2. FETCH DATA & FIND IMPULSE
            bars = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=LOOKBACK + 5)
            df = pd.DataFrame(bars, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
            
            current_candle_time = df['Timestamp'].iloc[-1]
            
            # 🛑 REVENGE TRADING LOCKOUT: Prevents "Machine-Gun" bug
            if current_candle_time == last_executed_candle_time:
                time.sleep(30)
                continue
            
            window = df.iloc[-LOOKBACK-1:-1] # Ignore currently open candle
            current_candle = df.iloc[-1]
            
            swing_low = window['Low'].min()
            swing_high = window['High'].max()
            swing_low_idx = window['Low'].idxmin()
            swing_high_idx = window['High'].idxmax()
            price_range = swing_high - swing_low

            # BTC Price filter: Ignore flat chops under $150
            if price_range < 150: 
                time.sleep(30)
                continue

            # 3. SMART BALANCE CHECK & EXECUTION
            balance_data = exchange.fetch_balance()
            usdt_balance = float(balance_data['USDT']['free'])
            
            # 🚨 INSUFFICIENT BALANCE SAFETY CATCH
            # Pauses bot if free margin is critically low, preventing crash
            if usdt_balance < 20:
                print(f"⚠️ INSUFFICIENT FREE MARGIN! Available: ${usdt_balance:.2f}. Pausing bot for 5 mins.")
                time.sleep(300)
                continue

            # Dynamic Position Sizing based on 1.0% total account balance
            risk_amount = usdt_balance * RISK_PERCENT

# --- BULLISH SETUP ---
            if swing_low_idx < swing_high_idx: 
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
                            
                            # 🛡️ THE MARGIN CAP (Properly Indented)
                            raw_trade_size = risk_amount / risk_per_coin
                            max_allowed_size = (usdt_balance * LEVERAGE * 0.75) / entry_level
                            trade_size = round(min(raw_trade_size, max_allowed_size), 3)

                            if trade_size <= 0:
                                print(f"⚠️ Margin too low to take trade. Skipped.")
                                continue   
                            
                            print(f"🟢 BULLISH V7.2 TRIGGERED! Entry: {entry_level:.2f} | Applied RR: 1:{applied_rr:.2f}")
                            
                            # Execute Market Order
                            exchange.create_market_buy_order(SYMBOL, trade_size)
                            
                            # Place Conditional SL & TP
                            exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', trade_size, None, params={
                                'triggerPrice': float(sl_level), 'reduceOnly': True
                            })
                            exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', trade_size, None, params={
                                'triggerPrice': float(tp_level), 'reduceOnly': True
                            })
                            
                            send_telegram(f"🚀 V7.2 LONG Executed!\nEntry: {entry_level:.2f}\nTarget: {tp_level:.2f}\nSL: {sl_level:.2f}\nRR: 1:{applied_rr:.2f}")
                            last_executed_candle_time = current_candle_time  # 🔒 LOCK IN THE CANDLE
                            time.sleep(60)

            # --- BEARISH SETUP ---
            elif swing_high_idx < swing_low_idx:  
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
                            
                            # 🛡️ THE MARGIN CAP (Properly Indented)
                            raw_trade_size = risk_amount / risk_per_coin
                            max_allowed_size = (usdt_balance * LEVERAGE * 0.75) / entry_level
                            trade_size = round(min(raw_trade_size, max_allowed_size), 3)

                            if trade_size <= 0:
                                print(f"⚠️ Margin too low to take trade. Skipped.")
                                continue   
                            
                            print(f"🔴 BEARISH V7.2 TRIGGERED! Entry: {entry_level:.2f} | Applied RR: 1:{applied_rr:.2f}")
                            
                            # Execute Market Order
                            exchange.create_market_sell_order(SYMBOL, trade_size)
                            
                            # Place Conditional SL & TP
                            exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', trade_size, None, params={
                                'triggerPrice': float(sl_level), 'reduceOnly': True
                            })
                            exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', trade_size, None, params={
                                'triggerPrice': float(tp_level), 'reduceOnly': True
                            })
                            
                            send_telegram(f"📉 V7.2 SHORT Executed!\nEntry: {entry_level:.2f}\nTarget: {tp_level:.2f}\nSL: {sl_level:.2f}\nRR: 1:{applied_rr:.2f}")
                            last_executed_candle_time = current_candle_time  # 🔒 LOCK IN THE CANDLE
                            time.sleep(60)

            time.sleep(30) # Loop delay

        except Exception as e:
            print(f"❌ Main Loop Error: {e}")
            time.sleep(10)

if __name__ == '__main__':
    run_harmonic_v7_btc()
