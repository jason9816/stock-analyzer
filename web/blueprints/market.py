"""市場追蹤 blueprint：美股 / 台股首頁、新增/移除/刷新/分類股票。"""

from flask import Blueprint, redirect, request, url_for

from config import WEB_PASSWORD
from core.analysis import get_stock_analysis
from data.provider import get_info
from data.store import (
    get_all_stock_meta,
    get_watchlist,
    load_data,
    save_analysis_cache,
    save_data,
    save_stock_meta,
)
from web.helpers import analyze_parallel, get_market, index_endpoint, normalize_symbol, render_index

bp = Blueprint('market', __name__)


@bp.route('/')
def index():
    return render_index('us')


@bp.route('/tw')
@bp.route('/tw/')
def tw_index():
    return render_index('tw')


def _add_symbol(symbol, market):
    """共用：驗證代號可抓到報價後加入 watchlist 並做 AI 分類"""
    data = load_data(market)
    if symbol in data.get('watchlist', []):
        return
    try:
        info = get_info(symbol)
        if info.get('regularMarketPrice') or info.get('currentPrice'):
            data.setdefault('watchlist', []).append(symbol)
            save_data(data, market)
            try:
                from services.ai import classify_stock

                save_stock_meta(symbol, classify_stock(symbol), market)
            except Exception:
                pass
    except Exception:
        pass


@bp.route('/add/<symbol>')
@bp.route('/tw/add/<symbol>')
def add_stock(symbol):
    market = get_market(request.path)
    _add_symbol(normalize_symbol(symbol, market), market)
    return redirect(url_for(index_endpoint(market)))


@bp.route('/add_custom', methods=['POST'])
@bp.route('/tw/add_custom', methods=['POST'])
def add_custom():
    """手動輸入股票代號加入追蹤"""
    market = get_market(request.path)
    symbol = request.form.get('symbol', '').strip()
    if symbol:
        _add_symbol(normalize_symbol(symbol, market), market)
    return redirect(url_for(index_endpoint(market)))


@bp.route('/remove/<symbol>')
@bp.route('/tw/remove/<symbol>')
def remove_stock(symbol):
    market = get_market(request.path)
    symbol = normalize_symbol(symbol, market)
    data = load_data(market)
    if symbol in data.get('watchlist', []):
        data['watchlist'].remove(symbol)
        data.get('analysis_cache', {}).pop(symbol, None)
        data.get('stock_meta', {}).pop(symbol, None)
        save_data(data, market)
    return redirect(url_for(index_endpoint(market)))


@bp.route('/refresh/<symbol>')
@bp.route('/tw/refresh/<symbol>')
def refresh_stock(symbol):
    """單一股票手動刷新"""
    market = get_market(request.path)
    symbol = normalize_symbol(symbol, market)
    try:
        result = get_stock_analysis(symbol)
        if result and 'error' not in result:
            save_analysis_cache(symbol, result, market)
    except Exception:
        pass
    return redirect(url_for(index_endpoint(market)))


@bp.route('/refresh_all')
@bp.route('/tw/refresh_all')
def refresh_all():
    """刷新所有股票分析"""
    market = get_market(request.path)
    results = analyze_parallel(get_watchlist(market))
    for r in results:
        if r and 'error' not in r:
            save_analysis_cache(r['symbol'], r, market)
    return redirect(url_for(index_endpoint(market)))


@bp.route('/classify/<symbol>')
@bp.route('/tw/classify/<symbol>')
def classify_one(symbol):
    """手動觸發 AI 分類"""
    if request.args.get('pwd', '') != WEB_PASSWORD:
        return '密碼錯誤', 403
    market = get_market(request.path)
    symbol = normalize_symbol(symbol, market)
    try:
        from services.ai import classify_stock

        save_stock_meta(symbol, classify_stock(symbol), market)
    except Exception:
        pass
    return redirect(url_for(index_endpoint(market)))


@bp.route('/classify_all')
@bp.route('/tw/classify_all')
def classify_all():
    """分類所有尚無 metadata 的股票"""
    if request.args.get('pwd', '') != WEB_PASSWORD:
        return '密碼錯誤', 403
    market = get_market(request.path)
    all_meta = get_all_stock_meta(market)
    for sym in get_watchlist(market):
        if sym not in all_meta:
            try:
                from services.ai import classify_stock

                save_stock_meta(sym, classify_stock(sym), market)
            except Exception:
                pass
    return redirect(url_for(index_endpoint(market)))
