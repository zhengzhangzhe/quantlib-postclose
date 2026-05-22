#!/usr/bin/env python3
"""Weekly institute research report heat tracker.

Fetches actual research reports from 东方财富 report list API,
aggregates by industry/institution/stock, and generates a standalone markdown report.

Usage:
    python3 scripts/institute_attention.py                      # This week
    python3 scripts/institute_attention.py --date 2026-05-23    # Specific date

Output:
    output/institute_attention/{date}/weekly.md
    data/institute_attention/{date}.json
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

# ── Paths ──
PROJ = Path(__file__).resolve().parent.parent
OUTPUT = PROJ / "output" / "institute_attention"
DATA_DIR = PROJ / "data" / "institute_attention"

API_URL = "https://reportapi.eastmoney.com/report/list"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
_DOW = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _day_of_week(date_str: str) -> str:
    return _DOW[date.fromisoformat(date_str).weekday()]


# ═══════════════════════════════════════════════════════════
# DATA LAYER
# ═══════════════════════════════════════════════════════════

def fetch_reports(begin: str, end: str) -> list[dict]:
    """Fetch all research reports in date range (paginated)."""
    all_reports = []
    page = 1
    while True:
        params = {
            "industryCode": "*", "pageSize": 50, "pageNo": page,
            "beginTime": begin, "endTime": end,
            "qType": 0, "code": "*",
        }
        try:
            r = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"    [warn] API 第{page}页失败: {e}")
            break

        reports = data.get("data") or []
        if not reports:
            break
        all_reports.extend(reports)
        if len(reports) < 50:
            break
        page += 1
        time.sleep(0.3)  # rate limit

    return all_reports


def aggregate_reports(reports: list[dict]) -> dict:
    """Aggregate reports by industry, institution, stock."""
    by_industry = Counter()
    by_org = Counter()
    by_stock = Counter()
    industry_samples = {}  # industry -> list of (title, org)
    rating_by_industry = {}  # industry -> Counter of ratings

    for r in reports:
        ind = r.get("indvInduName", "") or "未分类"
        org = r.get("orgSName", "") or "未知机构"
        stock = r.get("stockName", "") or "未知"
        title = r.get("title", "")
        rating = r.get("emRatingName", "")

        by_industry[ind] += 1
        by_org[org] += 1
        by_stock[stock] += 1

        if ind not in industry_samples:
            industry_samples[ind] = []
        if len(industry_samples[ind]) < 3:
            industry_samples[ind].append((title, org, stock))

        if ind not in rating_by_industry:
            rating_by_industry[ind] = Counter()
        if rating:
            rating_by_industry[ind][rating] += 1

    return {
        "total": len(reports),
        "by_industry": by_industry,
        "by_org": by_org,
        "by_stock": by_stock,
        "industry_samples": industry_samples,
        "rating_by_industry": rating_by_industry,
    }


def load_previous_week(date_str: str) -> dict | None:
    """Load the most recent prior-week snapshot."""
    d = date.fromisoformat(date_str)
    for i in range(1, 15):
        prev = (d - timedelta(days=i)).isoformat()
        path = DATA_DIR / f"{prev}.json"
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                if isinstance(data, list):
                    continue
                return data
            except Exception:
                continue
    return None


def load_month_ago(date_str: str) -> dict | None:
    """Load snapshot from ~4 weeks ago for month-over-month comparison."""
    d = date.fromisoformat(date_str)
    for i in range(25, 38):
        prev = (d - timedelta(days=i)).isoformat()
        path = DATA_DIR / f"{prev}.json"
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                if isinstance(data, list):
                    continue
                return data
            except Exception:
                continue
    return None


def save_snapshot(date_str: str, agg: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snap = {
        "date": date_str,
        "total": agg["total"],
        "by_industry": dict(agg["by_industry"].most_common(50)),
        "by_org": dict(agg["by_org"].most_common(20)),
        "by_stock": dict(agg["by_stock"].most_common(30)),
        "industry_samples": {k: v[:3] for k, v in agg["industry_samples"].items()},
    }
    with open(DATA_DIR / f"{date_str}.json", "w") as f:
        json.dump(snap, f, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# REPORT GENERATION
# ═══════════════════════════════════════════════════════════

def _heat_label(count: int, total: int) -> str:
    if count >= 5:
        return "🔥🔥"
    elif count >= 3:
        return "🔥"
    return ""


def _delta_str(now: int, prev: int | None) -> str:
    if prev is None or prev == 0:
        return "新"
    d = now - prev
    if d > 0:
        return f"↑{d}"
    elif d < 0:
        return f"↓{abs(d)}"
    return "→"


def render_weekly(date_str: str, agg: dict, prev_week: dict | None, prev_month: dict | None) -> str:
    L = []
    a = lambda s="": L.append(s)

    total = agg["total"]
    by_industry = agg["by_industry"]
    by_org = agg["by_org"]
    by_stock = agg["by_stock"]
    samples = agg["industry_samples"]
    prev_w_ind = prev_week.get("by_industry", {}) if prev_week else {}
    prev_m_ind = prev_month.get("by_industry", {}) if prev_month else {}

    dow = _day_of_week(date_str)
    a(f"# 机构研报热度周报 · {date_str} {dow}")
    a()
    a(f"*数据来源：东方财富研报中心 · 统计周期 7 天 · 共 {total} 份研报*")
    a()
    a("---")
    a()

    # ── 1. Industry heat ──
    a("## 1. 行业研报热度 Top 15")
    a()
    has_week = prev_week is not None
    has_month = prev_month is not None
    if has_week or has_month:
        a("| # | 行业 | 研报数 | 周环比 | 月环比 | 热度 |")
        a("|---|------|--------|--------|--------|------|")
    else:
        a("| # | 行业 | 研报数 | 热度 |")
        a("|---|------|--------|------|")
    top15 = by_industry.most_common(15)
    for i, (ind, count) in enumerate(top15, 1):
        heat = _heat_label(count, total)
        if has_week or has_month:
            w_delta = _delta_str(count, prev_w_ind.get(ind)) if has_week else "-"
            m_delta = _delta_str(count, prev_m_ind.get(ind)) if has_month else "-"
            a(f"| {i} | {ind} | {count} | {w_delta} | {m_delta} | {heat} |")
        else:
            a(f"| {i} | {ind} | {count} | {heat} |")
    a()
    a(f"> 本周覆盖 {len(by_industry)} 个行业 · 中位数 {max(1, total // max(len(by_industry), 1))} 份/行业")
    a()

    # ── 2. Institution activity ──
    a("## 2. 机构活跃度 Top 10")
    a()
    a("| # | 机构 | 发布研报数 |")
    a("|---|------|-----------|")
    for i, (org, count) in enumerate(by_org.most_common(10), 1):
        a(f"| {i} | {org} | {count} |")
    a()
    a(f"> 共 {len(by_org)} 家机构发布研报")
    a()

    # ── 3. Stock coverage ──
    a("## 3. 个股研报覆盖 Top 10")
    a()
    a("| # | 股票 | 研报数 |")
    a("|---|------|--------|")
    for i, (stock, count) in enumerate(by_stock.most_common(10), 1):
        a(f"| {i} | {stock} | {count} |")
    a()

    # ── 4. Featured reports ──
    a("## 4. 热门行业研报精选")
    a()
    for ind, _ in by_industry.most_common(8):
        reports = samples.get(ind, [])
        if not reports:
            continue
        a(f"### {ind}（{by_industry[ind]} 份）")
        a()
        for title, org, stock in reports[:3]:
            a(f"- **{stock}** · {org}：{title}")
        a()

    # ── 5. Week-over-week & month-over-month ──
    if has_week or has_month:
        a("## 5. 行业热度环比变化")
        a()

        if has_week:
            prev_w_total = prev_week.get("total", 0)
            a(f"### 周环比（vs {prev_week.get('date','?')}，{prev_w_total} 份）")
            a()
            changes_w = []
            all_w = set(list(by_industry.keys()) + list(prev_w_ind.keys()))
            for ind in all_w:
                now = by_industry.get(ind, 0)
                prev = prev_w_ind.get(ind, 0)
                changes_w.append((ind, now, prev, now - prev))
            changes_w.sort(key=lambda x: -x[3])

            a("| 行业 | 本周 | 上周 | 变化 |")
            a("|------|------|------|------|")
            for ind, now, prev, delta in changes_w[:10]:
                if delta != 0:
                    a(f"| {ind} | {now} | {prev} | {'↑' if delta > 0 else '↓'}{abs(delta)} |")
            if not any(d != 0 for _, _, _, d in changes_w):
                a("| — | — | — | 无明显变化 |")
            a()

        if has_month:
            prev_m_total = prev_month.get("total", 0)
            a(f"### 月环比（vs {prev_month.get('date','?')}，{prev_m_total} 份）")
            a()
            changes_m = []
            all_m = set(list(by_industry.keys()) + list(prev_m_ind.keys()))
            for ind in all_m:
                now = by_industry.get(ind, 0)
                prev = prev_m_ind.get(ind, 0)
                changes_m.append((ind, now, prev, now - prev))
            changes_m.sort(key=lambda x: -x[3])

            a("| 行业 | 本周 | 上月同期 | 变化 |")
            a("|------|------|----------|------|")
            for ind, now, prev, delta in changes_m[:10]:
                if delta != 0:
                    a(f"| {ind} | {now} | {prev} | {'↑' if delta > 0 else '↓'}{abs(delta)} |")
            if not any(d != 0 for _, _, _, d in changes_m):
                a("| — | — | — | 无明显变化 |")
            a()

        a(f"> 本周共 {total} 份研报")
        a()

    a("---")
    a()
    a(f"*自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 建议每周五收盘后运行*")

    return "\n".join(L)


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Weekly research report heat tracker")
    parser.add_argument("--date", default=date.today().isoformat(), help="Report date YYYY-MM-DD")
    args = parser.parse_args()

    report_date = args.date
    # Fetch reports from 7 days before report_date
    end_d = date.fromisoformat(report_date)
    begin_d = end_d - timedelta(days=7)
    begin_str = begin_d.isoformat()
    end_str = end_d.isoformat()

    print(f"{'='*50}")
    print(f"  Institute Research Heat Weekly · {report_date}")
    print(f"  Period: {begin_str} ~ {end_str}")
    print(f"{'='*50}")

    print("\n[1/3] 抓取研报数据...", end=" ", flush=True)
    reports = fetch_reports(begin_str, end_str)
    if not reports:
        print("无数据")
        sys.exit(1)
    print(f"{len(reports)}份研报")

    print("[2/3] 聚合统计...", end=" ", flush=True)
    agg = aggregate_reports(reports)
    print(f"{len(agg['by_industry'])}个行业, {len(agg['by_org'])}家机构")

    print("[3/3] 加载环比数据 & 生成周报...")
    prev_week = load_previous_week(report_date)
    prev_month = load_month_ago(report_date)
    w_tag = f"上周({prev_week.get('date','?')})" if prev_week else "无"
    m_tag = f"上月({prev_month.get('date','?')})" if prev_month else "无"
    print(f"  {w_tag} / {m_tag}")

    markdown = render_weekly(report_date, agg, prev_week, prev_month)
    out_dir = OUTPUT / report_date
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "weekly.md"
    with open(report_path, "w") as f:
        f.write(markdown)
    print(f"  报告: {report_path}")

    save_snapshot(report_date, agg)
    print(f"  快照: {DATA_DIR / f'{report_date}.json'}")

    print(f"\n{'='*50}")
    print(f"  完成! {report_path}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
