"""
core.signals package — split from monolithic signals.py

Re-exports all public functions for backward compatibility.
Existing `from core.signals import X` continues to work.
"""

from .breakout import (
    calc_levels,
    calc_prebreakout_score,
)
from .chip import (
    calc_analyst_revision_score,
    calc_chip_score,
    calc_insider_score,
    chip_label,
)
from .pattern import calc_candle_pattern
from .swing import (
    calc_signal_confidence,
    calc_swing_signal,
    detect_signal_conflicts,
    get_market_regime,
)
from .trend import (
    _check_minervini_template,
    _detect_weinstein_stage,
    calc_mid_trend,
)

__all__ = [
    'get_market_regime',
    'detect_signal_conflicts',
    'calc_signal_confidence',
    'calc_swing_signal',
    'calc_candle_pattern',
    'calc_chip_score',
    'chip_label',
    'calc_insider_score',
    'calc_analyst_revision_score',
    'calc_mid_trend',
    '_detect_weinstein_stage',
    '_check_minervini_template',
    'calc_prebreakout_score',
    'calc_levels',
]
