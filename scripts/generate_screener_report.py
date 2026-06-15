#!/usr/bin/env python3
"""Generate the weekly bigshot screener report from saved data."""

import json
from pathlib import Path
from datetime import datetime, timedelta

PROJ = Path(__file__).resolve().parent.parent

# ── Stock name keywords to match in大佬's posts ──
STOCK_KWS = [
    "利通","胜宏","中钨","亨通","兆龙","博杰","鼎泰","四方","沪硅","光迅",
    "华工","长飞","中兴","烽火","中际","旭创","诺德","香江","华电","粤电",
    "新亚","天地","晋控","春秋","闻泰","欧晶","盛剑","泓淋","远东","和胜",
    "厦钨","章源","士兰微","东方钽","天健","步步高","茂业","中环","航发",
    "卫星","嘉德","赛微","华能","江苏","深南","兰石","浙富","海陆","宝色",
    "科陆","雄韬","蔚蓝","黄河","克来","欧科","锐科","大族","博迁","新金",
    "豫能","力源","云端","中恒","紫金","铜陵","江西","生益","鹏鼎",
    "万通","川润","直真","大众","埃斯顿","华峰","中国铝","北方华创",
    "中微公司","长电科技","通富微电","长川科技","天孚通信","新易盛",
    "烽火通信","航天彩虹","浪潮信息","科大讯飞","江淮汽车",
]


def collect_own_picks():
    """Extract stocks each大佬 mentioned in their posts."""
    result = {}
    for user in ["-阿狼-","灰兔尾","文驹","幸运阿sai","F佬","喜帖街QAQ","猫指导"]:
        pf = PROJ / "data" / "nga" / "bigshot_content" / f"{user}.json"
        if not pf.exists():
            result[user] = set()
            continue
        posts = json.loads(pf.read_text())["posts"]
        stocks = set()
        for p in posts:
            for kw in STOCK_KWS:
                if kw in p["text"]:
                    stocks.add(kw)
        result[user] = stocks
    return result


def generate():
    # Load data
    snaps = sorted((PROJ / "data" / "postclose").glob("*/snapshot.json"))
    if snaps:
        date = snaps[-1].parent.name  # directory name is YYYY-MM-DD
    else:
        date = datetime.now().strftime("%Y-%m-%d")

    screen_file = PROJ / "data" / "nga" / "screen_results.json"
    if not screen_file.exists():
        print("No screen results yet")
        return
    screen = json.loads(screen_file.read_text())

    profiles = {}
    for f in (PROJ / "data" / "nga" / "bigshot_profiles").glob("*.json"):
        profiles[f.stem] = json.loads(f.read_text())

    own_picks = collect_own_picks()

    # Screen key → (user, label, style)
    SCREEN_MAP = [
        ("wj", "文驹", "文驹", "钨/有色/PCB"),
        ("tl", "灰兔尾", "兔佬", "有色/半导低位"),
        ("sai", "幸运阿sai", "sai佬", "半导体材料"),
        ("wolf", "-阿狼-", "狼大", "科技/军工"),
        ("fl", "F佬", "F佬", "超短情绪/量化跟随"),
        ("xjt", "喜帖街QAQ", "喜帖街", "存储模组/产业周期"),
        ("mao", "猫指导", "猫指导", "存储芯片/低吸策略"),
    ]

    # Date formatting
    d = datetime.strptime(date, '%Y-%m-%d')
    dow = ['周一','周二','周三','周四','周五','周六','周日'][d.weekday()]
    ws = d - timedelta(days=d.weekday())
    we = ws + timedelta(days=4)

    L = [f"# 大佬海选周报 · {date} {dow} ({ws.strftime('%m/%d')}~{we.strftime('%m/%d')})", "",
         "*每位大佬两部分：帖子里实际推过的股票 + 按方法论从全市场筛出的候选*", "", "---", ""]

    for key, user, label, style in SCREEN_MAP:
        cands = screen.get(key, [])
        profile = profiles.get(user, {})
        own = own_picks.get(user, set())

        L.append(f"## {label} ({style})")
        L.append(f"> {profile.get('philosophy','')[:80]}")
        L.append("")

        # Part 1:大佬's own picks
        if own:
            L.append(f"### 📝 帖子里推荐过的 ({len(own)}只)")
            # Load stock name map
            stock_map = {}
            map_file = PROJ / "data" / "nga" / "stock_abbr_map.json"
            if map_file.exists():
                stock_map = json.loads(map_file.read_text())
            items = []
            for abbr in sorted(own)[:15]:
                info = stock_map.get(abbr)
                items.append(f"{info[0]}({info[1]})" if info else abbr)
            L.append(" · ".join(items))
        else:
            L.append(f"### 📝 帖子里推荐过的")
            L.append("*未检测到*")
        L.append("")

        # Part 2: Screened picks
        L.append(f"### 🎯 按方法论海选 ({len(cands)}只)")
        if cands:
            L.append("| # | 股票 | 代码 | 涨跌 | 理由 |")
            L.append("|---|---|---|---|---|")
            for i, c in enumerate(cands[:10], 1):
                pct_str = f"{c.get('pct',0):+.1f}%"
                reasons = c.get("reasons", [c.get("sector","")])
                reason_str = " · ".join(str(r) for r in reasons[:3])
                L.append(f"| {i} | {c['name']} | {c['code']} | {pct_str} | {reason_str} |")
        else:
            L.append("*本周无符合条件的候选*")
        L.append("")
        L.append("---")
        L.append("")

    L.append(f"*生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 每周五更新*")

    # Save by screen date AND today's date (for history)
    today = datetime.now().strftime("%Y-%m-%d")
    for d in {date, today}:
        out = PROJ / "output" / "bigshot_screener" / f"{d}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(L))
    print(f"Reports saved for {date} & {today}")


if __name__ == "__main__":
    generate()
