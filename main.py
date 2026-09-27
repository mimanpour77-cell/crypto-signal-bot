"""
ربات معامله‌گر خودکار PancakeSwap (Spot)
استراتژی: SMA7 روی تایم‌فریم 1 ساعته و 4 ساعته
شبکه: BNB Chain (BEP20)
"""

import requests
import time
import json
import os
from datetime import datetime, timedelta
from web3 import Web3

# ================= تنظیمات =================
DRY_RUN = True

# کلید کیف پول
BSC_PRIVATE_KEY = os.environ.get("BSC_PRIVATE_KEY", "")
WALLET_ADDRESS = "0x54FF9b635C081b81631220ca1d4B0894F5faA9eC"

# تلگرام
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

CAPITAL = 2
RISK_PER_TRADE = 0.0025    # 0.25% هر معامله
MAX_DAILY_RISK = 0.01      # 1% سقف روزانه
MAX_CONCURRENT = 4         # حداکثر 4 پوزیشن همزمان

TREND_INTERVAL = "1day"
ENTRY_INTERVAL = "4hour"
ENTRY_INTERVAL_1H = "1hour"
TOP_N = 50
TOLERANCE = 0.001
SMA_PERIOD = 25
BTC_SYMBOL = "BTC-USDT"
STATE_FILE = "trading_state.json"

# ================= BSC / PancakeSwap =================
BSC_RPC = "https://bsc-dataseed.binance.org/"
PANCAKE_ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
USDT_BSC = "0x55d398326f99059fF775485246999027B3197955"
SLIPPAGE = 0.02

ROUTER_ABI = [
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactTokensForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},
]

ERC20_ABI = [
    {"inputs":[{"internalType":"address","name":"spender","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"approve","outputs":[{"internalType":"bool","name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"internalType":"address","name":"owner","type":"address"},{"internalType":"address","name":"spender","type":"address"}],"name":"allowance","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"address","name":"account","type":"address"}],"name":"balanceOf","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"stateMutability":"view","type":"function"},
]

TOKEN_ADDRESSES = {
    "BNB-USDT": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    "ETH-USDT": "0x2170Ed0880ac9A755fd29B2688956BD959F933F8",
    "BTC-USDT": "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c",
    "CAKE-USDT": "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
    "XRP-USDT": "0x1D2F0da169ceB9fC7B3144628dB156f3F6c60dBE",
    "ADA-USDT": "0x3EE2200Efb3400fAbB9AacF31297cBdD1d435D47",
    "DOGE-USDT": "0xbA2aE424d960c26247Dd6c32edC70B295c744C43",
    "SOL-USDT": "0x570A5D26f7765Ecb712C0924E4De545B89fD43dF",
    "MATIC-USDT": "0xCC42724C6683B7E57334c4E856f4c9965ED682bD",
    "DOT-USDT": "0x7083609fCE4d1d8Dc0C979AAb8c869Ea2C873402",
    "LINK-USDT": "0xF8A0BF9cF54Bb92F17374d9e9A321E6a111a51bD",
    "LTC-USDT": "0x4338665CBB7B2485A8855A139b75D5e34AB0DB94",
    "AVAX-USDT": "0x1CE0c2827e2eF14D5C4f29a091d735A204794041",
    "TRX-USDT": "0x85EAC5Ac2F758618dFa09bDbe0cf174e7d574D5B",
}

HEADERS = {"User-Agent": "Mozilla/5.0"}
w3 = Web3(Web3.HTTPProvider(BSC_RPC))


# ================= تلگرام =================
def send_telegram(msg):
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


# ================= PancakeSwap =================
def get_token_decimals(token_address):
    try:
        c = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
        return c.functions.decimals().call()
    except:
        return 18


def get_token_balance(token_address):
    try:
        c = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
        bal = c.functions.balanceOf(Web3.to_checksum_address(WALLET_ADDRESS)).call()
        dec = c.functions.decimals().call()
        return bal / (10 ** dec)
    except Exception as e:
        print(f"BALANCE ERROR: {e}")
        return 0


def get_usdt_balance():
    """موجودی USDT کیف پول"""
    return get_token_balance(USDT_BSC)


def get_bnb_balance():
    """موجودی BNB برای گس"""
    try:
        bal = w3.eth.get_balance(Web3.to_checksum_address(WALLET_ADDRESS))
        return bal / (10 ** 18)
    except:
        return 0


def get_amounts_out(amount_in_wei, path):
    router = w3.eth.contract(address=Web3.to_checksum_address(PANCAKE_ROUTER), abi=ROUTER_ABI)
    return router.functions.getAmountsOut(amount_in_wei, path).call()


def approve_token(token_address, amount_wei):
    c = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
    allowance = c.functions.allowance(
        Web3.to_checksum_address(WALLET_ADDRESS),
        Web3.to_checksum_address(PANCAKE_ROUTER)
    ).call()
    if allowance >= amount_wei:
        return True
    tx = c.functions.approve(
        Web3.to_checksum_address(PANCAKE_ROUTER), amount_wei
    ).build_transaction({
        'from': Web3.to_checksum_address(WALLET_ADDRESS),
        'gas': 100000,
        'gasPrice': w3.to_wei(3, 'gwei'),
        'nonce': w3.eth.get_transaction_count(Web3.to_checksum_address(WALLET_ADDRESS)),
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=BSC_PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    return True


def pancake_swap(token_address, amount_in_wei, is_buy):
    if is_buy:
        path = [Web3.to_checksum_address(USDT_BSC), Web3.to_checksum_address(token_address)]
    else:
        path = [Web3.to_checksum_address(token_address), Web3.to_checksum_address(USDT_BSC)]
    amounts = get_amounts_out(amount_in_wei, path)
    amount_out_min = int(amounts[-1] * (1 - SLIPPAGE))
    deadline = int(time.time()) + 600
    if not is_buy:
        approve_token(token_address, amount_in_wei)
    router = w3.eth.contract(address=Web3.to_checksum_address(PANCAKE_ROUTER), abi=ROUTER_ABI)
    tx = router.functions.swapExactTokensForTokens(
        amount_in_wei, amount_out_min, path,
        Web3.to_checksum_address(WALLET_ADDRESS), deadline
    ).build_transaction({
        'from': Web3.to_checksum_address(WALLET_ADDRESS),
        'gas': 350000,
        'gasPrice': w3.to_wei(3, 'gwei'),
        'nonce': w3.eth.get_transaction_count(Web3.to_checksum_address(WALLET_ADDRESS)),
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=BSC_PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)


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
        "today_stops": 0,
        "blocked_until": "",
        "total_pnl": 0.0
    }


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def reset_daily_if_needed(state):
    today = str(datetime.now().date())
    if state.get("today_date") != today:
        state["today_date"] = today
        state["today_risk_used"] = 0.0
        state["today_stops"] = 0
        print(f"[RESET] New day: {today}")
    return state


def is_blocked(state):
    """چک کن آیا امروز بلاک شده"""
    blocked_until = state.get("blocked_until", "")
    if not blocked_until:
        return False
    today = datetime.now().date()
    blocked_date = datetime.strptime(blocked_until, "%Y-%m-%d").date()
    if today <= blocked_date:
        return True
    # unblock
    state["blocked_until"] = ""
    save_state(state)
    return False


def block_for_tomorrow(state):
    """بلاک کردن امروز و فردا"""
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    state["blocked_until"] = str(tomorrow)
    save_state(state)
    print(f"[BLOCKED] Trading paused until {tomorrow}")
    send_telegram(
        f"🚨 <b>توقف معاملات</b>\n\n"
        f"۴ استاپ در یک روز خورد!\n"
        f"معاملات تا {tomorrow} متوقف شد.\n"
        f"سرمایه باقی‌مانده: ${CAPITAL:.2f}"
    )


# ================= KuCoin =================
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
        if sym.endswith('-USDT') and sym in TOKEN_ADDRESSES:
            vol = float(t.get('volValue', 0))
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


def check_setup(symbol, trend, interval=None):
    if interval is None:
        interval = ENTRY_INTERVAL
    candles = fetch_candles(symbol, interval)
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
        return {"side": "buy", "entry": c, "sl": l, "sma7": sma7, "mid": mid, "tf": interval}
    elif sell:
        return {"side": "sell", "entry": c, "sl": h, "sma7": sma7, "mid": mid, "tf": interval}
    return None


# ================= مدیریت پوزیشن =================
def calculate_position_size(entry, stop_loss, available_usdt):
    """محاسبه حجم با در نظر گرفتن موجودی"""
    risk_amount = CAPITAL * RISK_PER_TRADE
    stop_distance = abs(entry - stop_loss)
    if stop_distance == 0:
        return 0
    size = risk_amount / stop_distance
    # محدودیت: کل سرمایه تقسیم بر تعداد پوزیشن‌ها
    max_size_per_pos = CAPITAL / MAX_CONCURRENT / entry
    size = min(size, max_size_per_pos)
    # محدودیت: موجودی واقعی USDT
    if available_usdt > 0:
        max_size_balance = (available_usdt * 0.95) / entry  # 5% ذخیره
        size = min(size, max_size_balance)
    return size


def open_position(state, symbol, side, entry, stop_loss, size, timeframe="4h"):
    if side != "buy":
        return False

    # چک بلاک
    if is_blocked(state):
        return False

    risk_amount = abs(entry - stop_loss) * size
    daily_limit = CAPITAL * MAX_DAILY_RISK
    if state["today_risk_used"] + risk_amount > daily_limit:
        print(f"[BLOCKED] Daily risk limit reached")
        return False
    if len(state["open_positions"]) >= MAX_CONCURRENT:
        print(f"[BLOCKED] Max positions: {MAX_CONCURRENT}")
        return False

    token_address = TOKEN_ADDRESSES.get(symbol)
    if not token_address:
        return False

    usdt_amount = size * entry
    if usdt_amount < 0.10:
        print(f"[SKIP] Too small: ${usdt_amount:.4f}")
        return False

    r = abs(entry - stop_loss)
    next_tp = entry + r

    if DRY_RUN:
        print(f"[DRY RUN] WOULD BUY {symbol} [{timeframe}] @ {entry} | ${usdt_amount:.4f}")
        success = True
    else:
        try:
            usdt_wei = int(usdt_amount * (10 ** 18))
            approve_token(USDT_BSC, usdt_wei)
            receipt = pancake_swap(token_address, usdt_wei, is_buy=True)
            if receipt and receipt.status == 1:
                print(f"[BUY OK] TX: {receipt.transactionHash.hex()}")
                success = True
            else:
                success = False
        except Exception as e:
            print(f"[BUY ERROR] {e}")
            success = False

    if success:
        position = {
            "symbol": symbol,
            "token_address": token_address,
            "side": side,
            "entry": entry,
            "original_sl": stop_loss,
            "current_sl": stop_loss,
            "size": size,
            "R": r,
            "next_tp": next_tp,
            "tp_count": 0,
            "risk_amount": risk_amount,
            "timeframe": timeframe,
            "opened_at": str(datetime.now())
        }
        state["open_positions"].append(position)
        state["today_risk_used"] += risk_amount
        save_state(state)
        return True
    return False


def close_position(state, pos, current_price, reason="stop"):
    symbol = pos["symbol"]
    token_address = pos["token_address"]

    if DRY_RUN:
        pnl = (current_price - pos["entry"]) * pos["size"]
    else:
        try:
            bal = get_token_balance(token_address)
            if bal > 0:
                dec = get_token_decimals(token_address)
                bal_wei = int(bal * (10 ** dec))
                receipt = pancake_swap(token_address, bal_wei, is_buy=False)
                if receipt and receipt.status == 1:
                    print(f"[SELL OK] TX: {receipt.transactionHash.hex()}")
        except Exception as e:
            print(f"[SELL ERROR] {e}")
        pnl = (current_price - pos["entry"]) * pos["size"]

    pos["pnl"] = pnl
    pos["closed_at"] = str(datetime.now())
    pos["close_reason"] = reason
    state["closed_positions"].append(pos)
    state["total_pnl"] = state.get("total_pnl", 0) + pnl
    state["open_positions"].remove(pos)

    # اگه استاپ خورد، شمارنده رو زیاد کن
    if reason == "stop":
        state["today_stops"] = state.get("today_stops", 0) + 1
        print(f"[STOP #{state['today_stops']}] {symbol} | PnL: ${pnl:.6f}")
        # اگه به سقف روزانه رسید، بلاک کن
        if state["today_risk_used"] >= CAPITAL * MAX_DAILY_RISK:
            block_for_tomorrow(state)

    save_state(state)


def update_positions(state, current_prices):
    for pos in list(state["open_positions"]):
        symbol = pos["symbol"]
        if symbol not in current_prices:
            continue
        price = current_prices[symbol]
        r = pos["R"]

        if price <= pos["current_sl"]:
            print(f"[STOP HIT] {symbol} @ {pos['current_sl']:.6f}")
            close_position(state, pos, pos["current_sl"], reason="stop")
            continue

        while price >= pos["next_tp"]:
            pos["tp_count"] += 1
            new_sl = pos["next_tp"]
            pos["current_sl"] = new_sl
            pos["next_tp"] = new_sl + r
            print(f"[TP{pos['tp_count']}] {symbol} | SL → {new_sl:.6f}")
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


# ================= گزارش تلگرام =================
def send_positions_report(state, current_prices):
    """خلاصه پوزیشن‌ها رو به تلگرام بفرست"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    msg = f"📊 <b>گزارش ربات</b>\n"
    msg += f"━━━━━━━━━━━━━━\n"

    open_pos = state["open_positions"]
    total_unrealized = 0.0

    if open_pos:
        msg += f"<b>🟢 پوزیشن‌های باز ({len(open_pos)}):</b>\n"
        for p in open_pos:
            sym = p["symbol"]
            entry = p["entry"]
            price = current_prices.get(sym, entry)
            pnl = (price - entry) * p["size"]
            pnl_pct = ((price - entry) / entry) * 100
            total_unrealized += pnl
            emoji = "🟢" if pnl >= 0 else "🔴"
            tf = p.get("timeframe", "?")
            msg += (
                f"\n{emoji} <b>{sym}</b> [{tf}]\n"
                f"  ورود: ${entry:.4f}\n"
                f"  فعلی: ${price:.4f}\n"
                f"  سود: {'+' if pnl >= 0 else ''}${pnl:.4f} ({pnl_pct:+.2f}%)\n"
                f"  استاپ: ${p['current_sl']:.4f}\n"
                f"  هدف بعدی: ${p['next_tp']:.4f}\n"
            )
    else:
        msg += "<b>هیچ پوزیشن بازی نیست</b>\n"

    msg += f"\n━━━━━━━━━━━━━━\n"
    msg += f"💰 <b>موجودی و آمار:</b>\n"

    if not DRY_RUN:
        try:
            usdt_bal = get_usdt_balance()
            bnb_bal = get_bnb_balance()
            msg += f"  USDT: ${usdt_bal:.4f}\n"
            msg += f"  BNB (گس): {bnb_bal:.6f}\n"
        except:
            pass

    msg += f"  سود باز: {'+' if total_unrealized >= 0 else ''}${total_unrealized:.4f}\n"
    msg += f"  سود کل بسته‌شده: ${state.get('total_pnl', 0):.4f}\n"
    msg += f"  ریسک امروز: ${state['today_risk_used']:.4f} / ${CAPITAL*MAX_DAILY_RISK:.4f}\n"
    msg += f"  استاپ امروز: {state.get('today_stops', 0)}/{MAX_CONCURRENT}\n"

    if state.get("blocked_until"):
        msg += f"\n🚫 <b>معاملات متوقف تا: {state['blocked_until']}</b>\n"

    send_telegram(msg)


# ================= اجرای اصلی =================
def main():
    mode = "DRY RUN" if DRY_RUN else "LIVE"
    print(f"=== PancakeSwap Bot [{mode}] ===")
    print(f"Capital: ${CAPITAL} | Risk/Trade: ${CAPITAL*RISK_PER_TRADE:.6f}")
    print(f"Wallet: {WALLET_ADDRESS}")
    print(f"Timeframes: 1h + 4h 
