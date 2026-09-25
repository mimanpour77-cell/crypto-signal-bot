"""
ربات معامله‌گر خودکار Aster DEX
استراتژی: SMA7 (سایه/بادی/نیمه کندل)
فیلتر روند: SMA25 روزانه + قدرت نسبی نسبت به BTC
مدیریت ریسک: 0.25% هر معامله، 1% سقف روزانه
Trailing Stop پله‌ای: هر 1R، 1R بالاتر
"""

import requests
import time
import json
import os
import hmac
import hashlib
from datetime import datetime

# ================= تنظیمات =================
DRY_RUN = False          # False = معامله واقعی، True = فقط لاگ
LEVERAGE = 1             # بدون اهرم
MARGIN_MODE = "ISOLATED"

# کلیدهای Aster (از GitHub Secrets میان)
ASTER_API_KEY = os.environ.get("ASTER_API_KEY", "")
ASTER_SECRET_KEY = os.environ.get("ASTER_SECRET_KEY", "")
ASTER_AGENT_ADDRESS = os.environ.get("ASTER_AGENT_ADDRESS", "")

# تلگرام
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

CAPITAL = 2              # سرمایه کل (دلار)
RISK_PER_TRADE = 0.0025  # ریسک هر معامله: 0.25%
MAX_DAILY_RISK = 0.01    # حداکثر ریسک روزانه: 1%
MAX_CONCURRENT = 1       # فقط 1 پوزیشن

TREND_INTERVAL = "1day"
ENTRY_INTERVAL = "4hour"
TOP_N = 50
TOLERANCE = 0.001
SMA_PERIOD = 25
BTC_SYMBOL = "BTC-USDT"
STATE_FILE = "trading_state.json"

ASTER_BASE = "https://fapi.asterdex.com"

STABLECOINS = [
    'USDC','FDUSD','TUSD','BUSD','DAI','USDP','EUR','GBP','USD1','USDE',
    'USDS','PYUSD','USDD','USTC','FRAX','GUSD','LUSD','SUSD','USDT','USDT0',
    'USDR','USDX','USDY','ALUSD','MIM','DOLA','CUSD','CEUR','EURS','STEUR',
    'VAI','XUSD','USDN','UXD','USK','USDL','RLUSD','USDG','USDQ','USDJ',
    'USDF','USDH','USDTB','USDFI'
]

HEADERS = {"User-Agent": "Mozilla/5.0"}


# ================= تلگرام =================
def send_telegram(msg):
    """ارسال پیام به تلگرام"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print(f"TELEGRAM ERROR: {e}")


# ================= Aster API =================
def aster_sign(timestamp, method, path, query_string, body_str=""):
    """امضای Aster (شبیه Binance)"""
    # پیام = timestamp + method + path + query + body
    if body_str:
        message = f"{timestamp}{method.upper()}{path}{query_string}{body_str}"
    else:
        message = f"{timestamp}{method.upper()}{path}{query_string}"
    
    signature = hmac.new(
        ASTER_SECRET_KEY.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature


def aster_request(method, path, params=None, body=None, signed=True, debug=True):
    """درخواست به Aster API"""
    timestamp = str(int(time.time() * 1000))
    
    # ساخت query string
    if params:
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    else:
        query_string = ""
    
    # ساخت body
    body_str = json.dumps(body, separators=(',', ':')) if body else ""
    
    # هدرها
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    
    if signed:
        # برای Aster: signer توی body اضافه میشه
        if body:
            body["signer"] = ASTER_AGENT_ADDRESS
            body_str = json.dumps(body, separators=(',', ':'))
        
        signature = aster_sign(timestamp, method, path, query_string, body_str)
        
        # هدرهای Aster (شبیه Binance)
        headers["X-MBX-APIKEY"] = ASTER_API_KEY
        
        # timestamp و signature به query اضافه میشن (Binance style)
        if query_string:
            query_string += f"&timestamp={timestamp}&signature={signature}"
        else:
            query_string = f"timestamp={timestamp}&signature={signature}"
    
    # URL نهایی
    url = f"{ASTER_BASE}{path}"
    if query_string:
        url += f"?{query_string}"
    
    try:
        if method.upper() == "GET":
            r = requests.get(url, headers=headers, timeout=15)
        elif method.upper() == "POST":
            r = requests.post(url, headers=headers, data=body_str, timeout=15)
        elif method.upper() == "DELETE":
            r = requests.delete(url, headers=headers, timeout=15)
        else:
            return None
        
        if debug:
            print(f"[ASTER] {method} {path}")
            print(f"  Status: {r.status_code}")
            print(f"  Response: {r.text[:300]}")
        
        if r.status_code == 200:
            return r.json() if r.text else None
        else:
            return None
    except Exception as e:
        print(f"[ASTER ERROR] {e}")
        return None


def aster_place_order(symbol, side, quantity, stop_price=None):
    """ثبت سفارش MARKET در Aster"""
    params = {
        "symbol": symbol,
        "side": side.upper(),
        "type": "MARKET",
        "quantity": str(quantity),
    }
    
    # اگه استاپ لاس داشت، از STOP_MARKET استفاده می‌کنیم
    # برای سادگی، اول سفارش MARKET می‌زنیم و بعد استاپ رو جدا ثبت می‌کنیم
    
    r = aster_request("POST", "/fapi/v3/order", params=params)
    
    # حالا اگه استاپ لاس داشت، سفارش استاپ رو ثبت می‌کنیم
    if r and stop_price:
        stop_side = "SELL" if side.upper() == "BUY" else "BUY"
        stop_params = {
            "symbol": symbol,
            "side": stop_side,
            "type": "STOP_MARKET",
            "quantity": str(quantity),
            "stopPrice": str(stop_price),
            "reduceOnly": "true",
        }
        stop_r = aster_request("POST", "/fapi/v3/order", params=stop_params)
        print(f"[STOP LOSS REGISTERED] {stop_r}")
    
    return r


def aster_close_position(symbol, quantity=None):
    """بستن پوزیشن با سفارش MARKET معکوس"""
    # اول موقعیت فعلی رو می‌گیریم
    positions = aster_get_positions()
    if not positions:
        return None
    
    for pos in positions:
        if pos.get("symbol") == symbol:
            amt = float(pos.get("positionAmt", 0))
            if amt == 0:
                return None
            
            side = "SELL" if amt > 0 else "BUY"
            qty = abs(amt)
            
            params = {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": str(qty),
                "reduceOnly": "true",
            }
            return aster_request("POST", "/fapi/v3/order", params=params)
    return None


def aster_get_positions():
    return aster_request("GET", "/fapi/v3/positionRisk")


def aster_get_balance():
    return aster_request("GET", "/fapi/v3/balance")


def aster_set_leverage(symbol, leverage):
    params = {"symbol": symbol, "leverage": str(leverage)}
    return aster_request("POST", "/fapi/v3/leverage", params=params)


def aster_set_margin_type(symbol, margin_type="ISOLATED"):
    params = {"symbol": symbol, "marginType": margin_type}
    return aster_request("POST", "/fapi/v3/marginType", params=params)


# ================= حافظه =================
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        "open_positions": [],
        "closed_positions": [],
        "today_date": str(datetime.now().date()),
        "today_risk_used": 0.0,
        "total_pnl": 0.0
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


# ================= KuCoin (تحلیل بازار) =================
def fetch_candles(symbol, interval):
    """دریافت کندل‌ها از KuCoin (برای تحلیل)"""
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
    """دریافت 50 ارز برتر از KuCoin"""
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
    """تشخیص روند (SMA25 روزانه + قدرت نسبی به BTC)"""
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
    """بررسی ستاپ SMA7 در تایم 4 ساعته"""
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
    
    # ستاپ خرید
    buy = (trend == "UP") and l <= sma7 * (1 + TOLERANCE) and body_low > sma7 * (1 - TOLERANCE) and body_low > mid
    # ستاپ فروش
    sell = (trend == "DOWN") and h >= sma7 * (1 - TOLERANCE) and body_high < sma7 * (1 + TOLERANCE) and body_high < mid
    
    if buy:
        return {"side": "buy", "entry": c, "sl": l, "sma7": sma7, "mid": mid}
    elif sell:
        return {"side": "sell", "entry": c, "sl": h, "sma7": sma7, "mid": mid}
    return None


# ================= مدیریت پوزیشن =================
def calculate_position_size(entry, stop_loss):
    """محاسبه حجم بر اساس ریسک 0.25%"""
    risk_amount = CAPITAL * RISK_PER_TRADE
    stop_distance = abs(entry - stop_loss)
    if stop_distance == 0:
        return 0
    size = risk_amount / stop_distance
    if LEVERAGE == 1:
        max_size = CAPITAL / entry
        size = min(size, max_size)
    return size


def open_position(state, symbol, side, entry, stop_loss, size):
    """باز کردن پوزیشن"""
    risk_amount = abs(entry - stop_loss) * size
    daily_limit = CAPITAL * MAX_DAILY_RISK
    
    if state["today_risk_used"] + risk_amount > daily_limit:
        print(f"[BLOCKED] Daily risk limit reached")
        send_telegram(f"⛔️ سقف ریسک روزانه پر شده")
        return False
    
    if len(state["open_positions"]) >= MAX_CONCURRENT:
        print(f"[BLOCKED] Max positions reached")
        return False
    
    aster_symbol = symbol.replace("-", "")
    r = abs(entry - stop_loss)
    next_tp = entry + r if side == "buy" else entry - r
    
    if DRY_RUN:
        print(f"[DRY RUN] WOULD OPEN {side.upper()} {symbol}")
        print(f"  Entry: {entry}, SL: {stop_loss}, Size: {size:.8f}, R: {r:.6f}")
        msg = f"🔵 سیگنال {'خرید' if side=='buy' else 'فروش'}\nنماد: {symbol}\nورود: {entry}\nاستاپ: {stop_loss}\nحجم: {size:.6f}"
        send_telegram(msg)
        success = True
    else:
        # تنظیم اهرم و مارجین
        aster_set_leverage(aster_symbol, LEVERAGE)
        aster_set_margin_type(aster_symbol, MARGIN_MODE)
        time.sleep(0.5)
        
        # ثبت سفارش
        resp = aster_place_order(aster_symbol, side.upper(), size, stop_loss)
        print(f"[ASTER ORDER] {resp}")
        
        if resp and resp.get("orderId"):
            success = True
            msg = f"✅ پوزیشن باز شد\nنماد: {symbol}\nجهت: {side.upper()}\nورود: {entry}\nاستاپ: {stop_loss}\nحجم: {size:.6f}"
            send_telegram(msg)
        else:
            success = False
            send_telegram(f"❌ خطا در باز کردن پوزیشن {symbol}")
    
    if success:
        position = {
            "symbol": symbol,
            "aster_symbol": aster_symbol,
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
        return True
    return False


def update_positions(state, current_prices):
    """آپدیت Trailing Stop"""
    for pos in list(state["open_positions"]):
        symbol = pos["symbol"]
        if symbol not in current_prices:
            continue
        
        price = current_prices[symbol]
        side = pos["side"]
        r = pos["R"]
        
        if side == "buy":
            if price <= pos["current_sl"]:
                pnl = (pos["current_sl"] - pos["entry"]) * pos["size"]
                print(f"[STOP HIT] {symbol} @ {pos['current_sl']:.6f} | PnL: ${pnl:.6f}")
                if not DRY_RUN:
                    aster_close_position(pos["aster_symbol"])
                pos["pnl"] = pnl
                pos["closed_at"] = str(datetime.now())
                state["closed_positions"].append(pos)
                state["total_pnl"] = state.get("total_pnl", 0) + pnl
                state["open_positions"].remove(pos)
                send_telegram(f"🛑 استاپ خورد\n{symbol}\nقیمت: {pos['current_sl']}\nسود/زیان: ${pnl:.6f}")
                save_state(state)
                continue
            
            while price >= pos["next_tp"]:
                pos["tp_count"] += 1
                new_sl = pos["next_tp"]
                pos["current_sl"] = new_sl
                print(f"[TP{pos['tp_count']} HIT] {symbol} | SL → {new_sl:.6f}")
                pos["next_tp"] = new_sl + r
                send_telegram(f"📈 TP{pos['tp_count']} زده شد\n{symbol}\nاستاپ جدید: {new_sl:.6f}")
                save_state(state)
        
        else:  # sell
            if price >= pos["current_sl"]:
                pnl = (pos["entry"] - pos["current_sl"]) * pos["size"]
                print(f"[STOP HIT] {symbol} @ {pos['current_sl']:.6f} | PnL: ${pnl:.6f}")
                if not DRY_RUN:
                    aster_close_position(pos["aster_symbol"])
                pos["pnl"] = pnl
                pos["closed_at"] = str(datetime.now())
                state["closed_positions"].append(pos)
                state["total_pnl"] = state.get("total_pnl", 0) + pnl
                state["open_positions"].remove(pos)
                send_telegram(f"🛑 استاپ خورد\n{symbol}\nقیمت: {pos['current_sl']}\nسود/زیان: ${pnl:.6f}")
                save_state(state)
                continue
            
            while price <= pos["next_tp"]:
                pos["tp_count"] += 1
                new_sl = pos["next_tp"]
                pos["current_sl"] = new_sl
                print(f"[TP{pos['tp_count']} HIT] {symbol} | SL → {new_sl:.6f}")
                pos["next_tp"] = new_sl - r
                send_telegram(f"📉 TP{pos['tp_count']} زده شد\n{symbol}\nاستاپ جدید: {new_sl:.6f}")
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
    mode = "DRY RUN" if DRY_RUN else "LIVE TRADING"
    print(f"=== Aster Bot [{mode}] ===")
    print(f"Capital: ${CAPITAL} | Leverage: {LEVERAGE}x | Margin: {MARGIN_MODE}")
    print(f"Risk/Trade: ${CAPITAL*RISK_PER_TRADE:.6f} | Daily: ${CAPITAL*MAX_DAILY_RISK:.6f}")
    
    state = load_state()
    state = reset_daily_if_needed(state)
    
    print(f"\n--- Summary ---")
    print(f"Total PnL: ${state.get('total_pnl', 0):.6f}")
    print(f"Open: {len(state['open_positions'])} | Closed: {len(state.get('closed_positions', []))}")
    
    # آپدیت پوزیشن‌های باز
    if state["open_positions"]:
        print(f"\n--- Updating {len(state['open_positions'])} positions ---")
        symbols = [p["symbol"] for p in state["open_positions"]]
        prices = get_current_prices(symbols)
        update_positions(state, prices)
    
    # اسکن ستاپ‌های جدید
    print("\n--- Scanning ---")
    btc_closes = get_btc_daily_closes()
    if not btc_closes:
        print("BTC data unavailable")
        return
    
    top = get_top_symbols()
    print(f"Scanning {len(top)} coins...")
    
    found = 0
    for sym in top:
        trend = get_coin_trend(sym, btc_closes)
        if not trend:
            continue
        
        setup = check_setup(sym, trend)
        if setup:
            found += 1
            print(f"\n[SETUP] {sym} | {setup['side'].upper()}")
            size = calculate_position_size(setup["entry"], setup["sl"])
            if size > 0:
                open_position(state, sym, setup["side"], setup["entry"], setup["sl"], size)
        time.sleep(0.1)
    
    print(f"\n=== Complete | Found {found} setups ===")


if __name__ == "__main__":
    main()
