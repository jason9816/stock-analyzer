"""PortfolioTracker — 虛擬投資組合追蹤器（買/賣/持倉/現金/績效/狀態持久化）。

非真實下單；維護一份 JSON 狀態，供策略透過 buy()/sell() 操作多個群組。
"""

import json
import os
from datetime import datetime

from core.analysis import get_stock_analysis
from services import alpaca as alpaca_service
from strategy.config import ACTIVE_GROUPS, GROUP_CONFIG, STATE_FILE, logger
from strategy.helpers import get_current_price, notify_trade


class PortfolioTracker:
    """
    追蹤 4 個虛擬投資組合於同一 Alpaca 帳戶中
    所有狀態存入 strategy_state.json
    """

    def __init__(self):
        self.state_file = STATE_FILE
        self.groups = list(GROUP_CONFIG.keys())  # 全部 10 組
        self.active_groups = ACTIVE_GROUPS  # 啟用中的組
        self.state = self._load_state()

    # ── 狀態管理 ─────────────────────────────────────────

    def _default_state(self) -> dict:
        """預設初始狀態"""
        return {
            'created_at': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'groups': {
                g: {
                    'cash': GROUP_CONFIG[g]['allocation'],
                    'initial_allocation': GROUP_CONFIG[g]['allocation'],
                    'positions': {},  # {symbol: {qty, avg_price, buy_date, reason, theme, theme_news_count, bottleneck_score}}
                    'trades': [],  # [{action, symbol, qty, price, date, reason, pnl, ...}]
                    'total_realized_pnl': 0.0,
                    'last_scan': None,  # 上次掃描時間
                    'last_rebalance': None,
                    'pending_theme': None,  # G3 用：等待用戶選擇的題材
                    'current_theme': None,  # 當前研究的題材
                }
                for g in self.groups
            },
            'daily_reports': [],
            'weekly_reports': [],
        }

    def _load_state(self) -> dict:
        """從 JSON 載入狀態"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file) as f:
                    state = json.load(f)
                # 確保所有群組都存在
                for g in self.groups:
                    if g not in state.get('groups', {}):
                        default = self._default_state()
                        state.setdefault('groups', {})[g] = default['groups'][g]
                return state
            except (json.JSONDecodeError, Exception) as e:
                logger.warning('狀態檔案損壞，重新初始化: %s', e)
        return self._default_state()

    def _save_state(self):
        """儲存狀態至 JSON"""
        self.state['last_updated'] = datetime.now().isoformat()
        try:
            import tempfile

            dir_name = os.path.dirname(self.state_file) or '.'
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.json')
            with os.fdopen(fd, 'w') as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.state_file)
        except Exception as e:
            logger.error('儲存狀態失敗: %s', e)
            # 嘗試直接寫入
            try:
                with open(self.state_file, 'w') as f:
                    json.dump(self.state, f, indent=2, ensure_ascii=False)
            except Exception as e2:
                logger.error('直接寫入也失敗: %s', e2)

    # ── 交易操作 ─────────────────────────────────────────

    def buy(
        self,
        group: str,
        symbol: str,
        qty: int,
        price: float,
        reason: str,
        theme: str = None,
        theme_news_count: int = 0,
        bottleneck_score: float = None,
        execute: bool = True,
    ) -> dict:
        """
        記錄買入並透過 Alpaca 下單

        Args:
            group: 群組代號
            symbol: 股票代號
            qty: 股數
            price: 目標價格（市價單不保證）
            reason: 買入原因
            theme: 題材（G2/G3/G4）
            theme_news_count: 買入時的題材新聞數量
            bottleneck_score: 瓶頸評分（G4）
            execute: 是否真正下單
        Returns:
            交易結果 dict
        """
        g = self.state['groups'][group]
        cost = qty * price

        # 檢查現金是否足夠
        if cost > g['cash']:
            logger.warning('%s 現金不足: 需 $%.2f，可用 $%.2f', group, cost, g['cash'])
            return {'error': f'現金不足：需 ${cost:.2f}，可用 ${g["cash"]:.2f}'}

        # 檢查持倉數量上限
        max_pos = GROUP_CONFIG[group]['max_positions']
        if len(g['positions']) >= max_pos:
            logger.warning('%s 持倉已滿: %d/%d', group, len(g['positions']), max_pos)
            return {'error': f'持倉已滿：{len(g["positions"])}/{max_pos}'}

        result = {'status': 'pending', 'group': group, 'symbol': symbol, 'qty': qty, 'price': price}

        # 透過 Alpaca 下單
        if execute:
            order = alpaca_service.place_market_order(symbol, qty, 'buy', paper=True)
            if 'error' in order:
                logger.error('%s 買入 %s 下單失敗: %s', group, symbol, order['error'])
                result['error'] = order['error']
                result['status'] = 'error'
                return result
            result['order_id'] = order.get('id', '')
            result['order_status'] = order.get('status', '')
            # 使用實際成交價（如果有）
            if order.get('filled_avg_price'):
                price = order['filled_avg_price']
                cost = qty * price

        # 更新虛擬帳本
        g['cash'] -= cost

        # 如果已有同標的，合併計算均價
        if symbol in g['positions']:
            existing = g['positions'][symbol]
            old_qty = existing['qty']
            old_cost = old_qty * existing['avg_price']
            new_total_qty = old_qty + qty
            existing['avg_price'] = round((old_cost + cost) / new_total_qty, 4)
            existing['qty'] = new_total_qty
        else:
            g['positions'][symbol] = {
                'qty': qty,
                'avg_price': round(price, 4),
                'buy_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'reason': reason,
                'theme': theme,
                'theme_news_count': theme_news_count,
                'bottleneck_score': bottleneck_score,
            }

        # 記錄交易
        trade = {
            'action': 'buy',
            'symbol': symbol,
            'qty': qty,
            'price': round(price, 4),
            'cost': round(cost, 2),
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'reason': reason,
            'theme': theme,
        }
        g['trades'].append(trade)

        self._save_state()

        result['status'] = 'filled'
        result['price'] = round(price, 4)
        result['cost'] = round(cost, 2)
        result['remaining_cash'] = round(g['cash'], 2)

        logger.info('🟢 %s 買入 %s × %d @ $%.2f — %s', group, symbol, qty, price, reason)

        # 通知
        analysis = None
        try:
            analysis = get_stock_analysis(symbol)
        except Exception:
            pass
        stage = analysis.get('mid_trend', {}).get('stage', '') if analysis else ''

        notify_trade(
            group,
            'buy',
            symbol,
            price,
            qty,
            reason,
            theme=theme,
            bottleneck_score=bottleneck_score,
            stage=stage,
        )

        return result

    def sell(
        self,
        group: str,
        symbol: str,
        qty: int = None,
        price: float = None,
        reason: str = '',
        execute: bool = True,
    ) -> dict:
        """
        記錄賣出並透過 Alpaca 下單

        Args:
            group: 群組代號
            symbol: 股票代號
            qty: 股數（None = 全部）
            price: 估計價格
            reason: 賣出原因
            execute: 是否真正下單
        Returns:
            交易結果 dict
        """
        g = self.state['groups'][group]

        if symbol not in g['positions']:
            return {'error': f'{group} 未持有 {symbol}'}

        pos = g['positions'][symbol]
        sell_qty = qty or pos['qty']
        if sell_qty > pos['qty']:
            sell_qty = pos['qty']

        # 取得即時價格
        if price is None:
            price = get_current_price(symbol) or pos['avg_price']

        result = {
            'status': 'pending',
            'group': group,
            'symbol': symbol,
            'qty': sell_qty,
            'price': price,
        }

        # Alpaca 下單
        if execute:
            order = alpaca_service.place_market_order(symbol, sell_qty, 'sell', paper=True)
            if 'error' in order:
                logger.error('%s 賣出 %s 下單失敗: %s', group, symbol, order['error'])
                result['error'] = order['error']
                result['status'] = 'error'
                return result
            result['order_id'] = order.get('id', '')
            result['order_status'] = order.get('status', '')
            if order.get('filled_avg_price'):
                price = order['filled_avg_price']

        # 計算損益
        proceeds = sell_qty * price
        cost_basis = sell_qty * pos['avg_price']
        pnl = proceeds - cost_basis
        pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0

        # 更新虛擬帳本
        g['cash'] += proceeds
        g['total_realized_pnl'] += pnl

        # 更新或移除持倉
        remaining_qty = pos['qty'] - sell_qty
        if remaining_qty <= 0:
            del g['positions'][symbol]
        else:
            pos['qty'] = remaining_qty

        # 記錄交易
        trade = {
            'action': 'sell',
            'symbol': symbol,
            'qty': sell_qty,
            'price': round(price, 4),
            'proceeds': round(proceeds, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'reason': reason,
            'theme': pos.get('theme'),
        }
        g['trades'].append(trade)

        self._save_state()

        result['status'] = 'filled'
        result['price'] = round(price, 4)
        result['proceeds'] = round(proceeds, 2)
        result['pnl'] = round(pnl, 2)
        result['pnl_pct'] = round(pnl_pct, 2)

        pnl_str = f'+${pnl:.2f}' if pnl >= 0 else f'-${abs(pnl):.2f}'
        logger.info(
            '🔴 %s 賣出 %s × %d @ $%.2f — %s (%s, %.1f%%)',
            group,
            symbol,
            sell_qty,
            price,
            reason,
            pnl_str,
            pnl_pct,
        )

        notify_trade(
            group,
            'sell',
            symbol,
            price,
            sell_qty,
            f'{reason} | 損益 {pnl_str} ({pnl_pct:+.1f}%)',
            theme=pos.get('theme'),
        )

        return result

    # ── 查詢 ─────────────────────────────────────────────

    # ── Candidates 管理 ──

    def add_candidates(self, group: str, candidates: list):
        """新增候選股到指定群組的追蹤清單
        candidates: [{'symbol': 'POWL', 'score': 4.4, 'theme': '...', ...}]
        """
        g = self.state['groups'][group]
        if 'candidates' not in g:
            g['candidates'] = []

        existing = {c['symbol'] for c in g['candidates']}
        added = []
        for c in candidates:
            sym = c.get('symbol', '')
            if not sym or sym in existing:
                continue
            c.setdefault('date', datetime.now().strftime('%Y-%m-%d'))
            c.setdefault('status', 'watching')  # watching / bought / removed
            g['candidates'].append(c)
            existing.add(sym)
            added.append(sym)

        if added:
            self._save_state()
        return added

    def get_candidates(self, group: str) -> list:
        """取得指定群組的候選股清單"""
        return self.state['groups'][group].get('candidates', [])

    def remove_candidate(self, group: str, symbol: str):
        """從候選清單移除"""
        g = self.state['groups'][group]
        g['candidates'] = [c for c in g.get('candidates', []) if c['symbol'] != symbol]
        self._save_state()

    def get_all_strategy_data(self) -> dict:
        """取得所有策略群組的完整資料（供 API 用）"""
        result = {}
        for group in ACTIVE_GROUPS:
            perf = self.get_performance(group)
            result[group] = {
                'name': GROUP_CONFIG[group]['name'],
                'config': {
                    'allocation': GROUP_CONFIG[group]['allocation'],
                    'max_positions': GROUP_CONFIG[group]['max_positions'],
                    'stop_loss_pct': GROUP_CONFIG[group]['stop_loss_pct'],
                },
                'performance': perf,
                'candidates': self.get_candidates(group),
                'trades': self.state['groups'][group].get('trades', [])[-20:],
            }
        return result

    # ── 基本查詢 ──

    def get_positions(self, group: str) -> dict:
        """取得指定群組的持倉"""
        return self.state['groups'][group]['positions']

    def get_cash(self, group: str) -> float:
        """取得指定群組的可用現金"""
        return self.state['groups'][group]['cash']

    def get_performance(self, group: str) -> dict:
        """
        計算指定群組的績效

        Returns:
            {
                'total_value': float,        # 帳面總值（現金 + 持倉市值）
                'cash': float,
                'positions_value': float,     # 持倉市值
                'unrealized_pnl': float,      # 未實現損益
                'realized_pnl': float,        # 已實現損益
                'total_pnl': float,           # 總損益
                'total_pnl_pct': float,       # 總報酬率
                'num_positions': int,
                'positions': dict,
            }
        """
        g = self.state['groups'][group]
        positions_value = 0
        unrealized_pnl = 0
        positions_detail = {}

        for sym, pos in g['positions'].items():
            current_price = get_current_price(sym) or pos['avg_price']
            market_value = pos['qty'] * current_price
            cost_basis = pos['qty'] * pos['avg_price']
            pnl = market_value - cost_basis
            pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0

            positions_value += market_value
            unrealized_pnl += pnl

            positions_detail[sym] = {
                'qty': pos['qty'],
                'avg_price': pos['avg_price'],
                'current_price': round(current_price, 2),
                'market_value': round(market_value, 2),
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 2),
                'buy_date': pos.get('buy_date', ''),
                'theme': pos.get('theme', ''),
            }

        total_value = g['cash'] + positions_value
        initial = g['initial_allocation']
        total_pnl = total_value - initial
        total_pnl_pct = (total_pnl / initial * 100) if initial > 0 else 0

        return {
            'group': group,
            'name': GROUP_CONFIG[group]['name'],
            'total_value': round(total_value, 2),
            'cash': round(g['cash'], 2),
            'positions_value': round(positions_value, 2),
            'unrealized_pnl': round(unrealized_pnl, 2),
            'realized_pnl': round(g['total_realized_pnl'], 2),
            'total_pnl': round(total_pnl, 2),
            'total_pnl_pct': round(total_pnl_pct, 2),
            'num_positions': len(g['positions']),
            'positions': positions_detail,
        }

    def generate_report(self) -> str:
        """
        生成所有群組的績效報告

        Returns:
            報告文字
        """
        lines = ['═══ 多策略交易引擎績效報告 ═══', '']
        total_value = 0
        total_pnl = 0

        for g in self.groups:
            perf = self.get_performance(g)
            total_value += perf['total_value']
            total_pnl += perf['total_pnl']

            pnl_emoji = '📈' if perf['total_pnl'] >= 0 else '📉'
            lines.append(
                f'{pnl_emoji} {g} {GROUP_CONFIG[g]["name"]}：'
                f'${perf["total_value"]:,.0f} '
                f'({perf["total_pnl_pct"]:+.1f}%) '
                f'持倉 {perf["num_positions"]} 檔'
            )

            for sym, detail in perf['positions'].items():
                lines.append(
                    f'  ├ {sym}: {detail["qty"]}股 '
                    f'@ ${detail["avg_price"]:.2f} → ${detail["current_price"]:.2f} '
                    f'({detail["pnl_pct"]:+.1f}%)'
                )
            if not perf['positions']:
                lines.append('  └ （無持倉）')
            lines.append(f'  └ 現金: ${perf["cash"]:,.0f}')
            lines.append('')

        initial_total = sum(GROUP_CONFIG[g]['allocation'] for g in self.groups)
        total_pnl_pct = (total_pnl / initial_total * 100) if initial_total > 0 else 0

        lines.append(f'💰 總計: ${total_value:,.0f} ({total_pnl_pct:+.1f}%)')
        lines.append(f'📅 更新: {datetime.now().strftime("%Y-%m-%d %H:%M")}')

        return '\n'.join(lines)
