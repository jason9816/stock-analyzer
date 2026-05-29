"""
共用錯誤處理 — 取代散落各處的 bare except。

提供兩種用法：
  @safe(default=0)       — 裝飾器，函數出錯時回傳預設值並 log
  try_or(fn, default=0)  — 一次性 safe call

設計原則：
  1. 只捕 Exception，不吞 KeyboardInterrupt / SystemExit
  2. 一律寫 log（至少 debug），不做 silent pass
  3. default 可以是 callable（每次產生新 instance）
"""

import functools
import logging

logger = logging.getLogger('stock_analyzer')


def _resolve_default(default):
    """若 default 是 callable 就呼叫（避免 mutable default 共用）"""
    return default() if callable(default) else default


def safe(default=None, *, log_level='debug', context=''):
    """
    裝飾器：函數拋 Exception 時回傳 default 並 log。

    用法::

        @safe(default=0.0, context='計算 RSI')
        def calc_rsi(series): ...

        @safe(default=dict)
        def get_info(symbol): ...
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                ctx = context or func.__qualname__
                getattr(logger, log_level)('%s 失敗: %s', ctx, e)
                return _resolve_default(default)

        return wrapper

    return decorator


def try_or(func, *args, default=None, context='', log_level='debug', **kwargs):
    """
    一次性 safe call，不用裝飾器。

    用法::

        price = try_or(lambda: yf.Ticker(s).info['currentPrice'], default=0)
        data  = try_or(json.loads, text, default={}, context='解析 JSON')
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        ctx = context or getattr(func, '__qualname__', 'unknown')
        getattr(logger, log_level)('%s 失敗: %s', ctx, e)
        return _resolve_default(default)
