"""
研究報告生成器 — Obsidian Markdown + SVG → PDF → Telegram。

模組分層：
  render.py    純渲染（SVG / Markdown），無 IO
  pdf.py       md-to-pdf 轉檔邊界
  pipeline.py  編排 + 副作用（寫檔 / PDF / Telegram）

公開 API：
  save_and_send_report   完整流程
  generate_research_report  只產 Markdown（不寫檔）
"""

from .pipeline import save_and_send_report
from .render import generate_research_report

__all__ = ['save_and_send_report', 'generate_research_report']
