"""
ربات معامله‌گر خودکار PancakeSwap (Spot)
استراتژی: SMA7 روی تایم‌فریم 1 ساعته و 4 ساعته
شبکه: BNB Chain (BEP20)
"""

import requests
import time
import json
import os
from datetime import datetime
from web3 import Web3

# ================= تنظیمات =================
DRY_RUN = True           # True = فقط لاگ، False = معامله واقعی
LEVERAGE = 1             # اسپات: بدون اهرم

# کلید کیف پول (از GitHub Secrets)
BSC_PRIVATE_KEY = os.environ.get("BSC_PRIVATE_KEY", "")
WALLET_ADDRESS = "0x54FF9b635C081b81631220ca1d4B0894F5faA9eC"

# تلگرام (اختیاری)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

CAPITAL = 2
RISK_PER_TRADE = 0.0025
MAX_DAILY_RISK = 0.01
MAX_CONCURRENT = 1

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
SLIPPAGE = 0.02  # 2%

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
        amount_in_wei,
        amount_out_min,
        path,
        Web3.to_checksum_address(WALLET_ADDRESS),
        deadline
    ).build_transaction({
        'from': Web3.to_checksum_address(WALLET_ADDRESS),
        'gas': 350000,
        'gasPrice': w3.to_wei(3, 'gwei'),
        'nonce': w3.eth.get_transaction_count(Web3.to_checksum_address(WALLET_ADDRESS)),
    })
    
    signed = w3.eth.account.sign_transaction(tx, private_key=BSC_PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    return receipt


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


# ================= KuCoin (تحلیل) =================
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
            if sym in TOKEN_ADDRESSES:
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
    """استراتژی: SMA25 روزانه + قدرت نسبی به BTC (بدون تغییر)"""
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
    """استراتژی SMA7 (بدون تغییر) - پارامتری برای تایم‌فریم"""
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
def calculate_position_size(entry, stop_loss):
    """محاسبه حجم بر اساس ریسک 0.25% (بدون تغییر)"""
    risk_amount = CAPITAL * RISK_PER_TRADE
    stop_distance = abs(entry - stop_loss)
    if stop_distance == 0:
        return 0
    size = risk_amount / stop_distance
    if LEVERAGE == 1:
        max_size = CAPITAL / entry
        size = min(size, max_size)
    return size


def open_position(state, symbol, side, entry, stop_loss, size, timeframe="4h"):
    """باز کردن پوزیشن (فقط buy در اسپات)"""
    if side != "buy":
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
        print(f"[SKIP] No token address for {symbol}")
        return False
    
    usdt_amount = size * entry
    if usdt_amount < 0.10:
        print(f"[SKIP] Too small: ${usdt_amount:.4f}")
        return False
    
    r = abs(entry - stop_loss)
    next_tp = entry + r
    
    if DRY_RUN:
        print(f"[DRY RUN] WOULD BUY {symbol} [{timeframe}]")
        print(f"  Entry: {entry}, SL: {stop_loss}, Size: {size:.8f}, R: {r:.6f}")
        print(f"  USDT to spend: ${usdt_amount:.4f}")
        send_telegram(f"🔵 سیگنال خرید {symbol} [{timeframe}]\nورود: {entry}\nاستاپ: {stop_loss}\nحجم: ${usdt_amount:.4f}")
        success = True
    else:
        try:
            usdt_dec = 18
            usdt_wei = int(usdt_amount * (10 ** usdt_dec))
            approve_token(USDT_BSC, usdt_wei)
            receipt = pancake_swap(token_address, usdt_wei, is_buy=True)
            if receipt and receipt.status == 1:
                print(f"[BUY OK] TX: {receipt.transactionHash.hex()}")
                send_telegram(f"✅ خرید انجام شد\n{symbol} [{timeframe}]\nورود: {entry}\nحجم: ${usdt_amount:.4f}")
                success = True
            else:
                print(f"[BUY FAIL]")
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
    """بستن پوزیشن (فروش توکن)"""
    symbol = pos["symbol"]
    token_address = pos["token_address"]
    
    if DRY_RUN:
        pnl = (current_price - pos["entry"]) * pos["size"]
        print(f"[DRY RUN] WOULD SELL {symbol} @ {current_price:.6f} | PnL: ${pnl:.6f}")
    else:
        try:
            bal = get_token_balance(token_address)
            if bal > 0:
                dec = get_token_decimals(token_address)
                bal_wei = int(bal * (10 ** dec))
                receipt = pancake_swap(token_address, bal_wei, is_buy=False)
                if receipt and receipt.status == 1:
                    print(f"[SELL OK] TX: {receipt.transactionHash.hex()}")
                else:
                    print(f"[SELL FAIL]")
        except Exception as e:
            print(f"[SELL ERROR] {e}")
        pnl = (current_price - pos["entry"]) * pos["size"]
    
    pos["pnl"] = pnl
    pos["closed_at"] = str(datetime.now())
    pos["close_reason"] = reason
    state["closed_positions"].append(pos)
    state["total_pnl"] = state.get("total_pnl", 0) + pnl
    state["open_positions"].remove(pos)
    send_telegram(f"{'🛑' if reason=='stop' else '📈'} بسته شد {symbol}\nقیمت: {current_price}\nPnL: ${pnl:.6f}")
    save_state(state)


def update_positions(state, current_prices):
    """آپدیت Trailing Stop (بدون تغییر در منطق)"""
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
            send_telegram(f"📈 TP{pos['tp_count']} {symbol}\nاستاپ جدید: {new_sl:.6f}")
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
    mode = "DRY RUN" if DRY_RUN else "LIVE"
    print(f"=== PancakeSwap Bot [{mode}] ===")
    print(f"Capital: ${CAPITAL} | Risk/Trade: ${CAPITAL*RISK_PER_TRADE:.6f}")
    print(f"Wallet: {WALLET_ADDRESS}")
    print(f"Timeframes: 1h + 4h")
    
    state = load_state()
    state = reset_daily_if_needed(state)
    
    print(f"\nTotal PnL: ${state.get('total_pnl', 0):.6f}")
    print(f"Open: {len(state['open_positions'])} | Closed: {len(state.get('closed_positions', []))}")
    
    if state["open_positions"]:
        print(f"\n--- Updating {len(state['open_positions'])} positions ---")
        symbols = [p["symbol"] for p in state["open_positions"]]
        prices = get_current_prices(symbols)
        update_positions(state, prices)
    
    print("\n--- Scanning ---")
    btc_closes = get_btc_daily_closes()
    if not btc_closes:
        print("BTC data unavailable")
        return
    
    top = get_top_symbols()
    print(f"Scanning {len(top)} pairs (1h + 4h)...")
    
    for sym in top:
        trend = get_coin_trend(sym, btc_closes)
        if not trend:
            continue
        
        # تایم‌فریم 4 ساعته
        setup_4h = check_setup(sym, trend, ENTRY_INTERVAL)
        if setup_4h and setup_4h["side"] == "buy":
            print(f"\n[SETUP-4H] {sym} | BUY")
            size = calculate_position_size(setup_4h["entry"], setup_4h["sl"])
            if size > 0:
                open_position(state, sym, "buy", setup_4h["entry"], setup_4h["sl"], size, "4h")
        
        # تایم‌فریم 1 ساعته
        setup_1h = check_setup(sym, trend, ENTRY_INTERVAL_1H)
        if setup_1h and setup_1h["side"] == "buy":
            print(f"\n[SETUP-1H] {sym} | BUY")
            size = calculate_position_size(setup_1h["entry"], setup_1h["sl"])
            if size > 0:
                open_position(state, sym, "buy", setup_1h["entry"], setup_1h["sl"], size, "1h")
        
        time.sleep(0.1)
    
    print("\n=== Complete ===")


if __name__ == "__main__":
    main()
