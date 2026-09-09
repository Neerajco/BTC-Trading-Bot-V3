import ccxt
import time
import os
import pandas as pd
from notifier import send_telegram  # Assuming you have your telegram module

# --- 1. CONFIGURATION & V7.2 MATH ---
SYMBOL = 'PAXG/USDT'     # 🏆 Target Asset: GOLD
TIMEFRAME = '15m'
RISK_PERCENT = 0.01
LEVERAGE = 20            # 🛡️ Force Leverage to prevent Insufficient Balance

# 🎯 HARMONIC V7.2 LIVE MATH PARAMETERS
DIVISOR = 1.2          # 83.3% Deep Pullback
SL_MULTIPLIER = 0.91   # 91.0% Breathing Room
MIN_RR = 2.0           # Minimum acceptable Risk-to-Reward
MAX_RR = 7.0           # Strict 1:7 RR cap
LOOKBACK = 40          # Candles to find the impulse wave

# --- 2. EXCHANGE SETUP (Proxy-Free EU Server Mode) ---
# 🚨 PROXY LOGIC COMPLETELY REMOVED! Running natively on EU Server.
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

# ✅ DEMO MODE ENABLED
exchange.enable_demo_trading(True)

# 🛡️ INIT: FORCE LEVERAGE
try:
    exchange.set_leverage(LEVERAGE, SYMBOL)
    print(f"✅ Leverage successfully set to {LEVERAGE}x for {SYMBOL}")
except Exception as e:
    print(f"⚠️ Warning: Could not set leverage automatically: {e}. Please ensure it is set to 20x manually in Binance.")

def cleanup_ghost_orders():
    """🧹 Forcefully clears ALL leftover orders (The Nuke Method)"""
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
            total_ghosts = len(normal_orders) + len(stop_orders)
            
            if total_ghosts > 0:
                print(f"🧹 Trade Closed/Startup! Found {total_ghosts} Ghost Orders. Dropping the Nuke...")
                try:
                    exchange.cancel_all_orders(SYMBOL)
                    print("☢️ All Limit Orders Cleared!")
                    exchange.cancel_all_orders(SYMBOL, params={'stop': True})
                    print("☢️ All Conditional Orders Cleared!")
                except Exception as e:
                    print(f"⚠️ Nuke API Error: {e}")
                time.sleep(2) 
    except Exception as e:
        print(f"⚠️ Cleanup Error: {e}")

def check_recent_pnl():
    """Fetches the actual MOST RECENT trade accurately."""
    try:
        trades = exchange.fetch_my_trades(SYMBOL, limit=10) 
        if trades:
            trades.sort(key=lambda x: x['timestamp'])
            last_trade = trades[-1]
            price = last_trade['price']
            
            five_mins_ago = time.time() * 1000 - (5 * 60 * 1000)
            total_realized = sum(
                float(t['info'].get('realizedPnl', '0')) 
                for t in trades if t['timestamp'] >= five_mins_ago
            )

            if total_realized > 0:
                print(f"🏆 PNL REPORT: TRADE CLOSED IN PROFIT! Exit Price: {price} | Profit: +${total_realized:.2f}")
                send_telegram(f"🏆 PROFIT BOOKED!\nExit Price: {price}\nProfit: +${total_realized:.2f}")
            elif total_realized < 0:
                print(f"🛡️ PNL REPORT: TRADE CLOSED IN LOSS! Exit Price: {price} | Loss: ${total_realized:.2f}")
                send_telegram(f"🛡️ STOP LOSS HIT\nExit Price: {price}\nLoss: ${total_realized:.2f}")
    except Exception as e:
        print(f"⚠️ Could not fetch PNL history: {e}")

def run_gold_v7_engine():
    print("="*60)
    print(f"🚀 GOLD V7.2 ENGINE STARTED | Target RR: {MIN_RR} to {MAX_RR}")
    print("🌍 SERVER: DIRECT CONNECTION (EU-WEST NATIVE)")
    print("="*60)
    
    # 🧹 FORCE CLEANUP ON STARTUP
    print("🧹 Performing Startup Deep Clean...")
    cleanup_ghost_orders()
    
    was_in_trade = False  
    last_executed_candle_time = None  
    
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

            # --- STATE & LOGGING LOGIC ---
            if pos_amt != 0.0:
                print(f"⏳ {SYMBOL} Active Trade Running (Size: {pos_amt}). Waiting for TP/SL...")
                was_in_trade = True
                time.sleep(30)
                continue
            else:
                if was_in_trade:
                    print("\n" + "="*50)
                    print(f"🔄 {SYMBOL} TRADE CLOSED! No active position detected.")
                    check_recent_pnl()
                    print("📡 Returning to Scanning Mode...")
                    print("="*50 + "\n")
                    was_in_trade = False
                
                current_time = time.strftime('%Y-%m-%d %H:%M:%S')
                print(f"[{current_time}] 📡 Scanning Market {SYMBOL} for 83.3% Pullback...")

            # 2. FETCH DATA & FIND IMPULSE
            bars = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=LOOKBACK + 5)
            
            # 🛡️ SAFETY WALL
            if not bars or len(bars) < LOOKBACK:
                print("⚠️ Incomplete data received from exchange. Retrying...")
                time.sleep(10)
                continue
                
            df = pd.DataFrame(bars, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
            
            current_candle_time = df['Timestamp'].iloc[-1]
            
            # 🛑 REVENGE TRADING LOCKOUT
            if current_candle_time == last_executed_candle_time:
                time.sleep(30)
                continue
            
            window = df.iloc[-LOOKBACK-1:-1] 
            current_candle = df.iloc[-1]
            
            swing_low = window['Low'].min()
            swing_high = window['High'].max()
            swing_low_idx = window['Low'].idxmin()
            swing_high_idx = window['High'].idxmax()
            price_range = swing_high - swing_low

            if price_range < 15: 
                time.sleep(30)
                continue

            # 3. SMART BALANCE CHECK & EXECUTION
            balance_data = exchange.fetch_balance()
            usdt_balance = float(balance_data['USDT']['free'])
            
            if usdt_balance < 20:
                print(f"⚠️ INSUFFICIENT FREE MARGIN! Available: ${usdt_balance:.2f}. Pausing bot for 5 mins.")
                time.sleep(300)
                continue
                
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
                            
                            raw_trade_size = risk_amount / risk_per_coin
                            max_allowed_size = (usdt_balance * LEVERAGE * 0.75) / entry_level
                            trade_size = round(min(raw_trade_size, max_allowed_size), 4)

                            if trade_size <= 0:
                                print(f"⚠️ Margin too low to take trade. Skipped.")
                                continue   

                            print(f"🟢 BULLISH {SYMBOL} TRIGGERED! Entry: {entry_level:.2f} | Applied RR: 1:{applied_rr:.2f}")
                            
                            exchange.create_market_buy_order(SYMBOL, trade_size)
                            
                            exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', trade_size, None, params={
                                'triggerPrice': float(sl_level), 'reduceOnly': True
                            })
                            exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', trade_size, None, params={
                                'triggerPrice': float(tp_level), 'reduceOnly': True
                            })
                            
                            send_telegram(f"🚀 {SYMBOL} LONG Executed!\nEntry: {entry_level:.2f}\nTarget: {tp_level:.2f}\nSL: {sl_level:.2f}\nRR: 1:{applied_rr:.2f}")
                            last_executed_candle_time = current_candle_time  
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
                            
                            raw_trade_size = risk_amount / risk_per_coin
                            max_allowed_size = (usdt_balance * LEVERAGE * 0.75) / entry_level
                            trade_size = round(min(raw_trade_size, max_allowed_size), 4)

                            if trade_size <= 0:
                                print(f"⚠️ Margin too low to take trade. Skipped.")
                                continue   

                            print(f"🔴 BEARISH {SYMBOL} TRIGGERED! Entry: {entry_level:.2f} | Applied RR: 1:{applied_rr:.2f}")
                            
                            exchange.create_market_sell_order(SYMBOL, trade_size)
                            
                            exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', trade_size, None, params={
                                'triggerPrice': float(sl_level), 'reduceOnly': True
                            })
                            exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', trade_size, None, params={
                                'triggerPrice': float(tp_level), 'reduceOnly': True
                            })
                            
                            send_telegram(f"📉 {SYMBOL} SHORT Executed!\nEntry: {entry_level:.2f}\nTarget: {tp_level:.2f}\nSL: {sl_level:.2f}\nRR: 1:{applied_rr:.2f}")
                            last_executed_candle_time = current_candle_time  
                            time.sleep(60)

            time.sleep(60)

        except ccxt.NetworkError as e:
            print(f"📡 Network Timeout. Giving it a cooldown. Sleeping for 60s...")
            time.sleep(60)
        except Exception as e:
            print(f"❌ Main Loop Error: {e}")
            time.sleep(10)

if __name__ == '__main__':
    run_gold_v7_engine()
