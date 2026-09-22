import requests
import time
import json
import os
import hmac
import hashlib
from datetime import datetime

# ================= تنظیمات =================
USE_DEMO = True          # True = دمو، False = واقعی
LEVERAGE = 1             # بدون اهرم

API_KEY = os.environ.get("WEEX_API_KEY", "")
SECRET_KEY = os.environ.get("WEEX_SECRET_KEY", "")
PASSPHRASE = os.environ.get("WEEX_PASSPHRASE", "")

CAPITAL = 100            # سرمایه کل: 100 دلار
RISK_PER_TRADE = 0.0025  # 0.25% از سرمایه در هر معامله
MAX_DAILY_RISK = 0.01    # 1% حداکثر ریسک روزانه
MAX_CONCURRENT = 4       # حداکثر 4 پوزیشن همزمان

TREND_INTERVAL = "1day"
ENTRY_INTERVAL = "4hour"
TOP_N = 100
TOLERANCE = 0.001
SMA_PERIOD = 25
BTC_SYMBOL = "BTC-USDT"
STATE_FILE = "trading_state.json"

if USE_DEMO:
    WEEX_BASE = "https://api-contract.weex.com/capi/v3/sim"
else:
    WEEX_BASE = "https://api-contract.weex.com/capi/v3"

STABLECOINS = [
    'USDC','FDUSD','TUSD','BUSD','DAI','USDP','EUR','GBP','USD1','USDE',
    'USDS','PYUSD','USDD','USTC','FRAX','GUSD','LUSD','SUSD','USDT','USDT0',
    'USDR','USDX','USDY','ALUSD','MIM','DOLA','CUSD','CEUR','EURS','STEUR',
    'VAI','XUSD','USDN','UXD','USK','USDL','RLUSD','USDG','USDQ','USDJ',
    'USDF','USDH','USDTB','USDFI'
]

HEADERS = {"User-Agent": "Mozilla/5.0"}


# ================= WEEX API =================
def weex_sign(timestamp, method, request_path, body=""):
    message = f"{timestamp}{method}{request_path}{body}"
    signature = hmac.new(
        SECRET_KEY.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature


def weex_request(method, path, params=None, body=None):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ""
    
    if params:
        query = "&".join([f"{k}={v}" for k, v in params.items()])
        full_path = f"{path}?{query}"
    else:
        full_path = path
    
    signature = weex_sign(timestamp, method.upper(), full_path, body_str)
    
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }
    
    url = f"{WEEX_BASE}{full_path}"
    
    try:
        if method.upper() == "GET":
            r = requests.get(url, headers=headers, timeout=15)
        elif method.upper() == "POST":
            r = requests.post(url, headers=headers, data=body_str, timeout=15)
        else:
            return None
        return r.json()
    except Exception as e:
        print(f"WEEX ERROR: {e}")
        return None


def weex_get_balance():
    return weex_request("GET", "/balance")


def weex_get_positions():
    return weex_request("GET", "/position/allPosition")


def weex_place_order(symbol, side, size, stop_loss):
    """ثبت سفارش Market با حد ضرر"""
    client_order_id = f"bot_{int(time.time())}"
    body = {
        "symbol": symbol,
        "side": side,
        "type": "market",
        "size": str(size),
        "newClientOrderId": client_order_id,  # پارامتر اجباری
        "slTriggerPrice": str(stop_loss)
    }
    return weex_request("POST", "/order", body=body)


def weex_close_position(symbol):
    body = {"symbol": symbol}
    return weex_request("POST", "/closePosition", body=body)


# ================= حافظه =================
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        "open_positions": [],
        "today_date": str(datetime.now().date()),
        "today_risk_used": 0.0
    }


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def reset_daily_if_needed(state):
    today = str(datetime.now().date())
    if state["today_date"] != today:
        state["today_date"] = today
        state["today_risk_used"] = 0.0
        print(f"[RESET] New day: {today}")
    return state


# ================= KuCoin (دیتای بازار) =================
def fetch_candles(symbol, interval):
    try:
        data = requests.get(
            f"https://api.kucoin.com/api/v1/market/candles?type={interval}&symbol={symbol}",
            headers=HEADERS, timeout=15
        ).json()
        return data.get('data', [])
    except Exception as e:
        print(f"CANDLES ERROR {symbol}: {e}")
        return []


def get_top_symbols():
    try:
        data = requests.get(
            "https://api.kucoin.com/api/v1/market/allTickers",
            headers=HEADERS, timeout=15
        ).json()
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


def get_btc_daily_closes():
    candles = fetch_candles(BTC_SYMBOL, TREND_INTERVAL)
    if not candles or len(candles) < SMA_PERIOD + 2:
        return None
    candles = sorted(candles, key=lambda x: int(x[0]))
    return {c[0]: float(c[2]) for c in candles[:-1]}


def get_coin_trend(symbol, btc_closes):
    if symbol == BTC_SYMBOL:
        return None
    candles = fetch_candles(symbol, TREND_INTERVAL)
    if not candles or len(candles) < SMA_PERIOD + 2:
        return None
    candles = sorted(candles, key=lambda x: int(x[0]))[:-1]
    coin_closes = {c[0]: float(c[2]) for c in candles}
    
    closes_list = list(coin_closes.values())
    sma25 = sum(closes_list[-SMA_PERIOD:]) / SMA_PERIOD
    coin_trend = "UP" if closes_list[-1] > sma25 else "DOWN"
    
    if btc_closes is None:
        return None
    
    common = sorted(set(coin_closes.keys()) & set(btc_closes.keys()))
    if len(common) < SMA_PERIOD + 1:
        return None
    
    ratios = [coin_closes[t] / btc_closes[t] for t in common]
    ratio_sma = sum(ratios[-SMA_PERIOD:]) / SMA_PERIOD
    rel_trend = "UP" if ratios[-1] > ratio_sma else "DOWN"
    
    if coin_trend == rel_trend:
        return coin_trend
    return None


def check_setup(symbol, trend):
    candles = fetch_candles(symbol, ENTRY_INTERVAL)
    if not candles or len(candles) < 8:
        return None
    candles = sorted(candles, key=lambda x: int(x[0]))[:-1]
    
    opens = [float(c[1]) for c in candles]
    closes = [float(c[2]) for c in candles]
    highs = [float(c[3]) for c in candles]
    lows = [float(c[4]) for c in candles]
    
    sma7 = sum(closes[-7:]) / 7
    o, c, h, l = opens[-1], closes[-1], highs[-1], lows[-1]
    body_low = min(o, c)
    body_high = max(o, c)
    mid = (h + l) / 2
    
    buy = (trend == "UP") and l <= sma7 * (1 + TOLERANCE) and body_low > sma7 * (1 - TOLERANCE) and body_low > mid
    sell = (trend == "DOWN") and h >= sma7 * (1 - TOLERANCE) and body_high < sma7 * (1 + TOLERANCE) and body_high < mid
    
    if buy:
        return {"side": "buy", "entry": c, "sl": l, "sma7": sma7, "mid": mid}
    elif sell:
        return {"side": "sell", "entry": c, "sl": h, "sma7": sma7, "mid": mid}
    return None


# ================= مدیریت پوزیشن =================
def calculate_position_size(entry, stop_loss):
    """محاسبه حجم با در نظر گرفتن اهرم"""
    risk_amount = CAPITAL * RISK_PER_TRADE
    stop_distance = abs(entry - stop_loss)
    if stop_distance == 0:
        return 0
    size = risk_amount / stop_distance
    # اگه بدون اهرم باشیم، حجم رو بر اساس موجودی محدود می‌کنیم
    if LEVERAGE == 1:
        max_size = CAPITAL / entry
        size = min(size, max_size)
    return size


def open_position(state, symbol, side, entry, stop_loss, size):
    risk_amount = abs(entry - stop_loss) * size
    daily_limit = CAPITAL * MAX_DAILY_RISK
    
    if state["today_risk_used"] + risk_amount > daily_limit:
        print(f"[BLOCKED] Risk limit: ${state['today_risk_used']:.2f}/${daily_limit:.2f}")
        return False
    
    if len(state["open_positions"]) >= MAX_CONCURRENT:
        print(f"[BLOCKED] Max positions: {MAX_CONCURRENT}")
        return False
    
    # تبدیل نماد: BTC-USDT → BTCUSDT
    weex_symbol = symbol.replace("-", "")
    
    # ثبت سفارش (بدون تنظیم اهرم، چون اهرم 1x است)
    resp = weex_place_order(weex_symbol, side.upper(), size, stop_loss)
    print(f"[WEEX ORDER] {resp}")
    
    if not resp or resp.get("code") != "00000":
        print(f"[FAILED] Order not placed: {resp}")
        return False
    
    # ذخیره پوزیشن
    r = abs(entry - stop_loss)
    if side == "buy":
        next_tp = entry + r
    else:
        next_tp = entry - r
    
    position = {
        "symbol": symbol,
        "weex_symbol": weex_symbol,
        "side": side,
        "entry": entry,
        "original_sl": stop_loss,
        "current_sl": stop_loss,
        "size": size,
        "R": r,
        "next_tp": next_tp,
        "tp_count": 0,
        "risk_amount": risk_amount,
        "opened_at": str(datetime.now())
    }
    state["open_positions"].append(position)
    state["today_risk_used"] += risk_amount
    save_state(state)
    
    print(f"[OPENED] {side.upper()} {symbol} | Entry: {entry} | SL: {stop_loss} | Size: {size:.6f} | R: {r:.4f}")
    return True


def update_positions(state, current_prices):
    for pos in list(state["open_positions"]):
        symbol = pos["symbol"]
        if symbol not in current_prices:
            continue
        
        price = current_prices[symbol]
        side = pos["side"]
        r = pos["R"]
        
        if side == "buy":
            if price <= pos["current_sl"]:
                print(f"[STOP HIT] {symbol} @ {pos['current_sl']}")
                weex_close_position(pos["weex_symbol"])
                state["open_positions"].remove(pos)
                save_state(state)
                continue
            
            while price >= pos["next_tp"]:
                pos["tp_count"] += 1
                new_sl = pos["next_tp"]
                pos["current_sl"] = new_sl
                print(f"[TP{pos['tp_count']}] {symbol} @ {new_sl:.4f} | SL -> {new_sl:.4f}")
                pos["next_tp"] = new_sl + r
                save_state(state)
        
        else:
            if price >= pos["current_sl"]:
                print(f"[STOP HIT] {symbol} @ {pos['current_sl']}")
                weex_close_position(pos["weex_symbol"])
                state["open_positions"].remove(pos)
                save_state(state)
                continue
            
            while price <= pos["next_tp"]:
                pos["tp_count"] += 1
                new_sl = pos["next_tp"]
                pos["current_sl"] = new_sl
                print(f"[TP{pos['tp_count']}] {symbol} @ {new_sl:.4f} | SL -> {new_sl:.4f}")
                pos["next_tp"] = new_sl - r
                save_state(state)
    
    save_state(state)


def get_current_prices(symbols):
    prices = {}
    for sym in symbols:
        try:
            data = requests.get(
                f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={sym}",
                headers=HEADERS, timeout=10
            ).json()
            price = data.get('data', {}).get('price')
            if price:
                prices[sym] = float(price)
        except:
            pass
    return prices


# ================= اجرای اصلی =================
def main():
    print(f"=== Trading Bot Started (Demo: {USE_DEMO}, Leverage: {LEVERAGE}x) ===")
    print(f"Capital: ${CAPITAL} | Risk/Trade: ${CAPITAL*RISK_PER_TRADE} | Daily Limit: ${CAPITAL*MAX_DAILY_RISK}")
    
    state = load_state()
    state = reset_daily_if_needed(state)
    
    if state["open_positions"]:
        print(f"\n--- Updating {len(state['open_positions'])} open positions ---")
        symbols = [p["symbol"] for p in state["open_positions"]]
        prices = get_current_prices(symbols)
        update_positions(state, prices)
    
    print("\n--- Scanning for new setups ---")
    btc_closes = get_btc_daily_closes()
    if not btc_closes:
        print("BTC data unavailable")
        return
    
    top = get_top_symbols()
    print(f"Scanning {len(top)} coins...")
    
    for sym in top:
        trend = get_coin_trend(sym, btc_closes)
        if not trend:
            continue
        
        setup = check_setup(sym, trend)
        if setup:
            print(f"[SETUP FOUND] {sym} | {setup['side'].upper()} | Entry: {setup['entry']} | SL: {setup['sl']}")
            size = calculate_position_size(setup["entry"], setup["sl"])
            if size > 0:
                open_position(state, sym, setup["side"], setup["entry"], setup["sl"], size)
        time.sleep(0.1)
    
    print("\n=== Cycle complete ===")


main()
