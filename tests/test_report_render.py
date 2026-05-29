"""
report.render 純渲染層測試 — 用中性假資料（不含任何真實或捏造的財經宣稱）。

render 層是純函式（資料→字串），不需網路 / node / Telegram，可獨立執行：
    python -m pytest tests/test_report_render.py
    或  python tests/test_report_render.py
"""

from services.report import render

# 中性 fixture：symbol 用 TEST，reason 寫「範例」，不放任何看似真實的數據或公司
_FIXTURE = [
    {
        'symbol': 'TEST1',
        'score': 4.0,
        'scores': {
            '不可替代': 4.0,
            '產能受限': 4.0,
            '需求爆發': 4.0,
            '新聞未反映': 4.0,
            '股價未反映': 4.0,
        },
        'reasons': {
            k: '（範例說明）'
            for k in ['不可替代', '產能受限', '需求爆發', '新聞未反映', '股價未反映']
        },
        'swing': 30,
        'trend': 60,
        'momentum': 5.0,
    },
    {
        'symbol': 'TEST2',
        'score': 2.0,
        'scores': {
            '不可替代': 2.0,
            '產能受限': 2.0,
            '需求爆發': 2.0,
            '新聞未反映': 2.0,
            '股價未反映': 2.0,
        },
        'reasons': {},
    },
]


def test_score_emoji_thresholds():
    assert render.score_emoji(4.0) == '✅'
    assert render.score_emoji(3.0) == '⚠️'
    assert render.score_emoji(1.0) == '❌'


def test_generate_score_svg_is_valid_svg():
    svg = render.generate_score_svg(_FIXTURE)
    assert svg.startswith('<svg')
    assert svg.rstrip().endswith('</svg>')
    assert 'TEST1' in svg and 'TEST2' in svg
    # 規範：背景色、無 <marker>、& 已 escape
    assert '#1a1a2e' in svg
    assert '<marker' not in svg
    assert '&' not in svg or '&amp;' in svg


def test_generate_research_report_has_frontmatter_and_sections():
    md = render.generate_research_report(
        group='G2',
        theme='範例題材',
        theme_analysis='這是一段範例題材分析。',
        candidates=_FIXTURE,
        bought=[{'symbol': 'TEST1', 'qty': 1, 'price': 1.0, 'reason': '（範例）'}],
        headlines=['Example headline A & B'],
    )
    assert md.startswith('---')  # frontmatter
    assert '# 🔬 G2 研究報告' in md
    assert '## 🔍 瓶頸五條件評分' in md
    assert 'TEST1' in md
    # headline 內的 & 應被 escape
    assert 'Example headline A &amp; B' in md


if __name__ == '__main__':
    test_score_emoji_thresholds()
    test_generate_score_svg_is_valid_svg()
    test_generate_research_report_has_frontmatter_and_sections()
    print('✅ report.render 測試全數通過')
