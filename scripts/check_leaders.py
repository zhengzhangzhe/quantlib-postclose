#!/usr/bin/env python3
"""Check if sector leader stocks are still active — flag stale ones for review.

Usage:
    python3 scripts/check_leaders.py                     # Check last 30 days
    python3 scripts/check_leaders.py --days 60           # Last 60 days
"""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

try:
    from sector_leaders import SECTOR_LEADERS
except ImportError:
    SECTOR_LEADERS = {}

PROJ = Path(__file__).resolve().parent.parent
DATA = PROJ / "data" / "postclose"


def main():
    parser = argparse.ArgumentParser(description="Check sector leader activity")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    # Collect all snapshots in range
    snapshots = []
    today = date.today()
    for offset in range(args.days):
        d = today - timedelta(days=offset)
        path = DATA / d.isoformat() / "snapshot.json"
        if path.exists():
            with open(path) as f:
                snapshots.append(json.load(f))

    if not snapshots:
        print(f"No snapshots found in last {args.days} days")
        return

    print(f"Found {len(snapshots)} snapshots in {args.days} days\n")

    # Count ZT frequency for each leader
    zt_counts = {}  # {(code, name): count}
    for snap in snapshots:
        stocks = {s["code"]: s["name"] for s in snap.get("limit_up_stocks", [])}
        for sector, leaders in SECTOR_LEADERS.items():
            for code, name, _desc in leaders:
                key = (code, name)
                if key not in zt_counts:
                    zt_counts[key] = {"count": 0, "sectors": set()}
                if code in stocks:
                    zt_counts[key]["count"] += 1
                zt_counts[key]["sectors"].add(sector)

    # Report
    stale = []
    active = []
    for (code, name), info in sorted(zt_counts.items(), key=lambda x: -x[1]["count"]):
        sectors = "、".join(sorted(info["sectors"]))
        if info["count"] == 0:
            stale.append(f"  {name}({code}) — {sectors}")
        else:
            active.append(f"  {name}({code}) — ZT {info['count']}次/{args.days}天 — {sectors}")

    print(f"=== 活跃龙头 ({len(active)}) ===")
    for a in active:
        print(a)

    if stale:
        print(f"\n⚠️  边缘化龙头 ({len(stale)}) — {args.days}天内未涨停，建议检查：")
        for s in stale:
            print(s)
    else:
        print(f"\n✅ 所有龙头在{args.days}天内都有过涨停活动")

    # Check for missing sectors (no match between LLM output and SECTOR_LEADERS keys)
    print(f"\n📊 静态表覆盖 {len(SECTOR_LEADERS)} 个板块，{sum(len(v) for v in SECTOR_LEADERS.values())} 只龙头")


if __name__ == "__main__":
    main()
