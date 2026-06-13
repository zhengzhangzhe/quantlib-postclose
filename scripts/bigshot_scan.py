#!/usr/bin/env python3
"""NGA 大佬全量发言采集。

两步独立 session：
  A. 主题帖 OP — authorid 页面 → 只读第1页
  B. 回复 — searchpost 逐页翻

Usage:
    python3 scripts/bigshot_scan.py --uid 21321600 --name 幸运阿sai
"""

import argparse, json, re, sys, time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJ = Path(__file__).resolve().parent.parent
DATA_DIR = PROJ / "data" / "nga"
COOKIE_FILE = PROJ / "data" / "nga_cookie.txt"

NOISE_PATTERNS = [
    r"^前排\S*$", r"^前排", r"^(沙发|板凳|地板)$",
    r"^向大佬学习$", r"^大佬牛逼$", r"^学习[了啦]$",
    r"^mark\S*$", r"^插眼$", r"^支持$", r"^顶$", r"^好帖$",
    r"^先马后看$", r"^收藏$", r"^膜拜$", r"^打卡$",
    r"^\d{1,2}楼$", r"^看看$", r"^关注$", r"^插个眼$",
    r"^。。+$", r"^\.\.+$", r"^不错$", r"^好$",
]
NOISE_RE = re.compile("|".join(NOISE_PATTERNS))

LOCKED_KW = ["时间超过限制", "帐号权限不足", "锁定"]

# 狼大是6位老UID，searchpost不稳定
OLD_UIDS = {"150058"}


def load_cookie():
    return COOKIE_FILE.read_text().strip() if COOKIE_FILE.exists() else ""

def build_cookies(s):
    return [{"name": k, "value": v, "domain": ".nga.cn", "path": "/"}
            for pair in s.split("; ") if "=" in pair
            for k, v in [pair.split("=", 1)]]

def is_noise(text):
    t = text.strip()
    return len(t) < 30 or bool(NOISE_RE.match(t))

def new_page(cookie_str):
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(locale="zh-CN")
    ctx.add_cookies(build_cookies(cookie_str))
    page = ctx.new_page()
    return p, browser, page


# ═══ A. 主题帖 OP ═══

def scan_topics(page, uid, name):
    """authorid 页面 → 主题帖列表 → 每个帖第1页OP"""
    # Step 1: collect all topics
    topics = []
    for pg in range(1, 20):
        url = f"https://bbs.nga.cn/thread.php?authorid={uid}"
        if pg > 1: url += f"&page={pg}"
        try:
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
        except: break

        topic_els = page.query_selector_all("a.topic")
        tags = [t.inner_text().strip() for t in page.query_selector_all(".titleadd2")]
        found = 0
        for i, a in enumerate(topic_els):
            if i < len(tags) and tags[i] != "[大时代]":
                continue
            href = a.get_attribute("href") or ""
            m = re.search(r"tid=(\d+)", href)
            if m:
                topics.append({"tid": m.group(1), "title": a.inner_text().strip()})
                found += 1
        print(f"  主题列表第{pg}页: {found}个(大时代)")
        if found == 0: break
        time.sleep(1.0)

    print(f"  共{len(topics)}个大时代主题帖")

    # Step 2: read page 1 of each topic
    posts = []
    seen = set()
    valid = 0
    for i, t in enumerate(topics):
        tid, title = t["tid"], t["title"]
        try:
            page.goto(f"https://bbs.nga.cn/read.php?tid={tid}", timeout=10000, wait_until="domcontentloaded")
            page.wait_for_timeout(800)
        except: continue

        body = page.inner_text("body")
        if any(kw in body for kw in LOCKED_KW):
            continue
        valid += 1

        ae = page.query_selector_all("[id^=postauthor]")
        pe = page.query_selector_all(".postcontent")
        found = 0
        for a, p in zip(ae, pe):
            if a.inner_text().strip() != name: continue
            text = p.inner_text().strip()
            if not text or is_noise(text): continue
            key = (tid, text[:100])
            if key in seen: continue
            seen.add(key)
            posts.append({"tid": tid, "title": title, "page": 1, "text": text, "source": "topic_op"})
            found += 1
        if found:
            print(f"  [{i+1}] {tid}: {found}条 {title[:50]}")
        time.sleep(0.5)

    print(f"  有效主题帖: {valid}/{len(topics)}, OP内容: {len(posts)}条")
    return posts


# ═══ B. 回复 searchpost ═══

def scan_replies(page, uid, name):
    """searchpost 逐页翻，每页间隔1.5s"""
    posts = []
    empty_streak = 0
    max_empty = 3 if uid in OLD_UIDS else 2

    for pg in range(1, 100):
        url = f"https://bbs.nga.cn/thread.php?searchpost=1&authorid={uid}"
        if pg > 1: url += f"&page={pg}"

        try:
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
        except:
            empty_streak += 1
            if empty_streak >= max_empty: break
            continue

        topic_els = page.query_selector_all("a.topic")
        post_els = page.query_selector_all(".postcontent")
        tags = [t.inner_text().strip() for t in page.query_selector_all(".titleadd2")]

        found = 0
        for i in range(min(len(topic_els), len(post_els))):
            if i < len(tags) and tags[i] != "[大时代]":
                continue
            href = topic_els[i].get_attribute("href") or ""
            m = re.search(r"tid=(\d+)", href)
            if not m: continue
            text = post_els[i].inner_text().strip()
            if not text or is_noise(text): continue
            posts.append({
                "tid": m.group(1),
                "title": topic_els[i].inner_text().strip(),
                "page": 0, "text": text, "source": "searchpost",
            })
            found += 1

        print(f"  第{pg}页: {found}条")

        if found == 0:
            empty_streak += 1
            if empty_streak >= max_empty:
                print(f"  连续{empty_streak}页空，停止")
                break
        else:
            empty_streak = 0

        time.sleep(1.5)

    return posts


# ═══ Main ═══

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uid", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    uid, name = args.uid, args.name
    cookie = load_cookie()
    if not cookie:
        print("❌ 无 cookie"); sys.exit(1)

    print(f"\n{'='*55}")
    print(f"  {name} (UID: {uid})")
    print(f"{'='*55}")

    all_posts = []

    # A. 主题帖 OP（独立 session）
    print("\n[A] 主题帖 OP...")
    p, browser, page = new_page(cookie)
    try:
        ops = scan_topics(page, uid, name)
        all_posts.extend(ops)
    finally:
        browser.close()
        p.stop()

    # B. 回复 searchpost（独立 session）
    print("\n[B] searchpost 回复...")
    p, browser, page = new_page(cookie)
    try:
        replies = scan_replies(page, uid, name)
        all_posts.extend(replies)
    finally:
        browser.close()
        p.stop()

    # 去重
    seen = set()
    unique = []
    for p in all_posts:
        key = (p["tid"], p["text"][:100])
        if key not in seen:
            seen.add(key)
            unique.append(p)
    unique.sort(key=lambda x: x["tid"], reverse=True)

    # 统计
    n_op = sum(1 for p in unique if p["source"] == "topic_op")
    n_rp = sum(1 for p in unique if p["source"] == "searchpost")
    n_tids = len(set(p["tid"] for p in unique))
    n_chars = sum(len(p["text"]) for p in unique)

    print(f"\n{'='*55}")
    print(f"  {name}: {len(unique)}条 = {n_op}OP + {n_rp}回复")
    print(f"  覆盖{n_tids}个线程, {n_chars:,}字")
    print(f"{'='*55}")

    # 保存
    out = DATA_DIR / "bigshot_content" / f"{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump({
            "user": name, "uid": uid,
            "scanned_at": datetime.now().isoformat(),
            "posts_collected": len(unique),
            "posts": unique,
        }, f, ensure_ascii=False, indent=2)
    print(f"已保存 {out}")


if __name__ == "__main__":
    main()
