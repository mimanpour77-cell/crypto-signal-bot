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

DRY_RUN = True

BSC_PRIVATE_KEY = os.environ.get("BSC_PRIVATE_KEY", "")
WALLET_ADDRESS = "0x54FF9b635C081b81631220ca1d4B0894F5faA9eC"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

CAPITAL = 2
RISK_PER_TRADE = 0.0025
MAX_DAILY_RISK = 0.01
MAX_CONCURRENT = 4

TREND_INTERVAL = "1day"
ENTRY_INTERVAL = "4hour"
ENTRY_INTERVAL_1H = "1hour"
TOP_N = 50
TOLERANCE = 0.001
SMA_PERIOD = 25
BTC_SYMBOL = "BTC-USDT"
STATE_FILE = "trading_state.json"

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
