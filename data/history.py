"""
history_cache.py — 歷史日K線記憶體快取模組

功能：
  - 快取每支股票 1 年的歷史 OHLCV 資料，避免重複呼叫 yfinance API
  - 支援批次下載（一次抓多支股票）
  - 可注入即時K棒合併歷史資料，供指標計算使用
  - 執行緒安全（使用 threading.Lock）
"""

import logging
import threading
from datetime import datetime, timedelta

import pandas as pd

from data.provider import bulk_download

# ── 設定 ─────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# 快取過期時間（預設 12 小時）
_DEFAULT_TTL_HOURS = 12

# 記憶體快取：{symbol: {'df': DataFrame, 'updated_at': datetime, 'market': str}}
_history_cache: dict = {}
_cache_lock = threading.Lock()


# ── 內部工具函式 ──────────────────────────────────────────


def _is_expired(updated_at: datetime, ttl_hours: int = _DEFAULT_TTL_HOURS) -> bool:
    """檢查快取是否已過期"""
    if updated_at is None:
        return True
    return datetime.now() - updated_at > timedelta(hours=ttl_hours)


def _normalize_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    將 yfinance 回傳的 DatetimeIndex（含時區）轉為 'YYYY-MM-DD' 字串索引，
    與 analysis.py 的格式一致
    """
    if df.index.dtype == 'object':
        # 已經是字串，不需處理
        return df
    df = df.copy()
    df.index = df.index.strftime('%Y-%m-%d')
    return df


def _download_single(symbol: str, period: str = '1y') -> pd.DataFrame | None:
    """
    下載單一股票的歷史K線資料

    Args:
        symbol: 股票代碼，例如 'AAPL' 或 '2330.TW'
        period: 下載期間，預設 '1y'（一年）

    Returns:
        標準化後的 DataFrame，或下載失敗時回傳 None
    """
    try:
        df = bulk_download(symbol, period=period, progress=False, timeout=30)
        if df is None or df.empty:
            logger.warning(f"⚠️ {symbol} 下載無資料")
            return None

        # yf.download 單一股票時，columns 可能是 MultiIndex（新版 yfinance）
        # 需要攤平成單層 columns
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel('Ticker', axis=1)

        # 只保留 OHLCV 五欄
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        df = df[[c for c in required_cols if c in df.columns]]
        return _normalize_index(df)

    except Exception as e:
        logger.error(f"❌ 下載 {symbol} 歷史資料失敗：{e}")
        return None


def _detect_market(symbol: str) -> str:
    """根據股票代碼判斷市場類型"""
    if symbol.endswith('.TW') or symbol.endswith('.TWO'):
        return 'tw'
    return 'us'


# ── 核心公開函式 ──────────────────────────────────────────


def get_history(symbol: str, ttl_hours: int = _DEFAULT_TTL_HOURS) -> pd.DataFrame | None:
    """
    取得快取的歷史K線，若過期（超過 TTL）則自動重新下載

    Args:
        symbol: 股票代碼，例如 'AAPL' 或 '2330.TW'
        ttl_hours: 快取有效時數，預設 12 小時

    Returns:
        歷史 OHLCV DataFrame（index 為 'YYYY-MM-DD' 字串），
        若下載失敗且無快取則回傳 None
    """
    with _cache_lock:
        cached = _history_cache.get(symbol)
        if cached and not _is_expired(cached['updated_at'], ttl_hours):
            logger.debug(f"✅ {symbol} 命中快取（更新於 {cached['updated_at']}）")
            return cached['df'].copy()

    # 快取未命中或已過期 → 在鎖外面下載（避免長時間持鎖）
    logger.info(f"📥 {symbol} 快取過期或未命中，重新下載...")
    df = _download_single(symbol)

    if df is not None and not df.empty:
        market = _detect_market(symbol)
        with _cache_lock:
            _history_cache[symbol] = {
                'df': df,
                'updated_at': datetime.now(),
                'market': market,
            }
        return df.copy()

    # 下載失敗：嘗試回傳舊的快取資料（過期但總比沒有好）
    with _cache_lock:
        if cached:
            logger.warning(f"⚠️ {symbol} 下載失敗，使用過期快取資料")
            return cached['df'].copy()

    logger.error(f"❌ {symbol} 無可用的歷史資料")
    return None


def refresh_histories(symbols: list, market: str = 'us') -> dict:
    """
    批次更新歷史K線快取（強制重新下載，忽略 TTL）

    使用 yf.download(symbols_list) 一次抓全部，效率遠高於逐一下載。
    約 50 支股票一次批次只需 ~0.2 秒。

    Args:
        symbols: 股票代碼清單，例如 ['AAPL', 'MSFT', 'GOOG']
        market: 市場類型 'us' 或 'tw'

    Returns:
        {symbol: DataFrame} 字典，只包含成功下載的股票
    """
    if not symbols:
        return {}

    result = {}
    logger.info(f"🔄 批次下載 {len(symbols)} 支股票歷史K線（{market} 市場）...")

    try:
        # 批次下載：一次 HTTP 請求取得所有股票
        raw = bulk_download(
            symbols,
            period='1y',
            progress=False,
            group_by='ticker',
            timeout=60,
        )

        if raw is None or raw.empty:
            logger.error("❌ 批次下載回傳空資料")
            return result

        if len(symbols) == 1:
            # 單一股票：yf.download 回傳單層 columns (Open, High, Low, ...)
            sym = symbols[0]
            df = raw.copy()
            # 單一股票時也可能是 MultiIndex（新版 yfinance）
            if isinstance(df.columns, pd.MultiIndex):
                df = df.droplevel('Ticker', axis=1)

            required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            df = df[[c for c in required_cols if c in df.columns]]
            df = _normalize_index(df)
            df = df.dropna(how='all')

            if not df.empty:
                with _cache_lock:
                    _history_cache[sym] = {
                        'df': df,
                        'updated_at': datetime.now(),
                        'market': market,
                    }
                result[sym] = df
                logger.info(f"  ✅ {sym}: {len(df)} 天")
            else:
                logger.warning(f"  ⚠️ {sym}: 無有效資料")
        else:
            # 多支股票：yf.download 回傳 MultiIndex columns (ticker, field)
            for sym in symbols:
                try:
                    if sym not in raw.columns.get_level_values(0):
                        logger.warning(f"  ⚠️ {sym}: 未包含在下載結果中")
                        continue

                    df = raw[sym].copy()
                    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
                    df = df[[c for c in required_cols if c in df.columns]]
                    df = _normalize_index(df)
                    df = df.dropna(how='all')

                    if df.empty:
                        logger.warning(f"  ⚠️ {sym}: 資料全為 NaN")
                        continue

                    with _cache_lock:
                        _history_cache[sym] = {
                            'df': df,
                            'updated_at': datetime.now(),
                            'market': market,
                        }
                    result[sym] = df
                    logger.debug(f"  ✅ {sym}: {len(df)} 天")

                except Exception as e:
                    logger.error(f"  ❌ {sym} 解析失敗：{e}")

    except Exception as e:
        logger.error(f"❌ 批次下載失敗：{e}")
        # 降級處理：逐一下載
        logger.info("🔃 降級為逐一下載...")
        for sym in symbols:
            df = _download_single(sym)
            if df is not None and not df.empty:
                with _cache_lock:
                    _history_cache[sym] = {
                        'df': df,
                        'updated_at': datetime.now(),
                        'market': market,
                    }
                result[sym] = df

    logger.info(f"✅ 批次下載完成：成功 {len(result)}/{len(symbols)} 支")
    return result


def inject_live_candle(symbol: str, live_data: dict) -> pd.DataFrame | None:
    """
    合併歷史K線 + 今天即時數據，回傳完整的 DataFrame 供指標計算

    Args:
        symbol: 股票代碼，例如 '2330.TW' 或 'AAPL'
        live_data: 即時報價字典，格式如下：
            {
                'open': 2350,
                'high': 2360,
                'low': 2275,
                'price': 2315,      # 即時價（當作今天收盤價）
                'volume': 23470000
            }

    Returns:
        完整的 DataFrame（歷史 + 今天即時K棒），index 為 'YYYY-MM-DD' 字串，
        可直接傳入指標計算函式。若無歷史資料則回傳 None。
    """
    # 1. 從快取取得歷史資料
    hist = get_history(symbol)
    if hist is None:
        logger.error(f"❌ {symbol} 無歷史資料可合併")
        return None

    # 2. 驗證即時資料欄位完整性
    required_keys = ['open', 'high', 'low', 'price', 'volume']
    missing = [k for k in required_keys if k not in live_data or live_data[k] is None]
    if missing:
        logger.warning(f"⚠️ {symbol} 即時資料缺少欄位：{missing}，回傳純歷史資料")
        return hist

    # 3. 建立今天的 K 棒
    today_str = datetime.now().strftime('%Y-%m-%d')

    today_candle = pd.DataFrame(
        {
            'Open': [float(live_data['open'])],
            'High': [float(live_data['high'])],
            'Low': [float(live_data['low'])],
            'Close': [float(live_data['price'])],
            'Volume': [int(live_data['volume'])],
        },
        index=[today_str],
    )

    # 4. 移除歷史中今天的資料（若已存在），用即時資料替代
    hist_without_today = hist[hist.index != today_str]

    # 5. 合併歷史 + 今天即時K棒
    combined = pd.concat([hist_without_today, today_candle])

    logger.debug(
        f"📊 {symbol} 合併完成：歷史 {len(hist_without_today)} 天 + 即時 1 天 = {len(combined)} 天"
    )
    return combined


def get_cache_status() -> dict:
    """
    回傳快取狀態摘要，供監控與除錯使用

    Returns:
        {
            'total_cached': int,     # 已快取股票數量
            'symbols': list,         # 已快取的股票代碼清單
            'oldest': str | None,    # 最舊的更新時間（ISO 格式）
            'newest': str | None,    # 最新的更新時間（ISO 格式）
            'markets': dict,         # 各市場快取數量 {'us': N, 'tw': M}
            'expired_count': int,    # 已過期的快取數量
        }
    """
    with _cache_lock:
        if not _history_cache:
            return {
                'total_cached': 0,
                'symbols': [],
                'oldest': None,
                'newest': None,
                'markets': {},
                'expired_count': 0,
            }

        timestamps = [entry['updated_at'] for entry in _history_cache.values()]
        markets = {}
        expired_count = 0

        for entry in _history_cache.values():
            mkt = entry.get('market', 'unknown')
            markets[mkt] = markets.get(mkt, 0) + 1
            if _is_expired(entry['updated_at']):
                expired_count += 1

        oldest = min(timestamps)
        newest = max(timestamps)

        return {
            'total_cached': len(_history_cache),
            'symbols': list(_history_cache.keys()),
            'oldest': oldest.isoformat(),
            'newest': newest.isoformat(),
            'markets': markets,
            'expired_count': expired_count,
        }


def clear_cache(symbol: str | None = None) -> None:
    """
    清除快取資料

    Args:
        symbol: 指定清除某支股票，傳 None 清除全部
    """
    with _cache_lock:
        if symbol:
            removed = _history_cache.pop(symbol, None)
            if removed:
                logger.info(f"🗑️ 已清除 {symbol} 的快取")
            else:
                logger.warning(f"⚠️ {symbol} 不在快取中")
        else:
            count = len(_history_cache)
            _history_cache.clear()
            logger.info(f"🗑️ 已清除全部快取（共 {count} 支）")


# ── 主程式測試 ────────────────────────────────────────────

if __name__ == '__main__':
    # 設定 logging 輸出
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
    )

    print("=" * 60)
    print("  歷史K線快取模組 — 功能測試")
    print("=" * 60)

    # ── 測試 1：批次下載美股 ──
    print("\n🧪 測試 1：批次下載美股 (AAPL, MSFT, GOOG)")
    us_symbols = ['AAPL', 'MSFT', 'GOOG']
    results = refresh_histories(us_symbols, market='us')
    for sym, df in results.items():
        print(f"  {sym}: {len(df)} 天, 最新日期 {df.index[-1]}, 收盤 {df['Close'].iloc[-1]:.2f}")

    # ── 測試 2：單一股票快取命中 ──
    print("\n🧪 測試 2：快取命中測試 (AAPL)")
    df = get_history('AAPL')
    if df is not None:
        print(f"  AAPL 快取命中：{len(df)} 天")
    else:
        print("  ❌ AAPL 快取未命中")

    # ── 測試 3：注入即時K棒 ──
    print("\n🧪 測試 3：注入即時K棒 (AAPL)")
    live = {
        'open': 195.50,
        'high': 198.30,
        'low': 194.80,
        'price': 197.25,
        'volume': 52000000,
    }
    combined = inject_live_candle('AAPL', live)
    if combined is not None:
        print(f"  合併後：{len(combined)} 天")
        print(f"  最後一天：{combined.index[-1]}")
        print(f"  最後一天收盤：{combined['Close'].iloc[-1]}")
        print(f"  倒數第二天：{combined.index[-2]}")
    else:
        print("  ❌ 合併失敗")

    # ── 測試 4：台股下載 ──
    print("\n🧪 測試 4：台股下載 (2330.TW)")
    tw_results = refresh_histories(['2330.TW'], market='tw')
    for sym, df in tw_results.items():
        print(f"  {sym}: {len(df)} 天, 最新收盤 {df['Close'].iloc[-1]:.2f}")

    # ── 測試 5：快取狀態 ──
    print("\n🧪 測試 5：快取狀態")
    status = get_cache_status()
    print(f"  快取數量：{status['total_cached']}")
    print(f"  股票清單：{status['symbols']}")
    print(f"  市場分佈：{status['markets']}")
    print(f"  最舊更新：{status['oldest']}")
    print(f"  最新更新：{status['newest']}")
    print(f"  已過期：{status['expired_count']}")

    # ── 測試 6：清除快取 ──
    print("\n🧪 測試 6：清除單一快取 (GOOG)")
    clear_cache('GOOG')
    status = get_cache_status()
    print(f"  清除後剩餘：{status['total_cached']} 支 {status['symbols']}")

    print("\n" + "=" * 60)
    print("  所有測試完成 ✅")
    print("=" * 60)
