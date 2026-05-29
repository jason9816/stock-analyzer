"""
strategy — 多群組虛擬投資組合的可擴充策略框架。

公開 API：
  PortfolioTracker          虛擬組合狀態模型（買/賣/持倉/績效/持久化）
  Strategy                  策略基底介面（繼承它寫自己的策略）
  run_strategies            依序執行一組策略
  TechnicalRankingStrategy  範例策略（請替換成你自己的）

範例用法：
    from strategy import PortfolioTracker, run_strategies
    from strategy.example_strategy import TechnicalRankingStrategy

    tracker = PortfolioTracker()
    run_strategies([TechnicalRankingStrategy()], tracker)
"""

from strategy.base import Strategy, run_strategies
from strategy.tracker import PortfolioTracker

__all__ = ['PortfolioTracker', 'Strategy', 'run_strategies']
