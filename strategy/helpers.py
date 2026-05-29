"""策略共用工具 — Telegram 交易通知 + 市場時間/報價 helpers。"""

from datetime import datetime

from data.provider import get_ticker
from services.telegram import send_message as send_telegram
from strategy.config import GROUP_CONFIG


def notify_trade(
    group: str,
    action: str,
    symbol: str,
    price: float,
    qty: int,
    reason: str,
    theme: str = None,
    bottleneck_score: float = None,
    stage: str = None,
):
    """
    發送交易通知至 Telegram（G2/G3/G4）

    Args:
        group: 群組代號 (G1~G4)
        action: 'buy' 或 'sell'
        symbol: 股票代號
        price: 成交價
        qty: 數量
        reason: 交易原因
        theme: 題材名稱
        bottleneck_score: 瓶頸分數
        stage: 技術面階段（Stage 2 等）
    """
    config = GROUP_CONFIG.get(group, {})
    if not config.get('notify', False):
        return

    emoji = '📈' if action == 'buy' else '📉'
    action_zh = '買入' if action == 'buy' else '賣出'

    lines = [f'{emoji} {group} {action_zh} {symbol} ${price:.2f} x {qty}股']

    if theme:
        lines.append(f'題材：{theme}')
    if bottleneck_score is not None:
        stage_str = f' | 技術：{stage}' if stage else ''
        lines.append(f'瓶頸分：{bottleneck_score:.1f}{stage_str}')
    lines.append(f'原因：{reason}')

    if action == 'buy':
        lines.append(f'想跟單？在你的券商買入 {symbol}')

    send_telegram('\n'.join(lines))


def notify_sell_analysis(
    group: str,
    symbol: str,
    price: float,
    pnl_pct: float,
    theme_status: str,
    technical_status: str,
    decision: str,
):
    """
    發送賣出前分析通知

    Args:
        group: 群組代號
        symbol: 股票代號
        price: 當前價格
        pnl_pct: 損益百分比
        theme_status: 題材狀態描述
        technical_status: 技術面狀態描述
        decision: 最終決定
    """
    pnl_emoji = '+' if pnl_pct >= 0 else ''
    lines = [
        f'📉 {group} 準備賣出 {symbol} {pnl_emoji}{pnl_pct:.1f}%',
        f'題材狀態：{theme_status}',
        f'技術面：{technical_status}',
        f'決定：{decision}',
    ]
    send_telegram('\n'.join(lines))


# ══════════════════════════════════════════════════════════════════════════════
# 工具函式
# ══════════════════════════════════════════════════════════════════════════════


def is_market_hours() -> bool:
    """檢查是否為美股交易時段（ET 09:30-16:00）"""
    from zoneinfo import ZoneInfo

    now_et = datetime.now(ZoneInfo('America/New_York'))
    # 週末不交易
    if now_et.weekday() >= 5:
        return False
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et <= market_close


def is_first_trading_day_of_month() -> bool:
    """檢查是否為本月第一個交易日"""
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo('America/New_York'))
    today = now.date()
    # 簡化判斷：月初前 3 天內的工作日
    return today.day <= 3 and today.weekday() < 5


def get_current_price(symbol: str) -> float | None:
    """取得股票即時價格"""
    try:
        ticker = get_ticker(symbol)
        info = ticker.info
        price = info.get('currentPrice') or info.get('regularMarketPrice')
        return float(price) if price else None
    except Exception:
        return None
