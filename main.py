import requests
import time
import json
import os

TELEGRAM_TOKEN = "8715088429:AAEfwN6qsWy-GOxTkAJ8oLGUpwVOc-H1sAM"
CHAT_ID = "8956179287"

TREND_INTERVAL = "1day"
ENTRY_INTERVALS = ["1hour", "4hour"]
TOP_N = 15
TOLERANCE = 0.001
MEMORY_FILE = "last_alerts.json"

STABLECOINS = [
    'USDC','FDUSD','TUSD','BUSD','DAI','USDP','EUR','GBP','USD1','USDE',
    'USDS','PYUSD','USDD','USTC','FRAX','GUSD','LUSD','SUSD','USDT','USDT0',
    'USDR','USDX','USDY','ALUSD','MIM','DOLA','CUSD','CEUR','EURS','STEUR',
    'VAI','XUSD','USDN','UXD','USK','USDL','RLUSD','USDG','USDQ','USDJ',
    'USDF','USDH','USDTB','USDFI'
]

HEADERS = {"User-Agent": "Mozilla/5.0"}

if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, 'r') as f:
        last_alert_time = json.load(f)
else:
    last_alert_time = {}

def save_memory():
    with open(MEMORY_FILE, 'w') as f:
        json.dump(last_alert_time, f)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.get(url, params={"chat_id": CHAT_ID, "text": message}, timeout=10)
        print(f"TELEGRAM: {r.status_code}")
    except Exception as e:
        print(f"TG ERROR: {e}")

def get_top_symbols():
    try:
        data = requests.get("https://api.kucoin.com/api/v1/market/allTickers", headers=HEADERS, timeout=15).json()
    except Exception as e:
        print(f"SYMBOLS ERROR: {e}")
        return []
    pairs = []
    for t in data.get('data', {}).get('ticker', []):
        sym = t.get('symbol', '')
        if sym.endswith('-USDT'):
            base = sym.replace('-USDT', '')
            if base not in STABLECOINS:
                vol = float(t.get('volValue', 0))
                if vol > 1000000:
                    pairs.append((sym, vol))
    pairs.sort(key=lambda x: x[1], reverse=True)
    return [p[0] for p in pairs[:TOP_N]]

def get_daily_trend(symbol):
    try:
        data = requests.get(f"https://api.kucoin.com/api/v1/market/candles?type={TREND_INTERVAL}&symbol={symbol}", headers=HEADERS, timeout=15).json()
    except Exception as e:
        print(f"TREND ERROR {symbol}: {e}")
        return None
    candles = data.get('data', [])
    if not candles or len(candles) < 52:
        return None
    candles = sorted(candles, key=lambda x: int(x[0]))
    closes = [float(c[2]) for c in candles[:-1]]
    sma50 = sum(closes[-50:]) / 50
    last = closes[-1]
    if last > sma50:
        return "UP"
    elif last < sma50:
        return "DOWN"
    return None

def check_setup(symbol, interval, trend):
    try:
        data = requests.get(f"https://api.kucoin.com/api/v1/market/candles?type={interval}&symbol={symbol}", headers=HEADERS, timeout=15).json()
    except Exception as e:
        print(f"SETUP ERROR {symbol} {interval}: {e}")
        return
    candles = data.get('data', [])
    if not candles or len(candles) < 8:
        return
    candles = sorted(candles, key=lambda x: int(x[0]))[:-1]
    opens = [float(c[1]) for c in candles]
    closes = [float(c[2]) for c in candles]
    highs = [float(c[3]) for c in candles]
    lows = [float(c[4]) for c in candles]
    sma7 = sum(closes[-7:]) / 7
    last_time = candles[-1][0]
    key = f"{symbol}_{interval}"
    if key in last_alert_time and last_alert_time[key] == last_time:
        return
    o, c, h, l = opens[-1], closes[-1], highs[-1], lows[-1]
    body_low = min(o, c)
    body_high = max(o, c)
    mid = (h + l) / 2
    buy = (trend == "UP") and l <= sma7 * (1 + TOLERANCE) and body_low > sma7 * (1 - TOLERANCE) and body_low > mid
    sell = (trend == "DOWN") and h >= sma7 * (1 - TOLERANCE) and body_high < sma7 * (1 + TOLERANCE) and body_high < mid
    if buy:
        print(f"BUY: {symbol} {interval} | O:{o} C:{c} H:{h} L:{l} SMA7:{sma7:.4f} MID:{mid:.4f}")
        send_telegram(f"BUY - {symbol} - {interval}")
        last_alert_time[key] = last_time
        save_memory()
    elif sell:
        print(f"SELL: {symbol} {interval} | O:{o} C:{c} H:{h} L:{l} SMA7:{sma7:.4f} MID:{mid:.4f}")
        send_telegram(f"SELL - {symbol} - {interval}")
        last_alert_time[key] = last_time
        save_memory()

def main():
    print("Bot cycle started...")
    top = get_top_symbols()
    if top:
        print(f"Monitoring {len(top)} coins...")
        for sym in top:
            trend = get_daily_trend(sym)
            if trend:
                for iv in ENTRY_INTERVALS:
                    check_setup(sym, iv, trend)
                    time.sleep(0.3)
            time.sleep(0.3)
        print("Cycle done.")
    else:
        print("No symbols found.")

main()
