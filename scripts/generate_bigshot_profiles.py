#!/usr/bin/env python3
"""Generate the bigshot profiles report — only their own stock picks from posts."""

import json
from pathlib import Path
from datetime import datetime

PROJ = Path(__file__).resolve().parent.parent

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

BIGSHOT_MAP = [
    ("ddddd519", "d佬", "超短连板"),
    ("-阿狼-", "狼大", "科技/军工/波段"),
    ("灰兔尾", "兔佬", "有色/半导/波段"),
    ("文驹", "文驹", "钨/有色/中长线"),
    ("达达鸭儿呀", "鸭佬", "航天/新能源/短线"),
    ("幸运阿sai", "sai佬", "半导体材料/波段"),
]


def load_stock_map():
    map_file = PROJ / "data" / "nga" / "stock_abbr_map.json"
    if map_file.exists():
        return json.loads(map_file.read_text())
    return {}

def collect_picks(user):
    pf = PROJ / "data" / "nga" / "bigshot_content" / f"{user}.json"
    if not pf.exists():
        return set()
    posts = json.loads(pf.read_text())["posts"]
    stocks = set()
    for p in posts:
        for kw in STOCK_KWS:
            if kw in p["text"]:
                stocks.add(kw)
    return stocks


def generate():
    profiles = {}
    for f in (PROJ / "data" / "nga" / "bigshot_profiles").glob("*.json"):
        profiles[f.stem] = json.loads(f.read_text())

    date = datetime.now().strftime("%Y-%m-%d")

    L = [f"# 大佬画像报告 · {date}", "",
         "*仅展示大佬在帖子里实际推荐的股票*", "", "---", ""]

    for user, label, style in BIGSHOT_MAP:
        profile = profiles.get(user, {})
        own = collect_picks(user)

        L.append(f"## {label} ({style})")
        post_count = profile.get("posts_collected", "?")
        L.append(f"**{profile.get('style','')}** | {post_count}帖")
        L.append(f"> {profile.get('philosophy','')[:100]}")
        L.append("")

        L.append("### 🔍 选股逻辑")
        L.append(f"- 入场: {profile.get('entry_logic','')}")
        L.append(f"- 出场: {profile.get('exit_logic','')}")
        L.append(f"- 领域: {', '.join(profile.get('sectors',[]))}")
        L.append("")

        if own:
            L.append(f"### 📝 帖子里推荐过的股票 ({len(own)}只)")
            stock_map = load_stock_map()
            L.append("| # | 股票 | 代码 |")
            L.append("|---|------|------|")
            for i, abbr in enumerate(sorted(own)[:20], 1):
                info = stock_map.get(abbr)
                if info:
                    L.append(f"| {i} | {info[0]} | {info[1]} |")
                else:
                    L.append(f"| {i} | {abbr} | - |")
        else:
            L.append(f"### 📝 帖子里推荐过的股票")
            L.append("*未检测到股票提及*")
        L.append("")
        L.append("---")
        L.append("")

    L.append(f"*生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    out = PROJ / "output" / "bigshot_picks" / f"{date}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L))
    print(f"Report: {out}")


if __name__ == "__main__":
    generate()
