#!/usr/bin/env python3
"""Verify yesterday's daily picks against today's market data."""

import json, re, os, requests
from pathlib import Path
from datetime import datetime, date, timedelta

PROJ = Path(__file__).resolve().parent.parent
API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")

DISPLAY = {
    "幸运阿sai": "sai佬", "灰兔尾": "兔佬", "文驹": "文驹",
    "-阿狼-": "狼大", "F佬": "F佬", "喜帖街QAQ": "喜帖街", "猫指导": "猫指导",
}


def extract_target_price(entry_text: str) -> float | None:
    """Extract target price from entry timing text like '回踩20日线约28.5元'."""
    # Match patterns: 约28.5元, 约28.5, X元附近, X元
    patterns = [
        r'约\s*(\d+\.?\d*)\s*元',
        r'(\d+\.?\d*)\s*元\s*附近',
        r'回踩.*?(\d+\.?\d*)\s*元',
        r'突破\s*(\d+\.?\d*)\s*元',
        r'现价\s*(\d+\.?\d*)\s*元',
    ]
    for pat in patterns:
        m = re.search(pat, entry_text)
        if m:
            return float(m.group(1))
    return None


def check_pick(pick: dict, stocks_lookup: dict) -> dict:
    """Check if a pick's entry condition was met."""
    code = pick.get("code", "")
    entry = pick.get("entry_timing", "")
    target = extract_target_price(entry)

    stock = stocks_lookup.get(code, {})
    close = stock.get("close", 0)
    low = stock.get("low", close)  # approximate if no low data
    pct = stock.get("pct", 0)

    if not target or not close:
        return {**pick, "verify_status": "无法判断", "verify_detail": f"现价{close or '?'} 目标{target or '?'}",
                "today_close": close, "today_pct": pct}

    # Data sanity check: if price is 5x+ of target, likely unit mismatch
    if close > target * 5:
        status = "数据存疑 ⚠️"
        detail = f"现价{close}远大于目标{target}, 可能存在复权或单位差异"
    else:
        deviation = (close - target) / target * 100
        if abs(deviation) < 3:
            status = "接近目标 📍"
            detail = f"现价{close} 距目标{target}仅{deviation:+.1f}%"
        elif deviation > 0:
            status = f"高于目标{deviation:+.0f}%"
            detail = f"现价{close} > 目标{target}"
        else:
            status = f"低于目标{abs(deviation):.0f}%"
            detail = f"现价{close} < 目标{target}"

    return {**pick, "verify_status": status, "verify_detail": detail,
            "today_close": close, "today_pct": pct}


def render_report(all_checks: dict, today: str, yesterday: str) -> str:
    """Generate verification markdown."""
    L = [f"# 选股验证 · {today}", "",
         f"*验证 {yesterday} 大佬选股的入场条件 — 基于 {today} 收盘数据*", "", "---", ""]

    total = 0
    near = 0
    for name, checks in all_checks.items():
        display = DISPLAY.get(name, name)
        L.append(f"## {display}")
        L.append("")
        L.append("| # | 股票 | 操作 | 昨日入场时机 | 今日状态 | 详情 |")
        L.append("|---|------|------|-------------|----------|------|")
        for c in checks:
            total += 1
            if "接近目标" in c.get("verify_status", ""):
                near += 1
            emoji = {"接近目标 📍": "🟢"}.get(c.get("verify_status", ""), "")
            if "高于" in c.get("verify_status", ""):
                emoji = "🟡"
            elif "低于" in c.get("verify_status", ""):
                emoji = "🟡"
            elif "存疑" in c.get("verify_status", ""):
                emoji = "⚠️"
            L.append(f"| {emoji} | {c['name']}({c['code']}) | {c.get('action','')} | "
                     f"{c.get('entry_timing','')[:30]} | {c.get('verify_status','')} | "
                     f"{c.get('verify_detail','')} |")
        L.append("")

    L.append("---")
    L.append(f"**总计**: {near}/{total} 接近目标, 其余为偏离或数据存疑")
    L.append("")
    L.append(f"*生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    return "\n".join(L)


def main():
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()

    picks_file = PROJ / "output" / "daily_picks" / f"{yesterday}.json"
    if not picks_file.exists():
        # Write a placeholder so the website doesn't 404
        out_dir = PROJ / "output" / "verified"
        out_dir.mkdir(parents=True, exist_ok=True)
        placeholder = f"# 选股验证 · {today.isoformat()}\n\n*暂无昨日选股数据，明日收盘后自动验证*\n"
        (out_dir / f"{today.isoformat()}.md").write_text(placeholder)
        print(f"无昨日选股数据，已生成占位页")
        return

    print(f"验证选股 · {today.isoformat()} (昨日数据: {yesterday})")
    all_picks = json.loads(picks_file.read_text())

    # Fetch today's market data for price lookup
    from market_data import fetch_fund_flow
    stocks, _ = fetch_fund_flow()
    stocks_lookup = {s["code"]: s for s in stocks}
    print(f"今日数据: {len(stocks)} 只")

    all_checks = {}
    for name, result in all_picks.items():
        checks = [check_pick(p, stocks_lookup) for p in result.get("picks", [])]
        all_checks[name] = checks

        display = DISPLAY.get(name, name)
        triggered = sum(1 for c in checks if "已触发" in c.get("verify_status", ""))
        print(f"  {display}: {triggered}/{len(checks)} 触发")

    report = render_report(all_checks, today.isoformat(), yesterday)
    out_dir = PROJ / "output" / "verified"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{today.isoformat()}.md"
    report_path.write_text(report)
    print(f"\n验证报告: {report_path}")


if __name__ == "__main__":
    main()
