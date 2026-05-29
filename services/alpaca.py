"""
Alpaca 交易服務模組 — Paper Trading + Live Trading
串接你的分析系統信號 → Alpaca API 自動/半自動下單
"""

import json
import os
from datetime import datetime

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
)

# ── 設定 ──────────────────────────────────────────────
# API Keys 從環境變數或 config 讀取
# Paper Trading: https://app.alpaca.markets/paper/dashboard
# Live Trading:  https://app.alpaca.markets/
from config import ALPACA_PAPER_KEY, ALPACA_PAPER_SECRET


def get_client(paper=True) -> TradingClient | None:
    """
    取得 Alpaca Trading Client（API key 從 .env 讀取）

    Args:
        paper: True=模擬盤, False=真實交易
    """
    if paper:
        key = ALPACA_PAPER_KEY or os.environ.get('ALPACA_PAPER_KEY', '')
        secret = ALPACA_PAPER_SECRET or os.environ.get('ALPACA_PAPER_SECRET', '')
    else:
        key = os.environ.get('ALPACA_LIVE_KEY', '')
        secret = os.environ.get('ALPACA_LIVE_SECRET', '')

    if not key or not secret:
        print(
            f'⚠️ Alpaca {"Paper" if paper else "Live"} API Key 未設定（請在 .env 填入 ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET）'
        )
        return None

    return TradingClient(key, secret, paper=paper)


# ══════════════════════════════════════════════════════════
# 帳戶資訊
# ══════════════════════════════════════════════════════════


def get_account_info(paper=True) -> dict:
    """取得帳戶資訊：餘額、購買力、損益"""
    client = get_client(paper)
    if not client:
        return {'error': 'API Key 未設定'}

    try:
        acct = client.get_account()
        return {
            'account_id': acct.id,
            'status': acct.status.value if hasattr(acct.status, 'value') else str(acct.status),
            'cash': float(acct.cash),
            'buying_power': float(acct.buying_power),
            'portfolio_value': float(acct.portfolio_value),
            'equity': float(acct.equity),
            'last_equity': float(acct.last_equity),
            'pnl_today': float(acct.equity) - float(acct.last_equity),
            'pnl_today_pct': (
                (float(acct.equity) - float(acct.last_equity)) / float(acct.last_equity) * 100
            )
            if float(acct.last_equity) > 0
            else 0,
            'daytrade_count': acct.daytrade_count,
            'pattern_day_trader': acct.pattern_day_trader,
            'trading_blocked': acct.trading_blocked,
            'paper': paper,
        }
    except Exception as e:
        return {'error': str(e)}


def get_positions(paper=True) -> list:
    """取得目前持倉"""
    client = get_client(paper)
    if not client:
        return []

    try:
        positions = client.get_all_positions()
        result = []
        for p in positions:
            result.append(
                {
                    'symbol': p.symbol,
                    'qty': float(p.qty),
                    'side': p.side.value if hasattr(p.side, 'value') else str(p.side),
                    'avg_entry': float(p.avg_entry_price),
                    'current_price': float(p.current_price),
                    'market_value': float(p.market_value),
                    'cost_basis': float(p.cost_basis),
                    'unrealized_pl': float(p.unrealized_pl),
                    'unrealized_plpc': float(p.unrealized_plpc) * 100,  # 轉百分比
                    'change_today': float(p.change_today) * 100,
                }
            )
        return result
    except Exception as e:
        print(f'⚠️ 取得持倉失敗: {e}')
        return []


# ══════════════════════════════════════════════════════════
# 下單功能
# ══════════════════════════════════════════════════════════


def place_market_order(symbol: str, qty: float, side: str = 'buy', paper=True) -> dict:
    """
    市價單

    Args:
        symbol: 股票代號 (e.g., 'AAPL')
        qty: 數量（支持小數 = 碎股）
        side: 'buy' 或 'sell'
        paper: 模擬盤
    """
    client = get_client(paper)
    if not client:
        return {'error': 'API Key 未設定'}

    try:
        order_data = MarketOrderRequest(
            symbol=symbol.upper(),
            qty=qty,
            side=OrderSide.BUY if side == 'buy' else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(order_data=order_data)
        return _format_order(order)
    except Exception as e:
        return {'error': str(e), 'symbol': symbol}


def place_limit_order(
    symbol: str, qty: float, limit_price: float, side: str = 'buy', paper=True
) -> dict:
    """
    限價單

    Args:
        symbol: 股票代號
        qty: 數量
        limit_price: 限價
        side: 'buy' 或 'sell'
    """
    client = get_client(paper)
    if not client:
        return {'error': 'API Key 未設定'}

    try:
        order_data = LimitOrderRequest(
            symbol=symbol.upper(),
            qty=qty,
            limit_price=round(limit_price, 2),
            side=OrderSide.BUY if side == 'buy' else OrderSide.SELL,
            time_in_force=TimeInForce.GTC,  # Good Till Canceled
        )
        order = client.submit_order(order_data=order_data)
        return _format_order(order)
    except Exception as e:
        return {'error': str(e), 'symbol': symbol}


def place_bracket_order(
    symbol: str,
    qty: float,
    side: str = 'buy',
    take_profit: float = None,
    stop_loss: float = None,
    paper=True,
) -> dict:
    """
    括號單（自帶止盈止損）

    Args:
        symbol: 股票代號
        qty: 數量
        take_profit: 止盈價
        stop_loss: 止損價
    """
    client = get_client(paper)
    if not client:
        return {'error': 'API Key 未設定'}

    try:
        order_data = MarketOrderRequest(
            symbol=symbol.upper(),
            qty=qty,
            side=OrderSide.BUY if side == 'buy' else OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            order_class='bracket' if (take_profit and stop_loss) else 'simple',
            take_profit={'limit_price': round(take_profit, 2)} if take_profit else None,
            stop_loss={'stop_price': round(stop_loss, 2)} if stop_loss else None,
        )
        order = client.submit_order(order_data=order_data)
        return _format_order(order)
    except Exception as e:
        return {'error': str(e), 'symbol': symbol}


# ══════════════════════════════════════════════════════════
# 訂單管理
# ══════════════════════════════════════════════════════════


def get_orders(status: str = 'open', limit: int = 20, paper=True) -> list:
    """
    取得訂單列表

    Args:
        status: 'open', 'closed', 'all'
        limit: 最多幾筆
    """
    client = get_client(paper)
    if not client:
        return []

    try:
        status_map = {
            'open': QueryOrderStatus.OPEN,
            'closed': QueryOrderStatus.CLOSED,
            'all': QueryOrderStatus.ALL,
        }
        request = GetOrdersRequest(
            status=status_map.get(status, QueryOrderStatus.OPEN),
            limit=limit,
        )
        orders = client.get_orders(filter=request)
        return [_format_order(o) for o in orders]
    except Exception as e:
        print(f'⚠️ 取得訂單失敗: {e}')
        return []


def cancel_order(order_id: str, paper=True) -> dict:
    """取消單一訂單"""
    client = get_client(paper)
    if not client:
        return {'error': 'API Key 未設定'}

    try:
        client.cancel_order_by_id(order_id)
        return {'status': 'cancelled', 'order_id': order_id}
    except Exception as e:
        return {'error': str(e), 'order_id': order_id}


def cancel_all_orders(paper=True) -> dict:
    """取消所有未成交訂單"""
    client = get_client(paper)
    if not client:
        return {'error': 'API Key 未設定'}

    try:
        client.cancel_orders()
        return {'status': 'all_cancelled'}
    except Exception as e:
        return {'error': str(e)}


def close_position(symbol: str, paper=True) -> dict:
    """平倉（賣出全部持股）"""
    client = get_client(paper)
    if not client:
        return {'error': 'API Key 未設定'}

    try:
        client.close_position(symbol.upper())
        return {'status': 'closed', 'symbol': symbol}
    except Exception as e:
        return {'error': str(e), 'symbol': symbol}


# ══════════════════════════════════════════════════════════
# 信號 → 交易 轉換
# ══════════════════════════════════════════════════════════


def signal_to_trade(analysis: dict, max_position_usd: float = 1000, paper=True) -> dict | None:
    """
    將分析信號轉換為交易指令

    決策邏輯：
    - swing score >= 70 且 mid_trend 偏多 → 買入
    - swing score <= -50 或 sell_signal 觸發 → 賣出
    - 其他 → 不動作

    Args:
        analysis: get_stock_analysis() 的結果
        max_position_usd: 單一持倉上限（美元）
        paper: 模擬盤

    Returns:
        交易結果 dict 或 None（不動作）
    """
    symbol = analysis.get('symbol', '')
    price = analysis.get('price', 0)
    swing = analysis.get('swing', {})
    swing_score = swing.get('score', 0)
    mid_trend = analysis.get('mid_trend', {})
    mid_score = mid_trend.get('score', 0)
    status = analysis.get('status', '')

    if not symbol or not price or price <= 0:
        return None

    # 檢查是否已持有
    positions = get_positions(paper)
    held = {p['symbol']: p for p in positions}

    action = None
    reason = ''

    # ── 買入條件 ──
    if symbol not in held:
        if swing_score >= 70 and mid_score >= 50:
            action = 'buy'
            reason = f'強信號: swing={swing_score}, mid={mid_score}'
        elif swing_score >= 50 and mid_score >= 70 and '強勢' in status:
            action = 'buy'
            reason = f'趨勢確認: swing={swing_score}, mid={mid_score}, {status}'

    # ── 賣出條件 ──
    elif symbol in held:
        pos = held[symbol]
        if swing_score <= -50:
            action = 'sell'
            reason = f'弱信號: swing={swing_score}'
        elif pos['unrealized_plpc'] <= -5:  # 虧 5%
            action = 'sell'
            reason = f'止損: 虧損 {pos["unrealized_plpc"]:.1f}%'
        elif pos['unrealized_plpc'] >= 15:  # 賺 15%
            action = 'sell'
            reason = f'止盈: 獲利 {pos["unrealized_plpc"]:.1f}%'

    if not action:
        return None

    # 計算數量
    if action == 'buy':
        qty = max(1, int(max_position_usd / price))
    else:
        qty = held[symbol]['qty']

    # 執行交易
    result = place_market_order(symbol, qty, action, paper)
    result['reason'] = reason
    result['signal_score'] = swing_score

    # 記錄交易日誌
    _log_trade(result)

    return result


# ══════════════════════════════════════════════════════════
# 工具函式
# ══════════════════════════════════════════════════════════


def _format_order(order) -> dict:
    """格式化 Alpaca Order 物件為 dict"""
    return {
        'id': str(order.id),
        'symbol': order.symbol,
        'side': order.side.value if hasattr(order.side, 'value') else str(order.side),
        'qty': float(order.qty) if order.qty else 0,
        'filled_qty': float(order.filled_qty) if order.filled_qty else 0,
        'type': order.type.value if hasattr(order.type, 'value') else str(order.type),
        'status': order.status.value if hasattr(order.status, 'value') else str(order.status),
        'limit_price': float(order.limit_price) if order.limit_price else None,
        'stop_price': float(order.stop_price) if order.stop_price else None,
        'filled_avg_price': float(order.filled_avg_price) if order.filled_avg_price else None,
        'created_at': str(order.created_at),
        'submitted_at': str(order.submitted_at),
    }


_TRADE_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_log.json')


def _log_trade(trade: dict):
    """記錄交易到日誌"""
    try:
        logs = []
        if os.path.exists(_TRADE_LOG_FILE):
            with open(_TRADE_LOG_FILE) as f:
                logs = json.load(f)
        trade['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logs.append(trade)
        # 只保留最近 500 筆
        logs = logs[-500:]
        with open(_TRADE_LOG_FILE, 'w') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'⚠️ 記錄交易日誌失敗: {e}')


def get_trade_log(limit: int = 50) -> list:
    """讀取交易日誌"""
    try:
        if os.path.exists(_TRADE_LOG_FILE):
            with open(_TRADE_LOG_FILE) as f:
                logs = json.load(f)
            return logs[-limit:]
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return []


# ── 測試 ──
if __name__ == '__main__':
    print('=== Alpaca Trading Service ===')
    if ALPACA_PAPER_KEY:
        print('📊 帳戶資訊:')
        info = get_account_info(paper=True)
        for k, v in info.items():
            print(f'  {k}: {v}')

        print('\n📋 持倉:')
        positions = get_positions(paper=True)
        if positions:
            for p in positions:
                print(
                    f'  {p["symbol"]}: {p["qty"]}股 @ ${p["avg_entry"]:.2f} → ${p["current_price"]:.2f} ({p["unrealized_plpc"]:+.1f}%)'
                )
        else:
            print('  （無持倉）')
    else:
        print('⚠️ 請先設定 API Key:')
        print(
            '  python3 -c "from alpaca_service import setup_api_keys; setup_api_keys(\'your_key\', \'your_secret\')"'
        )
