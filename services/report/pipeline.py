"""
編排層 — 把純渲染與外部工具串成完整流程，副作用都集中在這裡。

流程：normalize（清洗輸入）→ render（SVG+Markdown）→ pdf（轉檔）→ telegram（傳送）。
寫檔、subprocess、網路傳送都在此檔；render.py 維持純函式。
"""

import os
import re
from datetime import datetime

from services.telegram import send_file as _send_telegram_file

from . import render
from .pdf import md_to_pdf

# 報告輸出在專案根目錄的 reports/（services/report/pipeline.py → 上三層為專案根）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_DIR = os.path.join(_PROJECT_ROOT, 'reports')


def _to_float(val, default=0.0):
    """安全轉 float，None/空字串/非數字 → default。"""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(re.sub(r'[^\d.\-]', '', str(val)) or default)
    except (ValueError, TypeError):
        return default


def _normalize_candidates(candidates: list) -> list:
    """清理 candidates，確保 score / scores 都是合法數字，避免 None 造成錯誤。"""
    criteria = ['不可替代', '產能受限', '需求爆發', '新聞未反映', '股價未反映']
    normalized = []
    for c in candidates or []:
        if not isinstance(c, dict) or not c.get('symbol'):
            continue
        scores = c.get('scores') or {}
        clean_scores = {name: _to_float(scores.get(name), 0.0) for name in criteria}
        score = c.get('score')
        if score is None:
            vals = [v for v in clean_scores.values() if v > 0]
            score = sum(vals) / len(vals) if vals else 0.0
        else:
            score = _to_float(score, 0.0)
        nc = dict(c)
        nc['score'] = score
        nc['scores'] = clean_scores
        nc['reasons'] = c.get('reasons') or {}
        normalized.append(nc)
    return normalized


def save_and_send_report(
    group: str,
    theme: str,
    theme_analysis: str,
    candidates: list,
    bought: list = None,
    headlines: list = None,
    send_telegram_pdf: bool = True,
) -> dict:
    """完整報告流程：SVG → Markdown → PDF → Telegram。回傳各產物路徑與發送狀態。"""
    now = datetime.now()
    date_str = now.strftime('%Y%m%d_%H%M')
    safe_theme = re.sub(r'[^\w\s]', '', theme).strip().replace(' ', '_')[:30]

    candidates = _normalize_candidates(candidates)

    research_dir = os.path.join(REPORT_DIR, 'research')
    figures_dir = os.path.join(research_dir, 'figures')
    os.makedirs(figures_dir, exist_ok=True)

    result = {'md_path': None, 'pdf_path': None, 'svg_path': None, 'sent': False}

    # 1. SVG 圖表
    try:
        svg_content = render.generate_score_svg(candidates)
        svg_path = os.path.join(figures_dir, 'bottleneck_scores.svg')
        with open(svg_path, 'w', encoding='utf-8') as f:
            f.write(svg_content)
        result['svg_path'] = svg_path
    except Exception as e:
        print(f'⚠️ SVG 生成失敗: {e}')

    # 2. Obsidian Markdown
    md_path = os.path.join(research_dir, f'{date_str}_{group}_{safe_theme}.md')
    try:
        report_md = render.generate_research_report(
            group, theme, theme_analysis, candidates, bought, headlines
        )
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(report_md)
        result['md_path'] = md_path
    except Exception as e:
        print(f'⚠️ Markdown 生成失敗: {e}')
        return result

    # 3. md-to-pdf 轉 PDF
    try:
        pdf_path = md_to_pdf(md_path)
        if os.path.exists(pdf_path):
            result['pdf_path'] = pdf_path
    except Exception as e:
        print(f'⚠️ PDF 生成失敗: {e}')

    # 4. 傳 Telegram
    if send_telegram_pdf and result['pdf_path'] and os.path.exists(result['pdf_path']):
        try:
            _send_telegram_file(result['pdf_path'], f'🔬 {group} 研究報告：{theme}')
            result['sent'] = True
        except Exception as e:
            print(f'⚠️ Telegram 傳送失敗: {e}')

    return result
