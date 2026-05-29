"""
市場資料抽象層 — 所有模組透過這裡取得 yfinance 資料。

抽換資料來源時只需改這個檔案的內部實作，消費端不用動。
目前後端為 yfinance，未來可換成 Alpha Vantage、自建 API 等。
"""

import json
import logging
import os
import time

import pandas as pd
import yfinance as yf

logger = logging.getLogger('stock_analyzer')


# ══════════════════════════════════════════════════════════
#  Ticker 物件（需要多次存取同一標的時使用）
# ══════════════════════════════════════════════════════════


def get_ticker(symbol):
    """
    取得 Ticker 物件，保留完整 yfinance 介面。

    適用於需要同一標的多次存取（info + history + options）的場景，
    避免重複建立 Ticker。長期目標是消除對此函數的依賴，改用下方
    的具體函數。
    """
    return yf.Ticker(symbol)


# ══════════════════════════════════════════════════════════
#  基本資料
# ══════════════════════════════════════════════════════════


def get_info(symbol):
    """取得股票基本資料（名稱、sector、market cap 等）。"""
    try:
        return yf.Ticker(symbol).info or {}
    except Exception as e:
        logger.debug('get_info(%s) 失敗: %s', symbol, e)
        return {}


def get_history(symbol, period='6mo', interval='1d'):
    """取得 K 線歷史（DataFrame: Open/High/Low/Close/Volume）。"""
    try:
        return yf.Ticker(symbol).history(period=period, interval=interval)
    except Exception as e:
        logger.debug('get_history(%s) 失敗: %s', symbol, e)
        return pd.DataFrame()


def get_news(symbol, limit=5):
    """取得股票新聞列表。"""
    try:
        return (yf.Ticker(symbol).news or [])[:limit]
    except Exception as e:
        logger.debug('get_news(%s) 失敗: %s', symbol, e)
        return []


# ══════════════════════════════════════════════════════════
#  衍生性商品
# ══════════════════════════════════════════════════════════


def get_option_expirations(symbol):
    """取得可用的選擇權到期日列表。"""
    try:
        return yf.Ticker(symbol).options or []
    except Exception as e:
        logger.debug('get_option_expirations(%s) 失敗: %s', symbol, e)
        return []


def get_option_chain(symbol, expiration):
    """取得指定到期日的選擇權鏈（calls, puts DataFrame）。"""
    try:
        chain = yf.Ticker(symbol).option_chain(expiration)
        return chain.calls, chain.puts
    except Exception as e:
        logger.debug('get_option_chain(%s, %s) 失敗: %s', symbol, expiration, e)
        return pd.DataFrame(), pd.DataFrame()


# ══════════════════════════════════════════════════════════
#  批次下載
# ══════════════════════════════════════════════════════════


def bulk_download(symbols, period='6mo', interval='1d', **kwargs):
    """
    批次下載多檔股票歷史（yf.download wrapper）。

    回傳 DataFrame，多股票時為 MultiIndex columns。
    """
    kwargs.setdefault('progress', False)
    kwargs.setdefault('threads', True)
    try:
        return yf.download(
            symbols,
            period=period,
            interval=interval,
            **kwargs,
        )
    except Exception as e:
        logger.debug('bulk_download 失敗: %s', e)
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════
#  S&P 500 成分股（動態從 Wikipedia 取得）
# ══════════════════════════════════════════════════════════

_SP500_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '.sp500_cache.json',
)
_SP500_CACHE_TTL = 86400  # 24 小時


def get_sp500_symbols():
    """
    取得目前 S&P 500 成分股代碼列表。

    從 Wikipedia 抓取，本地快取 24 小時。快取失敗時 fallback
    到上次成功的結果。
    """
    # 嘗試讀取快取
    if os.path.exists(_SP500_CACHE_FILE):
        try:
            with open(_SP500_CACHE_FILE) as f:
                cache = json.load(f)
            if time.time() - cache.get('ts', 0) < _SP500_CACHE_TTL:
                return cache['symbols']
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    # 從 Wikipedia 抓取
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        df = pd.read_html(url)[0]
        symbols = (
            df['Symbol']
            .str.replace('.', '-', regex=False)  # BRK.B → BRK-B
            .tolist()
        )
        # 寫入快取
        with open(_SP500_CACHE_FILE, 'w') as f:
            json.dump({'ts': time.time(), 'symbols': symbols}, f)
        logger.info('S&P 500 成分股已更新（%d 支）', len(symbols))
        return symbols
    except Exception as e:
        logger.warning('無法從 Wikipedia 取得 S&P 500: %s', e)

    # fallback: 讀取過期快取
    if os.path.exists(_SP500_CACHE_FILE):
        try:
            with open(_SP500_CACHE_FILE) as f:
                return json.load(f).get('symbols', [])
        except (json.JSONDecodeError, OSError):
            pass

    return []
