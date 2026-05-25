#!/usr/bin/env python3
"""View postclose reviews and morning briefings in browser.

Usage:
    python3 scripts/serve.py                    # Serve on port 8899
    python3 scripts/serve.py --port 8888        # Custom port
    python3 scripts/serve.py --no-browser       # Don't open browser
"""

import argparse
import http.server
import json
import os
import re
import webbrowser
from datetime import datetime
from pathlib import Path

try:
    import markdown as md_lib
    HAS_MD = True
except ImportError:
    HAS_MD = False

PROJ = Path(__file__).resolve().parent.parent
OUTPUT = PROJ / "output"
_DOW = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

CSS = """
:root {
  --bg: #0d1117; --card: #161b22; --border: #30363d;
  --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff;
  --green: #3fb950; --red: #f85149; --yellow: #d2991d;
  --buy: #238636; --watch: #9e6a03; --avoid: #da3633;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6; padding: 20px; max-width: 900px; margin: 0 auto; }
h1 { border-bottom: 1px solid var(--border); padding-bottom: 12px; margin: 24px 0 12px; color: #f0f6fc; }
h2 { margin: 20px 0 10px; color: #f0f6fc; font-size: 1.25em; }
h3 { margin: 16px 0 8px; font-size: 1.1em; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 0.9em; }
th, td { border: 1px solid var(--border); padding: 8px 10px; text-align: left; }
th { background: #21262d; }
tr:nth-child(even) { background: #0d1117; }
tr:hover { background: #1c2128; }
blockquote { border-left: 3px solid var(--accent); padding: 8px 16px; margin: 12px 0; background: #161b22; color: var(--muted); }
code { background: #21262d; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }
hr { border: none; border-top: 1px solid var(--border); margin: 20px 0; }
ul, ol { padding-left: 24px; margin: 8px 0; }
li { margin: 4px 0; }
strong { color: #f0f6fc; }
.action-buy { color: var(--green); font-weight: bold; }
.action-watch { color: var(--yellow); font-weight: bold; }
.action-avoid { color: var(--red); font-weight: bold; }
.header { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--border); margin-bottom: 20px; }
.header h1 { border: none; margin: 0; font-size: 1.1em; }
.nav a { margin-left: 16px; color: var(--muted); }
.nav a.active { color: var(--accent); }
.date-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px; }
.date-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.date-card:hover { border-color: var(--accent); }
.date-card .date { font-weight: bold; color: var(--accent); }
.date-card .stats { font-size: 0.8em; color: var(--muted); margin-top: 4px; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin: 16px 0; }
.sector-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
.sector-card.buy { border-left: 3px solid var(--green); }
.sector-card.watch { border-left: 3px solid var(--yellow); }
.sector-card.avoid { border-left: 3px solid var(--red); }
.sector-card h3 { margin: 0 0 6px 0; font-size: 1em; display: flex; justify-content: space-between; }
.sector-card .reason { font-size: 0.85em; color: var(--muted); margin: 6px 0; }
.sector-card .stocks { font-size: 0.85em; }
.sector-card .stock { display: inline-block; background: #21262d; padding: 2px 8px; border-radius: 4px; margin: 2px 4px 2px 0; font-size: 0.85em; }
.footer { margin-top: 40px; padding-top: 12px; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.8em; text-align: center; }
.meta { color: var(--muted); font-size: 0.85em; margin-bottom: 16px; }
"""  # noqa: E501


def _render_briefing_card(md_text: str) -> str:
    """Render morning briefing as a card-based HTML layout."""
    # Extract key sections
    date_match = re.search(r'# 盘前简报 · (\d{4}-\d{2}-\d{2})', md_text)
    date_str = date_match.group(1) if date_match else ""

    # Parse sector recommendations table
    recs = []
    in_table = False
    for line in md_text.split('\n'):
        if line.startswith('| 板块 |'):
            in_table = True
            continue
        if in_table:
            if line.startswith('|') and '---' not in line:
                parts = [p.strip() for p in line.split('|')[1:-1]]
                if len(parts) >= 6:
                    recs.append({
                        'sector': parts[0], 'source': parts[1],
                        'action': parts[2], 'confidence': parts[3],
                        'reason': parts[4], 'stocks': parts[5],
                    })
            elif not line.startswith('|'):
                in_table = False

    # Extract stance
    stance = ""
    stance_match = re.search(r'> (.+仓位[^。]+)', md_text)
    if stance_match:
        stance = stance_match.group(1)

    # Extract risk alerts
    risks = []
    in_risks = False
    for line in md_text.split('\n'):
        if '## 5. 风险提示' in line:
            in_risks = True
            continue
        if in_risks and line.startswith('- '):
            risks.append(line[2:])
        elif in_risks and line.startswith('## '):
            break

    # Extract consistency check
    consistency = []
    in_consistency = False
    for line in md_text.split('\n'):
        if '## 一致性校验' in line:
            in_consistency = True
            continue
        if in_consistency and line.startswith('- '):
            consistency.append(line[2:])
        elif in_consistency and (line.startswith('## ') or line == '---'):
            break

    # Build HTML
    html = f'<div class="meta">生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}</div>\n'

    # Stance
    if stance:
        html += f'<blockquote><strong>📋 整体策略：</strong>{stance}</blockquote>\n'

    # Sector cards
    action_map = {'🟢 买入': 'buy', '🟡 关注': 'watch', '🔴 回避': 'avoid'}
    html += '<div class="card-grid">\n'
    for r in recs:
        action = r.get('action', '')
        cls = action_map.get(action, '')
        html += f'<div class="sector-card {cls}">\n'
        html += f'<h3>{r["sector"]} <span class="action-{cls}">{action}</span></h3>\n'
        html += f'<div class="reason">📌 {r["reason"]}</div>\n'
        if r.get('stocks'):
            html += '<div class="stocks">'
            for stock in r['stocks'].split('<br>'):
                stock = stock.strip()
                if stock:
                    html += f'<span class="stock">{stock}</span>'
            html += '</div>\n'
        html += '</div>\n'
    html += '</div>\n'

    # Risks
    if risks:
        html += '<h3>⚠️ 风险提示</h3>\n<ul>\n'
        for r in risks:
            html += f'<li>{r}</li>\n'
        html += '</ul>\n'

    # Consistency check
    if consistency:
        html += '<details open><summary style="cursor:pointer;font-weight:bold;padding:8px 0;color:var(--yellow)">🔍 一致性校验</summary>\n<ul style="font-size:0.85em">\n'
        for c in consistency:
            cls = ''
            if c.startswith('🔴'):
                cls = ' style="color:var(--red)"'
            elif c.startswith('❌'):
                cls = ' style="color:var(--red)"'
            elif c.startswith('📌'):
                cls = ' style="color:var(--yellow)"'
            html += f'<li{cls}>{c}</li>\n'
        html += '</ul></details>\n'

    return html


def _md_to_html(md_text: str, report_type: str = "postclose") -> str:
    """Convert markdown to styled HTML."""
    if HAS_MD:
        body = md_lib.markdown(md_text, extensions=['tables', 'fenced_code'])
    else:
        # Simple fallback
        body = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', md_text)
        body = re.sub(r'^### (.+)$', r'<h3>\1</h3>', body, flags=re.M)
        body = re.sub(r'^## (.+)$', r'<h2>\1</h2>', body, flags=re.M)
        body = re.sub(r'^# (.+)$', r'<h1>\1</h1>', body, flags=re.M)
        body = re.sub(r'^- (.+)$', r'<li>\1</li>', body, flags=re.M)
        body = re.sub(r'^> (.+)$', r'<blockquote>\1</blockquote>', body, flags=re.M)
        body = body.replace('\n', '<br>\n')

    # Add action colors
    body = body.replace('🟢 买入', '<span class="action-buy">🟢 买入</span>')
    body = body.replace('🟡 关注', '<span class="action-watch">🟡 关注</span>')
    body = body.replace('🔴 回避', '<span class="action-avoid">🔴 回避</span>')

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>复盘报告</title>
<style>{CSS}</style>
</head>
<body>
{body}
<div class="footer">Auto-generated · 仅供参考，不构成投资建议</div>
</body>
</html>"""


class ReportHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(OUTPUT), **kwargs)

    def do_GET(self):
        path = self.path.rstrip('/') or '/'

        if path == '/':
            self._serve_index()
        elif '/full' in path:
            # Full briefing page
            date_match = re.match(r'/(morning)/(\d{4}-\d{2}-\d{2})/full', path)
            if date_match:
                md_path = f"/{date_match.group(1)}/{date_match.group(2)}/briefing.md"
                self._serve_md_as_html(md_path, card_only=False)
            else:
                self.send_error(404)
        elif path.endswith('.md'):
            self._serve_md_as_html(path, card_only=('morning' in path and 'briefing' in path))
        else:
            super().do_GET()

    def _serve_index(self):
        """Generate and serve index page listing all reports."""
        items = {}
        for sub in ['postclose', 'morning', 'institute_attention', 'consistency']:
            subdir = OUTPUT / sub
            if not subdir.exists():
                continue
            for d in subdir.iterdir():
                if not d.is_dir() or not d.name.startswith('20'):
                    continue
                if d.name not in items:
                    items[d.name] = {'date': d.name, 'has_postclose': False, 'has_morning': False, 'has_institute': False, 'has_consistency': False}
                if sub == 'postclose' and (d / 'review.md').exists():
                    items[d.name]['has_postclose'] = True
                if sub == 'morning' and (d / 'briefing.md').exists():
                    items[d.name]['has_morning'] = True
                if sub == 'institute_attention' and (d / 'weekly.md').exists():
                    items[d.name]['has_institute'] = True
                if sub == 'consistency' and (d / 'check.md').exists():
                    items[d.name]['has_consistency'] = True

        # Build index HTML
        rows = []
        for item in sorted(items.values(), key=lambda x: x['date'], reverse=True):
            d = datetime.strptime(item['date'], '%Y-%m-%d')
            dow = _DOW[d.weekday()]
            links = []
            if item['has_postclose']:
                links.append('<a href="/postclose/{0}/review.md">📊 复盘</a>'.format(item['date']))
            if item['has_morning']:
                links.append('<a href="/morning/{0}/briefing.md">📋 摘要</a>'.format(item['date']))
                links.append('<a href="/morning/{0}/full">🌅 盘前全文</a>'.format(item['date']))
            if item['has_institute']:
                links.append('<a href="/institute_attention/{0}/weekly.md">🔬 研报热度</a>'.format(item['date']))
            if item['has_consistency']:
                links.append('<a href="/consistency/{0}/check.md">🔍 一致性校验</a>'.format(item['date']))
            rows.append(f"""
            <div class="date-card">
                <div class="date">{item['date']} {dow}</div>
                <div class="stats">{' · '.join(links)}</div>
            </div>""")

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>复盘报告</title><style>{CSS}</style>
</head>
<body>
<div class="header">
  <h1>📈 每日复盘 & 盘前简报</h1>
  <div class="nav">
    <a href="/" class="active">全部</a>
  </div>
</div>
<div class="date-list">{''.join(rows)}</div>
<div class="footer">Auto-generated · 仅供参考，不构成投资建议</div>
</body>
</html>"""

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(html.encode()))
        self.end_headers()
        self.wfile.write(html.encode())

    def _serve_md_as_html(self, path, card_only=False):
        filepath = OUTPUT / path.lstrip('/')
        if not filepath.exists():
            self.send_error(404)
            return

        md_text = filepath.read_text()

        # Determine report type
        is_briefing = 'briefing' in str(filepath) or 'morning' in str(filepath)

        # Full markdown → HTML
        full_body = md_lib.markdown(md_text, extensions=['tables', 'fenced_code']) if HAS_MD else md_text
        full_body = full_body.replace('🟢 买入', '<span class="action-buy">🟢 买入</span>')
        full_body = full_body.replace('🟡 关注', '<span class="action-watch">🟡 关注</span>')
        full_body = full_body.replace('🔴 回避', '<span class="action-avoid">🔴 回避</span>')

        if md_text.startswith('# 盘前简报') or '盘前简报 ·' in md_text[:200]:
            title_match = re.search(r'# 盘前简报 · (\d{4}-\d{2}-\d{2})', md_text)
            title = f"盘前简报 · {title_match.group(1)}" if title_match else "盘前简报"
            if card_only:
                # Card-only view with nav to full
                card = _render_briefing_card(md_text)
                stance_match = re.search(r'> (.+仓位[^。]+)', md_text)
                stance = stance_match.group(1) if stance_match else ""
                body = f'<p style="margin-bottom:12px"><a href="/">← 返回列表</a> | <a href="/morning/{title_match.group(1)}/full">📄 查看全文</a></p>\n'
                if stance:
                    body += f'<blockquote><strong>📋 {stance}</strong></blockquote>\n'
                body += card
            else:
                # Full content with card at top
                card = _render_briefing_card(md_text)
                body = f'<p style="margin-bottom:12px"><a href="/">← 返回列表</a> | <a href="/morning/{title_match.group(1)}/briefing.md">📋 只看摘要</a></p>\n'
                body += f'<details open><summary style="cursor:pointer;font-size:1.1em;font-weight:bold;padding:8px 0;color:var(--accent)">📋 卡片摘要（点击收起）</summary>{card}</details>\n<hr>\n{full_body}'
        elif 'POSTCLOSE REVIEW' in md_text:
            title_match = re.search(r'POSTCLOSE REVIEW · (\d{4}-\d{2}-\d{2})', md_text)
            title = f"收盘复盘 · {title_match.group(1)}" if title_match else "收盘复盘"
            body = full_body
        elif '机构研报热度周报' in md_text:
            title_match = re.search(r'机构研报热度周报 · (\d{4}-\d{2}-\d{2})', md_text)
            title = f"机构研报热度 · {title_match.group(1)}" if title_match else "机构研报热度"
            body = full_body
        elif '盘前预测准确性校验' in md_text or '一致性校验' in md_text:
            title_match = re.search(r'(?:盘前预测准确性校验|一致性校验) · (\d{4}-\d{2}-\d{2})', md_text)
            title = f"一致性校验 · {title_match.group(1)}" if title_match else "一致性校验"
            body = full_body
        else:
            title = "复盘报告"
            body = full_body

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title><style>{CSS}</style>
</head>
<body>
<p style="margin-bottom:16px"><a href="/">← 返回列表</a></p>
{body}
<div class="footer">Auto-generated · 仅供参考，不构成投资建议</div>
</body>
</html>"""

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(html.encode()))
        self.end_headers()
        self.wfile.write(html.encode())


def main():
    parser = argparse.ArgumentParser(description="Serve reports via HTTP")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    # Ensure output dirs exist
    for sub in ['postclose', 'morning', 'institute_attention', 'consistency']:
        (OUTPUT / sub).mkdir(parents=True, exist_ok=True)

    url = f"http://localhost:{args.port}"
    print(f"  📈 复盘报告服务")
    print(f"  {url}")
    print(f"  按 Ctrl+C 停止")

    if not args.no_browser:
        webbrowser.open(url)

    server = http.server.HTTPServer(('0.0.0.0', args.port), ReportHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止")


if __name__ == "__main__":
    main()
