"""背景 worker 狀態 API（前端 polling 用）。"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from data.store import load_data
from web.workers import _worker_status

bp = Blueprint('workers_api', __name__)


@bp.route('/api/worker-status')
def api_worker_status():
    """回傳背景 worker 的即時狀態。快速/完整兩個迴圈各有獨立欄位。"""
    market = request.args.get('market', 'us')
    status = _worker_status.get(market, {})
    data = load_data(market)
    cache = data.get('analysis_cache', {})
    watchlist = data.get('watchlist', [])

    now = datetime.now()
    oldest_age = 0
    for sym in watchlist:
        if sym not in cache:
            oldest_age = 999999
            break
        try:
            ut = datetime.strptime(cache[sym].get('updated_at', ''), '%Y-%m-%d %H:%M:%S')
            oldest_age = max(oldest_age, (now - ut).total_seconds())
        except Exception:
            oldest_age = 999999

    return jsonify(
        {
            'running': status.get('running', False),
            'price_mode': status.get('price_mode', 'idle'),
            'price_current': status.get('price_current', ''),
            'full_mode': status.get('full_mode', 'idle'),
            'full_current': status.get('full_current', ''),
            'last_updated': status.get('last_updated', ''),
            'round': status.get('round', 0),
            'remaining': len(status.get('queue', [])),
            'total': len(watchlist),
            'cached': len([s for s in watchlist if s in cache]),
            'oldest_age_min': round(oldest_age / 60, 1),
            'price_updates': status.get('price_updates', 0),
            'full_updates': status.get('full_updates', 0),
        }
    )
