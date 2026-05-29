"""
PDF 轉換邊界 — 把 Markdown 轉成 PDF。

目前用 md-to-pdf（node 套件，完整支援 Obsidian callout / 表格 / 中文）。
要換 PDF 引擎時只改這個檔，render.py / pipeline.py 不受影響。
"""

import os
import subprocess

from config import MD_TO_PDF_PATH

# 樣式表與本檔同層，隨程式入庫
CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'obsidian-pdf.css')


def md_to_pdf(md_path: str) -> str:
    """用 md-to-pdf 將 Markdown 轉為 PDF，回傳輸出的 .pdf 路徑。"""
    env = dict(os.environ)
    bin_dir = os.path.dirname(MD_TO_PDF_PATH)
    if bin_dir and os.path.isdir(bin_dir):
        env['PATH'] = bin_dir + os.pathsep + env.get('PATH', '')
    cmd = [MD_TO_PDF_PATH, '--stylesheet', CSS_PATH, md_path]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120, cwd=os.path.dirname(md_path), env=env
    )
    if result.returncode != 0:
        raise RuntimeError(f'md-to-pdf 失敗: {result.stderr}')
    return md_path.replace('.md', '.pdf')
