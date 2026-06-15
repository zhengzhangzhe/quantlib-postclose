#!/usr/bin/env python3
"""Build static HTML site from output/ markdown files for GitHub Pages."""

import re
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
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--accent:#58a6ff;--green:#3fb950;--red:#f85149;--yellow:#d2991d;--buy:#238636;--watch:#9e6a03;--avoid:#da3633}
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
.action-buy{color:var(--green);font-weight:bold}
.action-watch{color:var(--yellow);font-weight:bold}
.action-avoid{color:var(--red);font-weight:bold}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin:16px 0}
.sector-card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px}
.sector-card.buy{border-left:3px solid var(--green)}
.sector-card.watch{border-left:3px solid var(--yellow)}
.sector-card.avoid{border-left:3px solid var(--red)}
.sector-card h3{margin:0 0 6px;font-size:1em;display:flex;justify-content:space-between}
.sector-card .reason{font-size:0.85em;color:var(--muted);margin:6px 0}
.sector-card .stocks{font-size:0.85em}
.sector-card .stock{display:inline-block;background:#21262d;padding:2px 8px;border-radius:4px;margin:2px 4px 2px 0;font-size:0.85em}
.meta{color:var(--muted);font-size:0.85em;margin-bottom:16px}
details summary{cursor:pointer;font-weight:bold;padding:8px 0;color:var(--accent)}
"""

_DOW = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def md_to_html(md_text: str) -> str:
    if HAS_MD:
        return md_lib.markdown(md_text, extensions=['tables', 'fenced_code'])
    return md_text.replace('\n', '<br>')


def _render_briefing_card(md_text: str) -> str:
    """Render morning briefing as a card-based HTML layout, mirroring serve.py."""
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

    stance_match = re.search(r'> (.+仓位[^。]+)', md_text)
    stance = stance_match.group(1) if stance_match else ""

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

    html = ''
    if stance:
        html += f'<blockquote><strong>📋 整体策略：</strong>{stance}</blockquote>\n'

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

    if risks:
        html += '<h3>⚠️ 风险提示</h3>\n<ul>\n'
        for r in risks:
            html += f'<li>{r}</li>\n'
        html += '</ul>\n'

    if consistency:
        html += '<details open><summary>🔍 一致性校验</summary>\n<ul style="font-size:0.85em">\n'
        for c in consistency:
            cls = 'style="color:var(--red)"' if c.startswith('🔴') or c.startswith('❌') else \
                  'style="color:var(--yellow)"' if c.startswith('📌') else ''
            html += f'<li {cls}>{c}</li>\n'
        html += '</ul></details>\n'

    return html


def render_page(md_text: str, filepath: str) -> str:
    """Render a markdown file to full HTML page."""
    return md_to_html(md_text)


def render_briefing_pages(md_text: str) -> tuple[str, str]:
    """Return (card_only_html, full_html) for morning briefing."""
    return _render_briefing_card(md_text), md_to_html(md_text)


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
    for sub in ['postclose', 'morning', 'institute_attention', 'consistency', 'bigshot_screener']:
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
            links.append('<a href="/quantlib-postclose/p/{0}/briefing.html">📋 摘要</a>'.format(item['date']))
            links.append('<a href="/quantlib-postclose/p/{0}/full.html">🌅 盘前全文</a>'.format(item['date']))
        if item['institute']:
            links.append('<a href="/quantlib-postclose/p/{0}/weekly.html">🔬 研报</a>'.format(item['date']))
        if item['consistency']:
            links.append('<a href="/quantlib-postclose/p/{0}/check.html">🔍 校验</a>'.format(item['date']))
        rows.append(f"""<div class="date-card">
<div class="date">{item['date']} {dow}</div>
<div class="stats">{' · '.join(links)}</div>
</div>""")

    # Dynamically build profile links from output/bigshot_profiles/
    prof_dir = OUTPUT / "bigshot_profiles"
    profile_links = []
    if prof_dir.exists():
        import json
        for md_file in sorted(prof_dir.glob("*.md")):
            name = md_file.stem
            display = name
            prof_json = PROJ / "data" / "nga" / "bigshot_profiles" / f"{name}.json"
            if prof_json.exists():
                try:
                    d = json.loads(prof_json.read_text())
                    display = d.get("display", name)
                except: pass
            profile_links.append(f'<a href="/quantlib-postclose/p/{name}.html">{display}</a>')
    profiles_links = " · ".join(profile_links) if profile_links else "暂无"

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
<div class="date-list">{''.join(rows)}
<div class="date-card" style="border-color:var(--green)">
    <div class="date">📌 大佬画像</div>
    <div class="stats">{profiles_links}</div>
	    <div class="stats" style="margin-top:4px"><a href="/quantlib-postclose/p/daily_picks.html">🎯 今日选股</a> · <a href="/quantlib-postclose/p/verified.html">✅ 选股验证</a></div>
	</div>
</div>
</div>
<div class="footer">自动生成 · 仅供参考，不构成投资建议</div>
</body>
</html>"""

    with open(DIST / 'index.html', 'w') as f:
        f.write(index_html)

    # Build individual pages
    page_dir = DIST / 'p'
    for item in items.values():
        d = item['date']
        out_dir = page_dir / d
        out_dir.mkdir(parents=True, exist_ok=True)

        for key, fname in [('postclose', 'review'), ('institute', 'weekly'), ('consistency', 'check')]:
            src = item.get(key)
            if src:
                src_path = Path(src)
                if src_path.exists():
                    md_text = src_path.read_text()
                    body = render_page(md_text, src)
                    html = wrap_page(f"复盘 · {d}", body)
                    with open(out_dir / f'{fname}.html', 'w') as f:
                        f.write(html)

        # Morning briefing: two pages (card summary + full)
        if item['morning']:
            src_path = Path(item['morning'])
            if src_path.exists():
                md_text = src_path.read_text()
                card, full = render_briefing_pages(md_text)
                # Card-only summary
                with open(out_dir / 'briefing.html', 'w') as f:
                    f.write(wrap_page(f"盘前简报 · {d}", card))
                # Full content
                with open(out_dir / 'full.html', 'w') as f:
                    f.write(wrap_page(f"盘前简报全文 · {d}", full))

    # Build screener page
    scr_dir = OUTPUT / "bigshot_screener"
    if scr_dir.exists():
        latest = sorted(scr_dir.glob("*.md"), reverse=True)
        if latest:
            body = md_to_html(latest[0].read_text())
            html = wrap_page("每日海选", body)
            with open(page_dir / "screener.html", "w") as f:
                f.write(html)



    # Build daily picks page
    picks_dir = OUTPUT / "daily_picks"
    if picks_dir.exists():
        latest = sorted(picks_dir.glob("*.md"), reverse=True)
        if latest:
            body = md_to_html(latest[0].read_text())
            html = wrap_page("今日选股", body)
            with open(page_dir / "daily_picks.html", "w") as f:
                f.write(html)

    # Build verified page
    verify_dir = OUTPUT / "verified"
    if verify_dir.exists():
        latest = sorted(verify_dir.glob("*.md"), reverse=True)
        if latest:
            body = md_to_html(latest[0].read_text())
            html = wrap_page("选股验证", body)
            with open(page_dir / "verified.html", "w") as f:
                f.write(html)

    # Build bigshot profile pages
    prof_dir = OUTPUT / "bigshot_profiles"
    if prof_dir.exists():
        for md_file in sorted(prof_dir.glob("*.md")):
            name = md_file.stem
            body = md_to_html(md_file.read_text())
            html = wrap_page(f"大佬画像 · {name}", body)
            with open(page_dir / f"{name}.html", "w") as f:
                f.write(html)
            print(f"  Profile: {page_dir / f'{name}.html'}")

    print(f"Built {len(items)} dates → {DIST}/")
    print(f"Index: {DIST / 'index.html'}")


if __name__ == "__main__":
    build_site()
