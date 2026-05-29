from datetime import datetime

import numpy as np

from core.indicators import (
    calc_adx,
    calc_atr,
    calc_bollinger,
    calc_kd,
    calc_macd,
    calc_mfi,
    calc_obv,
    calc_rsi,
    calc_vwap,
    get_options_pcr,
    safe,
)
from core.signals import (
    calc_analyst_revision_score,
    calc_chip_score,
    calc_insider_score,
    calc_levels,
    calc_mid_trend,
    calc_swing_signal,
    chip_label,
)
from data.provider import get_history, get_ticker

# ── 槓桿 ETF 對照表（只有本模組使用）──────────────────────
LEVERAGE_ETF = {
    'NVDA': {'etf': 'NVDL', 'mult': '2x', 'name': 'GraniteShares 2x Long NVDA'},
    'TSLA': {'etf': 'TSLL', 'mult': '2x', 'name': 'Direxion 2x Bull TSLA'},
    'AMD': {'etf': 'AMDU', 'mult': '2x', 'name': 'Direxion 2x Bull AMD'},
    'MSFT': {'etf': 'MSFU', 'mult': '2x', 'name': 'Direxion 2x Bull MSFT'},
    'META': {'etf': 'METU', 'mult': '2x', 'name': 'Direxion 2x Bull META'},
    'GOOGL': {'etf': 'GOOL', 'mult': '2x', 'name': 'T-Rex 2x Long GOOGL'},
    'AMZN': {'etf': 'AMZU', 'mult': '2x', 'name': 'Direxion 2x Bull AMZN'},
    'AAPL': {'etf': 'AAPU', 'mult': '2x', 'name': 'Direxion 2x Bull AAPL'},
    'QQQ': {'etf': 'QLD', 'mult': '2x', 'name': 'ProShares Ultra QQQ'},
    'SPY': {'etf': 'SSO', 'mult': '2x', 'name': 'ProShares Ultra S&P500'},
    'SOXX': {'etf': 'SOXL', 'mult': '3x', 'name': 'Direxion 3x Bull Semiconductor'},
}


# ── main analysis ────────────────────────────────────────
def get_stock_analysis(symbol):
    print(f"正在分析 {symbol}...")
    ticker = get_ticker(symbol)
    info = ticker.info

    hist = ticker.history(period="1y")
    hist.index = hist.index.strftime('%Y-%m-%d')
    hist['MA5'] = hist['Close'].rolling(5).mean()
    hist['MA10'] = hist['Close'].rolling(10).mean()
    hist['MA20'] = hist['Close'].rolling(20).mean()
    hist['MA60'] = hist['Close'].rolling(60).mean()
    hist['RSI'] = calc_rsi(hist['Close'])
    macd_line, signal_line, macd_hist = calc_macd(hist['Close'])
    hist['MACD'] = macd_line
    hist['MACD_signal'] = signal_line
    hist['MACD_hist'] = macd_hist
    bb_up, bb_mid, bb_low = calc_bollinger(hist['Close'])
    hist['BB_upper'] = bb_up
    hist['BB_mid'] = bb_mid
    hist['BB_lower'] = bb_low
    kd_k, kd_d = calc_kd(hist['High'], hist['Low'], hist['Close'])
    hist['KD_K'] = kd_k
    hist['KD_D'] = kd_d
    hist['ATR'] = calc_atr(hist['High'], hist['Low'], hist['Close'])
    hist['OBV'] = calc_obv(hist['Close'], hist['Volume'])
    adx, di_plus, di_minus = calc_adx(hist['High'], hist['Low'], hist['Close'])
    hist['ADX'] = adx
    hist['DI_plus'] = di_plus
    hist['DI_minus'] = di_minus
    hist['MFI'] = calc_mfi(hist['High'], hist['Low'], hist['Close'], hist['Volume'])
    hist['VWAP'] = calc_vwap(hist['High'], hist['Low'], hist['Close'], hist['Volume'])

    # ── 中期趨勢計算 ──
    from core.indicators import get_index_history

    index_hist = get_index_history('^GSPC')  # S&P500，帶快取
    mid = calc_mid_trend(
        hist,
        index_hist=index_hist,
        w52h=info.get('fiftyTwoWeekHigh'),
        w52l=info.get('fiftyTwoWeekLow'),
    )

    # VIX 當前值（餵給 swing 的市場體制 gate；抓不到則 regime=unknown 不影響分數）
    vix_now = None
    try:
        vix_hist = get_index_history('^VIX')
        if vix_hist is not None and len(vix_hist) > 0:
            vix_now = float(vix_hist['Close'].iloc[-1])
    except Exception:
        vix_now = None

    cp = hist['Close'].iloc[-1]
    prev = hist['Close'].iloc[-2]
    chg = round(cp - prev, 2)
    chg_pct = round(chg / prev * 100, 2)

    # Levels
    levels = calc_levels(hist, cp)
    pressures = sorted([l for l in levels if l['kind'] == 'P'], key=lambda x: x['price'])
    supports = sorted(
        [l for l in levels if l['kind'] == 'S'], key=lambda x: -x['price']
    )  # descending (nearest first)

    nearest_p = pressures[0]['price'] if pressures else round(cp * 1.05, 2)
    nearest_s = supports[0]['price'] if supports else round(cp * 0.95, 2)

    # Financial
    q_labels, rev, gm, nm = [], [], [], []
    try:
        fin = ticker.quarterly_financials
        cols = fin.columns[:4][::-1]
        q_labels = [d.strftime('%Y Q') + str((d.month - 1) // 3 + 1) for d in cols]
        rev = [round(fin.loc['Total Revenue'][d] / 1e9, 2) for d in cols]
        gm = [
            round(fin.loc['Gross Profit'][d] / fin.loc['Total Revenue'][d] * 100, 1) for d in cols
        ]
        try:
            nm = [
                round(fin.loc['Net Income'][d] / fin.loc['Total Revenue'][d] * 100, 1) for d in cols
            ]
        except Exception:
            pass
    except Exception:
        pass

    # Chip
    inst_own = round(info.get('heldPercentInstitutions', 0) * 100, 2)
    insider_own = round(info.get('heldPercentInsiders', 0) * 100, 2)
    short_ratio = round(info.get('shortRatio', 0), 2)
    short_pct = round(info.get('shortPercentOfFloat', 0) * 100, 2)
    beta = round(info.get('beta', 0), 2)
    pcr = get_options_pcr(symbol)
    # 內部人交易分析
    mkt_cap_raw = info.get('marketCap', 0)
    insider_sc, insider_note = calc_insider_score(ticker, market_cap=mkt_cap_raw)
    # 分析師 EPS Revision 動量
    analyst_sc, analyst_note = calc_analyst_revision_score(ticker)
    # RSI/MACD 用於軋空偵測
    _rsi_for_chip = hist['RSI'].iloc[-1] if not np.isnan(hist['RSI'].iloc[-1]) else 50
    _macd_h_for_chip = hist['MACD_hist'].iloc[-1] if not np.isnan(hist['MACD_hist'].iloc[-1]) else 0
    chip_score, chip_details, squeeze_flag = calc_chip_score(
        inst_own,
        short_pct,
        pcr,
        beta,
        short_ratio=short_ratio,
        rsi=_rsi_for_chip,
        macd_hist_val=_macd_h_for_chip,
        insider_score=insider_sc,
        analyst_score=analyst_sc,
    )
    chip_lbl, chip_color = chip_label(chip_score, squeeze_flag)

    # Valuation
    pe = safe(lambda: round(info['trailingPE'], 2), 'N/A')
    fwd_pe = safe(lambda: round(info['forwardPE'], 2), 'N/A')
    pb = safe(lambda: round(info['priceToBook'], 2), 'N/A')
    div_yield = safe(
        lambda: round(info['dividendYield'] * 100, 2) if info.get('dividendYield') else 0, 0
    )
    mkt_cap = info.get('marketCap', 0)
    mkt_cap_str = (
        f"{mkt_cap / 1e12:.2f}T"
        if mkt_cap >= 1e12
        else f"{mkt_cap / 1e9:.1f}B"
        if mkt_cap >= 1e9
        else f"{mkt_cap / 1e6:.0f}M"
    )
    w52h = round(info.get('fiftyTwoWeekHigh', 0), 2)
    w52l = round(info.get('fiftyTwoWeekLow', 0), 2)
    w52_pos = round((cp - w52l) / (w52h - w52l) * 100, 1) if w52h > w52l else 50

    # Technicals
    rsi_val = round(hist['RSI'].iloc[-1], 1) if not np.isnan(hist['RSI'].iloc[-1]) else 'N/A'
    macd_val = round(hist['MACD'].iloc[-1], 2)
    macd_sig = round(hist['MACD_signal'].iloc[-1], 2)
    macd_hist_val = round(hist['MACD_hist'].iloc[-1], 2)
    macd_cross = "金叉（多）" if macd_val > macd_sig else "死叉（空）"

    ma5v = hist['MA5'].iloc[-1]
    ma10v = hist['MA10'].iloc[-1]
    ma20v = hist['MA20'].iloc[-1]

    # Volume analysis
    vol_5 = hist['Volume'].tail(5).mean()
    vol_20 = hist['Volume'].tail(20).mean()
    vol_ratio = round(vol_5 / vol_20, 2) if vol_20 > 0 else 1
    vol_trend = "放量" if vol_ratio > 1.3 else "縮量" if vol_ratio < 0.7 else "量能正常"

    # ── 分析師評等 ──
    target_high = safe(lambda: round(info['targetHighPrice'], 2), None)
    target_low = safe(lambda: round(info['targetLowPrice'], 2), None)
    target_mean = safe(lambda: round(info['targetMeanPrice'], 2), None)
    target_median = safe(lambda: round(info['targetMedianPrice'], 2), None)
    recommend_key = info.get('recommendationKey', 'N/A')
    num_analysts = info.get('numberOfAnalystOpinions', 0)
    target_upside = round((target_mean / cp - 1) * 100, 1) if target_mean else None

    rec_summary = {}
    try:
        recs = ticker.recommendations
        if recs is not None and len(recs) > 0:
            latest = recs.iloc[-1]
            for col in ['strongBuy', 'buy', 'hold', 'sell', 'strongSell']:
                if col in latest.index:
                    rec_summary[col] = int(latest[col])
    except Exception:
        pass

    # ── 財報日期 ──
    next_earnings = None
    try:
        cal = ticker.calendar
        if cal is not None:
            if isinstance(cal, dict):
                ed = cal.get('Earnings Date', [])
                if ed:
                    next_earnings = (
                        str(ed[0])[:10] if hasattr(ed[0], 'strftime') else str(ed[0])[:10]
                    )
            elif hasattr(cal, 'loc'):
                ed = cal.loc['Earnings Date'] if 'Earnings Date' in cal.index else None
                if ed is not None:
                    next_earnings = str(ed.iloc[0])[:10] if hasattr(ed, 'iloc') else str(ed)[:10]
    except Exception:
        pass
    earnings_days = None
    if next_earnings:
        try:
            ed = datetime.strptime(next_earnings, '%Y-%m-%d')
            earnings_days = (ed - datetime.now()).days
        except Exception:
            pass

    # ── 趨勢判斷（使用中期趨勢分數）──
    mid_score = mid['score']
    if mid_score >= 60:
        status = f"🔥 中線強勢（{mid['stage']}）"
        status_color = "#22c55e"
        status_bg = "#14532d"
        tag_summary = f"中線強勢 {mid_score}分"
    elif mid_score >= 30:
        status = f"📈 中線偏多（{mid['stage']}）"
        status_color = "#4ade80"
        status_bg = "#14532d"
        tag_summary = f"中線偏多 {mid_score}分"
    elif mid_score >= 10:
        if cp > ma5v > ma10v > ma20v:
            status = "⚡ 短線強勢、中線觀望"
            status_color = "#fbbf24"
            status_bg = "#713f12"
            tag_summary = "短多中觀望"
        else:
            status = f"⚡ 中線觀望（{mid['stage']}）"
            status_color = "#fbbf24"
            status_bg = "#713f12"
            tag_summary = "中線觀望"
    elif mid_score >= -10:
        status = f"⚡ 盤整觀望（{mid['stage']}）"
        status_color = "#fbbf24"
        status_bg = "#713f12"
        tag_summary = "方向不明"
    elif mid_score >= -30:
        status = f"🔻 中線偏空（{mid['stage']}）"
        status_color = "#f87171"
        status_bg = "#7f1d1d"
        tag_summary = "中線偏空"
    else:
        status = f"🔻 中線空頭（{mid['stage']}）"
        status_color = "#f87171"
        status_bg = "#7f1d1d"
        tag_summary = "中線空頭"

    # Build advice
    def fmt(v):
        return f"${v:,.2f}" if isinstance(v, float) else f"${v}"

    # 確保 nearest_p > 現價, nearest_s < 現價，否則用百分比推算
    if nearest_p <= cp:
        nearest_p = round(cp * 1.05, 2)  # 預設 +5%
    if nearest_s >= cp:
        nearest_s = round(cp * 0.95, 2)  # 預設 -5%
    # 第二壓力位
    p2 = (
        pressures[1]['price']
        if len(pressures) > 1 and pressures[1]['price'] > cp
        else round(cp * 1.10, 2)
    )

    # ── 混合策略：短線進場 + 中線持有 ──
    # 停利目標拉到第二壓力位（中線持有），停損以 MA20 為基準
    mid_tp = max(p2, round(cp * 1.10, 2))  # 中線停利：第二壓力位或 +10%

    if "偏多" in status and "整理" not in status:
        aggressive = f"🔥 多頭排列確認！均線 MA5 > MA10 > MA20，趨勢明確向上。【短線進場點】回檔至 MA5({fmt(round(ma5v, 2))}) 附近分批買進。【中線目標】第一目標 {fmt(nearest_p)}（近壓力），不急賣；持有看第二目標 {fmt(mid_tp)}。"
        conservative = f"等待回測 MA10({fmt(round(ma10v, 2))}) 不破後的紅K確認再進場。或等突破 {fmt(nearest_p)} 後追買，以中線持有為目標。"
        risk = f"RSI {'已達 ' + str(rsi_val) + '，短線有過熱風險，可先買一半倉位，回檔再加碼' if isinstance(rsi_val, (int, float)) and rsi_val > 65 else '正常'}。{vol_trend}{'，量價配合良好，適合持有' if vol_trend == '放量' else '，注意上漲無量可能為假突破，先輕倉' if vol_trend == '縮量' else ''}。"
        stop_loss = round(max(ma20v * 0.98, cp * 0.88), 2)  # 中線停損：MA20 下方 2% 或不低於 -12%
        take_profit = mid_tp
        sell_signal = f"⚠️ 出場信號：① 收盤跌破 MA20({fmt(round(ma20v, 2))}) → 減半倉 ② 短線信號轉🔴且 MACD 死叉確認 → 全部出場 ③ 到達 {fmt(mid_tp)} 可先賣一半鎖利"
    elif "整理" in status and "偏多" in status:
        aggressive = f"⚡ 回檔整理中，中線趨勢未破壞（仍在 MA20 上方）。【短線進場點】在 {fmt(nearest_s)}（支撐位）附近輕倉買進，站回 MA5({fmt(round(ma5v, 2))}) 再加碼。【中線目標】{fmt(mid_tp)}。"
        conservative = f"等待 K 線站回 MA5({fmt(round(ma5v, 2))}) 以上且成交量放大，確認回檔結束再進場，以中線持有為目標。"
        risk = f"若跌破 MA20({fmt(round(ma20v, 2))})，中線轉空，需嚴格停損。MACD 目前{macd_cross}，{'柱狀體轉正中，回檔可能結束' if macd_hist_val > 0 else '柱狀體為負，可能繼續整理，耐心等待'}。"
        stop_loss = round(max(ma20v * 0.97, cp * 0.88), 2)
        take_profit = mid_tp
        sell_signal = f"⚠️ 出場信號：① 收盤跌破 MA20({fmt(round(ma20v, 2))}) → 停損出場 ② MACD 柱狀體持續擴大為負 → 減倉 ③ 回到 MA5 上方後再觀察是否續漲"
    elif "偏空" in status:
        tp_target = max(round(ma10v, 2), round(cp * 1.03, 2))
        aggressive = f"🔻 空頭排列，不建議中線持有。若要搶反彈，僅在 {fmt(nearest_s)}（強支撐位）出現止跌長下影線時極短線操作，目標 {fmt(tp_target)}（MA10 附近），嚴格停損 {fmt(round(nearest_s * 0.97, 2))}。這是短打，不要戀棧。"
        conservative = f"空手觀望，等待價格站回 MA20({fmt(round(ma20v, 2))}) 以上，且 MACD 金叉確認趨勢反轉後再考慮中線佈局。目前不適合持有。"
        risk = f"均線空頭排列壓力沉重，每根均線都是反彈的壓力。空單比例 {short_pct}%{'，若偏高可能觸發軋空反彈，但不改變空頭趨勢' if short_pct > 8 else ''}。下方支撐 {fmt(nearest_s)}，跌破恐加速下跌。"
        stop_loss = round(nearest_s * 0.97, 2)
        take_profit = tp_target
        sell_signal = f"⚠️ 空頭走勢中不建議持有。若搶反彈進場，碰到 MA10({fmt(round(ma10v, 2))}) 就要出場，不要幻想反轉。"
    else:
        aggressive = f"盤整格局，短線可在 {fmt(nearest_s)} 附近低買，但不要重倉。突破 {fmt(nearest_p)} 後可加碼轉中線持有，目標 {fmt(mid_tp)}。"
        conservative = f"方向不明確，建議觀望。等待突破 {fmt(nearest_p)} 後順勢買進並中線持有，或跌破 {fmt(nearest_s)} 後離場觀望。"
        risk = f"盤整期間假突破頻繁，注意設好停損。MACD {macd_cross}，可作為方向參考。突破方向確認前輕倉為宜。"
        stop_loss = round(nearest_s * 0.97, 2)
        take_profit = nearest_p
        sell_signal = f"⚠️ 盤整中以區間操作為主。突破 {fmt(nearest_p)} 轉中線持有；跌破 {fmt(nearest_s)} 立即停損。"

    # 最終保險：停利必須 > 現價，停損必須 < 現價
    if take_profit <= cp:
        take_profit = round(cp * 1.05, 2)
    if stop_loss >= cp:
        stop_loss = round(cp * 0.95, 2)

    # ── 綜合研判：結合短線信號 + 操作判斷 + 籌碼 ──
    # 注意：此時 sector_perf 尚未計算，swing 先不含 sector 題材（±5 分差異）
    swing = calc_swing_signal(hist, info=info, earnings_days=earnings_days, vix=vix_now)
    sw_score = swing['score']
    chip_s = chip_score
    trend_bullish = mid_score >= 30  # 中線偏多或強勢
    trend_consolidate = -10 <= mid_score < 30  # 中線觀望/盤整
    trend_bearish = mid_score < -10  # 中線偏空或空頭
    chip_positive = chip_s >= 30  # 🟢
    chip_negative = chip_s < 0  # 🔴
    signal_buy = sw_score >= 30  # 🟢
    signal_caution_low = 15 <= sw_score < 30  # 🟡 逢低留意
    signal_neutral = -14 <= sw_score <= 14  # ⚪
    signal_caution_high = -29 <= sw_score <= -15  # 🟡 注意風險
    signal_sell = sw_score <= -30  # 🔴

    verdict_parts = []

    # 趨勢 + 信號組合
    if trend_bullish and signal_sell:
        verdict_parts.append(
            "📊 趨勢判斷：中線趨勢仍然向上（均線多頭排列），但短線多個指標顯示已經過熱。這代表不是趨勢反轉，而是短線漲太快需要休息。"
        )
        verdict_parts.append(
            "💡 白話建議：如果你已經有持股，現在是「分批停利」的好時機 — 先賣掉 1/3 ~ 1/2 鎖定獲利，剩下的設好停損繼續持有。如果你還沒買，千萬不要現在追進去，等它拉回到均線附近（回檔 5~8%）再考慮進場。"
        )
        verdict_parts.append(
            f"⏰ 等待訊號：等股價回檔到 MA10({fmt(round(ma10v, 2))}) 附近，且短線信號轉為 🟢 或 ⚪ 時，就是比較好的重新買入時機。"
        )
    elif trend_bullish and signal_caution_high:
        verdict_parts.append(
            "📊 趨勢判斷：中線趨勢向上，短線出現一些過熱的初期跡象，但還沒到需要大動作的程度。"
        )
        verdict_parts.append(
            "💡 白話建議：有持股的人可以「先減碼一小部分」（1/4 左右），把停利點設在最近壓力位附近。沒持股的人不建議現在追買，等拉回再說。"
        )
    elif trend_bullish and signal_buy:
        verdict_parts.append(
            "📊 趨勢判斷：中線多頭趨勢 + 短線剛好回到便宜價位，這是教科書級的買點！"
        )
        if chip_positive:
            verdict_parts.append(
                "💡 白話建議：趨勢向上＋大戶看好＋短線到低點，三個條件都到齊了。可以積極分批買進，第一批先進 1/3 倉位，跌到支撐位再加碼。"
            )
        else:
            verdict_parts.append(
                "💡 白話建議：趨勢和短線信號都不錯，但籌碼面沒有特別加分。可以買，但倉位不要太重（先進 1/4），設好停損。"
            )
    elif trend_bullish and signal_neutral:
        verdict_parts.append("📊 趨勢判斷：中線趨勢向上，短線不上不下，沒有特別好或壞的買賣點。")
        verdict_parts.append(
            f"💡 白話建議：趨勢是好的，但現在進場「時機普通」。可以小量試單，或者耐心等回檔到 MA5({fmt(round(ma5v, 2))}) 附近再進場。急著買容易買在半山腰。"
        )
    elif trend_consolidate and signal_buy:
        verdict_parts.append(
            "📊 趨勢判斷：短線在回檔整理中，但中線趨勢沒壞。現在短線指標顯示可能跌夠了。"
        )
        verdict_parts.append(
            f"💡 白話建議：這是「回檔找買點」的好機會。可在目前價位或支撐位 {fmt(nearest_s)} 附近分批買進。但一定要設停損在 MA20({fmt(round(ma20v, 2))}) 以下，跌破就代表整理變成反轉了。"
        )
    elif trend_consolidate and signal_sell:
        verdict_parts.append(
            "📊 趨勢判斷：正在整理中但短線指標轉差，有可能從「整理」惡化成「反轉」。"
        )
        verdict_parts.append(
            f"💡 白話建議：先觀望不要買。有持股的人把停損拉近到 MA20({fmt(round(ma20v, 2))}) 附近，跌破立刻走。等短線信號好轉再說。"
        )
    elif trend_consolidate:
        verdict_parts.append("📊 趨勢判斷：股價在短線整理中，中線趨勢還沒壞但也不算強。")
        verdict_parts.append(
            "💡 白話建議：觀望為主。等突破整理區間（站回 MA5 以上）且短線信號轉正再進場。現在進場勝率不高。"
        )
    elif trend_bearish and signal_buy:
        verdict_parts.append(
            "📊 趨勢判斷：中線趨勢向下，但短線跌到很超賣的位置，可能有技術性反彈。"
        )
        verdict_parts.append(
            f"💡 白話建議：⚠️ 這只適合「搶短反彈」，不是真正的買點！如果要做，用極小倉位（不超過總資金 10%），目標只看到 MA10({fmt(round(ma10v, 2))})，嚴格停損 {fmt(round(nearest_s * 0.97, 2))}。新手建議直接跳過，等趨勢翻多再來。"
        )
    elif trend_bearish and signal_sell:
        verdict_parts.append("📊 趨勢判斷：趨勢向下 + 短線也沒有止跌訊號，情況很差。")
        verdict_parts.append(
            "💡 白話建議：🚨 有持股的立刻停損出場，不要凹！沒持股的絕對不要去接刀。等到趨勢翻轉（站回 MA20 以上）+ 短線出現 🟢 信號再考慮。"
        )
    elif trend_bearish:
        verdict_parts.append("📊 趨勢判斷：中線趨勢向下，目前不適合做多。")
        verdict_parts.append(
            f"💡 白話建議：空手觀望是最好的操作。等待股價站回 MA20({fmt(round(ma20v, 2))}) 以上且短線信號轉正，才考慮進場。"
        )
    else:
        verdict_parts.append("📊 趨勢判斷：方向不明確，多空拉鋸中。")
        verdict_parts.append(
            "💡 白話建議：等方向出來再操作。突破壓力位做多、跌破支撐位做空（或離場）。現在進場像丟銅板。"
        )

    # 籌碼面加註
    if chip_positive and not trend_bearish:
        verdict_parts.append(
            "🏦 籌碼加分：機構持股高、空單低，大戶站在多方，回檔時有接盤力道，比較不用擔心暴跌。"
        )
    elif chip_negative:
        verdict_parts.append(
            "🏦 籌碼警示：籌碼面偏空（機構持股偏低或空單偏高），即使技術面好看，也要注意大戶可能在出貨，倉位不宜過重。"
        )

    # 財報提醒
    if next_earnings and earnings_days is not None and 0 < earnings_days <= 14:
        verdict_parts.append(
            f"📅 財報倒數 {earnings_days} 天（{next_earnings}）：財報前股價容易大幅波動。新手建議不要在財報前重倉，或至少設好停損。財報後再根據結果決定操作方向。"
        )

    # 分析師目標價
    if target_upside is not None:
        if target_upside > 20:
            verdict_parts.append(
                f"🎯 華爾街分析師平均目標價 {fmt(target_mean)}（上漲空間 +{target_upside}%），多數看好後市。"
            )
        elif target_upside < -5:
            verdict_parts.append(
                f"🎯 注意：分析師平均目標價 {fmt(target_mean)}，低於現價（{target_upside}%），市場可能已經漲過頭。"
            )

    verdict = "\n".join(verdict_parts)

    # ── 短線 vs 中長線操作建議 ──
    # 短線（1-5 天 swing trade）
    if signal_buy and not trend_bearish:
        short_action = "買入"
        short_action_color = "#4ade80"
        short_entry = f"現價附近或回檔至 {fmt(nearest_s)} 分批進場"
        short_target = fmt(nearest_p)
        short_stop = fmt(round(nearest_s * 0.98, 2))
        short_note = f"RSI {rsi_val}，短線超賣反彈機會大。MACD 柱狀體{'轉正，動能回升' if macd_hist_val > 0 else '仍為負但收斂中'}。"
    elif signal_caution_low and not trend_bearish:
        short_action = "逢低留意"
        short_action_color = "#fbbf24"
        short_entry = f"等回檔至 {fmt(nearest_s)} 附近再進場"
        short_target = fmt(nearest_p)
        short_stop = fmt(round(nearest_s * 0.97, 2))
        short_note = "短線指標偏多但未到最佳買點，耐心等待回檔。"
    elif signal_sell:
        if trend_bullish:
            short_action = "短線過熱，等回檔"
            short_action_color = "#fbbf24"
            short_entry = f"不追高，等回檔至 MA10({fmt(round(ma10v, 2))}) 附近再加碼"
            short_target = fmt(nearest_p)
            short_stop = fmt(round(ma20v * 0.97, 2))
            short_note = "中線多頭沒壞，短線過熱是正常回檔，不需要賣出。耐心等回測均線就是加碼點。"
        else:
            short_action = "賣出/觀望"
            short_action_color = "#f87171"
            short_entry = "不建議進場"
            short_target = "—"
            short_stop = fmt(round(ma10v * 0.98, 2)) if ma10v else "—"
            short_note = f"短線過熱且中線趨勢不佳，RSI {rsi_val}。有持股先減碼，等信號轉正再考慮。"
    elif signal_caution_high:
        if trend_bullish:
            short_action = "持有，留意回檔"
            short_action_color = "#fbbf24"
            short_entry = f"不建議追高，等回檔至 MA5({fmt(round(ma5v, 2))}) 再考慮加碼"
            short_target = fmt(nearest_p)
            short_stop = fmt(round(ma20v * 0.97, 2))
            short_note = "中線多頭，短線稍有壓力但不需恐慌。持股續抱，新倉等拉回。"
        else:
            short_action = "減碼/觀望"
            short_action_color = "#fbbf24"
            short_entry = "不建議新倉"
            short_target = "—"
            short_stop = fmt(round(cp * 0.97, 2))
            short_note = "短線指標偏空且中線趨勢不強，有持股考慮先減 1/4~1/3。"
    else:
        short_action = "觀望"
        short_action_color = "#94a3b8"
        short_entry = f"等突破 {fmt(nearest_p)} 或回檔至 {fmt(nearest_s)}"
        short_target = fmt(nearest_p)
        short_stop = fmt(round(nearest_s * 0.97, 2))
        short_note = "短線方向不明，等訊號出來再操作。"

    # 中長線（2 週 ~ 數月）
    if trend_bullish:
        if signal_buy or signal_caution_low:
            mid_action = "買入"
            mid_action_color = "#4ade80"
            mid_entry = f"分批進場：第一批現價，第二批等回測 MA10({fmt(round(ma10v, 2))})"
            mid_target = fmt(mid_tp)
            mid_stop = fmt(round(ma20v * 0.97, 2))
            mid_note = f"中線多頭趨勢明確，回檔就是加碼機會。正股加碼永久持有，不設賣出點。突破 {fmt(nearest_p)} 後可加碼。"
        elif signal_sell or signal_caution_high:
            mid_action = "持有/減碼"
            mid_action_color = "#fbbf24"
            mid_entry = "不建議新倉，等短線修正後再進場"
            mid_target = fmt(mid_tp)
            mid_stop = fmt(round(ma20v * 0.97, 2))
            mid_note = f"中線趨勢沒壞但短線過熱。已持有正股續抱不賣，設停利在 {fmt(nearest_p)}，跌破 MA20({fmt(round(ma20v, 2))}) 減碼但不清倉。"
        else:
            mid_action = "輕倉試單"
            mid_action_color = "#fbbf24"
            mid_entry = f"等回檔到 MA5({fmt(round(ma5v, 2))}) 附近"
            mid_target = fmt(mid_tp)
            mid_stop = fmt(round(ma20v * 0.97, 2))
            mid_note = "趨勢向上但目前位置普通，不急。"
    elif trend_consolidate:
        if signal_buy:
            mid_action = "逢低佈局"
            mid_action_color = "#4ade80"
            mid_entry = f"支撐位 {fmt(nearest_s)} 附近分批低接"
            mid_target = fmt(mid_tp)
            mid_stop = fmt(round(ma20v * 0.96, 2))
            mid_note = f"中線整理中但未轉空，跌到支撐是佈局機會。跌破 MA20({fmt(round(ma20v, 2))}) 要停損。"
        else:
            mid_action = "觀望"
            mid_action_color = "#94a3b8"
            mid_entry = f"等站回 MA20({fmt(round(ma20v, 2))}) 以上再考慮"
            mid_target = fmt(mid_tp)
            mid_stop = fmt(round(nearest_s * 0.96, 2))
            mid_note = f"整理期間不確定性高，等方向確認。突破 {fmt(nearest_p)} 做多，跌破 {fmt(nearest_s)} 離場。"
    elif trend_bearish:
        mid_action = "不建議"
        mid_action_color = "#f87171"
        mid_entry = f"等站回 MA20({fmt(round(ma20v, 2))}) + MACD 金叉確認"
        mid_target = "—"
        mid_stop = "—"
        mid_note = "中線趨勢向下，不適合中長線持有。等趨勢反轉信號出現再進場。"
    else:
        mid_action = "觀望"
        mid_action_color = "#94a3b8"
        mid_entry = f"等突破 {fmt(nearest_p)} 確認方向"
        mid_target = fmt(mid_tp)
        mid_stop = fmt(round(nearest_s * 0.96, 2))
        mid_note = "方向不明，耐心等待。"

    # Chip summary text
    chip_notes = []
    if inst_own > 70:
        chip_notes.append(f"機構持股 {inst_own}%（高），大型資金看好")
    elif inst_own < 40:
        chip_notes.append(f"機構持股 {inst_own}%（低），需注意流動性")
    else:
        chip_notes.append(f"機構持股 {inst_own}%")
    if short_pct > 10:
        dtc_note = f"，DTC {short_ratio} 天" if short_ratio > 3 else ""
        chip_notes.append(f"空單比例 {short_pct}% 偏高{dtc_note}")
        if squeeze_flag:
            chip_notes.append("🚀 具備軋空條件")
    elif short_pct > 5:
        chip_notes.append(f"空單比例 {short_pct}%，中等水準")
    else:
        chip_notes.append(f"空單比例 {short_pct}%（低），空方壓力小")
    if pcr > 1.5:
        chip_notes.append(f"PCR {pcr}（極高，反向底部信號）")
    elif pcr > 1:
        chip_notes.append(f"PCR {pcr}（>1），期權市場偏避險")
    elif pcr > 0.7:
        chip_notes.append(f"PCR {pcr}，期權情緒中性")
    elif pcr > 0:
        chip_notes.append(f"PCR {pcr}（<0.7），期權市場偏樂觀")
    if insider_note:
        chip_notes.append(insider_note)
    if analyst_note:
        chip_notes.append(analyst_note)
    chip_summary = "。".join(chip_notes) + "。"

    # ── 新聞面 ──
    news_items = []
    try:
        raw_news = ticker.news or []
        for n in raw_news[:6]:
            content = n.get('content', {})
            title = content.get('title', n.get('title', ''))
            link = (
                content.get('canonicalUrl', {}).get('url', '')
                or content.get('clickThroughUrl', {}).get('url', '')
                or n.get('link', '')
            )
            pub = content.get('pubDate', n.get('providerPublishTime', ''))
            provider = content.get('provider', {}).get('displayName', '') or n.get('publisher', '')
            if title:
                # 處理時間戳
                if isinstance(pub, (int, float)):
                    pub = datetime.fromtimestamp(pub).strftime('%m/%d %H:%M')
                elif isinstance(pub, str) and len(pub) > 10:
                    pub = pub[:10]
                news_items.append({'title': title, 'link': link, 'time': pub, 'provider': provider})
    except Exception:
        pass

    # ── 板塊 ETF 比較 ──
    sector_etf_map = {
        'Technology': ('XLK', '科技板塊 ETF'),
        'Communication Services': ('XLC', '通訊板塊 ETF'),
        'Consumer Cyclical': ('XLY', '消費板塊 ETF'),
        'Financial Services': ('XLF', '金融板塊 ETF'),
        'Healthcare': ('XLV', '醫療板塊 ETF'),
        'Energy': ('XLE', '能源板塊 ETF'),
        'Industrials': ('XLI', '工業板塊 ETF'),
    }
    sector_name = info.get('sector', '')
    sector_etf, sector_etf_name = sector_etf_map.get(sector_name, ('SPY', 'S&P 500'))
    sector_perf = {}
    try:
        etf_hist = get_history(sector_etf, period="3mo")['Close']
        stock_hist_3m = hist['Close'].astype(float)
        # 計算近 1 週、1 月、3 月報酬率比較
        for label, days in [('1W', 5), ('1M', 22), ('3M', 60)]:
            if len(stock_hist_3m) >= days and len(etf_hist) >= days:
                s_ret = round((stock_hist_3m.iloc[-1] / stock_hist_3m.iloc[-days] - 1) * 100, 1)
                e_ret = round((etf_hist.iloc[-1] / etf_hist.iloc[-days] - 1) * 100, 1)
                sector_perf[label] = {'stock': s_ret, 'etf': e_ret, 'diff': round(s_ret - e_ret, 1)}
    except Exception:
        pass

    # ── 短線波段信號（所有基本面/題材資料已備齊）──
    swing = calc_swing_signal(
        hist, info=info, sector_perf=sector_perf, earnings_days=earnings_days, vix=vix_now
    )

    # Tag line
    fundamentals_tag = (
        "基本面強"
        if (isinstance(pe, float) and pe < 30 and pe > 0)
        else "高估值"
        if (isinstance(pe, float) and pe > 50)
        else "基本面中性"
    )
    tag_line = f"{tag_summary}＋{fundamentals_tag}＋{chip_lbl[2:]}"

    # ── 槓桿策略建議 ──
    lev_info = LEVERAGE_ETF.get(symbol)
    lev_strategy = None
    lev_etf = None
    if lev_info:
        lev_etf = lev_info['etf']
        lev_mult = lev_info['mult']
        if rsi_val < 30:
            lev_strategy = f"🚨 RSI 極低（{rsi_val:.0f}）！額外資金買 {lev_etf}（{lev_mult}）的好時機。反彈至 RSI>65 時獲利了結，全部轉回 {symbol} 正股永久持有。"
        elif rsi_val < 35:
            lev_strategy = f"📈 RSI 偏低（{rsi_val:.0f}），可用額外資金買 {lev_etf}（{lev_mult}）。目標 RSI>65 了結，獲利轉回 {symbol} 正股。"
        elif rsi_val < 45:
            lev_strategy = f"📊 RSI 中低（{rsi_val:.0f}），適合加碼 {symbol} 正股（永久持有）。槓桿 {lev_etf} 等 RSI<35 再出手。"
        elif rsi_val > 70:
            lev_strategy = f"🔄 RSI 過熱（{rsi_val:.0f}）！持有 {lev_etf} 的話現在轉回 {symbol} 正股鎖利。正股繼續持有不動。"
        elif rsi_val > 65:
            lev_strategy = f"⚠️ RSI 偏高（{rsi_val:.0f}），持有 {lev_etf} 考慮了結轉正股。不要追高買槓桿。正股持有不動。"
        else:
            lev_strategy = f"💤 RSI 中性（{rsi_val:.0f}），等待機會。{lev_etf} 在 RSI<35 時才值得出手。正股持有不動。"

    return {
        "symbol": symbol,
        "name": info.get('shortName', symbol),
        "sector": info.get('sector', ''),
        "price": round(cp, 2),
        "chg": chg,
        "chg_pct": chg_pct,
        "status": status,
        "status_color": status_color,
        "status_bg": status_bg,
        "tag_line": tag_line,
        # Advice
        "aggressive": aggressive,
        "conservative": conservative,
        "risk": risk,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "sell_signal": sell_signal,
        "verdict": verdict,
        # 短線操作建議
        "short_action": short_action,
        "short_action_color": short_action_color,
        "short_entry": short_entry,
        "short_target": short_target,
        "short_stop": short_stop,
        "short_note": short_note,
        # 中長線操作建議
        "mid_action": mid_action,
        "mid_action_color": mid_action_color,
        "mid_entry": mid_entry,
        "mid_target": mid_target,
        "mid_stop": mid_stop,
        "mid_note": mid_note,
        # 槓桿策略
        "lev_strategy": lev_strategy,
        "lev_etf": lev_etf,
        # Chip
        "inst_own": inst_own,
        "insider_own": insider_own,
        "short_ratio": short_ratio,
        "short_pct": short_pct,
        "beta": beta,
        "pcr": pcr,
        "chip_score": chip_score,
        "chip_lbl": chip_lbl,
        "chip_color": chip_color,
        "chip_summary": chip_summary,
        "chip_details": chip_details,
        "squeeze_flag": squeeze_flag,
        "insider_note": insider_note,
        "analyst_note": analyst_note,
        "analyst_score": analyst_sc,
        # Valuation
        "pe": pe,
        "fwd_pe": fwd_pe,
        "pb": pb,
        "div_yield": div_yield,
        "mkt_cap": mkt_cap_str,
        "w52h": w52h,
        "w52l": w52l,
        "w52_pos": w52_pos,
        # Technicals
        "rsi": rsi_val,
        "macd_val": macd_val,
        "macd_sig": macd_sig,
        "macd_hist_val": macd_hist_val,
        "macd_cross": macd_cross,
        "vol_ratio": vol_ratio,
        "vol_trend": vol_trend,
        # Levels
        "pressures": pressures[:5],
        "supports": supports[:5],
        "nearest_p": nearest_p,
        "nearest_s": nearest_s,
        # Chart data
        "dates": hist.index.tolist(),
        "opens": [round(v, 2) for v in hist['Open'].tolist()],
        "highs": [round(v, 2) for v in hist['High'].tolist()],
        "lows": [round(v, 2) for v in hist['Low'].tolist()],
        "closes": [round(v, 2) for v in hist['Close'].tolist()],
        "volumes": [int(v) for v in hist['Volume'].tolist()],
        "ma5": [None if np.isnan(v) else round(v, 2) for v in hist['MA5'].tolist()],
        "ma10": [None if np.isnan(v) else round(v, 2) for v in hist['MA10'].tolist()],
        "ma20": [None if np.isnan(v) else round(v, 2) for v in hist['MA20'].tolist()],
        "ma60": [None if np.isnan(v) else round(v, 2) for v in hist['MA60'].tolist()],
        "bb_upper": [None if np.isnan(v) else round(v, 2) for v in hist['BB_upper'].tolist()],
        "bb_lower": [None if np.isnan(v) else round(v, 2) for v in hist['BB_lower'].tolist()],
        "rsi_data": [None if np.isnan(v) else round(v, 1) for v in hist['RSI'].tolist()],
        "macd_data": [None if np.isnan(v) else round(v, 2) for v in hist['MACD'].tolist()],
        "macd_signal_data": [
            None if np.isnan(v) else round(v, 2) for v in hist['MACD_signal'].tolist()
        ],
        "macd_hist_data": [
            None if np.isnan(v) else round(v, 2) for v in hist['MACD_hist'].tolist()
        ],
        # Financial
        "q_labels": q_labels,
        "rev": rev,
        "gm": gm,
        "nm": nm,
        # News
        "news": news_items,
        # Analyst
        "target_high": target_high,
        "target_low": target_low,
        "target_mean": target_mean,
        "target_median": target_median,
        "target_upside": target_upside,
        "recommend_key": recommend_key,
        "num_analysts": num_analysts,
        "rec_summary": rec_summary,
        # Earnings
        "next_earnings": next_earnings,
        "earnings_days": earnings_days,
        # Sector
        "sector_etf": sector_etf,
        "sector_etf_name": sector_etf_name,
        "sector_perf": sector_perf,
        # Pre/Post market
        "premarket_price": info.get('preMarketPrice'),
        "premarket_chg_pct": round(info.get('preMarketChangePercent', 0), 2)
        if info.get('preMarketChangePercent')
        else None,
        "postmarket_price": info.get('postMarketPrice'),
        "postmarket_chg_pct": round(info.get('postMarketChangePercent', 0), 2)
        if info.get('postMarketChangePercent')
        else None,
        # Swing signal
        "swing": swing,
        # 中期趨勢
        "mid_trend": mid,
    }
