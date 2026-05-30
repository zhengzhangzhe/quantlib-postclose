#!/usr/bin/env python3
"""NGA 大时代「大佬」挖掘器。

找出被社区称呼为「X佬」「X指导」「X大」的用户。

Usage:
    python3 scripts/nga_bigshot.py                  # Console
    python3 scripts/nga_bigshot.py --save --json     # Save snapshot + JSON
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJ = Path(__file__).resolve().parent.parent
DATA_DIR = PROJ / "data" / "nga" / "bigshots"
COOKIE_FILE = PROJ / "data" / "nga_cookie.txt"

NOISE_CHARS = set(
    "大了什怎这那我你一不么没还就和的有在到看跟把被让给为从对向与如同比"
    "更最都很也才可能想要说做来去上下里外中前后左右各位多少谢新旧小长今明"
    "昨每整全任何再又已经将正只虽然但而或因为所以如果之其此当於于与且及乃"
    "啊吧呢吗哦哎哈哇呵哟噢咧嘛哪"
)
GENERIC_EN = set("ABCTXYZIOUMNS")


def load_cookie() -> str:
    return COOKIE_FILE.read_text().strip() if COOKIE_FILE.exists() else ""


def build_cookie_data(s: str) -> list[dict]:
    cookies = []
    for pair in s.split("; "):
        if "=" in pair:
            k, v = pair.split("=", 1)
            cookies.append({"name": k, "value": v, "domain": ".nga.cn", "path": "/"})
    return cookies


def _try_match(nick: str, candidates: list, quoted: set, op: str) -> str:
    """Match nickname to username. quoted users take priority."""
    # Priority 1: quoted users in the same reply
    for uname in quoted:
        if nick_matches(nick, uname):
            return uname
    # Priority 2: OP of the thread
    if op and nick_matches(nick, op):
        return op
    # Priority 3: candidates (already priority-ordered by caller)
    for uname in candidates:
        if nick_matches(nick, uname):
            return uname
    return ""


def nick_matches(nick: str, username: str) -> bool:
    nl = nick.lower().strip()
    ul = username.lower()
    if not nl or nl in NOISE_CHARS:
        return False
    if len(nl) == 1 and nl.isascii():
        if nl.upper() in GENERIC_EN:
            return False
        return ul.startswith(nl) and ul.count(nl) >= 1
    # Single Chinese: anywhere in username (quality gated by +R by filter)
    if len(nl) == 1:
        return nl in ul
    return nl in ul


def main():
    parser = argparse.ArgumentParser(description="NGA 大时代 大佬挖掘器")
    parser.add_argument("--forum-pages", type=int, default=6)
    parser.add_argument("--tail-pages", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    cookie = load_cookie()
    if not cookie:
        print("❌ 无 cookie"); sys.exit(1)

    print(f"NGA 大佬挖掘 · {datetime.now().strftime('%H:%M')}")
    print(f"搜 {args.forum_pages} 页论坛 × 每帖尾 {args.tail_pages} 页\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="zh-CN")
        ctx.add_cookies(build_cookie_data(cookie))
        page = ctx.new_page()

        # ── Get all thread TIDs ──
        tids = []
        for pg in range(1, args.forum_pages + 1):
            try:
                page.goto(f"https://bbs.nga.cn/thread.php?fid=706&page={pg}",
                          timeout=10000, wait_until="domcontentloaded")
                page.wait_for_timeout(1000)
            except: break
            links = page.query_selector_all("a.topic")
            for link in links:
                href = link.get_attribute("href") or ""
                m = re.search(r'tid=(\d+)', href)
                if m and m.group(1) not in [t[0] for t in tids]:
                    tids.append((m.group(1), link.inner_text()[:60]))
        print(f"获取 {len(tids)} 个帖子")

        # ── Phase 1: Build username pool from tail pages ──
        print("Phase 1: 收集用户名池...")
        all_users = set()
        thread_info = {}  # tid -> {op, max_page}

        for i, (tid, _) in enumerate(tids):
            try:
                page.goto(f"https://bbs.nga.cn/read.php?tid={tid}",
                          timeout=8000, wait_until="domcontentloaded")
                page.wait_for_timeout(500)
            except: continue

            op_el = page.query_selector("#topicAuthorName")
            op = op_el.inner_text().strip() if op_el else ""
            if op: all_users.add(op)

            max_pg = 1
            for a in page.query_selector_all("a"):
                href = a.get_attribute("href") or ""
                for pg_m in re.finditer(r'page=(\d+)', href):
                    max_pg = max(max_pg, int(pg_m.group(1)))
            thread_info[tid] = {"op": op, "max_page": max_pg}

            # Scan tail pages for users
            pages = {1, 2}
            for offset in range(args.tail_pages):
                pg = min(max_pg - offset, 200)
                if pg > 2: pages.add(pg)

            for pg in sorted(pages):
                try:
                    url = f"https://bbs.nga.cn/read.php?tid={tid}"
                    if pg > 1: url += f"&page={pg}"
                    page.goto(url, timeout=8000, wait_until="domcontentloaded")
                    page.wait_for_timeout(300)
                except: continue
                # Authors
                for el in page.query_selector_all("[id^=postauthor]"):
                    all_users.add(el.inner_text().strip())
                # Quoted
                for post in page.query_selector_all(".postcontent"):
                    for m in re.finditer(r"\+R by \[([^\]]+)\]", post.inner_text()):
                        all_users.add(m.group(1))

            if (i + 1) % 20 == 0:
                print(f"  {i+1}/{len(tids)}, {len(all_users)} users")

        print(f"  完成: {len(all_users)} 个用户\n")

        # ── Phase 2: Find大佬 mentions ──
        print("Phase 2: 匹配 X佬/X指导/X大...")
        all_mentions = []
        all_quoted = set()  # ALL +R by usernames (for quality filter)
        thread_quoted = {}  # tid → set of usernames quoted in that thread

        for i, (tid, title) in enumerate(tids):
            info = thread_info.get(tid, {})
            max_pg = info.get("max_page", 1)
            op = info.get("op", "")
            tid_quoted = set()  # quoted users in THIS thread
            thread_quoted[tid] = tid_quoted

            pages = {1, 2}
            for offset in range(args.tail_pages):
                pg = min(max_pg - offset, 200)
                if pg > 2: pages.add(pg)

            for pg in sorted(pages):
                try:
                    url = f"https://bbs.nga.cn/read.php?tid={tid}"
                    if pg > 1: url += f"&page={pg}"
                    page.goto(url, timeout=8000, wait_until="domcontentloaded")
                    page.wait_for_timeout(300)
                except: continue

                for post in page.query_selector_all(".postcontent"):
                    text = post.inner_text()

                    # Extract quoted users (highest priority for matching)
                    quoted = set()
                    for m in re.finditer(r"\+R by \[([^\]]+)\]", text):
                        qname = m.group(1)
                        quoted.add(qname)
                        all_quoted.add(qname)
                        tid_quoted.add(qname)  # per-thread tracking

                    # Build priority candidates (same-reply → per-thread → global)
                    candidates = list(quoted)
                    for u in tid_quoted:
                        if u not in candidates: candidates.append(u)
                    if op and op not in candidates: candidates.append(op)
                    for u in all_quoted:
                        if u not in candidates: candidates.append(u)
                    for u in all_users:
                        if u not in candidates: candidates.append(u)

                    # Helper: try all nick suffix lengths, shortest first
                    def try_nick(raw, candidates, strict_quoted=False):
                        for end in range(1, min(len(raw) + 1, 5)):
                            nick = raw[-end:]
                            if nick in NOISE_CHARS: continue
                            pool = list(quoted) if strict_quoted else candidates
                            mu = _try_match(nick, pool, quoted, op)
                            if mu: return mu
                        return ""

                    # Find X佬 / X指导
                    for m in re.finditer(r"([\w一-鿿]{1,4})(?:佬|指导)", text):
                        mu = try_nick(m.group(1).strip(), candidates)
                        if mu:
                            all_mentions.append({"username": mu, "nickname": m.group(0), "text": text[:200], "tid": tid, "title": title})

                    # X大: only match against quoted users
                    for m in re.finditer(r"([\w一-鿿]{1,4})大(?!佬)", text):
                        if not quoted: continue
                        mu = try_nick(m.group(1).strip(), candidates, strict_quoted=True)
                        if mu:
                            all_mentions.append({"username": mu, "nickname": m.group(0), "text": text[:200], "tid": tid, "title": title})

            if (i + 1) % 20 == 0:
                print(f"  {i+1}/{len(tids)}, {len(all_mentions)} mentions")

        browser.close()

    if not all_mentions:
        print("未发现大佬"); return

    # ── Filter: user must appear in at least one +R by across ALL scanned text ──
    before = len(all_mentions)
    all_mentions = [m for m in all_mentions if m["username"] in all_quoted]
    print(f"  过滤: {before} → {len(all_mentions)} ({len(all_quoted)}人有+R by)")
    if not all_mentions:
        print("未发现大佬"); return

    # ── Aggregate ──
    counter = Counter(m["username"] for m in all_mentions)
    ranked = []
    for uname, count in counter.most_common(30):
        mentions = [m for m in all_mentions if m["username"] == uname]
        nicknames = list(set(m["nickname"] for m in mentions))
        samples = []
        threads = set()
        for m in mentions:
            threads.add(m.get("title", "")[:30])
            if len(samples) < 3:
                samples.append(f"{m['nickname']}: {m['text'][:100]}")

        ranked.append({
            "username": uname, "mentions": count,
            "nicknames": nicknames, "samples": samples,
            "threads": list(threads)[:3],
        })

    if args.json:
        print(json.dumps({"time": datetime.now().isoformat(), "bigshots": ranked},
                         ensure_ascii=False, indent=2))
    else:
        for i, r in enumerate(ranked, 1):
            nicks = "/".join(r["nicknames"][:4])
            print(f"  {i:2d}. {r['username']:20s} {nicks:20s} ({r['mentions']}次)")
            for s in r["samples"][:2]:
                print(f"      {s[:100]}")
            if r["threads"]:
                print(f"      📌 {' · '.join(r['threads'][:2])}")
            print()

    if args.save and ranked:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        with open(DATA_DIR / f"{today}.json", "w") as f:
            json.dump({"date": today, "bigshots": ranked}, f, ensure_ascii=False, indent=2)
        print(f"快照: {DATA_DIR / f'{today}.json'}")


if __name__ == "__main__":
    main()
