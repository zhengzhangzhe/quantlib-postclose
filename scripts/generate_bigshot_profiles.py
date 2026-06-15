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
    ("-阿狼-", "狼大", "科技/军工/波段"),
    ("灰兔尾", "兔佬", "有色/半导/波段"),
    ("文驹", "文驹", "钨/有色/中长线"),
    ("幸运阿sai", "sai佬", "半导体材料/波段"),
    ("F佬", "F佬", "超短情绪/量化跟随"),
    ("喜帖街QAQ", "喜帖街", "存储模组/产业周期"),
    ("猫指导", "猫指导", "存储芯片/低吸策略"),
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
        sectors = profile.get('sectors', [])
        sector_names = [
            s['name'] if isinstance(s, dict) else s
            for s in sectors
        ]
        L.append(f"- 领域: {', '.join(sector_names)}")
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

    # Also generate individual profile pages for the website
    prof_out = PROJ / "output" / "bigshot_profiles"
    prof_out.mkdir(parents=True, exist_ok=True)
    for user, label, style in BIGSHOT_MAP:
        profile = profiles.get(user, {})
        if not profile:
            continue
        md = profile_to_markdown(user, label, style, profile)
        (prof_out / f"{user}.md").write_text(md)
        print(f"  Profile: {prof_out / f'{user}.md'}")


def profile_to_markdown(user: str, label: str, style: str, profile: dict) -> str:
    """Convert profile JSON to standalone markdown page."""
    L = []
    a = lambda s="": L.append(s)

    posts = profile.get("posts_collected", "?")
    uid = profile.get("uid", "?")
    a(f"# {label}（{user}）投资画像")
    a()
    a(f"> {posts}条发言 · UID: {uid} · {style}")
    a()
    a("---")
    a()

    # Trading system
    ts = profile.get("trading_system", "")
    if isinstance(ts, dict):
        a(f"## 交易体系：{ts.get('name', '')}")
        a()
        if ts.get("foundation"):
            a(ts["foundation"])
            a()
        if ts.get("trend_judgment"):
            tj = ts["trend_judgment"]
            a("| 状态 | 特征 | 应对 |")
            a("|------|------|------|")
            if isinstance(tj, dict):
                for k, v in tj.items():
                    if isinstance(v, dict):
                        a(f"| {k} | {v.get('condition','')} | {v.get('action','')} |")
                    else:
                        a(f"| {k} | {v} |")
            a()
        if ts.get("mainline_three_layer"):
            a("### 主线判断三层体系")
            a()
            a("| 层级 | 信号 | 含义 |")
            a("|------|------|------|")
            for layer in ts["mainline_three_layer"]:
                a(f"| 第{layer.get('layer','?')}层 | {layer.get('signal','')} | {layer.get('meaning','')} |")
            a()
    elif isinstance(ts, str) and ts:
        a(f"## 交易体系：{ts}")
        a()

    # Risk system
    rs = profile.get("risk_system")
    if rs and isinstance(rs, dict):
        a("## 风控体系")
        a()
        if rs.get("tiers"):
            a("| 级别 | 触发条件 | 操作 |")
            a("|------|----------|------|")
            for t in rs["tiers"]:
                a(f"| {t.get('level','')} | {t.get('trigger','')} | {t.get('action','')} |")
            a()
        if rs.get("position"):
            a(f"- 仓位结构：{rs['position']}")
        if rs.get("limits"):
            a(f"- 仓位限制：{rs['limits']}")
        a()
    elif profile.get("risk_management"):
        a("## 风控体系")
        a()
        for r in profile["risk_management"]:
            a(f"- {r}")
        a()

    # Style detail
    if profile.get("style_detail"):
        a("## 风格概述")
        a()
        a(profile["style_detail"])
        a()

    # Philosophy
    ph = profile.get("philosophy", [])
    if ph:
        a("## 投资哲学")
        a()
        for p in ph:
            a(f"- {p}")
        a()

    # Sectors
    sectors = profile.get("sectors", [])
    if sectors:
        a("## 能力圈")
        a()
        a("| 领域 | 权重 | 逻辑 |")
        a("|------|------|------|")
        for s in sectors:
            name = s["name"] if isinstance(s, dict) else s
            weight = s.get("weight", "") if isinstance(s, dict) else ""
            reason = s.get("reason", "") if isinstance(s, dict) else ""
            a(f"| {name} | {weight} | {reason} |")
        a()

    # Entry/Exit logic
    entry = profile.get("entry_logic", [])
    if entry:
        a("## 入场逻辑")
        a()
        for e in entry:
            a(f"- {e}")
        a()

    exit_logic = profile.get("exit_logic", [])
    if exit_logic:
        a("## 出场逻辑")
        a()
        for e in exit_logic:
            a(f"- {e}")
        a()

    # Key indicators
    ki = profile.get("key_indicators", [])
    if ki:
        a("## 关键指标")
        a()
        for k in ki:
            a(f"- {k}")
        a()

    # Stock preferences
    sp = profile.get("stock_preferences", {})
    if sp:
        a("## 标的池")
        a()
        for cat, stocks in sp.items():
            a(f"- **{cat}**：{'、'.join(stocks[:8])}{' 等' if len(stocks) > 8 else ''}")
        a()

    # Notable traits
    nt = profile.get("notable_traits", [])
    if nt:
        a("## 显著特征")
        a()
        for t in nt:
            a(f"- {t}")
        a()

    # Latest view
    lv = profile.get("latest_view")
    if lv:
        a("## 最新观点")
        a()
        if lv.get("bias"):
            a(f"偏多偏空：{lv['bias']}")
        if lv.get("outlook"):
            a(f"展望：{lv['outlook']}")
        if lv.get("stocks"):
            a(f"关注标的：{'、'.join(lv['stocks'])}")
        if lv.get("as_of"):
            a(f"（截至 {lv['as_of']}）")
        a()

    a(f"*自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    return "\n".join(L)


if __name__ == "__main__":
    generate()
