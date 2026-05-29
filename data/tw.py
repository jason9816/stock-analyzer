"""
台股工具模組 — 代號正規化、中文名對照、大盤指標
"""

from data.provider import get_ticker

# ── 代號正規化 ──
_two_cache = set()
_tw_cache = set()


def normalize_tw_symbol(symbol):
    """
    智慧判斷上市(.TW) vs 上櫃(.TWO)
    2330 → 2330.TW (上市)
    6488 → 6488.TWO (上櫃)
    已帶後綴的直接回傳
    """
    symbol = symbol.strip().upper()
    if symbol.endswith('.TW') or symbol.endswith('.TWO'):
        return symbol
    code = symbol.replace('.TW', '').replace('.TWO', '')
    if code in _two_cache:
        return f'{code}.TWO'
    if code in _tw_cache:
        return f'{code}.TW'
    try:
        t = get_ticker(f'{code}.TW')
        h = t.history(period='5d')
        if len(h) > 0:
            _tw_cache.add(code)
            return f'{code}.TW'
    except Exception:
        pass  # yfinance lookup failed for .TW
    try:
        t = get_ticker(f'{code}.TWO')
        h = t.history(period='5d')
        if len(h) > 0:
            _two_cache.add(code)
            return f'{code}.TWO'
    except Exception:
        pass  # yfinance lookup failed for .TWO
    return f'{code}.TW'


def display_symbol(symbol):
    """2330.TW → 2330, 6488.TWO → 6488"""
    return symbol.replace('.TW', '').replace('.TWO', '')


# ── 中文名對照 ──
_tw_name_cache = {}


def _load_tw_names():
    """從 TWSE/TPEx 公開 API 載入中文公司簡稱"""
    global _tw_name_cache
    if _tw_name_cache:
        return _tw_name_cache
    import requests

    try:
        r = requests.get('https://openapi.twse.com.tw/v1/opendata/t187ap03_L', timeout=10)
        for item in r.json():
            code = item.get('公司代號', '').strip()
            name = item.get('公司簡稱', '').strip()
            if code and name:
                _tw_name_cache[code] = name
    except Exception:
        pass  # TWSE API unavailable
    try:
        r2 = requests.get('https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O', timeout=10)
        for item in r2.json():
            code = item.get('SecuritiesCompanyCode', '').strip()
            name = item.get('CompanyAbbreviation', '').strip()
            if code and name:
                _tw_name_cache[code] = name
    except Exception:
        pass  # TPEx API unavailable
    print(f'📋 載入台股中文名：{len(_tw_name_cache)} 筆')
    return _tw_name_cache


def get_tw_chinese_name(symbol):
    """取得台股中文名"""
    code = symbol.replace('.TW', '').replace('.TWO', '').strip()
    names = _load_tw_names()
    return names.get(code, '')


# ── 大盤指標 ──
def get_taiex():
    try:
        t = get_ticker('^TWII')
        info = t.info
        price = info.get('regularMarketPrice', 0)
        prev = info.get('regularMarketPreviousClose', price)
        chg_pct = (price - prev) / prev * 100 if prev else 0
        return {'price': price, 'chg_pct': chg_pct}
    except Exception:
        return {'price': 'N/A', 'chg_pct': 0}


def get_usdtwd():
    try:
        t = get_ticker('TWD=X')
        info = t.info
        return info.get('regularMarketPrice', 'N/A')
    except Exception:
        return 'N/A'
