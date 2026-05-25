#!/usr/bin/env python3
"""Build static HTML site from output/ markdown files for GitHub Pages."""

import re
import shutil
import sys
from datetime import datetime, date
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OUTPUT = PROJ / "output"
DIST = PROJ / "dist"

try:
    import markdown as md_lib
    HAS_MD = True
except ImportError:
    HAS_MD = False

CSS = """
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--accent:#58a6ff;--green:#3fb950;--red:#f85149;--yellow:#d2991d}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding:20px;max-width:900px;margin:0 auto}
h1{border-bottom:1px solid var(--border);padding-bottom:12px;margin:24px 0 12px;color:#f0f6fc}
h2{margin:20px 0 10px;color:#f0f6fc;font-size:1.25em}
h3{margin:16px 0 8px;font-size:1.1em}
a{color:var(--accent);text-decoration:none}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:0.85em}
th,td{border:1px solid var(--border);padding:6px 8px;text-align:left}
th{background:#21262d}
tr:nth-child(even){background:#0d1117}
tr:hover{background:#1c2128}
blockquote{border-left:3px solid var(--accent);padding:8px 16px;margin:12px 0;background:#161b22;color:var(--muted)}
code{background:#21262d;padding:2px 4px;border-radius:3px;font-size:0.85em}
hr{border:none;border-top:1px solid var(--border);margin:20px 0}
ul,ol{padding-left:24px;margin:8px 0}
li{margin:4px 0}
strong{color:#f0f6fc}
.date-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px}
.date-card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px}
.date-card:hover{border-color:var(--accent)}
.date-card .date{font-weight:bold;color:var(--accent)}
.date-card .stats{font-size:0.8em;color:var(--muted);margin-top:4px}
.footer{margin-top:40px;padding-top:12px;border-top:1px solid var(--border);color:var(--muted);font-size:0.8em;text-align:center}
.header h1{border:none;margin:0;font-size:1.1em}
.action-buy{color:var(--green);font-weight:bold}
.action-watch{color:var(--yellow);font-weight:bold}
.action-avoid{color:var(--red);font-weight:bold}
"""

_DOW = ["周一","周二","周三","周四","周五","周六","周日"]


def md_to_html(md_text: str) -> str:
    if HAS_MD:
        body = md_lib.markdown(md_text, extensions=['tables', 'fenced_code'])
    else:
        body = md_text.replace('\n', '<br>')
    return body


def wrap_page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>
<p style="margin-bottom:16px"><a href="/quantlib-postclose/">← 首页</a></p>
{body}
<div class="footer">自动生成 · 仅供参考，不构成投资建议</div>
</body>
</html>"""


def build_site():
    DIST.mkdir(parents=True, exist_ok=True)

    items = {}
    for sub in ['postclose', 'morning', 'institute_attention', 'consistency']:
        subdir = OUTPUT / sub
        if not subdir.exists():
            continue
        for d in subdir.iterdir():
            if not d.is_dir() or not d.name.startswith('20'):
                continue
            key = d.name
            if key not in items:
                items[key] = {
                    'date': key,
                    'postclose': None, 'morning': None,
                    'institute': None, 'consistency': None,
                }
            if sub == 'postclose' and (d / 'review.md').exists():
                items[key]['postclose'] = str(d / 'review.md')
            if sub == 'morning' and (d / 'briefing.md').exists():
                items[key]['morning'] = str(d / 'briefing.md')
            if sub == 'institute_attention' and (d / 'weekly.md').exists():
                items[key]['institute'] = str(d / 'weekly.md')
            if sub == 'consistency' and (d / 'check.md').exists():
                items[key]['consistency'] = str(d / 'check.md')

    # Build index
    rows = []
    for item in sorted(items.values(), key=lambda x: x['date'], reverse=True):
        try:
            d = datetime.strptime(item['date'], '%Y-%m-%d')
            dow = _DOW[d.weekday()]
        except Exception:
            dow = ""
        links = []
        if item['postclose']:
            links.append('<a href="/quantlib-postclose/p/{0}/review.html">📊 复盘</a>'.format(item['date']))
        if item['morning']:
            links.append('<a href="/quantlib-postclose/p/{0}/briefing.html">🌅 盘前</a>'.format(item['date']))
        if item['institute']:
            links.append('<a href="/quantlib-postclose/p/{0}/weekly.html">🔬 研报</a>'.format(item['date']))
        if item['consistency']:
            links.append('<a href="/quantlib-postclose/p/{0}/check.html">🔍 校验</a>'.format(item['date']))
        rows.append(f"""<div class="date-card">
<div class="date">{item['date']} {dow}</div>
<div class="stats">{' · '.join(links)}</div>
</div>""")

    index_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>复盘报告</title>
<style>{CSS}</style>
</head>
<body>
<div class="header"><h1>📈 每日复盘 & 盘前简报</h1></div>
<div class="date-list">{''.join(rows)}</div>
<div class="footer">自动生成 · 仅供参考，不构成投资建议</div>
</body>
</html>"""

    with open(DIST / 'index.html', 'w') as f:
        f.write(index_html)

    # Build individual pages
    page_dir = DIST / 'p'
    for item in items.values():
        d = item['date']
        for key, fname in [('postclose', 'review'), ('morning', 'briefing'),
                          ('institute', 'weekly'), ('consistency', 'check')]:
            src = item.get(key)
            if src:
                src_path = Path(src)
                if src_path.exists():
                    out_dir = page_dir / d
                    out_dir.mkdir(parents=True, exist_ok=True)
                    md_text = src_path.read_text()
                    body = md_to_html(md_text)
                    html = wrap_page(f"复盘 · {d}", body)
                    with open(out_dir / f'{fname}.html', 'w') as f:
                        f.write(html)

    print(f"Built {len(items)} dates → {DIST}/")
    print(f"Index: {DIST / 'index.html'}")


if __name__ == "__main__":
    build_site()
