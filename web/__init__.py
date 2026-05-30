"""
Flask 應用工廠 —— 依 config.FEATURE_FLAGS 條件註冊 blueprint。

關閉某功能（如 ENABLE_TRADING=false）時，對應 blueprint 完全不註冊，
該網址回 404，前端導航列也會隱藏連結。
"""

import os

from flask import Flask

from config import FEATURE_FLAGS


def create_app():
    flags = FEATURE_FLAGS
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
        static_folder=os.path.join(os.path.dirname(__file__), 'static'),
    )

    # 把功能開關傳進所有模板（導航列用 {% if flags.TRADING %}）
    @app.context_processor
    def inject_flags():
        return {'flags': flags}

    # 市場首頁（美股 / 台股任一開啟就註冊；blueprint 內各路由仍以市場區分）
    if flags['US_MARKET'] or flags['TW_MARKET']:
        from web.blueprints.market import bp as market_bp

        app.register_blueprint(market_bp)

    if flags['AI_ANALYSIS']:
        from web.blueprints.ai_summary import bp as ai_bp

        app.register_blueprint(ai_bp)

    if flags['TRADING']:
        from web.blueprints.trading import bp as trading_bp

        app.register_blueprint(trading_bp)

    if flags['STRATEGY']:
        from web.blueprints.strategy import bp as strategy_bp

        app.register_blueprint(strategy_bp)

    if flags['AI_CHAT']:
        from web.blueprints.chat import bp as chat_bp

        app.register_blueprint(chat_bp)

    if flags['BG_WORKERS']:
        from web.blueprints.workers_api import bp as workers_bp

        app.register_blueprint(workers_bp)

    return app
