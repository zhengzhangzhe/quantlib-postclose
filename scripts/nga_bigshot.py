#!/usr/bin/env python3
"""NGA 大时代「大佬」挖掘器 v4.

规则：每条回复找「X佬/X指导/X大」→ 看回复对象(+R by)或帖主(OP)是否匹配 → 计数。

Usage:
    python3 scripts/nga_bigshot.py --save
    python3 scripts/nga_bigshot.py --json
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJ = Path(__file__).resolve().parent.parent
DATA_DIR = PROJ / "data" / "nga" / "bigshots"
COOKIE_FILE = PROJ / "data" / "nga_cookie.txt"


def load_cookie() -> str:
    return COOKIE_FILE.read_text().strip() if COOKIE_FILE.exists() else ""


def build_cookies(s: str) -> list[dict]:
    cookies = []
    for pair in s.split("; "):
        if "=" in pair:
            k, v = pair.split("=", 1)
            cookies.append({"name": k, "value": v, "domain": ".nga.cn", "path": "/"})
    return cookies


def nick_matches(nick: str, username: str) -> bool:
    """Check if X in X佬 plausibly refers to username."""
    nl = nick.lower().strip()
    ul = username.lower()
    if len(nl) < 1 or len(nl) > 4:
        return False
    # Common Chinese chars that are NOT valid nicknames
    noise = set("大了什怎这那我你一不么没还就和的有在到看跟把被让给为从对向"
                "与如同比更最都很也才可能想要说做来去上下里外中前后左右各位"
                "多少谢新旧小长今明昨啊吧呢吗哦哎哈哇呵哟噢咧嘛哪")
    if nl in noise:
        return False
    # English single char: must start username AND appear >=2 times
    if len(nl) == 1 and nl.isascii():
        generic = set("ABCTXYZIOUMNS")
        if nl.upper() in generic:
            return False
        return ul.startswith(nl)
    # Chinese or multi-char: anywhere
    return nl in ul


def main():
    parser = argparse.ArgumentParser(description="NGA 大时代 大佬挖掘器 v4")
    parser.add_argument("--forum-pages", type=int, default=5)
    parser.add_argument("--tail-pages", type=int, default=40)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    cookie = load_cookie()
    if not cookie:
        print("❌ 无 cookie"); sys.exit(1)

    print(f"NGA 大佬挖掘 v4 · {datetime.now().strftime('%H:%M')}")
    print(f"搜 {args.forum_pages} 页论坛 × 尾 {args.tail_pages} 页\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="zh-CN")
        ctx.add_cookies(build_cookies(cookie))
        page = ctx.new_page()

        # Get all threads
        tids = []
        for pg in range(1, args.forum_pages + 1):
            try:
                page.goto(f"https://bbs.nga.cn/thread.php?fid=706&page={pg}",
                          timeout=10000, wait_until="domcontentloaded")
                page.wait_for_timeout(800)
            except: break
            for link in page.query_selector_all("a.topic"):
                href = link.get_attribute("href") or ""
                m = re.search(r'tid=(\d+)', href)
                if m and m.group(1) not in [t[0] for t in tids]:
                    tids.append((m.group(1), link.inner_text()[:60]))
        print(f"获取 {len(tids)} 个帖子")

        # Scan each thread
        all_mentions = []
        total_pages = 0

        for i, (tid, title) in enumerate(tids):
            try:
                page.goto(f"https://bbs.nga.cn/read.php?tid={tid}",
                          timeout=8000, wait_until="domcontentloaded")
                page.wait_for_timeout(500)
            except: continue

            op_el = page.query_selector("#postauthor0")
            if not op_el:
                op_el = page.query_selector("#topicAuthorName")
            op = op_el.inner_text().strip() if op_el else ""

            max_pg = 1
            for a in page.query_selector_all("a"):
                href = a.get_attribute("href") or ""
                for pg_m in re.finditer(r'page=(\d+)', href):
                    max_pg = max(max_pg, int(pg_m.group(1)))

            # Collect ALL +R by targets in this thread (for relaxed matching)
            tid_targets = set()
            if op:
                tid_targets.add(op)

            # Spread scan: head, middle, tail
            pages = {1, 2}
            for offset in range(args.tail_pages):
                pg = min(max_pg - offset, 300)
                if pg > 2: pages.add(pg)
            # For deep threads, also scan middle
            if max_pg > 100:
                mid = max_pg // 2
                for offset in range(min(10, args.tail_pages // 2)):
                    pg = min(mid + offset, 300)
                    if pg > 2 and pg < max_pg: pages.add(pg)

            for pg in sorted(pages):
                try:
                    url = f"https://bbs.nga.cn/read.php?tid={tid}"
                    if pg > 1: url += f"&page={pg}"
                    page.goto(url, timeout=8000, wait_until="domcontentloaded")
                    page.wait_for_timeout(300)
                except: continue
                total_pages += 1

                for post in page.query_selector_all(".postcontent"):
                    text = post.inner_text()

                    # Collect quoted users
                    local_targets = set()
                    for m in re.finditer(r"\+R by \[([^\]]+)\]", text):
                        user = m.group(1)
                        local_targets.add(user)
                        tid_targets.add(user)

                    if "佬" not in text and "指导" not in text and "大" not in text:
                        continue

                    # Targets: local (+R by in this reply) first, then OP + tid_targets
                    targets = list(local_targets)
                    if op and op not in targets:
                        targets.append(op)
                    for u in tid_targets:
                        if u not in targets:
                            targets.append(u)

                    # Find X佬 / X指导 / X大 mentions
                    for m in re.finditer(r"([\w一-鿿]{1,4}?)(?:佬|指导|大(?!佬))", text):
                        raw = m.group(1).strip()
                        matched_user = ""
                        for end in range(min(len(raw), 4), 0, -1):
                            nick = raw[-end:]
                            for t in targets:
                                if nick_matches(nick, t):
                                    matched_user = t
                                    break
                            if matched_user:
                                break
                        if matched_user:
                            all_mentions.append({
                                "username": matched_user,
                                "nickname": m.group(0),
                                "text": text[:200],
                                "tid": tid,
                                "title": title,
                            })

            if (i + 1) % 20 == 0:
                print(f"  {i+1}/{len(tids)}, {len(all_mentions)} mentions")

        browser.close()

    if not all_mentions:
        print("未发现"); return

    # Aggregate
    counter = Counter(m["username"] for m in all_mentions)

    if args.json:
        ranked = []
        for uname, count in counter.most_common(30):
            mentions = [m for m in all_mentions if m["username"] == uname]
            ranked.append({
                "username": uname, "mentions": count,
                "nicknames": list(set(m["nickname"] for m in mentions)),
                "samples": [m["text"][:120] for m in mentions[:3]],
            })
        print(json.dumps({"time": datetime.now().isoformat(), "bigshots": ranked},
                         ensure_ascii=False, indent=2))
    else:
        for i, (uname, count) in enumerate(counter.most_common(20), 1):
            mentions = [m for m in all_mentions if m["username"] == uname]
            nicks = "/".join(set(m["nickname"] for m in mentions))
            print(f"  {i:2d}. {uname:20s} {nicks:20s} ({count}次)")
            for m in mentions[:2]:
                print(f"      {m['text'][:100]}")

    if args.save and counter:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        ranked = []
        for uname, count in counter.most_common(30):
            mentions = [m for m in all_mentions if m["username"] == uname]
            ranked.append({
                "username": uname, "mentions": count,
                "nicknames": list(set(m["nickname"] for m in mentions)),
                "samples": [m["text"][:120] for m in mentions[:3]],
            })
        with open(DATA_DIR / f"{today}.json", "w") as f:
            json.dump({"date": today, "bigshots": ranked}, f, ensure_ascii=False, indent=2)
        print(f"快照: {DATA_DIR / f'{today}.json'}")


if __name__ == "__main__":
    main()
