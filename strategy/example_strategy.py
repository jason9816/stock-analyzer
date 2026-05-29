"""
範例策略 — 純技術面複合排名（Technical Ranking）。

這是給 clone 者照抄的「樣板」：示範如何繼承 Strategy、用 get_stock_analysis
取得分數、透過 PortfolioTracker 做月度再平衡。**請替換成你自己的策略邏輯。**

策略內容：
  - 每月第一個交易日，掃描 S&P 500 前段，依「複合分數」排名
  - 買入 Top-N（等權重），跌出 Top-(N*2) 時賣出，個股停損
  - 複合分數 = swing×0.3 + mid_trend×0.4 + 20日動量百分位×0.3
"""

import math
from datetime import date, datetime

from core.analysis import get_stock_analysis
from data.provider import get_sp500_symbols
from strategy.base import Strategy
from strategy.config import GROUP_CONFIG, logger
from strategy.helpers import get_current_price, is_first_trading_day_of_month


def composite_score(analysis: dict) -> float | None:
    """複合分數：swing×30% + mid_trend×40% + 20日動量百分位×30%。"""
    swing = analysis.get('swing', {})
    swing_score = swing.get('score', 0) if isinstance(swing, dict) else 0

    mid_trend = analysis.get('mid_trend', {})
    mid_score = mid_trend.get('score', 0) if isinstance(mid_trend, dict) else 0

    closes = analysis.get('closes', [])
    momentum_20d = 0
    if closes and len(closes) >= 21 and closes[-21] > 0:
        momentum_20d = (closes[-1] / closes[-21] - 1) * 100
    momentum_percentile = max(0, min(100, (momentum_20d + 20) / 40 * 100))

    return round(swing_score * 0.3 + mid_score * 0.4 + momentum_percentile * 0.3, 2)


class TechnicalRankingStrategy(Strategy):
    """純技術面複合排名 Top-N，月度再平衡（範例）。"""

    group = 'G1'
    name = '純技術面排名（範例）'

    def __init__(self, scan_limit: int = 150):
        self.scan_limit = scan_limit  # 掃描 S&P 500 前 N 支（控制耗時）

    def run(self, tracker) -> None:
        logger.info('═══ %s 開始 ═══', self.name)
        group = self.group
        config = GROUP_CONFIG[group]
        g = tracker.state['groups'][group]
        positions = g['positions']

        # 1. 停損檢查（每次都執行）
        for sym, pos in list(positions.items()):
            price = get_current_price(sym)
            if price is None:
                continue
            pnl_pct = (price / pos['avg_price'] - 1) * 100
            if pnl_pct <= config['stop_loss_pct']:
                tracker.sell(group, sym, price=price, reason=f'停損 {pnl_pct:.1f}%')

        # 2. 月度再平衡：同月內不重複
        last_rebalance = g.get('last_rebalance')
        if last_rebalance:
            try:
                last_date = datetime.fromisoformat(last_rebalance).date()
                today = date.today()
                if last_date.year == today.year and last_date.month == today.month:
                    logger.info('%s 本月已再平衡，僅做停損', group)
                    return
            except (ValueError, TypeError):
                pass
        if not is_first_trading_day_of_month():
            logger.info('%s 非月初交易日，僅做停損檢查', group)
            return

        # 3. 掃描並排名
        scan_pool = get_sp500_symbols()[: self.scan_limit]
        scored = []
        for i, sym in enumerate(scan_pool):
            try:
                analysis = get_stock_analysis(sym)
                comp = composite_score(analysis)
                if comp is not None:
                    scored.append(
                        {'symbol': sym, 'composite': comp, 'price': analysis.get('price', 0)}
                    )
            except Exception as e:
                logger.debug('%s 分析 %s 失敗: %s', group, sym, e)
        scored.sort(key=lambda x: x['composite'], reverse=True)

        max_pos = config['max_positions']
        top_n = scored[:max_pos]
        keep_symbols = {s['symbol'] for s in scored[: max_pos * 2]}  # 跌出 Top-2N 賣出

        # 4. 賣出跌出排名的持倉
        for sym in list(positions.keys()):
            if sym not in keep_symbols:
                tracker.sell(group, sym, price=get_current_price(sym), reason='跌出排名')

        # 5. 等權重買入 Top-N 中未持有者
        held = set(positions.keys())
        to_buy = [s for s in top_n if s['symbol'] not in held]
        slots = max_pos - len(positions)
        if slots > 0 and to_buy:
            budget = min(g['cash'] / min(len(to_buy), slots), config['allocation'] / max_pos)
            for stock in to_buy[:slots]:
                price = stock['price']
                if price <= 0:
                    continue
                qty = math.floor(budget / price)
                if qty > 0:
                    tracker.buy(
                        group,
                        stock['symbol'],
                        qty,
                        price,
                        reason=f'Top-{max_pos} 排名（複合分 {stock["composite"]:.1f}）',
                    )

        g['last_rebalance'] = datetime.now().isoformat()
        tracker._save_state()
        logger.info('═══ %s 完成：%d 檔持倉 ═══', group, len(positions))
