"""策略追蹤 blueprint：策略群組候選股 + 持倉 + 績效。"""

from flask import Blueprint, jsonify, request

from strategy import PortfolioTracker

bp = Blueprint('strategy', __name__)


@bp.route('/api/strategy')
def api_strategy():
    """取得所有策略群組的候選股 + 持倉 + 績效"""
    return jsonify(PortfolioTracker().get_all_strategy_data())


@bp.route('/api/strategy/<group>/candidates', methods=['DELETE'])
def api_strategy_remove_candidate(group):
    """從候選清單移除股票"""
    data = request.get_json() or {}
    symbol = data.get('symbol', '').upper().strip()
    if not symbol:
        return jsonify({'error': '請提供 symbol'}), 400
    PortfolioTracker().remove_candidate(group.upper(), symbol)
    return jsonify({'ok': True, 'removed': symbol})
