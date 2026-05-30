#!/usr/bin/env python3
"""NGA 大时代 热帖抓取 + 关键词热度。

Usage:
    python3 scripts/nga_scraper.py                     # Print top 20 threads
    python3 scripts/nga_scraper.py --json               # Output JSON
"""

import json
import re
import sys
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
COOKIE_FILE = PROJ / "data" / "nga_cookie.txt"

KEYWORDS = {
    # A股板块/概念
    "半导体", "芯片", "AI", "人工智能", "算力", "光模块", "CPO",
    "机器人", "自动驾驶", "智能驾驶", "汽车", "新能源", "光伏", "储能", "电池",
    "医药", "消费", "白酒", "食品", "银行", "券商", "保险",
    "房地产", "化工", "有色", "煤炭", "石油", "黄金",
    "上证", "深证", "创业板", "科创板", "北交",
    "涨停", "跌停", "连板", "炸板", "分歧", "缩量", "放量",
    "美股", "纳斯达克", "纳指", "标普", "道琼斯", "港股", "恒指",
    "利好", "利空", "加息", "降息", "政策", "关税", "制裁",
    "主力", "游资", "机构", "散户", "量化",
    "PCB", "面板", "玻璃基板", "光刻机", "EDA",
    "军工", "航天", "低空经济", "飞行汽车",
    "电力", "电网", "核电", "风电", "绿电",
    "次新股", "ST", "高股息", "红利", "出海", "国产替代",
    "存储", "HBM", "铜缆", "连接器", "封装", "先进封装",
    "通信", "5G", "6G", "卫星", "光通信", "光纤",
    "鸿蒙", "华为", "小米", "苹果", "特斯拉",
    "药明", "减肥药", "CRO", "创新药", "疫苗",
    "大金融", "中特估", "国企改革", "市值管理",
    "原油", "天然气", "锂", "钴", "稀土", "铜", "铝",
    "数据中心", "云计算", "服务器",
    "核聚变", "超导", "量子", "固态电池", "钠电池",
    "鸿蒙原生", "欧拉", "鲲鹏", "昇腾",
    "可转债", "ETF", "基金", "北向", "融资融券",
    "抖音", "微信", "TikTok", "出海",
    "GPT", "ChatGPT", "DeepSeek", "Sora",
}


def load_cookie() -> str:
    if COOKIE_FILE.exists():
        return COOKIE_FILE.read_text().strip()
    return ""


def fetch_threads() -> list[dict]:
    """Fetch NGA 大时代 thread list via curl (fast, reliable)."""
    cookie = load_cookie()
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    url = "https://bbs.nga.cn/thread.php?fid=706"

    cmd = ["curl", "-s", "--max-time", "15", url,
           "-H", f"User-Agent: {ua}",
           "-H", "Accept-Language: zh-CN,zh;q=0.9"]
    if cookie:
        cmd.extend(["-b", cookie])

    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20)
        html = r.stdout.decode("gbk", errors="ignore")
    except Exception:
        html = r.stdout.decode("gb18030", errors="ignore") if r and r.stdout else ""

    if not html:
        return []

    titles = re.findall(r"topic'>(.*?)</a>", html)
    authors = re.findall(r'nuke\.php[^>]+>(.*?)</a>', html)

    threads = []
    for i in range(min(len(titles), len(authors))):
        title = re.sub(r"<[^>]+>", "", titles[i]).strip()
        if title and len(title) > 2:
            threads.append({"title": title, "author": authors[i].strip()})

    return threads


def extract_keywords(threads: list[dict]) -> list[tuple]:
    text = "".join(t["title"] for t in threads)
    hits = Counter()
    for kw in KEYWORDS:
        cnt = text.count(kw)
        if cnt > 0:
            hits[kw] = cnt
    return hits.most_common(15)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="NGA 大时代 热帖抓取")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    print(f"NGA 大时代 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    threads = fetch_threads()
    if not threads:
        print("❌ 无法获取数据（cookie 过期或网络问题）")
        sys.exit(1)

    keywords = extract_keywords(threads)

    if args.json:
        print(json.dumps({
            "time": datetime.now().isoformat(),
            "count": len(threads),
            "threads": threads[:args.top],
            "keywords": [{"word": k, "count": c} for k, c in keywords],
        }, ensure_ascii=False, indent=2))
        return

    print()
    for i, t in enumerate(threads[:args.top], 1):
        print(f"  {i:2d}. [{t['author']}] {t['title'][:70]}")

    print(f"\n🔥 关键词: {' · '.join(f'{k}({c})' for k,c in keywords)}")


if __name__ == "__main__":
    main()
