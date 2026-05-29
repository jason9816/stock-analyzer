"""
Web 層共用工具：快取、平行分析、市場判斷、首頁渲染。
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from flask import render_template, request

from core.analysis import get_stock_analysis
from core.indicators import get_dxy, get_market_vix, get_sp500, get_us10y
from data.store import get_all_stock_meta, load_data
from data.tw import get_taiex, get_tw_chinese_name, get_usdtwd, normalize_tw_symbol

# ── 簡易快取（5 分鐘 TTL）──
_cache = {}
CACHE_TTL = 300


def cached(key, fn):
    """快取函數結果，5 分鐘內不重複抓取"""
    now = time.time()
    if key in _cache and (now - _cache[key]['t']) < CACHE_TTL:
        return _cache[key]['v']
    val = fn()
    _cache[key] = {'v': val, 't': now}
    return val


def analyze_parallel(watchlist, max_workers=8):
    """平行分析多支股票，比逐一分析快 5-8 倍"""
    results = [None] * len(watchlist)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(get_stock_analysis, s): i for i, s in enumerate(watchlist)}
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = {'symbol': watchlist[idx], 'error': str(e)}
    return results


# ── 市場判斷工具 ──


def get_market(path):
    """從 URL path 判斷市場"""
    return 'tw' if '/tw' in path else 'us'


def normalize_symbol(symbol, market):
    if market == 'tw':
        return normalize_tw_symbol(symbol)
    return symbol.upper().strip()


def index_endpoint(market):
    """blueprint 端點名（供 url_for 使用）"""
    return 'market.tw_index' if market == 'tw' else 'market.index'


# 模板需要的所有欄位預設值（快取資料缺欄位時補上）
_DEFAULTS = {
    'chip_score': 0,
    'chip_lbl': '—',
    'chip_color': '#94a3b8',
    'chip_summary': '載入中...',
    'chip_details': {},
    'inst_own': 0,
    'insider_own': 0,
    'short_pct': 0,
    'short_ratio': 0,
    'pcr': 0,
    'beta': 0,
    'squeeze_flag': False,
    'insider_note': '',
    'analyst_note': '',
    'analyst_score': 0,
    'status': '載入中...',
    'status_color': '#94a3b8',
    'status_bg': '#1e293b',
    'tag_line': '',
    'chg_pct': 0,
    'chg': 0,
    'price': 0,
    'nearest_p': 0,
    'nearest_s': 0,
    'pressures': [],
    'supports': [],
    'rsi': 'N/A',
    'macd_val': 0,
    'macd_sig': 0,
    'macd_hist_val': 0,
    'macd_cross': '',
    'vol_ratio': 1,
    'vol_trend': '',
    'aggressive': '',
    'conservative': '',
    'risk': '',
    'stop_loss': 0,
    'take_profit': 0,
    'sell_signal': '',
    'verdict': '分析資料載入中...',
    'short_action': '—',
    'short_action_color': '#94a3b8',
    'short_entry': '',
    'short_target': '',
    'short_stop': '',
    'short_note': '',
    'mid_action': '—',
    'mid_action_color': '#94a3b8',
    'mid_entry': '',
    'mid_target': '',
    'mid_stop': '',
    'mid_note': '',
    'pe': 'N/A',
    'fwd_pe': 'N/A',
    'pb': 'N/A',
    'div_yield': 0,
    'mkt_cap': 'N/A',
    'w52h': 0,
    'w52l': 0,
    'w52_pos': 50,
    'q_labels': [],
    'rev': [],
    'gm': [],
    'nm': [],
    'news': [],
    'rec_summary': {},
    'target_high': None,
    'target_low': None,
    'target_mean': None,
    'target_upside': None,
    'recommend_key': 'N/A',
    'num_analysts': 0,
    'next_earnings': None,
    'earnings_days': None,
    'sector_etf': 'SPY',
    'sector_etf_name': '',
    'sector_perf': {},
    'dates': [],
    'closes': [],
    'volumes': [],
    'opens': [],
    'highs': [],
    'lows': [],
    'ma5': [],
    'ma10': [],
    'ma20': [],
    'ma60': [],
    'bb_upper': [],
    'bb_lower': [],
    'rsi_data': [],
    'macd_data': [],
    'macd_signal_data': [],
    'macd_hist_data': [],
    'lev_strategy': None,
    'lev_etf': None,
    'premarket_price': None,
    'postmarket_price': None,
}


def render_index(market):
    """US / TW 共用的首頁渲染邏輯"""
    if market == 'tw':
        market_info = {'taiex': get_taiex(), 'usdtwd': get_usdtwd()}
        currency = 'NT$'
    else:
        sp500, sp500_chg = get_sp500()
        market_info = {
            'vix': get_market_vix(),
            'sp500': sp500,
            'sp500_chg': sp500_chg,
            'dxy': get_dxy(),
            'us10y': get_us10y(),
        }
        currency = '$'

    data = load_data(market)
    watchlist = data.get('watchlist', [])
    cache = data.get('analysis_cache', {})

    # 分頁（每頁 20 筆）
    page = request.args.get('page', 1, type=int)
    per_page = 20
    total_pages = max(1, (len(watchlist) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    page_symbols = watchlist[(page - 1) * per_page : page * per_page]

    _default_swing = {'signal': '—', 'signal_color': '#94a3b8', 'score': 0}
    _default_mid = {'label': '—', 'color': '#94a3b8', 'score': 0, 'stage': ''}

    report_data = []
    for sym in page_symbols:
        if sym in cache:
            r = cache[sym]['data'].copy()
            for k, v in _DEFAULTS.items():
                if k not in r:
                    r[k] = v
            if not isinstance(r.get('swing'), dict):
                r['swing'] = _default_swing
            if not isinstance(r.get('mid_trend'), dict):
                r['mid_trend'] = _default_mid
            if market == 'tw':
                cn = get_tw_chinese_name(r.get('symbol', ''))
                if cn:
                    r['name'] = cn
            report_data.append(r)

    order = {s: i for i, s in enumerate(page_symbols)}
    report_data.sort(key=lambda x: order.get(x.get('symbol', ''), 999))

    stale_count = 0
    now = datetime.now()
    for sym in watchlist:
        if sym not in cache:
            stale_count += 1
        else:
            try:
                ut = datetime.strptime(cache[sym].get('updated_at', ''), '%Y-%m-%d %H:%M:%S')
                if (now - ut).total_seconds() > 3600:
                    stale_count += 1
            except (ValueError, TypeError):
                stale_count += 1

    ai_analysis = data.get('ai_analysis', {})
    market_ai = data.get('market_ai')
    updated_at = {sym: cache[sym].get('updated_at', '') for sym in cache}

    stock_meta = get_all_stock_meta(market)
    categories = sorted(
        {
            stock_meta.get(s, {}).get('category', '')
            for s in watchlist
            if stock_meta.get(s, {}).get('category')
        }
    )

    return render_template(
        'index.html',
        market=market,
        currency=currency,
        market_info=market_info,
        data=report_data,
        page=page,
        total_pages=total_pages,
        stale_count=stale_count,
        cached_count=len([s for s in watchlist if s in cache]),
        total_stocks=len(watchlist),
        page_symbols=page_symbols,
        stock_meta=stock_meta,
        categories=categories,
        updated_at=updated_at,
        ai_analysis=ai_analysis,
        market_ai=market_ai,
        now=datetime.now().strftime('%Y-%m-%d %H:%M'),
    )
