"""
純渲染層 — 資料進、字串出，無任何 IO/副作用（好測試、可獨立重用）。

- SVG 圖表（遵循 obsidian-svg-embed 規範：背景 #1a1a2e、polygon 箭頭、& 轉 &amp;）
- Obsidian Flavored Markdown 報告（frontmatter、callout、表格、SVG 嵌入）

不在此檔做的事：寫檔、轉 PDF、傳 Telegram（那些在 pipeline.py）。
"""

import re
from datetime import datetime


def score_emoji(score) -> str:
    if score >= 3.5:
        return '✅'
    elif score >= 2.5:
        return '⚠️'
    return '❌'


def generate_score_svg(candidates: list) -> str:
    """生成瓶頸五條件評分 SVG（純函式）。"""
    criteria = ['不可替代', '產能受限', '需求爆發', '新聞未反映', '股價未反映']

    row_height = 50
    chart_height = 60
    padding = 40
    header_height = 60
    per_stock = chart_height + len(criteria) * row_height + 30
    total_h = header_height + len(candidates) * per_stock + padding
    width = 700

    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {total_h}" '
        f'width="{width}" height="{total_h}">',
        '  <defs>',
        '    <style>',
        '      .title { font: bold 16px sans-serif; fill: #fff; }',
        '      .stock-name { font: bold 14px sans-serif; fill: #fff; }',
        '      .label { font: 12px sans-serif; fill: #ccc; }',
        '      .score-text { font: bold 12px sans-serif; }',
        '      .pass-line { stroke: #2ecc71; stroke-width: 1; stroke-dasharray: 6,4; opacity: 0.5; }',
        '    </style>',
        '  </defs>',
        f'  <rect width="{width}" height="{total_h}" fill="#1a1a2e"/>',
        f'  <text x="{width // 2}" y="35" text-anchor="middle" class="title">瓶頸五條件評分</text>',
    ]

    y_offset = header_height
    for c in candidates:
        sym = c.get('symbol', '?')
        total = c.get('score', 0)
        scores = c.get('scores', {})
        emoji = '✅' if total >= 3.5 else '❌'

        svg_lines.append(
            f'  <text x="30" y="{y_offset + 20}" class="stock-name">'
            f'{sym}（總分 {total:.1f} {emoji}）</text>'
        )

        bar_y = y_offset + 35
        bar_max_w = 350
        bar_x = 200
        bar_h = 20

        for i, name in enumerate(criteria):
            val = scores.get(name, 0)
            if isinstance(val, str):
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    val = 0
            cy = bar_y + i * row_height
            svg_lines.append(f'  <text x="30" y="{cy + 15}" class="label">{name}</text>')
            svg_lines.append(
                f'  <rect x="{bar_x}" y="{cy}" width="{bar_max_w}" '
                f'height="{bar_h}" rx="3" fill="#2a2a4a"/>'
            )
            fill_w = val / 5.0 * bar_max_w
            color = '#2ecc71' if val >= 3.5 else '#f39c12' if val >= 2.5 else '#e74c3c'
            svg_lines.append(
                f'  <rect x="{bar_x}" y="{cy}" width="{fill_w:.0f}" '
                f'height="{bar_h}" rx="3" fill="{color}"/>'
            )
            svg_lines.append(
                f'  <text x="{bar_x + bar_max_w + 15}" y="{cy + 15}" '
                f'class="score-text" fill="{color}">{val:.1f}</text>'
            )

        pass_x = bar_x + (3.5 / 5.0 * bar_max_w)
        svg_lines.append(
            f'  <line x1="{pass_x:.0f}" y1="{bar_y - 5}" '
            f'x2="{pass_x:.0f}" y2="{bar_y + len(criteria) * row_height - 15}" '
            f'class="pass-line"/>'
        )
        svg_lines.append(
            f'  <text x="{pass_x:.0f}" y="{bar_y - 10}" '
            f'text-anchor="middle" font-size="10" fill="#2ecc71">3.5 通過線</text>'
        )
        y_offset += per_stock

    svg_lines.append('</svg>')
    return '\n'.join(svg_lines)


def generate_research_report(
    group: str,
    theme: str,
    theme_analysis: str,
    candidates: list,
    bought: list = None,
    headlines: list = None,
) -> str:
    """生成 Obsidian Flavored Markdown 研究報告（純函式）。"""
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M')
    safe_theme = re.sub(r'[^\w\s]', '', theme).strip().replace(' ', '_')[:30]

    group_names = {
        'G2': '自動題材掃描',
        'G3': '用戶導向題材',
        'G4': 'AI 伺服器 + 太空 DC',
    }
    group_name = group_names.get(group, group)

    lines = ['---', f'title: "{group} 研究報告 — {theme}"', f'date: {date_str}', 'tags:']
    lines.append(f'  - {group.lower()}')
    lines.append('  - research')
    lines.append(f'  - {safe_theme}')
    lines.append(f'group: {group}')
    lines.append(f'theme: "{theme}"')
    if bought:
        lines.append(f'bought: [{", ".join(b.get("symbol", "") for b in bought)}]')
    lines.append('---')
    lines.append('')

    lines.append(f'# 🔬 {group} 研究報告 — {theme}')
    lines.append('')
    lines.append(f'> {date_str} {time_str} | {group_name}')
    lines.append('')

    lines.append('## 📰 題材分析')
    lines.append('')
    if theme_analysis:
        lines.append(theme_analysis)
    lines.append('')

    if headlines:
        lines.append('> [!info] 相關新聞')
        for h in headlines[:5]:
            headline_safe = h.replace('&', '&amp;') if '&' in h else h
            lines.append(f'> - {headline_safe}')
        lines.append('')

    lines.append('---')
    lines.append('')

    if candidates:
        lines.append('## 🔍 瓶頸五條件評分')
        lines.append('')
        lines.append(
            '| 股票 | 不可替代 | 產能受限 | 需求爆發 | 新聞未反映 | 股價未反映 | 總分 | 結果 |'
        )
        lines.append('|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|')
        for c in candidates:
            sym = c.get('symbol', '?')
            s = c.get('scores', {})
            total = c.get('score', 0)
            emoji = score_emoji(total)
            lines.append(
                f"| {sym} "
                f"| {s.get('不可替代', '-')} "
                f"| {s.get('產能受限', '-')} "
                f"| {s.get('需求爆發', '-')} "
                f"| {s.get('新聞未反映', '-')} "
                f"| {s.get('股價未反映', '-')} "
                f"| **{total:.1f}** | {emoji} |"
            )
        lines.append('')
        lines.append('![瓶頸評分圖](figures/bottleneck_scores.svg)')
        lines.append('')
        lines.append('---')
        lines.append('')

        for c in candidates:
            sym = c.get('symbol', '?')
            total = c.get('score', 0)
            emoji = score_emoji(total)
            reasons = c.get('reasons', {})
            scores = c.get('scores', {})

            callout_type = 'success' if total >= 3.5 else 'warning' if total >= 2.5 else 'failure'
            lines.append(f'> [!{callout_type}] {sym}（總分 {total:.1f} {emoji}）')
            lines.append('>')

            criteria_desc = [
                ('不可替代', '市場上幾家公司能做這件事？有沒有短期替代方案？'),
                ('產能受限', '現有產能能滿足需求嗎？擴產需要多久？'),
                ('需求爆發', '下游需求 YoY 成長多少？成長的驅動力是什麼？'),
                ('新聞未反映', '主流媒體和分析師是否已經大量報導？散戶是否已知？'),
                ('股價未反映', '目前估值是否已經 price in？跟同業比如何？'),
            ]
            for name, desc in criteria_desc:
                score = scores.get(name, 0)
                reason = reasons.get(name, '無資料')
                score_str = f'{score}/5' if isinstance(score, (int, float)) else str(score)
                lines.append(f'> **{name}（{score_str}）** — _{desc}_')
                lines.append(f'> {reason}')
                lines.append('>')
            lines.append('')

    tech_candidates = [c for c in candidates if c.get('swing') is not None]
    if tech_candidates:
        lines.append('## 📊 技術面確認')
        lines.append('')
        lines.append('| 股票 | Swing | Trend | 20日動量 | 結果 |')
        lines.append('|:---|:---:|:---:|:---:|:---:|')
        for c in tech_candidates:
            sym = c.get('symbol', '?')
            swing = c.get('swing', 0)
            trend = c.get('trend', 0)
            mom = c.get('momentum', '-')
            passed = swing >= 20 and trend >= 50
            result = '✅ 通過' if passed else '❌ 不通過'
            lines.append(f'| {sym} | {swing} | {trend} | {mom}% | {result} |')
        lines.append('')

    if bought:
        lines.append('## ✅ 買入決定')
        lines.append('')
        for b in bought:
            sym = b.get('symbol', '?')
            qty = b.get('qty', 0)
            price = b.get('price', 0)
            reason = b.get('reason', '')
            lines.append(f'> [!success] 買入 {sym} x{qty} @ ${price:.2f}')
            lines.append(f'> {reason}')
            lines.append('')
    elif candidates:
        passed = [c for c in candidates if c.get('score', 0) >= 3.5]
        if not passed:
            lines.append('> [!warning] 本次掃描沒有符合瓶頸條件（總分 ≥ 3.5）的股票。')
            lines.append('')

    lines.append('---')
    lines.append(f'*報告產生時間：{now.strftime("%Y-%m-%d %H:%M")} | 瓶頸投資系統 {group}*')

    return '\n'.join(lines)
