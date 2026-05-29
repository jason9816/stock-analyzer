"""
策略擴充介面 — clone 此專案的人透過繼承 Strategy 來實作自己的策略。

一個「策略」= 一個 group（對應 config.GROUP_CONFIG 的一筆）+ 一個 run() 方法。
run() 在每次排程觸發時被呼叫，透過 PortfolioTracker 做買/賣（虛擬組合）。

最小範例見 strategy/example_strategy.py。
"""

from abc import ABC, abstractmethod

from strategy.config import logger


class Strategy(ABC):
    """所有策略的基底類別。

    子類別需要：
      - 設定 class 屬性 `group`（對應 GROUP_CONFIG 的 key，如 'G1'）
      - 實作 run(tracker)：執行一個週期（掃描 → 決策 → 透過 tracker 買賣）
    """

    group: str = ''
    name: str = ''

    @abstractmethod
    def run(self, tracker) -> None:
        """執行一次策略週期。透過 tracker.buy()/tracker.sell() 操作虛擬組合。"""
        raise NotImplementedError


def run_strategies(strategies, tracker) -> None:
    """依序執行一組策略；單一策略出錯不影響其他策略。"""
    for strat in strategies:
        try:
            strat.run(tracker)
        except Exception as e:
            logger.error('策略 %s 執行失敗: %s', getattr(strat, 'group', strat), e)
