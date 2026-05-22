#!/usr/bin/env python3
"""Push morning briefing to phone via WeChat (Server酱) or Bark.

Usage:
    python3 scripts/notify.py --date 2026-05-22                    # Push briefing
    python3 scripts/notify.py --date 2026-05-22 --channel bark    # Via Bark
    python3 scripts/notify.py --test                               # Test push
"""

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

import requests

PROJ = Path(__file__).resolve().parent.parent
OUTPUT = PROJ / "output"

# ── Push channels ──────────────────────────────────────────

def push_serverchan(send_key: str, title: str, content: str) -> bool:
    """Push via Server酱 (WeChat). Free tier: 5 msgs/day."""
    url = f"https://sctapi.ftqq.com/{send_key}.send"
    r = requests.post(url, data={"title": title, "desp": content}, timeout=15)
    return r.status_code == 200 and '"code":0' in r.text


def push_bark(device_key: str, title: str, content: str) -> bool:
    """Push via Bark (iOS only)."""
    url = f"https://api.day.app/{device_key}"
    r = requests.post(url, json={
        "title": title,
        "body": content,
        "group": "盘前简报",
    }, timeout=15)
    return r.status_code == 200


# ── Briefing parser ────────────────────────────────────────

def _parse_sectors(md_text: str) -> list[dict]:
    """Extract sector recommendations from briefing markdown."""
    recs = []
    in_table = False
    for line in md_text.split('\n'):
        if line.startswith('| 板块 |'):
            in_table = True
            continue
        if in_table:
            if line.startswith('|') and '---' not in line:
                parts = [p.strip() for p in line.split('|')[1:-1]]
                if len(parts) >= 6:
                    recs.append({
                        'sector': parts[0], 'action': parts[2],
                        'reason': parts[4],
                    })
            elif not line.startswith('|'):
                break
    return recs


def build_push_text(trade_date: str) -> str | None:
    """Build push notification text from briefing markdown."""
    md_path = OUTPUT / "morning" / trade_date / "briefing.md"
    if not md_path.exists():
        print(f"简报不存在: {md_path}")
        return None

    md = md_path.read_text()

    # Extract one-sentence summary
    summary = ""
    m = re.search(r'## 1\. 隔夜事件总结\n\n(.+?)(?:\n##|\n\n##)', md, re.DOTALL)
    if m:
        summary = m.group(1).strip()

    # Extract stance
    stance = ""
    m2 = re.search(r'> (.+仓位[^\n]+)', md)
    if m2:
        stance = m2.group(1)

    # Extract sectors
    recs = _parse_sectors(md)

    # Build compact text
    lines = [f"📈 盘前简报 {trade_date}", ""]

    if summary:
        # Truncate for push
        if len(summary) > 200:
            summary = summary[:200] + "..."
        lines.append(summary)
        lines.append("")

    if stance:
        lines.append(f"💡 {stance}")
        lines.append("")

    # Sectors by action
    buys = [r for r in recs if '买入' in r['action']]
    watches = [r for r in recs if '关注' in r['action']]
    avoids = [r for r in recs if '回避' in r['action']]

    if buys:
        lines.append("🟢 买入：")
        for r in buys:
            lines.append(f"  {r['sector']} — {r['reason'][:40]}")
        lines.append("")
    if watches:
        lines.append("🟡 关注：")
        for r in watches:
            lines.append(f"  {r['sector']} — {r['reason'][:40]}")
        lines.append("")
    if avoids:
        lines.append("🔴 回避：")
        for r in avoids:
            lines.append(f"  {r['sector']} — {r['reason'][:40]}")
        lines.append("")

    # Risk alerts
    in_risks = False
    risks = []
    for line in md.split('\n'):
        if '## 5. 风险提示' in line:
            in_risks = True
            continue
        if in_risks and line.startswith('- '):
            risks.append(line[2:])
        elif in_risks and line.startswith('## '):
            break
    if risks:
        lines.append("⚠️ 风险：")
        for r in risks[:3]:
            lines.append(f"  {r}")

    return "\n".join(lines)


def _parse_stocks_from_table(md_text: str) -> dict:
    """Extract {sector: [(name, code, note), ...]} from briefing table."""
    result = {}
    in_table = False
    for line in md_text.split('\n'):
        if line.startswith('| 板块 |'):
            in_table = True
            continue
        if in_table:
            if line.startswith('|') and '---' not in line:
                parts = [p.strip() for p in line.split('|')[1:-1]]
                if len(parts) >= 6:
                    sector = parts[0]
                    stocks_str = parts[5]
                    # Parse stocks from format: "name(code) — note<br>name(code) — note"
                    stocks = []
                    for seg in re.split(r'<br>|\n', stocks_str):
                        seg = seg.strip()
                        if not seg:
                            continue
                        m = re.match(r'([^(]+)\((\d+)\)\s*[—\-]?\s*(.*)', seg)
                        if m:
                            stocks.append((m.group(1).strip(), m.group(2), m.group(3).strip()))
                    result[sector] = stocks
            elif not line.startswith('|'):
                break
    return result


def build_push_text(trade_date: str, server_url: str = "") -> str:
    """Build WeChat push — compact format, no newlines (template msg limitation).

    Uses | as visual separator between sections.
    """
    md_path = OUTPUT / "morning" / trade_date / "briefing.md"
    if not md_path.exists():
        return ""

    md = md_path.read_text()

    parts = [f"📈 盘前简报 {trade_date}"]

    # 1. Stance
    m2 = re.search(r'> (.+仓位[^\n]+)', md)
    if m2:
        parts.append(f"💡{m2.group(1)}")

    # 2. Sectors with stocks — compact format
    recs = _parse_sectors(md)
    stocks_map = _parse_stocks_from_table(md)

    buys = [r for r in recs if '买入' in r['action']]
    watches = [r for r in recs if '关注' in r['action']]
    avoids = [r for r in recs if '回避' in r['action']]

    def _fmt(r):
        stocks = stocks_map.get(r['sector'], [])
        names = ", ".join(f"{n}({c})" for n, c, _ in stocks[:5])
        reason = r['reason'][:50]
        return f"{r['sector']} | {names} | {reason}"

    if buys:
        parts.append("🟢买入:")
        for r in buys:
            parts.append(_fmt(r))
    if watches:
        parts.append("🟡关注:")
        for r in watches[:6]:
            parts.append(_fmt(r))
    if avoids:
        parts.append("🔴回避:")
        for r in avoids:
            parts.append(_fmt(r))

    # 3. Risks
    in_risks = False
    risk_lines = []
    for line in md.split('\n'):
        if '## 5. 风险提示' in line:
            in_risks = True
            continue
        if in_risks and line.startswith('- '):
            risk_lines.append(line[2:])
        elif in_risks and line.startswith('## '):
            break
    if risk_lines:
        parts.append("⚠️" + " | ".join(rl[:40] for rl in risk_lines[:3]))

    parts.append("— AI生成，仅供参考 —")

    text = "\n\n".join(parts)

    if server_url:
        text += f"\n\n📄 完整报告: {server_url}"

    return text


# ── Main ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Push briefing to phone")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--channel", default="serverchan", choices=["serverchan", "bark"])
    parser.add_argument("--key", default=None, help="SendKey (Server酱) or DeviceKey (Bark)")
    parser.add_argument("--server-url", default="", help="HTTP server URL for full report link")
    parser.add_argument("--test", action="store_true", help="Send a test message")
    args = parser.parse_args()

    # Get key from env
    key = args.key or os.environ.get("PUSH_KEY", "")
    if not key:
        print("请设置 PUSH_KEY 环境变量或用 --key 指定")
        print("  Server酱: https://sct.ftqq.com/ 获取 SendKey")
        print("  Bark: App Store 下载后获取 DeviceKey")
        sys.exit(1)

    if args.test:
        title = "🧪 推送测试"
        content = f"测试消息 — {date.today()}\n\n如果你看到这条消息，说明推送配置成功！"
        if args.channel == "serverchan":
            ok = push_serverchan(key, title, content)
        else:
            ok = push_bark(key, title, content)
        print("✅ 测试推送成功！" if ok else "❌ 推送失败，检查 key")
        return

    # Build and send
    title = f"盘前简报 · {args.date}"
    content = build_push_text(args.date)

    if args.channel == "serverchan":
        ok = push_serverchan(key, title, content)
    else:
        ok = push_bark(key, title, content)

    print("✅ 推送成功！" if ok else "❌ 推送失败")


if __name__ == "__main__":
    main()
