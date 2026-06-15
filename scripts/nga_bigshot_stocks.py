#!/usr/bin/env python3
"""NGA 大佬股票推荐追踪器。

扫描热帖，收集已知大佬的发言，提取股票推荐，验证准确率。

Usage:
    python3 scripts/nga_bigshot_stocks.py                   # Console output
    python3 scripts/nga_bigshot_stocks.py --json --save      # JSON + save
"""

import argparse
import json
import re
import sys
import time as _time
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJ = Path(__file__).resolve().parent.parent
DATA_DIR = PROJ / "data" / "nga"
COOKIE_FILE = PROJ / "data" / "nga_cookie.txt"

# Known大佬 and their main threads
BIGSHOTS = {
    "幸运阿sai": ["46870606", "46879941", "46859072", "44279886",  # 主帖+活跃
                  "46910384", "46906089", "46887918", "46756363", "46872529"],
    "文驹":     ["46756363", "45974302"],  # 中钨高新 + 自立自强
    "灰兔尾":   ["46756363", "45974302"],  # 中钨高新 + 自立自强 (非OP, 但常驻)
    "ddddd519": ["44790803", "46292895", "46350659"],  # 纯超短 + 5000元 + 没有慧根
    "达达鸭儿呀": ["46350659"],       # 没有慧根就要会跟
    "-阿狼-":   ["45974302"],         # 自立自强
    # 其他活跃熱帖追加扫描
    "_hot_threads": ["46581190", "46872529", "46553777", "45902809", "45905087"],
}

# Stock detection: 6-digit codes
STOCK_CODE_RE = re.compile(r'(?<!\d)(00|30|60|68)\d{4}(?!\d)')

# Buy/sell signal keywords
BUY_KW = ["买入", "加仓", "建仓", "上车", "跟了", "入", "梭哈", "埋伏",
          "捞", "吸", "低吸", "抄底", "补仓", "开仓", "all in", "满仓"]
SELL_KW = ["卖出", "清仓", "止损", "割肉", "下车", "跑了", "止盈",
           "减仓", "出清", "撤退", "砸了", "溜了", "走了"]
WATCH_KW = ["关注", "观察", "看看", "加入自选", "留意", "盯着", "选股"]

# Method keywords
METHOD_KW = {
    "技术面": ["MACD", "KDJ", "均线", "量价", "放量", "缩量", "突破", "支撑",
              "压力", "布林", "RSI", "金叉", "死叉", "背驰", "顶底", "分时"],
    "基本面": ["业绩", "营收", "利润", "PE", "估值", "年报", "季报", "现金流",
              "ROE", "毛利率", "市占率", "扩产", "定增", "公告"],
    "消息面": ["新闻", "政策", "利好", "利空", "催化", "消息", "国家",
             "发改委", "工信部", "国务院", "补贴", "制裁"],
    "情绪面": ["情绪", "恐慌", "贪婪", "分歧", "一致", "高潮", "退潮",
             "冰点", "修复", "反包", "核按钮"],
}


def load_cookie() -> str:
    return COOKIE_FILE.read_text().strip() if COOKIE_FILE.exists() else ""


def build_cookies(s: str) -> list[dict]:
    cookies = []
    for pair in s.split("; "):
        if "=" in pair:
            k, v = pair.split("=", 1)
            cookies.append({"name": k, "value": v, "domain": ".nga.cn", "path": "/"})
    return cookies


def build_stock_map(snaps: dict) -> dict:
    """Build stock name → code mapping from postclose snapshots. Auto-generates abbreviations."""
    name_to_code = {}
    code_to_name = {}
    for snap in snaps.values():
        for s in snap.get("limit_up_stocks", []):
            code = str(s.get("code", "")).split(".")[0].zfill(6)
            name = s.get("name", "")
            if name and code:
                name_to_code[name] = code
                code_to_name[code] = name

    # Common suffixes to strip for abbreviation generation
    SUFFIXES = ["股份", "科技", "集团", "控股", "电气", "电子", "信息",
                "实业", "能源", "技术", "医疗", "生物", "材料", "工业",
                "有限", "公司", "国际", "智能", "光电", "通信", "证券"]

    abbr_map = {}
    for name, code in name_to_code.items():
        # Full name
        abbr_map[name] = code
        # Name without suffixes → abbreviation
        short = name
        for sfx in SUFFIXES:
            if short.endswith(sfx):
                short = short[:-len(sfx)]
                abbr_map[short] = code
        # 2-char prefix (only for names >= 4 chars)
        if len(name) >= 4:
            abbr_map[name[:2]] = code
        # 3-char prefix
        if len(name) >= 3:
            abbr_map[name[:3]] = code
    return abbr_map, code_to_name


def extract_stocks(text: str, stock_map: dict) -> list[tuple]:
    """Extract stock references: returns [(code, name, match_text)]."""
    results = []
    # Try 6-digit codes first
    for m in STOCK_CODE_RE.finditer(text):
        code = m.group(0)
        # Get name from code_to_name if available
        results.append((code, "", code))

    # Try stock names (longest first to avoid partial matches)
    matches = []
    common_words = {"今天","昨天","明天","现在","可以","还是","已经","一个","这个",
                    "什么","怎么","为什么","因为","所以","如果","虽然","但是","不过"}
    for name, code in sorted(stock_map.items(), key=lambda x: -len(x[0])):
        if len(name) < 2: continue
        if name in common_words: continue
        if name in text:
            # Check this isn't a substring of a longer match
            matches.append((code, name, name))
    results.extend(matches)
    # Deduplicate by code
    seen = set()
    unique = []
    for code, name, match_text in results:
        if code not in seen:
            seen.add(code)
            unique.append((code, name, match_text))
    return unique


def classify_direction(text: str) -> str:
    """Classify trade direction based on keywords."""
    text_lower = text.lower()
    buy_score = sum(1 for kw in BUY_KW if kw in text_lower)
    sell_score = sum(1 for kw in SELL_KW if kw in text_lower)
    watch_score = sum(1 for kw in WATCH_KW if kw in text_lower)
    if buy_score > sell_score and buy_score > watch_score:
        return "buy"
    elif sell_score > buy_score and sell_score > watch_score:
        return "sell"
    elif watch_score > 0:
        return "watch"
    return "mention"


def extract_methods(text: str) -> list[str]:
    """Extract analysis methods from text."""
    methods = []
    for category, keywords in METHOD_KW.items():
        for kw in keywords:
            if kw in text:
                methods.append(kw)
    return methods


def parse_postdate(text: str, today: date) -> date | None:
    """Parse NGA .postdate format: 'MM-DD HH:MM' → date."""
    m = re.match(r"(\d{2})-(\d{2})\s", text.strip())
    if not m:
        return None
    mm, dd = int(m.group(1)), int(m.group(2))
    d = date(today.year, mm, dd)
    if d > today:
        d = date(today.year - 1, mm, dd)
    return d


def load_checkpoint() -> date | None:
    """Load last scan date from checkpoint file."""
    cp_file = PROJ / "data" / "nga" / "last_scan.json"
    if cp_file.exists():
        data = json.loads(cp_file.read_text())
        return date.fromisoformat(data.get("last_scan", ""))
    return None


def save_checkpoint(scan_date: date):
    """Save scan date to checkpoint file."""
    cp_file = PROJ / "data" / "nga" / "last_scan.json"
    cp_file.parent.mkdir(parents=True, exist_ok=True)
    cp_file.write_text(json.dumps({"last_scan": scan_date.isoformat()}, indent=2))


def load_postclose_snapshots() -> dict:
    """Load all available postclose snapshots for cross-validation."""
    snap_dir = PROJ / "data" / "postclose"
    snaps = {}
    if snap_dir.exists():
        for d in snap_dir.iterdir():
            if d.is_dir():
                snap_file = d / "snapshot.json"
                if snap_file.exists():
                    with open(snap_file) as f:
                        snaps[d.name] = json.load(f)
    return snaps


def validate_pick(stock_code: str, pick_date: str, snaps: dict) -> dict | None:
    """Check if a stock pick was correct by looking at postclose data."""
    # Find nearest snapshots after pick_date
    available = sorted([d for d in snaps.keys() if d >= pick_date])
    if len(available) < 2:
        return None

    # Check if stock appeared in limit-up pool in the next few days
    appeared_lu = False
    best_pct = 0
    for snap_date in available[:5]:  # next 5 trading days
        snap = snaps[snap_date]
        for s in snap.get("limit_up_stocks", []):
            code = str(s.get("code", "")).split(".")[0].zfill(6)
            if code == stock_code:
                appeared_lu = True
                best_pct = max(best_pct, s.get("pct_chg", 0))
    return {"hit": appeared_lu, "best_pct": best_pct}


def main():
    parser = argparse.ArgumentParser(description="NGA 大佬股票追踪")
    parser.add_argument("--forum-pages", type=int, default=5)
    parser.add_argument("--tail-pages", type=int, default=20)
    parser.add_argument("--incremental", action="store_true",
                        help="Incremental: scan from last page backwards, stop when hitting old posts")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    cookie = load_cookie()
    if not cookie:
        print("❌ 无 cookie"); sys.exit(1)

    print(f"大佬股票追踪 · {datetime.now().strftime('%H:%M')}")
    print(f"追踪 {len(BIGSHOTS)} 位大佬\n")

    # Load postclose data for stock name mapping
    snaps = load_postclose_snapshots()
    stock_map, code_to_name = build_stock_map(snaps)
    print(f"股票映射: {len(stock_map)} 个名称\n")

    all_posts = defaultdict(list)  # username → [posts]
    all_picks = []  # [{username, stock, direction, text, date}]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="zh-CN")
        ctx.add_cookies(build_cookies(cookie))
        page = ctx.new_page()

        # Get target threads (大佬主帖 + 热帖)
        all_target_tids = set()
        for user, user_tids in BIGSHOTS.items():
            if user == "_hot_threads": continue
            for tid in user_tids: all_target_tids.add(tid)
        for tid in BIGSHOTS.get("_hot_threads", []): all_target_tids.add(tid)

        tids = []
        for tid in all_target_tids:
            tids.append((tid, f"主帖#{tid[:6]}"))
        print(f"目标 {len(tids)} 个帖子 (大佬主帖)")

        # Scan threads — collect大佬's own posts
        checkpoint = load_checkpoint() if args.incremental else None
        today = date.today()
        if checkpoint:
            print(f"增量模式: 上次扫描 {checkpoint}, 仅扫描此后的帖子")
        else:
            print("全量模式" + (" (首次增量→初始化末5页)" if args.incremental else ""))

        for i, (tid, title) in enumerate(tids):
            try:
                page.goto(f"https://bbs.nga.cn/read.php?tid={tid}",
                          timeout=8000, wait_until="domcontentloaded")
                page.wait_for_timeout(500)
            except: continue

            # Get max page
            max_pg = 1
            for a in page.query_selector_all("a"):
                href = a.get_attribute("href") or ""
                for pg_m in re.finditer(r'page=(\d+)', href):
                    max_pg = max(max_pg, int(pg_m.group(1)))

            if args.incremental:
                # ── Incremental mode: scan from last page backwards ──
                MAX_INCR_PAGES = 5
                pg = max(max_pg, 1)
                scanned = 0
                stop_thread = False
                while pg >= 1 and scanned < MAX_INCR_PAGES and not stop_thread:
                    try:
                        url = f"https://bbs.nga.cn/read.php?tid={tid}"
                        if pg > 1: url += f"&page={pg}"
                        page.goto(url, timeout=8000, wait_until="domcontentloaded")
                        page.wait_for_timeout(300)
                    except:
                        pg -= 1
                        continue

                    scanned += 1
                    author_els = page.query_selector_all("[id^=postauthor]")
                    authors = [el.inner_text().strip() for el in author_els]
                    post_els = page.query_selector_all(".postcontent")
                    date_els = page.query_selector_all(".postdate")

                    # Determine if this page has any new posts
                    newest_tracked_date = None
                    for j, (author, post_el) in enumerate(zip(authors, post_els)):
                        if author not in BIGSHOTS:
                            continue
                        post_date = None
                        if j < len(date_els):
                            post_date = parse_postdate(date_els[j].inner_text().strip(), today)
                        if post_date:
                            if newest_tracked_date is None or post_date > newest_tracked_date:
                                newest_tracked_date = post_date

                    # Stop if all tracked posts on this page are older than checkpoint
                    if newest_tracked_date and checkpoint and newest_tracked_date < checkpoint:
                        stop_thread = True
                        break

                    # Process this page
                    for j, (author, post_el) in enumerate(zip(authors, post_els)):
                        if author not in BIGSHOTS:
                            continue
                        # In incremental mode, skip posts older than checkpoint
                        if checkpoint and j < len(date_els):
                            post_date = parse_postdate(date_els[j].inner_text().strip(), today)
                            if post_date and post_date < checkpoint:
                                continue
                        text = post_el.inner_text()
                        all_posts[author].append({
                            "text": text, "tid": tid, "title": title,
                            "page": pg, "post_idx": j,
                        })
                        stocks = extract_stocks(text, stock_map)
                        for code, name, match_text in stocks:
                            direction = classify_direction(text)
                            if direction in ("buy", "watch"):
                                all_picks.append({
                                    "username": author, "code": code,
                                    "name": name or code, "direction": direction,
                                    "text": text[:200], "tid": tid,
                                    "title": title, "page": pg,
                                })

                    pg -= 1
                    _time.sleep(0.3)

                if scanned > 0:
                    print(f"  {title}: 扫 {scanned} 页 (末页{max_pg})" +
                          (" [已追上]" if stop_thread else ""))

            else:
                # ── Full mode: orig page selection logic ──
                pages = {1, 2, 3, 4, 5}
                for offset in range(args.tail_pages):
                    pg = min(max_pg - offset, 300)
                    if pg > 5: pages.add(pg)
                if max_pg > 100:
                    mid = max_pg // 2
                    for offset in range(10):
                        pg = min(mid + offset, 300)
                        if pg > 5 and pg < max_pg: pages.add(pg)

                for pg in sorted(pages):
                    try:
                        url = f"https://bbs.nga.cn/read.php?tid={tid}"
                        if pg > 1: url += f"&page={pg}"
                        page.goto(url, timeout=8000, wait_until="domcontentloaded")
                        page.wait_for_timeout(300)
                    except: continue

                    author_els = page.query_selector_all("[id^=postauthor]")
                    authors = [el.inner_text().strip() for el in author_els]
                    post_els = page.query_selector_all(".postcontent")

                    for j, (author, post_el) in enumerate(zip(authors, post_els)):
                        if author not in BIGSHOTS:
                            continue
                        text = post_el.inner_text()
                        all_posts[author].append({
                            "text": text, "tid": tid, "title": title,
                            "page": pg, "post_idx": j,
                        })
                        stocks = extract_stocks(text, stock_map)
                        for code, name, match_text in stocks:
                            direction = classify_direction(text)
                            if direction in ("buy", "watch"):
                                all_picks.append({
                                    "username": author, "code": code,
                                    "name": name or code, "direction": direction,
                                    "text": text[:200], "tid": tid,
                                    "title": title, "page": pg,
                                })

            if (i + 1) % 20 == 0:
                total_posts = sum(len(v) for v in all_posts.values())
                total_picks = len(all_picks)
                print(f"  {i+1}/{len(tids)}, {total_posts} posts, {total_picks} picks")

        browser.close()

    # Save checkpoint for incremental mode
    if args.incremental:
        save_checkpoint(today)
        print(f"检查点已更新: {today}")

    if not all_posts:
        print("未找到大佬发言"); return

    # Summary
    print(f"\n{'='*50}")
    print(f"大佬发言统计:")
    for user in BIGSHOTS:
        post_count = len(all_posts.get(user, []))
        picks = [p for p in all_picks if p["username"] == user]
        print(f"  {user:20s} {post_count:3d} posts  {len(picks):3d} picks")

    # Aggregate picks
    pick_summary = defaultdict(lambda: {"buy": [], "watch": [], "mention": []})
    for p in all_picks:
        pick_summary[p["username"]][p["direction"]].append(p["code"])

    print(f"\n{'='*50}")
    print(f"推荐汇总:")
    for user in BIGSHOTS:
        ps = pick_summary.get(user, {})
        buys = set(ps.get("buy", []))
        watches = set(ps.get("watch", []))
        if buys or watches:
            print(f"\n  {user}:")
            if buys:
                print(f"    🟢 买入/加仓: {', '.join(sorted(buys))}")
            if watches:
                print(f"    🟡 关注: {', '.join(sorted(watches))}")

    # Save
    if args.save:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        recs_dir = DATA_DIR / "recommendations"
        recs_dir.mkdir(parents=True, exist_ok=True)
        snap = {
            "date": today,
            "post_counts": {u: len(v) for u, v in all_posts.items()},
            "posts": {u: [{"text": p["text"][:300], "tid": p["tid"], "page": p["page"]}
                          for p in v[:50]] for u, v in all_posts.items()},
            "picks": all_picks,
            "summary": {u: {
                "buys": list(set(ps.get("buy", []))),
                "watches": list(set(ps.get("watch", []))),
            } for u, ps in pick_summary.items()},
        }
        with open(recs_dir / f"{today}.json", "w") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        print(f"\n快照: {recs_dir / f'{today}.json'}")

    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))

    # ── Report ──
    report = render_report(pick_summary, all_posts, all_picks)
    report_dir = PROJ / "output" / "bigshot_picks"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{datetime.now().strftime('%Y-%m-%d')}.md"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"报告: {report_path}")


def render_report(pick_summary, all_posts, all_picks) -> str:
    L = []
    a = lambda s="": L.append(s)

    today = datetime.now().strftime("%Y-%m-%d")
    a(f"# 大佬推荐追踪报告 · {today}")
    a()
    a("*数据来源：NGA大时代 · 股票映射来自复盘快照 · 仅供参考*")
    a()
    a("---")
    a()

    # Summary table
    a("## 推荐总览")
    a()
    a("| 大佬 | 发言数 | 买入 | 关注 |")
    a("|------|--------|------|------|")
    for user in BIGSHOTS:
        post_count = len(all_posts.get(user, []))
        ps = pick_summary.get(user, {"buy": [], "watch": [], "mention": []})
        buys = ", ".join(set(ps.get("buy", [])))
        watches = ", ".join(set(ps.get("watch", [])))
        a(f"| {user} | {post_count} | {buys or '-'} | {watches or '-'} |")
    a()

    # Detail per大佬
    a("## 详细推荐")
    a()
    for user in BIGSHOTS:
        ps = pick_summary.get(user, {"buy": [], "watch": [], "mention": []})
        buys = set(ps.get("buy", []))
        watches = set(ps.get("watch", []))
        if not buys and not watches:
            continue

        a(f"### {user}")
        a()
        picks = [p for p in all_picks if p["username"] == user]
        for p in picks[:8]:
            emoji = {"buy": "🟢", "watch": "🟡", "sell": "🔴", "mention": "⚪"}.get(p["direction"], "")
            a(f"- {emoji} **{p.get('name', p['code'])}** ({p['code']})")
            ctx = p["text"][:120].replace("\n", " ")
            a(f"  > {ctx}")
        a()

    a("---")
    a()
    a(f"*生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    return "\n".join(L)


if __name__ == "__main__":
    main()
