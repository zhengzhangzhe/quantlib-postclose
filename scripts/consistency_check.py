#!/usr/bin/env python3
"""Postclose vs Morning Briefing consistency validator.

Validates that morning briefing recommendations align with the previous
trading day's postclose review, flagging omissions and contradictions.

Usage:
    python3 scripts/consistency_check.py                     # Today
    python3 scripts/consistency_check.py --date 2026-05-25   # Specific date

Output:
    output/consistency/{date}.md
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OUTPUT = PROJ / "output"
DATA_DIR = PROJ / "data" / "postclose"

WEAK_TYPES = {"资金撤退方向", "失败轮动", "失败轮动/资金撤退方向"}
STRONG_TYPES = {"主线", "趋势型主线"}


# ═══════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════

def _prev_trading_day(d: date) -> date:
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def load_postclose(for_date: str) -> dict | None:
    """Load most recent postclose snapshot before for_date."""
    td = date.fromisoformat(for_date)
    for _ in range(7):
        td = _prev_trading_day(td)
        path = DATA_DIR / td.isoformat() / "snapshot.json"
        if path.exists():
            with open(path) as f:
                snap = json.load(f)
            snap["_loaded_date"] = td.isoformat()
            return snap
    return None


def load_briefing(date_str: str) -> str | None:
    """Load morning briefing markdown for given date."""
    path = OUTPUT / "morning" / date_str / "briefing.md"
    if path.exists():
        return path.read_text()
    return None


def parse_briefing_table(md_text: str) -> dict:
    """Extract sector recommendations table from briefing markdown.
    Returns: {sector_name: {action, stocks}}
    """
    recs = {}
    in_table = False
    sector_idx = action_idx = None
    for line in md_text.split("\n"):
        if "板块" in line and "操作" in line:
            in_table = True
            headers = [h.strip() for h in line.split("|")[1:-1]]
            for i, h in enumerate(headers):
                if "板块" in h:
                    sector_idx = i
                elif "操作" in h:
                    action_idx = i
            continue
        if in_table:
            if line.startswith("|") and "---" not in line:
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if sector_idx is not None and len(parts) > sector_idx:
                    sector = parts[sector_idx]
                    action = parts[action_idx] if action_idx is not None and len(parts) > action_idx else ""
                    # Extract stocks from last column (usually contains <br> separated names)
                    stocks_raw = parts[-1] if len(parts) > max(sector_idx or 0, action_idx or 0) + 1 else ""
                    stocks = []
                    for s in stocks_raw.split("<br>"):
                        s_clean = re.sub(r'\(.*?\)', '', s.strip())
                        s_clean = re.sub(r'[^一-鿿\w]', '', s_clean)
                        if s_clean and len(s_clean) < 10:
                            stocks.append(s_clean)
                    recs[sector] = {"action": action, "stocks": stocks}
            elif not line.startswith("|"):
                in_table = False
    return recs


# ═══════════════════════════════════════════════════════════
# VALIDATION RULES
# ═══════════════════════════════════════════════════════════

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
    return "".join(result)


def _theme_overlap(name1: str, name2: str) -> bool:
    def _key(s):
        s = s.replace("/", "").replace("·", "").replace(" ", "")
        return s.split("（")[0].strip()
    k1, k2 = _key(name1), _key(name2)
    return k1 and k2 and (k1 in k2 or k2 in k1)


def _match_br(name: str, br_recs: dict) -> dict | None:
    if name in br_recs:
        return br_recs[name]
    for br_name, br_info in br_recs.items():
        if _theme_overlap(name, br_name):
            return br_info
    return None


def validate(postclose: dict, br_recs: dict, br_full_text: str = "") -> list[dict]:
    """Run all consistency checks. Returns list of {level, msg} dicts."""
    results = []

    pc_themes = {}
    for t in postclose.get("themes", []):
        name = t.get("name", "")
        pc_themes[name] = {
            "type": t.get("type", ""),
            "stocks": set(t.get("member_stocks", [])),
        }

    # ── Summary ──
    covered = 0
    for name in pc_themes:
        if _match_br(name, br_recs):
            covered += 1
    results.append({
        "level": "info",
        "msg": f"复盘 {postclose.get('_loaded_date','?')} → 简报覆盖 {covered}/{len(pc_themes)} 个主题",
    })

    # ── Rule 1: Missing non-survivor themes ──
    for name, info in pc_themes.items():
        if _match_br(name, br_recs):
            continue
        if info["type"] not in {"活口", "失败轮动", "资金撤退方向"}:
            results.append({
                "level": "warn",
                "msg": f"⚠️ 遗漏重要主题：「{name}」（{info['type']}）未出现在简报中",
            })

    # ── Rule 2: Rating contradiction ──
    for name, info in pc_themes.items():
        if info["type"] not in WEAK_TYPES:
            continue
        br = _match_br(name, br_recs)
        if br and "买入" in br.get("action", ""):
            results.append({
                "level": "error",
                "msg": f"❌ 评级矛盾：「{name}」复盘={info['type']}，简报={br['action']}",
            })

    # ── Rule 3: Strong themes getting "回避" ──
    for name, info in pc_themes.items():
        if info["type"] not in STRONG_TYPES:
            continue
        br = _match_br(name, br_recs)
        if br and "回避" in br.get("action", ""):
            results.append({
                "level": "error",
                "msg": f"❌ 评级异常：「{name}」为{info['type']}，简报建议「回避」",
            })

    # ── Rule 4: Anchor stock mention check ──
    # Check if main theme anchor stocks appear anywhere in the briefing text
    if br_full_text:
        missing_count = 0
        for name, info in pc_themes.items():
            if info["type"] not in STRONG_TYPES:
                continue
            anchors = list(info["stocks"])[:3]
            all_missing = True
            for s in anchors:
                if _normalize(s).replace(" ", "") in br_full_text.replace(" ", ""):
                    all_missing = False
                    break
            if all_missing and anchors:
                missing_count += 1
                results.append({
                    "level": "warn",
                    "msg": f"📌 建议纳入：「{name}」核心标的均未出现：{'、'.join(anchors[:2])}",
                })

    # ── Summary verdict ──
    errors = sum(1 for r in results if r["level"] == "error")
    warns = sum(1 for r in results if r["level"] == "warn")
    if errors == 0 and warns == 0:
        results.append({"level": "info", "msg": "✅ 简报与复盘一致，未发现问题"})
    elif errors > 0:
        results.append({"level": "error", "msg": f"🔴 发现 {errors} 个严重问题 + {warns} 个建议，简报质量存疑"})
    elif warns > 0:
        results.append({"level": "warn", "msg": f"🟡 发现 {warns} 个建议项，简报基本可用"})

    return results


# ═══════════════════════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════════════════════

def render_report(date_str: str, postclose: dict, br_recs: dict,
                  results: list[dict]) -> str:
    L = []
    a = lambda s="": L.append(s)

    a(f"# 一致性校验 · {date_str}")
    a()
    a(f"*复盘 {postclose.get('_loaded_date','?')} → 简报 {date_str}*")
    a()
    a("---")
    a()

    a("## 校验结果")
    a()
    for r in results:
        a(f"- {r['msg']}")
    a()

    a("## 复盘主题一览")
    a()
    a("| 主题 | 类型 | 成员数 | 简报状态 |")
    a("|------|------|--------|----------|")
    for t in postclose.get("themes", []):
        name = t.get("name", "")
        ttype = t.get("type", "")
        stocks = t.get("member_stocks", [])
        br = _match_br(name, br_recs)
        if br:
            status = f"✅ 已覆盖 ({br.get('action','')})"
        elif ttype in ("活口", "失败轮动", "资金撤退方向"):
            status = "💤 已隐去"
        else:
            status = "⚠️ 遗漏"
        a(f"| {name} | {ttype} | {len(stocks)} | {status} |")
    a()

    a("---")
    a()
    a(f"*生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    return "\n".join(L)


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Postclose vs Briefing consistency check")
    parser.add_argument("--date", default=date.today().isoformat(), help="Briefing date")
    args = parser.parse_args()
    date_str = args.date

    print(f"{'='*50}")
    print(f"  Consistency Check · {date_str}")
    print(f"{'='*50}")

    # Load data
    print("\n[1/3] 加载数据...")
    postclose = load_postclose(date_str)
    if not postclose:
        print("  ❌ 未找到复盘快照")
        sys.exit(1)
    print(f"  复盘: {postclose.get('_loaded_date','?')} ({len(postclose.get('themes',[]))}个主题)")

    briefing_md = load_briefing(date_str)
    if not briefing_md:
        print(f"  ❌ 未找到简报: output/morning/{date_str}/briefing.md")
        sys.exit(1)
    print(f"  简报: {date_str}")

    # Parse
    print("\n[2/3] 解析 & 校验...")
    br_recs = parse_briefing_table(briefing_md)
    print(f"  解析出 {len(br_recs)} 个板块推荐")

    results = validate(postclose, br_recs, briefing_md)

    # Report
    print("\n[3/3] 生成报告...")
    for r in results:
        prefix = {"error": "  ❌", "warn": "  ⚠️", "info": "  ℹ️"}.get(r["level"], "   ")
        print(f"{prefix} {r['msg']}")

    markdown = render_report(date_str, postclose, br_recs, results)
    out_dir = OUTPUT / "consistency" / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "check.md"
    with open(report_path, "w") as f:
        f.write(markdown)
    print(f"\n  报告: {report_path}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
