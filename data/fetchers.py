"""
統一即時報價服務 — 台股（TWSE 官方 API）與美股（yfinance）

提供批次即時報價介面，支援：
  - 台股：優先使用 TWSE/OTC 盤中即時 API，失敗時降級為 yfinance
  - 美股：使用 yfinance.download() 批次取得當日 OHLCV
  - 內建 10 秒 TTL 快取，避免短時間重複呼叫 API
"""

import logging
import time

import requests

from data.provider import bulk_download

logger = logging.getLogger(__name__)

# ── TTL 快取 ──────────────────────────────────────────────────────────────────

_cache: dict[str, dict] = {}
_cache_ts: dict[str, float] = {}
_CACHE_TTL = 10  # 秒


def _get_cached(key: str) -> dict | None:
    """從快取取得資料，若已過期則回傳 None"""
    if key in _cache and (time.time() - _cache_ts.get(key, 0)) < _CACHE_TTL:
        return _cache[key]
    return None


def _set_cache(key: str, value: dict) -> None:
    """將資料寫入快取並記錄時間戳"""
    _cache[key] = value
    _cache_ts[key] = time.time()


# ── 台股：TWSE 盤中即時 API ──────────────────────────────────────────────────

_TWSE_API = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"


def _build_twse_codes(symbols: list[str]) -> str:
    """
    將台股代號轉換為 TWSE API 格式

    規則：
      - 以 .TWO 結尾 → otc_XXXX.tw（上櫃）
      - 其他（.TW 或純數字）→ tse_XXXX.tw（上市）
    多檔以 '|' 連接
    """
    parts = []
    for sym in symbols:
        sym_upper = sym.strip().upper()
        # 取出純數字代號
        code = sym_upper.replace(".TWO", "").replace(".TW", "")
        if sym_upper.endswith(".TWO"):
            parts.append(f"otc_{code}.tw")
        else:
            parts.append(f"tse_{code}.tw")
    return "|".join(parts)


def _parse_twse_price(item: dict) -> float:
    """
    解析 TWSE 即時成交價

    處理 z="-" 的情況（尚未成交）：
      1. 優先使用最佳買價 b（以 '_' 分隔，取第一個）
      2. 再降級為昨收價 y
    """
    z = item.get("z", "-")
    if z and z != "-":
        try:
            return float(z)
        except (ValueError, TypeError):
            pass

    # 尚未成交 → 嘗試最佳買價
    b = item.get("b", "")
    if b and b != "-":
        try:
            return float(b.split("_")[0])
        except (ValueError, TypeError):
            pass

    # 最終降級 → 昨收價
    y = item.get("y", "0")
    try:
        return float(y)
    except (ValueError, TypeError):
        return 0.0


def _safe_float(value: str, default: float = 0.0) -> float:
    """安全地將字串轉換為浮點數，失敗時回傳預設值"""
    if not value or value == "-":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _fetch_tw_from_twse(symbols: list[str]) -> dict[str, dict]:
    """
    透過 TWSE 盤中即時 API 取得台股報價

    回傳格式與 fetch_realtime_prices() 一致。
    成交量（v）單位為「張」，乘以 1000 轉為「股」以統一單位。
    """
    result = {}
    if not symbols:
        return result

    ex_ch = _build_twse_codes(symbols)
    timestamp = int(time.time() * 1000)

    try:
        resp = requests.get(
            _TWSE_API,
            params={"ex_ch": ex_ch, "_": timestamp},
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://mis.twse.com.tw/stock/fibest.jsp",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning("TWSE API 請求失敗: %s", e)
        return result
    except ValueError as e:
        logger.warning("TWSE API 回傳非 JSON: %s", e)
        return result

    msg_array = data.get("msgArray", [])
    if not msg_array:
        logger.warning("TWSE API 回傳空資料 (msgArray 為空)")
        return result

    # 建立 symbol 查找表：tse_2330 → 2330.TW
    sym_lookup = {}
    for sym in symbols:
        sym_upper = sym.strip().upper()
        code = sym_upper.replace(".TWO", "").replace(".TW", "")
        sym_lookup[code] = sym_upper

    for item in msg_array:
        code = item.get("c", "")  # 股票代號，例如 "2330"
        if code not in sym_lookup:
            continue

        original_sym = sym_lookup[code]
        price = _parse_twse_price(item)
        prev_close = _safe_float(item.get("y", "0"))

        # OHLCV — TWSE 即時 API 提供 o(開盤), h(最高), l(最低), z(成交), v(成交量/張)
        open_price = _safe_float(item.get("o", "0"))
        high_price = _safe_float(item.get("h", "0"))
        low_price = _safe_float(item.get("l", "0"))

        # 成交量：張 → 股（乘以 1000）
        volume_lots = _safe_float(item.get("v", "0"))
        volume_shares = int(volume_lots * 1000)

        # 成交時間
        trade_time = item.get("t", "")

        result[original_sym] = {
            "price": price,
            "open": open_price if open_price else price,
            "high": high_price if high_price else price,
            "low": low_price if low_price else price,
            "volume": volume_shares,
            "prev_close": prev_close,
            "time": trade_time,
            "source": "twse",
        }

    return result


def _fetch_tw_from_yfinance(symbols: list[str]) -> dict[str, dict]:
    """
    使用 yfinance 作為台股報價的降級方案

    當 TWSE API 失敗或回傳不完整時使用。
    """
    result = {}
    if not symbols:
        return result

    try:
        tickers = " ".join(symbols)
        df = bulk_download(tickers, period="5d", progress=False, timeout=10)
        if df.empty:
            return result

        # 取最後一個交易日的資料
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2] if len(df) >= 2 else last_row

        for sym in symbols:
            sym_upper = sym.strip().upper()
            try:
                # yfinance 多股下載時，欄位是 MultiIndex (field, symbol)
                if len(symbols) > 1:
                    o = float(last_row[("Open", sym_upper)])
                    h = float(last_row[("High", sym_upper)])
                    l = float(last_row[("Low", sym_upper)])
                    c = float(last_row[("Close", sym_upper)])
                    v = int(last_row[("Volume", sym_upper)])
                    pc = float(prev_row[("Close", sym_upper)])
                else:
                    o = float(last_row["Open"])
                    h = float(last_row["High"])
                    l = float(last_row["Low"])
                    c = float(last_row["Close"])
                    v = int(last_row["Volume"])
                    pc = float(prev_row["Close"])

                result[sym_upper] = {
                    "price": c,
                    "open": o,
                    "high": h,
                    "low": l,
                    "volume": v,
                    "prev_close": pc,
                    "time": "",
                    "source": "yfinance",
                }
            except (KeyError, TypeError, ValueError) as e:
                logger.debug("yfinance 解析 %s 失敗: %s", sym_upper, e)
                continue

    except Exception as e:
        logger.warning("yfinance 台股降級查詢失敗: %s", e)

    return result


# ── 美股：yfinance batch download ────────────────────────────────────────────


def _fetch_us_prices(symbols: list[str]) -> dict[str, dict]:
    """
    使用 yfinance.download() 批次取得美股當日 OHLCV

    使用 period='5d' 確保能取到最近一個交易日（避免假日空資料），
    然後取最後一列作為當日報價。單次呼叫可處理 50+ 檔股票，約 0.2 秒。
    """
    result = {}
    if not symbols:
        return result

    try:
        tickers = " ".join(s.strip().upper() for s in symbols)
        df = bulk_download(tickers, period="5d", progress=False, timeout=10)
        if df.empty:
            logger.warning("yfinance 美股下載回傳空資料")
            return result

        last_row = df.iloc[-1]
        prev_row = df.iloc[-2] if len(df) >= 2 else last_row

        for sym in symbols:
            sym_upper = sym.strip().upper()
            try:
                if len(symbols) > 1:
                    o = float(last_row[("Open", sym_upper)])
                    h = float(last_row[("High", sym_upper)])
                    l = float(last_row[("Low", sym_upper)])
                    c = float(last_row[("Close", sym_upper)])
                    v = int(last_row[("Volume", sym_upper)])
                    pc = float(prev_row[("Close", sym_upper)])
                else:
                    o = float(last_row["Open"])
                    h = float(last_row["High"])
                    l = float(last_row["Low"])
                    c = float(last_row["Close"])
                    v = int(last_row["Volume"])
                    pc = float(prev_row["Close"])

                result[sym_upper] = {
                    "price": c,
                    "open": o,
                    "high": h,
                    "low": l,
                    "volume": v,
                    "prev_close": pc,
                    "time": "",
                    "source": "yfinance",
                }
            except (KeyError, TypeError, ValueError) as e:
                logger.debug("yfinance 解析 %s 失敗: %s", sym_upper, e)
                continue

    except Exception as e:
        logger.warning("yfinance 美股批次下載失敗: %s", e)

    return result


# ── 統一介面 ──────────────────────────────────────────────────────────────────


def fetch_realtime_prices(symbols: list[str], market: str) -> dict[str, dict]:
    """
    批次取得即時報價（統一介面）

    Args:
        symbols: 股票代號清單
                 台股: ['2330.TW', '2317.TW', '6488.TWO']
                 美股: ['AAPL', 'NVDA', 'TSLA']
        market:  'tw' 或 'us'

    Returns:
        以股票代號為 key 的字典，每檔包含：
        {
            'price': 最新成交價 (float),
            'open': 開盤價 (float),
            'high': 最高價 (float),
            'low': 最低價 (float),
            'volume': 成交量，單位為「股」(int),
            'prev_close': 前日收盤價 (float),
            'time': 成交時間 (str),
            'source': 資料來源 'twse' | 'yfinance' (str),
        }

    注意事項:
        - 台股成交量已統一轉換為「股」（TWSE 原始單位為「張」）
        - 台股優先使用 TWSE API，失敗時自動降級為 yfinance
        - 美股使用 yfinance 批次下載
        - 所有 HTTP 請求 timeout=10 秒
        - 永不拋出例外，失敗時回傳部分結果或空字典
        - 內建 10 秒 TTL 快取
    """
    if not symbols:
        return {}

    # 正規化代號
    symbols = [s.strip().upper() for s in symbols]
    market = market.strip().lower()

    # 檢查快取
    cache_key = f"{market}:{','.join(sorted(symbols))}"
    cached = _get_cached(cache_key)
    if cached is not None:
        logger.debug("快取命中: %s", cache_key)
        return cached

    result = {}

    if market == "tw":
        # 台股：優先 TWSE API，失敗降級 yfinance
        result = _fetch_tw_from_twse(symbols)

        # 檢查是否有遺漏的股票，用 yfinance 補齊
        missing = [s for s in symbols if s not in result]
        if missing:
            logger.info("TWSE 遺漏 %d 檔，降級 yfinance: %s", len(missing), missing)
            fallback = _fetch_tw_from_yfinance(missing)
            result.update(fallback)

    elif market == "us":
        # 美股：yfinance 批次下載
        result = _fetch_us_prices(symbols)

    else:
        logger.warning("不支援的市場類型: %s（請使用 'tw' 或 'us'）", market)
        return {}

    # 寫入快取
    if result:
        _set_cache(cache_key, result)

    return result


# ── 便捷函式 ──────────────────────────────────────────────────────────────────


def fetch_tw_prices(symbols: list[str]) -> dict[str, dict]:
    """取得台股即時報價的便捷函式"""
    return fetch_realtime_prices(symbols, market="tw")


def fetch_us_prices(symbols: list[str]) -> dict[str, dict]:
    """取得美股即時報價的便捷函式"""
    return fetch_realtime_prices(symbols, market="us")


def clear_cache() -> None:
    """清除所有報價快取"""
    _cache.clear()
    _cache_ts.clear()
    logger.debug("報價快取已清除")


# ── 測試區塊 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s | %(message)s")

    print("=" * 60)
    print("📈 台股即時報價測試（TWSE API）")
    print("=" * 60)

    tw_symbols = ["2330.TW", "2317.TW", "2454.TW", "6488.TWO"]
    tw_prices = fetch_tw_prices(tw_symbols)
    for sym, info in tw_prices.items():
        chg = info["price"] - info["prev_close"] if info["prev_close"] else 0
        chg_pct = (chg / info["prev_close"] * 100) if info["prev_close"] else 0
        print(
            f"  {sym:10s} | 現價 {info['price']:>10.2f} | "
            f"開 {info['open']:>10.2f} | 高 {info['high']:>10.2f} | "
            f"低 {info['low']:>10.2f} | 量 {info['volume']:>12,} 股 | "
            f"漲跌 {chg:>+.2f} ({chg_pct:>+.2f}%) | "
            f"來源: {info['source']} | 時間: {info['time']}"
        )

    # 測試快取：第二次呼叫應命中快取
    print("\n🔄 快取測試（應顯示快取命中）...")
    tw_prices_cached = fetch_tw_prices(tw_symbols)
    assert tw_prices_cached == tw_prices, "快取結果不一致！"
    print("  ✅ 快取命中成功")

    print("\n" + "=" * 60)
    print("📈 美股即時報價測試（yfinance）")
    print("=" * 60)

    us_symbols = ["AAPL", "NVDA", "TSLA", "MSFT", "GOOGL"]
    us_prices = fetch_us_prices(us_symbols)
    for sym, info in us_prices.items():
        chg = info["price"] - info["prev_close"] if info["prev_close"] else 0
        chg_pct = (chg / info["prev_close"] * 100) if info["prev_close"] else 0
        print(
            f"  {sym:10s} | 現價 {info['price']:>10.2f} | "
            f"開 {info['open']:>10.2f} | 高 {info['high']:>10.2f} | "
            f"低 {info['low']:>10.2f} | 量 {info['volume']:>14,} 股 | "
            f"漲跌 {chg:>+.2f} ({chg_pct:>+.2f}%) | "
            f"來源: {info['source']}"
        )

    print("\n✅ 全部測試完成")
