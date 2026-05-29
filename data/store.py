import json
import os
import tempfile
import threading
from datetime import datetime

import numpy as np

from config import DATA_FILE, DEFAULT_STOCKS

# 台股資料檔（與 DATA_FILE 同目錄）
TW_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tw_data.json')

_file_lock = threading.Lock()


class _NumpyEncoder(json.JSONEncoder):
    """Handle numpy types that standard json can't serialize"""

    def default(self, obj):
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def _get_data_file(market='us'):
    """根據市場回傳對應的資料檔路徑"""
    if market == 'tw':
        return TW_DATA_FILE
    return DATA_FILE


def load_data(market='us'):
    data_file = _get_data_file(market)
    if os.path.exists(data_file):
        try:
            with open(data_file) as f:
                return json.load(f)
        except json.JSONDecodeError:
            # Corrupted file — try to recover
            with open(data_file) as f:
                raw = f.read()
            idx = raw.find('"analysis_cache"')
            if idx > 0:
                try:
                    return json.loads(raw[:idx].rstrip().rstrip(',') + '\n}')
                except (json.JSONDecodeError, ValueError):
                    pass  # JSON recovery failed, fall through to defaults
            if market == 'tw':
                return {'watchlist': []}
            return {
                'watchlist': DEFAULT_STOCKS[:],
                'purchased': [],
                'pick_history': [],
            }
    if market == 'tw':
        return {'watchlist': []}
    return {
        'watchlist': DEFAULT_STOCKS[:],
        'purchased': [],
        'pick_history': [],
    }


def save_data(data, market='us'):
    data_file = _get_data_file(market)
    with _file_lock:
        dir_name = os.path.dirname(data_file) or '.'
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.json')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, cls=_NumpyEncoder)
            os.replace(tmp_path, data_file)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # cleanup best-effort
            raise


def get_watchlist(market='us'):
    return load_data(market)['watchlist']


def get_analysis_cache(market='us'):
    """取得所有股票的分析快取"""
    data = load_data(market)
    return data.get('analysis_cache', {})


def save_analysis_cache(symbol, result, market='us'):
    """儲存單一股票的分析結果（含時間戳）"""
    data = load_data(market)
    if 'analysis_cache' not in data:
        data['analysis_cache'] = {}
    data['analysis_cache'][symbol] = {
        'data': result,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    save_data(data, market)


def clear_analysis_cache(symbol=None, market='us'):
    """清除快取：指定 symbol 清單一筆，不指定清全部"""
    data = load_data(market)
    if symbol:
        data.get('analysis_cache', {}).pop(symbol, None)
    else:
        data['analysis_cache'] = {}
    save_data(data, market)


def get_stock_meta(symbol, market='us'):
    """Get stored metadata for a stock (category, tags, description)"""
    data = load_data(market)
    return data.get('stock_meta', {}).get(symbol, {})


def save_stock_meta(symbol, meta, market='us'):
    """Save stock metadata"""
    data = load_data(market)
    if 'stock_meta' not in data:
        data['stock_meta'] = {}
    data['stock_meta'][symbol] = meta
    save_data(data, market)


def get_all_stock_meta(market='us'):
    """Get all stock metadata"""
    data = load_data(market)
    return data.get('stock_meta', {})


# ── 瓶頸股研究資料（runtime 產生，非預設）──────────────────
_BOTTLENECK_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'bottleneck_meta.json',
)


def load_bottleneck():
    """載入瓶頸股研究資料，檔案不存在回空 dict。"""
    if os.path.exists(_BOTTLENECK_FILE):
        try:
            with open(_BOTTLENECK_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_bottleneck(meta):
    """儲存瓶頸股研究資料。"""
    with _file_lock:
        dir_name = os.path.dirname(_BOTTLENECK_FILE) or '.'
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.json')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, _BOTTLENECK_FILE)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
