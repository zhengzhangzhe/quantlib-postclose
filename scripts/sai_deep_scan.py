#!/usr/bin/env python3
"""Sai佬 (幸运阿sai, UID 21321600) 全量发言采集。

两步高效采集：
  A. searchpost 页面翻页 → 提取 sai佬所有回复
  B. 主题帖列表 → 每个帖只读第1页 → 提取 OP 内容
  C. 去重合并 → 清洗短回复 → 保存

Usage:
    python3 scripts/sai_deep_scan.py              # 采集并保存
    python3 scripts/sai_deep_scan.py --dry-run    # 只打印，不保存
"""

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJ = Path(__file__).resolve().parent.parent
DATA_DIR = PROJ / "data" / "nga"
COOKIE_FILE = PROJ / "data" / "nga_cookie.txt"
OUTPUT_FILE = DATA_DIR / "bigshot_content" / "幸运阿sai.json"

SAI_UID = "21321600"
SAI_NAME = "幸运阿sai"

# 短回复/无意义内容过滤
NOISE_PATTERNS = [
    r"^前排\S*$", r"^前排", r"^前排.*$",
    r"^(沙发|板凳|地板)$",
    r"^向大佬学习$", r"^大佬牛逼$", r"^学习[了啦]$",
    r"^mark\S*$", r"^插眼$", r"^支持$", r"^顶$", r"^好帖$",
    r"^先马后看$", r"^收藏$", r"^膜拜$", r"^打卡$",
    r"^\d{1,2}楼$", r"^等着看$", r"^学习了$", r"^来看看$",
    r"^。。+$", r"^\.\.+$", r"^不错$", r"^好$",
    r"^看看$", r"^关注$", r"^插个眼$",
]
NOISE_RE = re.compile("|".join(NOISE_PATTERNS))


def load_cookie() -> str:
    return COOKIE_FILE.read_text().strip() if COOKIE_FILE.exists() else ""


def build_cookies(s: str) -> list[dict]:
    cookies = []
    for pair in s.split("; "):
        if "=" in pair:
            k, v = pair.split("=", 1)
            cookies.append({"name": k, "value": v, "domain": ".nga.cn", "path": "/"})
    return cookies


def is_noise(text: str) -> bool:
    """过滤无意义短回复。"""
    text = text.strip()
    if len(text) < 15:
        return True
    if NOISE_RE.match(text):
        return True
    return False


# ═══════════════════════════════════════════════════════════
# A. 回复采集：searchpost 翻页
# ═══════════════════════════════════════════════════════════

def _max_searchpost_page(page) -> int:
    """Find max page number from searchpost pagination links."""
    max_pg = 1
    for a in page.query_selector_all("a"):
        href = a.get_attribute("href") or ""
        m = re.search(r"searchpost=1.*?page=(\d+)", href)
        if m:
            max_pg = max(max_pg, int(m.group(1)))
    return max_pg


def collect_replies(page) -> list[dict]:
    """翻页 searchpost 页面，提取 sai佬所有回复。"""
    all_replies = []

    # Hit first page to discover max pages
    url = f"https://bbs.nga.cn/thread.php?authorid={SAI_UID}&searchpost=1"
    try:
        page.goto(url, timeout=15000, wait_until="domcontentloaded")
        page.wait_for_timeout(800)
    except Exception as e:
        print(f"超时: {e}")
        return all_replies

    max_pg = _max_searchpost_page(page)
    print(f"  searchpost 共 {max_pg} 页")

    for page_num in range(1, max_pg + 1):
        if page_num > 1:
            url = f"https://bbs.nga.cn/thread.php?authorid={SAI_UID}&searchpost=1&page={page_num}"
            try:
                page.goto(url, timeout=15000, wait_until="domcontentloaded")
                page.wait_for_timeout(800)
            except Exception as e:
                print(f"    第{page_num}页超时: {e}")
                continue

        # Extract: each entry has .topic (thread link), .author, .postcontent
        topic_els = page.query_selector_all("a.topic")
        post_els = page.query_selector_all(".postcontent")

        found = 0
        for i in range(min(len(topic_els), len(post_els))):
            topic_a = topic_els[i]
            href = topic_a.get_attribute("href") or ""
            title = topic_a.inner_text().strip()
            tid_match = re.search(r"tid=(\d+)", href)
            if not tid_match:
                continue

            text = post_els[i].inner_text().strip()
            if not text or is_noise(text):
                continue

            all_replies.append({
                "tid": tid_match.group(1),
                "title": title,
                "page": 0,
                "text": text,
                "source": "searchpost",
            })
            found += 1

        print(f"    第{page_num}页: {found}条")
        time.sleep(0.5)

    return all_replies


# ═══════════════════════════════════════════════════════════
# B. 主题帖采集：只读第1页 OP 内容
# ═══════════════════════════════════════════════════════════

def discover_topics(page) -> list[dict]:
    """从 authorid 页面获取 sai佬所有主题帖。"""
    threads = []
    page_num = 1
    while True:
        url = f"https://bbs.nga.cn/thread.php?authorid={SAI_UID}"
        if page_num > 1:
            url += f"&page={page_num}"
        try:
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            page.wait_for_timeout(800)
        except Exception:
            break

        found = 0
        for a in page.query_selector_all("a.topic"):
            href = a.get_attribute("href") or ""
            title = a.inner_text().strip()
            tid_match = re.search(r"tid=(\d+)", href)
            if tid_match and title:
                threads.append({"tid": tid_match.group(1), "title": title})
                found += 1
        if found == 0:
            break
        page_num += 1
        time.sleep(0.5)

    return threads


def collect_topic_ops(page, threads: list[dict]) -> list[dict]:
    """读取每个主题帖第1页，提取 sai佬 的 OP 内容。"""
    op_posts = []

    for i, t in enumerate(threads):
        tid = t["tid"]
        title = t["title"]
        print(f"  [{i+1}/{len(threads)}] {tid} {title[:50]}...", end=" ", flush=True)

        try:
            page.goto(f"https://bbs.nga.cn/read.php?tid={tid}",
                      timeout=10000, wait_until="domcontentloaded")
            page.wait_for_timeout(500)
        except Exception:
            print("跳过")
            continue

        # Find OP (first post by sai佬, or topic author on page 1)
        author_els = page.query_selector_all("[id^=postauthor]")
        post_els = page.query_selector_all(".postcontent")

        found = 0
        for author_el, post_el in zip(author_els, post_els):
            author = author_el.inner_text().strip()
            if author != SAI_NAME:
                continue
            text = post_el.inner_text().strip()
            if not text or is_noise(text):
                continue
            op_posts.append({
                "tid": tid,
                "title": title,
                "page": 1,
                "text": text,
                "source": "topic_op",
            })
            found += 1

        print(f"{found}条")
        time.sleep(0.3)

    return op_posts


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Sai佬 全量发言采集")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cookie = load_cookie()
    if not cookie:
        print("❌ 无 cookie"); sys.exit(1)

    print("=" * 55)
    print(f"  Sai佬 全量发言采集 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  UID: {SAI_UID}")
    print("=" * 55)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="zh-CN")
        ctx.add_cookies(build_cookies(cookie))
        page = ctx.new_page()

        # A. 回复采集
        print("\n[A] searchpost 回复采集...")
        replies = collect_replies(page)
        print(f"  回复: {len(replies)} 条")

        # B. 主题帖 OP 采集
        print("\n[B] 主题帖列表 + OP 采集...")
        topics = discover_topics(page)
        print(f"  主题帖: {len(topics)} 个")
        ops = collect_topic_ops(page, topics)
        print(f"  OP内容: {len(ops)} 条")

        browser.close()

    # C. 合并去重
    all_posts = replies + ops

    # Dedup by (tid, text[:100])
    seen = set()
    unique = []
    for p in all_posts:
        key = (p["tid"], p["text"][:100])
        if key not in seen:
            seen.add(key)
            unique.append(p)

    # Sort by tid descending (newer first)
    unique.sort(key=lambda x: x["tid"], reverse=True)

    print(f"\n{'=' * 55}")
    print(f"  合计: {len(replies)} 回复 + {len(ops)} OP = {len(all_posts)} 条")
    print(f"  去重后: {len(unique)} 条有效发言")
    print(f"{'=' * 55}")

    if unique:
        by_thread = defaultdict(int)
        for p in unique:
            by_thread[p["tid"]] += 1
        print("\n各帖发言数:")
        # Map tid → title
        tid_title = {}
        for t in topics:
            tid_title[t["tid"]] = t["title"]
        for p in unique:
            tid_title[p["tid"]] = p.get("title", "")
        for tid, count in sorted(by_thread.items(), key=lambda x: -x[1]):
            title = tid_title.get(tid, "")[:60]
            print(f"  {tid}: {count}条 - {title}")

    output = {
        "user": SAI_NAME,
        "uid": SAI_UID,
        "scanned_at": datetime.now().isoformat(),
        "posts_collected": len(unique),
        "threads_scanned": len(topics),
        "posts": unique,
    }

    if args.dry_run:
        print("\n[Dry-run] 未保存")
        return

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n已保存到 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
