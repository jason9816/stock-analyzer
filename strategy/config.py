"""
策略引擎共用設定 — logger、狀態檔路徑、群組配置範本。

GROUP_CONFIG 是「範本」：clone 此專案的人可在此定義自己的交易群組，
每組對應一個策略（見 strategy/base.py 的 Strategy 介面與 example_strategy.py）。
預設只附一個範例組 G1，請依需求增刪。
"""

import logging
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 投資組合狀態持久化檔（虛擬組合，非真實下單）
STATE_FILE = os.path.join(_PROJECT_ROOT, 'strategy_state.json')

logger = logging.getLogger('strategy')
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            '%(asctime)s [Strategy] %(levelname)s  %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# ── 群組配置範本 ──
# 每個群組是一筆獨立的虛擬資金 + 一個策略。新增群組：在此加一筆，
# 再寫一個對應的 Strategy 子類（group 屬性設成同一個 key）並註冊到 runner。
GROUP_CONFIG = {
    'G1': {
        'name': '純技術面排名（範例）',
        'allocation': 10000,  # 該組初始虛擬資金（美元）
        'max_positions': 4,  # 最大持倉檔數
        'scan_freq': 'daily',
        'stop_loss_pct': -15.0,  # 個股停損門檻（%）
        'notify': False,  # 是否發 Telegram 通知
        'min_swing': 20,  # 範例策略用的進場門檻
        'min_trend': 50,
        'active': True,
    },
    # 範例：要新增自己的群組，照上面格式加一筆，例如
    # 'G2': {'name': '我的題材策略', 'allocation': 10000, 'max_positions': 3,
    #        'scan_freq': 'daily', 'stop_loss_pct': -12.0, 'notify': True, 'active': True},
}

# 啟用中的群組
ACTIVE_GROUPS = [g for g, c in GROUP_CONFIG.items() if c.get('active')]
