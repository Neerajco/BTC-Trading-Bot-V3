import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"⚠️ Telegram Config Missing! Log: {msg}")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        params = {'chat_id': CHAT_ID, 'text': msg}
        # 5-second timeout to prevent network hanging
        requests.get(url, params=params, timeout=5) 
    except Exception as e:
        print(f"❌ Telegram Network Error: {e}")