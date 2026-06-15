#!/usr/bin/env python3
"""增量更新大佬发言 —— 按时间驱动，只收最近7天的新帖。

searchpost 翻页 → 解析 .postdate (MM-DD HH:MM) → 超过7天就停
topic list 翻页 → 新tid读OP → 已有跳过

Usage:
    python3 scripts/bigshot_incremental.py
"""

import json, re, sys, time
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJ = Path(__file__).resolve().parent.parent
DATA_DIR = PROJ / "data" / "nga"
COOKIE_FILE = PROJ / "data" / "nga_cookie.txt"
CONTENT_DIR = DATA_DIR / "bigshot_content"

BIGSHOTS = [
    ("21321600", "幸运阿sai", "幸运阿sai"),
    ("60916468", "灰兔尾", "灰兔尾"),
    ("66278813", "文驹", "文驹"),
    ("150058", "-阿狼-", "-阿狼-"),
    ("66662897", "fuelish", "F佬"),
    ("61233918", "喜帖街QAQ", "喜帖街QAQ"),
    ("370218", "猫指导", "猫指导"),
]

CUTOFF_DAYS = 7
LOCKED_KW = ["时间超过限制", "帐号权限不足", "锁定"]


def load_cookie():
    return COOKIE_FILE.read_text().strip() if COOKIE_FILE.exists() else ""


def build_cookies(s):
    return [{"name": k, "value": v, "domain": ".nga.cn", "path": "/"}
            for pair in s.split("; ") if "=" in pair
            for k, v in [pair.split("=", 1)]]


def parse_postdate(text: str, today: date) -> date | None:
    """解析 .postdate 格式: 'MM-DD HH:MM' 返回 date。"""
    m = re.match(r"(\d{2})-(\d{2})\s", text.strip())
    if not m:
        return None
    mm, dd = int(m.group(1)), int(m.group(2))
    # 尝试今年
    d = date(today.year, mm, dd)
    # 如果日期在未来 → 去年
    if d > today:
        d = date(today.year - 1, mm, dd)
    return d


def is_noise(text):
    return len(text.strip()) < 30


def main():
    cookie = load_cookie()
    if not cookie:
        print("❌ 无 cookie"); sys.exit(1)

    today = date.today()
    cutoff = today - timedelta(days=CUTOFF_DAYS)
    print(f"增量采集 · {today} · 只收 {cutoff} 之后的发言\n")

    total_new = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="zh-CN")
        ctx.add_cookies(build_cookies(cookie))
        page = ctx.new_page()

        for uid, name, display in BIGSHOTS:
            print(f"--- {display} (UID:{uid}) ---")

            # Load existing
            existing = CONTENT_DIR / f"{name}.json"
            old_posts = {}
            if existing.exists():
                with open(existing) as f:
                    old = json.load(f)
                old_posts = {(p["tid"], p["text"][:100]): p for p in old["posts"]}
            print(f"  已有 {len(old_posts)} 条")

            new_posts = []

            # === A. 主题帖 OP（按时间增量：authorid页最新在前，2页无新即停） ===
            topics = []
            zero_new_streak = 0
            for pg_num in range(1, 100):
                url = f"https://bbs.nga.cn/thread.php?authorid={uid}"
                if pg_num > 1:
                    url += f"&page={pg_num}"
                try:
                    page.goto(url, timeout=15000, wait_until="domcontentloaded")
                    page.wait_for_timeout(600)
                except:
                    break
                page_new = 0
                for a in page.query_selector_all("a.topic"):
                    href = a.get_attribute("href") or ""
                    m = re.search(r"tid=(\d+)", href)
                    if m:
                        tid = m.group(1)
                        if not any(k[0] == tid for k in old_posts):
                            topics.append({"tid": tid, "title": a.inner_text().strip()})
                            page_new += 1
                if page_new == 0:
                    zero_new_streak += 1
                    if zero_new_streak >= 2:
                        break
                else:
                    zero_new_streak = 0
                if not page.query_selector_all("a.topic"):
                    break
                time.sleep(0.3)

            op_new = 0
            for t in topics[:10]:  # 最多10个新主题帖
                tid = t["tid"]
                try:
                    page.goto(f"https://bbs.nga.cn/read.php?tid={tid}", timeout=10000, wait_until="domcontentloaded")
                    page.wait_for_timeout(400)
                except:
                    continue
                body = page.inner_text("body")
                if any(kw in body for kw in LOCKED_KW):
                    continue
                ae = page.query_selector_all("[id^=postauthor]")
                pe = page.query_selector_all(".postcontent")
                for a, p_el in zip(ae, pe):
                    if a.inner_text().strip() != name:
                        continue
                    text = p_el.inner_text().strip()
                    if is_noise(text):
                        continue
                    key = (tid, text[:100])
                    if key not in old_posts:
                        new_posts.append({"tid": tid, "title": t["title"], "page": 1, "text": text, "source": "topic_op"})
                        op_new += 1
                time.sleep(0.2)
            if op_new:
                print(f"  OP新增: {op_new} 条")

            # === B. searchpost 回复（时间驱动） ===
            sp_new = 0
            for pg_num in range(1, 100):
                url = f"https://bbs.nga.cn/thread.php?searchpost=1&authorid={uid}"
                if pg_num > 1:
                    url += f"&page={pg_num}"
                try:
                    page.goto(url, timeout=15000, wait_until="domcontentloaded")
                    page.wait_for_timeout(600)
                except:
                    break

                topic_els = page.query_selector_all("a.topic")
                post_els = page.query_selector_all(".postcontent")
                date_els = page.query_selector_all(".postdate")

                # 先看本页最后一条的时间，超过7天则整页及之后全是旧帖 → 停
                if date_els and topic_els:
                    last_i = min(len(date_els), len(topic_els)) - 1
                    last_date = parse_postdate(date_els[last_i].inner_text().strip(), today)
                    if last_date and last_date < cutoff:
                        print(f"  searchpost p{pg_num}: 最后一条 {last_date} 已超7天, 停止")
                        break

                found = 0
                for i in range(min(len(topic_els), len(post_els))):
                    post_date = None
                    if i < len(date_els):
                        post_date = parse_postdate(date_els[i].inner_text().strip(), today)
                    # 超过7天的跳过
                    if post_date and post_date < cutoff:
                        continue

                    href = topic_els[i].get_attribute("href") or ""
                    m = re.search(r"tid=(\d+)", href)
                    if not m:
                        continue
                    text = post_els[i].inner_text().strip()
                    if is_noise(text):
                        continue

                    key = (m.group(1), text[:100])
                    if key in old_posts:
                        continue

                    new_posts.append({
                        "tid": m.group(1),
                        "title": topic_els[i].inner_text().strip(),
                        "page": 0, "text": text, "source": "searchpost",
                        "post_date": post_date.isoformat() if post_date else None,
                    })
                    found += 1

                sp_new += found

                if pg_num % 5 == 1 or found > 0:
                    print(f"  searchpost p{pg_num}: +{found}新")

                time.sleep(0.5)

            n = op_new + sp_new
            print(f"  → 本周新增: {n} 条\n")
            total_new += n

            if n > 0:
                all_posts = list(old_posts.values()) + new_posts
                all_posts.sort(key=lambda x: x["tid"], reverse=True)
                output = {
                    "user": name, "uid": uid,
                    "scanned_at": datetime.now().isoformat(),
                    "posts_collected": len(all_posts),
                    "posts": all_posts,
                }
                existing.parent.mkdir(parents=True, exist_ok=True)
                with open(existing, "w") as f:
                    json.dump(output, f, ensure_ascii=False, indent=2)
                # F佬 alias
                if display == "F佬":
                    with open(CONTENT_DIR / "F佬.json", "w") as f:
                        json.dump(output, f, ensure_ascii=False, indent=2)

        browser.close()

    print(f"总计新增 {total_new} 条")
    if total_new == 0:
        print("(本周无新发言)")


if __name__ == "__main__":
    main()
