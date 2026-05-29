"""Alpaca 模擬交易 blueprint：交易面板 + 下單/查詢 API。"""

from flask import Blueprint, jsonify, render_template, request

from services.alpaca import (
    cancel_all_orders,
    cancel_order,
    close_position,
    get_account_info,
    get_orders,
    get_positions,
    get_trade_log,
    place_limit_order,
    place_market_order,
)

bp = Blueprint('trading', __name__)


@bp.route('/trading')
def trading_panel():
    """交易面板頁面"""
    return render_template(
        'trading.html',
        account=get_account_info(paper=True),
        positions=get_positions(paper=True),
        orders=get_orders('open', paper=True),
        recent_trades=get_trade_log(20),
    )


@bp.route('/api/trading/account')
def api_trading_account():
    return jsonify(get_account_info(paper=True))


@bp.route('/api/trading/positions')
def api_trading_positions():
    return jsonify(get_positions(paper=True))


@bp.route('/api/trading/orders')
def api_trading_orders():
    return jsonify(get_orders(request.args.get('status', 'open'), paper=True))


@bp.route('/api/trading/buy', methods=['POST'])
def api_trading_buy():
    data = request.get_json() or {}
    symbol = data.get('symbol', '').upper().strip()
    qty = float(data.get('qty', 0))
    order_type = data.get('type', 'market')
    limit_price = data.get('limit_price')
    if not symbol or qty <= 0:
        return jsonify({'error': '請提供 symbol 和 qty'}), 400
    if order_type == 'limit' and limit_price:
        result = place_limit_order(symbol, qty, float(limit_price), 'buy', paper=True)
    else:
        result = place_market_order(symbol, qty, 'buy', paper=True)
    return jsonify(result)


@bp.route('/api/trading/sell', methods=['POST'])
def api_trading_sell():
    data = request.get_json() or {}
    symbol = data.get('symbol', '').upper().strip()
    qty = float(data.get('qty', 0))
    order_type = data.get('type', 'market')
    limit_price = data.get('limit_price')
    if not symbol or qty <= 0:
        return jsonify({'error': '請提供 symbol 和 qty'}), 400
    if order_type == 'limit' and limit_price:
        result = place_limit_order(symbol, qty, float(limit_price), 'sell', paper=True)
    else:
        result = place_market_order(symbol, qty, 'sell', paper=True)
    return jsonify(result)


@bp.route('/api/trading/cancel', methods=['POST'])
def api_trading_cancel():
    data = request.get_json() or {}
    order_id = data.get('order_id', '')
    if order_id == 'all':
        return jsonify(cancel_all_orders(paper=True))
    if not order_id:
        return jsonify({'error': '請提供 order_id'}), 400
    return jsonify(cancel_order(order_id, paper=True))


@bp.route('/api/trading/close', methods=['POST'])
def api_trading_close():
    data = request.get_json() or {}
    symbol = data.get('symbol', '').upper().strip()
    if not symbol:
        return jsonify({'error': '請提供 symbol'}), 400
    return jsonify(close_position(symbol, paper=True))


@bp.route('/api/trading/log')
def api_trading_log():
    return jsonify(get_trade_log(request.args.get('limit', 50, type=int)))
