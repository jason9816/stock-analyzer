import threading
from datetime import datetime

import numpy as np
import pandas as pd

from data import provider as yf_provider


# ── helpers ──────────────────────────────────────────────
def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def get_market_vix():
    return safe(
        lambda: round(yf_provider.get_history("^VIX", period="5d")['Close'].iloc[-1], 2), "N/A"
    )


def get_sp500():
    try:
        sp = yf_provider.get_history("^GSPC", period="5d")['Close']
        return round(sp.iloc[-1], 2), round((sp.iloc[-1] / sp.iloc[-2] - 1) * 100, 2)
    except Exception:
        return "N/A", 0


def get_dxy():
    return safe(
        lambda: round(yf_provider.get_history("DX-Y.NYB", period="5d")['Close'].iloc[-1], 2), "N/A"
    )


def get_us10y():
    return safe(
        lambda: round(yf_provider.get_history("^TNX", period="5d")['Close'].iloc[-1], 2), "N/A"
    )


def get_options_pcr(symbol):
    """Enhanced PCR: multi-expiration + OI blend (40% vol + 60% OI)"""
    try:
        expirations = yf_provider.get_option_expirations(symbol)
        if not expirations:
            return 0.0
        total_put_vol = total_call_vol = 0
        total_put_oi = total_call_oi = 0
        for exp in expirations[:3]:  # Nearest 3 expirations
            calls, puts = yf_provider.get_option_chain(symbol, exp)
            total_put_vol += puts['volume'].sum()
            total_call_vol += calls['volume'].sum()
            total_put_oi += puts['openInterest'].sum()
            total_call_oi += calls['openInterest'].sum()
        pcr_vol = total_put_vol / total_call_vol if total_call_vol > 0 else 0
        pcr_oi = total_put_oi / total_call_oi if total_call_oi > 0 else 0
        # Blended: 40% volume (timely) + 60% OI (stable)
        pcr = 0.4 * pcr_vol + 0.6 * pcr_oi
        return round(pcr, 2)
    except Exception:
        return 0.0


def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def calc_macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast).mean()
    ema_slow = close.ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_bollinger(close, window=20, num_std=2):
    sma = close.rolling(window).mean()
    std = close.rolling(window).std()
    return sma + num_std * std, sma, sma - num_std * std


def calc_kd(high, low, close, k_period=9, d_period=3):
    """KD 隨機指標 (Stochastic Oscillator)"""
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(com=d_period - 1, adjust=False).mean()
    d = k.ewm(com=d_period - 1, adjust=False).mean()
    return k, d


def calc_atr(high, low, close, period=14):
    """ATR 平均真實波幅 — 用於停損設定和波動異常判斷"""
    tr = pd.DataFrame(
        {'hl': high - low, 'hc': abs(high - close.shift(1)), 'lc': abs(low - close.shift(1))}
    ).max(axis=1)
    return tr.rolling(period).mean()


def calc_obv(close, volume):
    """OBV 能量潮 — 確認突破真假"""
    direction = np.where(close > close.shift(1), 1, np.where(close < close.shift(1), -1, 0))
    obv = (volume * direction).cumsum()
    return pd.Series(obv, index=close.index)


def calc_adx(high, low, close, period=14):
    """ADX 趨勢強度 + DI+/DI- 方向指標"""
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    tr = pd.DataFrame(
        {'hl': high - low, 'hc': abs(high - close.shift(1)), 'lc': abs(low - close.shift(1))}
    ).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100
    adx = dx.rolling(period).mean()
    return adx, plus_di, minus_di


def calc_mfi(high, low, close, volume, period=14):
    """MFI 資金流量指標 — 量化版 RSI"""
    typical_price = (high + low + close) / 3
    money_flow = typical_price * volume
    delta = typical_price.diff()
    pos_flow = money_flow.where(delta > 0, 0).rolling(period).sum()
    neg_flow = money_flow.where(delta < 0, 0).rolling(period).sum()
    # 改善 #5：MFI 極端情況處理
    # 正負流都為 0 → MFI = 50（中性），不再產生極端值
    mfi = pos_flow.copy()
    for idx in mfi.index:
        p, n = pos_flow.get(idx, 0), neg_flow.get(idx, 0)
        if p == 0 and n == 0:
            mfi[idx] = 50
        elif n == 0:
            mfi[idx] = 100
        elif p == 0:
            mfi[idx] = 0
        else:
            mfi[idx] = 100 - (100 / (1 + p / n))
    return mfi


def calc_vwap(high, low, close, volume, period=20):
    """VWAP 成交量加權均價（rolling N日）"""
    typical_price = (high + low + close) / 3
    vwap = (typical_price * volume).rolling(period).sum() / volume.rolling(period).sum()
    return vwap


def calc_fibonacci_levels(hist, lookback=60):
    """費氏回撤位 — 找近期波段高低點的 38.2%/50%/61.8%"""
    recent = hist.tail(lookback)
    high = recent['High'].max()
    low = recent['Low'].min()
    diff = high - low
    levels = {
        'fib_0': high,  # 0% (高點)
        'fib_236': high - diff * 0.236,
        'fib_382': high - diff * 0.382,
        'fib_500': high - diff * 0.500,
        'fib_618': high - diff * 0.618,
        'fib_786': high - diff * 0.786,
        'fib_100': low,  # 100% (低點)
    }
    return levels


# ══════════════════════════════════════════════════════════════
# 大盤指數數據快取（每日更新一次）
# S&P500 / 加權指數歷史數據，用於計算相對強度 RS
# 避免每次分析都重新抓取，每日 09:00 更新
# ══════════════════════════════════════════════════════════════
_index_cache = {
    'sp500': {'data': None, 'updated': None},
    'twii': {'data': None, 'updated': None},
}
_index_lock = threading.Lock()


def get_index_history(symbol='^GSPC', force_refresh=False):
    """
    取得大盤指數歷史收盤價（1 年），帶快取
    - symbol: '^GSPC' (S&P500) 或 '^TWII' (加權指數)
    - 快取每日只更新一次，避免重複 API 呼叫
    - force_refresh=True 強制重抓
    """
    cache_key = 'sp500' if symbol == '^GSPC' else 'twii' if symbol == '^TWII' else symbol

    with _index_lock:
        cached = _index_cache.get(cache_key, {'data': None, 'updated': None})
        now = datetime.now()

        # 檢查是否需要更新（今天還沒更新過，或強制刷新）
        needs_update = (
            force_refresh
            or cached['data'] is None
            or cached['updated'] is None
            or cached['updated'].date() < now.date()
        )

        if not needs_update:
            return cached['data']

    # 在鎖外面抓數據（避免長時間持鎖）
    try:
        print(f"📊 更新大盤指數快取：{symbol}...")
        hist = yf_provider.get_history(symbol, period='1y')
        if hist is not None and len(hist) > 0:
            close_series = hist['Close']
            with _index_lock:
                _index_cache[cache_key] = {'data': close_series, 'updated': datetime.now()}
            print(f"✅ {symbol} 快取更新完成（{len(close_series)} 天）")
            return close_series
    except Exception as e:
        print(f"⚠️ 更新 {symbol} 失敗：{e}")

    # 失敗時返回舊快取
    with _index_lock:
        return _index_cache.get(cache_key, {}).get('data')


def refresh_all_index_cache():
    """強制更新所有大盤指數快取（排程用）"""
    print("🔄 排程更新大盤指數快取...")
    get_index_history('^GSPC', force_refresh=True)
    get_index_history('^TWII', force_refresh=True)
    print("✅ 大盤指數快取全部更新完成")
