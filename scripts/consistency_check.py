#!/usr/bin/env python3
"""Morning Briefing prediction accuracy validator.

Compares morning briefing recommendations against the day's actual market
outcome (from postclose review), measuring prediction accuracy.

Usage:
    python3 scripts/consistency_check.py                     # Today
    python3 scripts/consistency_check.py --date 2026-05-25   # Specific date

Requires both morning briefing and postclose review to have run for the date.

Output:
    output/consistency/{date}/check.md
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OUTPUT = PROJ / "output"
DATA_DIR = PROJ / "data" / "postclose"

ACTION_SCORE = {"买入": 3, "关注": 1, "回避": -2}

def _action_key(action: str) -> str:
    """Strip emoji prefix from action."""
    return action.replace("🟢 ", "").replace("🟡 ", "").replace("🔴 ", "")
STRONG_RESULT = {"主线", "趋势型主线", "次主线"}
WEAK_RESULT = {"局部活口", "活口", "资金撤退方向", "失败轮动"}


# ═══════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════

def load_postclose(date_str: str) -> dict | None:
    path = DATA_DIR / date_str / "snapshot.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def load_briefing(date_str: str) -> str | None:
    path = OUTPUT / "morning" / date_str / "briefing.md"
    if path.exists():
        return path.read_text()
    return None


def parse_briefing_table(md_text: str) -> dict:
    """Extract sector recommendations from briefing markdown.
    Returns: {sector_name: {action, stocks, source}}
    """
    recs = {}
    in_table = False
    s_idx = a_idx = src_idx = None
    for line in md_text.split("\n"):
        if "板块" in line and "操作" in line:
            in_table = True
            headers = [h.strip() for h in line.split("|")[1:-1]]
            for i, h in enumerate(headers):
                if "板块" in h:
                    s_idx = i
                elif "操作" in h:
                    a_idx = i
            continue
        if in_table:
            if line.startswith("|") and "---" not in line:
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if s_idx is None or len(parts) <= s_idx:
                    continue
                sector = parts[s_idx]
                action = parts[a_idx] if a_idx is not None and len(parts) > a_idx else ""
                # Extract stocks from last column
                stocks_raw = parts[-1] if len(parts) > max(s_idx, a_idx or 0) + 1 else ""
                stocks = []
                for s in stocks_raw.split("<br>"):
                    s_clean = re.sub(r'\(.*?\)', '', s.strip())
                    s_clean = re.sub(r'\s*—\s*.*', '', s_clean)
                    s_clean = re.sub(r'[🔥🆕📈🟢🟡🔴⚠️💤📌🔍❌\s·\d]+', '', s_clean)
                    if s_clean and len(s_clean) > 1 and len(s_clean) < 10:
                        stocks.append(s_clean)
                recs[sector] = {"action": action, "stocks": stocks}
            elif not line.startswith("|"):
                in_table = False
    return recs


def _normalize(s: str) -> str:
    result = []
    for ch in str(s):
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        elif code == 0x3000:
            result.append(" ")
        else:
            result.append(ch)
    return "".join(result).replace(" ", "")


def _theme_overlap(name1: str, name2: str) -> bool:
    """Fuzzy theme name matching using character overlap ratio."""
    def _clean(s):
        return s.replace("/", "").replace("·", "").replace(" ", "").split("（")[0].strip()
    k1, k2 = _clean(name1), _clean(name2)
    if not k1 or not k2:
        return False
    # Direct substring
    if k1 in k2 or k2 in k1:
        return True
    # Character overlap ratio
    common = sum(1 for c in set(k1) if c in k2)
    ratio = common / min(len(set(k1)), len(set(k2)))
    return ratio >= 0.5


# ═══════════════════════════════════════════════════════════
# PREDICTION ACCURACY
# ═══════════════════════════════════════════════════════════

def evaluate_predictions(br_recs: dict, postclose: dict) -> dict:
    """Compare briefing recommendations with actual market outcome."""

    # Build postclose theme index
    pc_themes = {}
    for t in postclose.get("themes", []):
        pc_themes[t.get("name", "")] = t

    # Build postclose stock index (limit-up stocks only)
    pc_stocks = {}
    for s in postclose.get("limit_up_stocks", []):
        pc_stocks[_normalize(s.get("name", ""))] = s

    results = {"hits": [], "misses": [], "partial": [], "unmatched": []}
    total_weighted = 0
    hit_weighted = 0
    matched_themes = set()  # avoid duplicate matching

    for sector, br in br_recs.items():
        action = br.get("action", "")
        pred_score = ACTION_SCORE.get(_action_key(action), 0)
        stocks = br.get("stocks", [])

        # Find FIRST unmatched postclose theme
        pc_theme = None
        for name, t in pc_themes.items():
            if _theme_overlap(sector, name) and name not in matched_themes:
                pc_theme = t
                matched_themes.add(name)
                break

        if not pc_theme:
            results["unmatched"].append({
                "sector": sector, "action": action,
                "note": "简报提及但今日复盘无对应主题",
            })
            continue

        actual_type = pc_theme.get("type", "")
        actual_stocks = set(_normalize(s) for s in pc_theme.get("member_stocks", []))
        pc_name = pc_theme.get("name", sector)

        # Check stock accuracy
        hit_stocks = []
        for s in stocks:
            ns = _normalize(s)
            stk = pc_stocks.get(ns, {})
            if stk and stk.get("pct_chg", 0) >= 9.5:
                hit_stocks.append({
                    "name": s,
                    "pct": stk.get("pct_chg", 0),
                    "consecutive": stk.get("consecutive", 0),
                })

        hit_rate = len(hit_stocks) / max(len(stocks), 1)

        # Prediction accuracy: only judge buy/avoid; "关注" is neutral
        if pred_score >= 3:  # 买入
            if actual_type in STRONG_RESULT:
                results["hits"].append({
                    "sector": pc_name, "action": action,
                    "predicted": f"买入", "actual": actual_type,
                    "hit_rate": hit_rate, "hit_stocks": hit_stocks,
                })
                total_weighted += pred_score
                hit_weighted += pred_score
            elif actual_type in WEAK_RESULT:
                results["misses"].append({
                    "sector": pc_name, "action": action,
                    "predicted": f"买入", "actual": actual_type,
                    "hit_rate": hit_rate, "hit_stocks": hit_stocks,
                })
                total_weighted += pred_score
            else:
                results["partial"].append({
                    "sector": pc_name, "action": action,
                    "predicted": action, "actual": actual_type,
                    "hit_rate": hit_rate, "hit_stocks": hit_stocks,
                })

        elif pred_score < 0:  # 回避
            if actual_type in WEAK_RESULT:
                results["hits"].append({
                    "sector": pc_name, "action": action,
                    "predicted": f"回避", "actual": actual_type,
                    "hit_rate": 0, "hit_stocks": [],
                })
                total_weighted += abs(pred_score)
                hit_weighted += abs(pred_score)
            elif actual_type in STRONG_RESULT:
                results["misses"].append({
                    "sector": pc_name, "action": action,
                    "predicted": f"回避", "actual": actual_type,
                    "hit_rate": 0, "hit_stocks": [],
                })
                total_weighted += abs(pred_score)
            else:
                results["partial"].append({
                    "sector": pc_name, "action": action,
                    "predicted": action, "actual": actual_type,
                    "hit_rate": hit_rate, "hit_stocks": hit_stocks,
                })

        else:  # 关注 — neutral, not counted in accuracy
            results["partial"].append({
                "sector": pc_name, "action": action,
                "predicted": action, "actual": actual_type,
                "hit_rate": hit_rate, "hit_stocks": hit_stocks,
            })

    # Compute accuracy
    total_hits = len(results["hits"])
    total_misses = len(results["misses"])
    total_partial = len(results["partial"])
    total_unmatched = len(results["unmatched"])
    accuracy = (
        hit_weighted / max(total_weighted, 1) * 100
        if total_weighted > 0 else None
    )

    return {
        **results,
        "stats": {
            "hits": total_hits, "misses": total_misses,
            "partial": total_partial, "unmatched": total_unmatched,
            "accuracy": accuracy,
        },
    }


# ═══════════════════════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════════════════════

def render_report(date_str: str, br_recs: dict, postclose: dict,
                  eval_results: dict) -> str:
    L = []
    a = lambda s="": L.append(s)

    stats = eval_results["stats"]

    a(f"# 盘前预测准确性校验 · {date_str}")
    a()
    a(f"*对比：盘前简报推荐 vs 当日收盘实际走势*")
    a()
    a("---")
    a()

    # ── Scorecard ──
    a("## 准确率总评")
    a()
    acc = stats["accuracy"]
    if acc is not None:
        grade = "🟢" if acc >= 60 else ("🟡" if acc >= 40 else "🔴")
        a(f"**{grade} 预测准确率：{acc:.0f}%**")
    a(f"- 命中：{stats['hits']} 个板块")
    a(f"- 失误：{stats['misses']} 个板块")
    a(f"- 中性(关注)：{stats['partial']} 个板块")
    if stats["unmatched"]:
        a(f"- 未匹配：{stats['unmatched']} 个板块（简报提了但复盘无对应）")
    a()

    # ── Hits ──
    a("## ✅ 预测命中")
    a()
    if eval_results["hits"]:
        for r in eval_results["hits"]:
            a(f"### {r['sector']} — {r['predicted']} → 实际：{r['actual']}")
            a()
            if r.get("hit_stocks"):
                stocks_str = "、".join(
                    f"{s['name']}({s['pct']:+.1f}%)" for s in r["hit_stocks"]
                )
                a(f"推荐且涨停：{stocks_str}")
            a()
    else:
        a("今日无明确命中。")
        a()

    # ── Misses ──
    a("## ❌ 预测失误")
    a()
    if eval_results["misses"]:
        for r in eval_results["misses"]:
            a(f"### {r['sector']} — {r['predicted']} → 实际：{r['actual']}")
            a()
            a(f"预测认为应{r['predicted']}，但当天走势为「{r['actual']}」")
            if r.get("miss_stocks"):
                a(f"推荐未涨停：{'、'.join(r['miss_stocks'][:5])}")
            a()
    else:
        a("今日无重大失误。")
        a()

    # ── Partial (关注) ──
    if eval_results["partial"]:
        a("## 🟡 中性（关注）")
        a()
        for r in eval_results["partial"]:
            stocks_str = ""
            if r.get("hit_stocks"):
                stocks_str = " — 涨停：" + "、".join(
                    f"{s['name']}({s['pct']:+.1f}%)" for s in r["hit_stocks"]
                )
            a(f"- {r['sector']}：预测「{r['action']}」→ 实际「{r['actual']}」{stocks_str}")
        a()

    # ── Unmatched ──
    if eval_results["unmatched"]:
        a("## ❓ 未匹配")
        a()
        for r in eval_results["unmatched"]:
            a(f"- {r['sector']}：{r['note']}")
        a()

    # ── Detail table ──
    a("## 全量明细")
    a()
    a("| 简报板块 | 推荐 | 今日走势 | 命中率 |")
    a("|----------|------|----------|--------|")
    for r in eval_results["hits"]:
        rate = f"{r.get('hit_rate', 0)*100:.0f}%"
        a(f"| {r['sector']} | {r['action']} | {r['actual']} ✅ | {rate} |")
    for r in eval_results["misses"]:
        rate = f"{r.get('hit_rate', 0)*100:.0f}%"
        a(f"| {r['sector']} | {r['action']} | {r['actual']} ❌ | {rate} |")
    for r in eval_results["partial"]:
        rate = f"{r.get('hit_rate', 0)*100:.0f}%"
        a(f"| {r['sector']} | {r['action']} | {r['actual']} 🟡 | {rate} |")
    for r in eval_results["unmatched"]:
        a(f"| {r['sector']} | {r['action']} | 无对应 ❓ | — |")
    a()

    a("---")
    a()
    a(f"*生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    return "\n".join(L)


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Morning briefing prediction accuracy check"
    )
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="Date to check (briefing + postclose must exist)")
    args = parser.parse_args()
    date_str = args.date

    print(f"{'='*50}")
    print(f"  Prediction Accuracy Check · {date_str}")
    print(f"{'='*50}")

    # Load data
    print("\n[1/3] 加载数据...")
    briefing_md = load_briefing(date_str)
    if not briefing_md:
        print(f"  ❌ 无简报: output/morning/{date_str}/briefing.md")
        sys.exit(1)
    print(f"  简报: {date_str}")

    postclose = load_postclose(date_str)
    if not postclose:
        print(f"  ❌ 无复盘: data/postclose/{date_str}/snapshot.json")
        print(f"  提示：先跑 postclose_review.py --date {date_str}")
        sys.exit(1)
    print(f"  复盘: {date_str} ({postclose.get('limit_up_count', '?')}只涨停)")

    # Parse
    print("\n[2/3] 解析 & 校验...")
    br_recs = parse_briefing_table(briefing_md)
    print(f"  简报 {len(br_recs)} 个板块推荐")
    print(f"  复盘 {len(postclose.get('themes', []))} 个主题")

    eval_results = evaluate_predictions(br_recs, postclose)

    # Report
    print("\n[3/3] 生成报告...")
    stats = eval_results["stats"]
    print(f"  命中: {stats['hits']} | 失误: {stats['misses']} | 中性: {stats['partial']} | 未匹配: {stats['unmatched']}")
    if stats["accuracy"] is not None:
        print(f"  准确率: {stats['accuracy']:.0f}%")

    markdown = render_report(date_str, br_recs, postclose, eval_results)
    out_dir = OUTPUT / "consistency" / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "check.md"
    with open(report_path, "w") as f:
        f.write(markdown)
    print(f"\n  报告: {report_path}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
