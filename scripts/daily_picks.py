#!/usr/bin/env python3
"""Daily LLM stock picks — each bigshot's profile × today's postclose × screener results."""

import json, os, requests
from pathlib import Path
from datetime import datetime, date

PROJ = Path(__file__).resolve().parent.parent
API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
LLM_URL = "https://api.deepseek.com/v1/chat/completions"

from market_data import fetch_fund_flow

# Display mapping
DISPLAY = {
    "幸运阿sai": "sai佬", "灰兔尾": "兔佬", "文驹": "文驹",
    "-阿狼-": "狼大", "F佬": "F佬", "喜帖街QAQ": "喜帖街", "猫指导": "猫指导",
}


def load_review(today: str) -> str:
    """Load today's postclose review markdown, truncate to ~8K chars."""
    path = PROJ / "output" / "postclose" / today / "review.md"
    if not path.exists():
        return "（今日复盘尚未生成）"
    text = path.read_text()
    # Keep the important sections, drop boilerplate
    if len(text) > 8000:
        # Find section boundaries
        for cutoff in ["## 12.", "## 13.", "## 14."]:
            idx = text.find(cutoff)
            if idx > 2000:
                text = text[:idx]
                break
        if len(text) > 8000:
            text = text[:8000] + "\n...(截断)"
    return text


def load_screener() -> dict:
    """Load latest screener results."""
    path = PROJ / "data" / "nga" / "screen_results.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def load_profile(name: str) -> dict:
    """Load a bigshot's profile JSON."""
    path = PROJ / "data" / "nga" / "bigshot_profiles" / f"{name}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def load_fund_flow_leaders() -> list:
    """Fetch top stocks by net inflow — captures slow-moving institutional leaders."""
    try:
        stocks, _ = fetch_fund_flow()
    except Exception:
        return []
    stocks.sort(key=lambda x: -x["net_flow"])
    return stocks[:200]


def match_profile(name: str, profile: dict, stocks: list) -> list:
    """Cross-reference stocks with bigshot's profile keywords + stock_preferences."""
    # Build keyword list from sectors + stock_preferences
    keywords = set()
    for s in profile.get("sectors", []):
        sname = s["name"] if isinstance(s, dict) else s
        for part in sname.replace("/"," ").replace("（"," ").replace("）"," ").split():
            if len(part) >= 2: keywords.add(part)
    for sp_list in profile.get("stock_preferences", {}).values():
        for stock in sp_list:
            keywords.add(stock)

    matches = []
    for s in stocks:
        matched = []
        for kw in keywords:
            if kw in s["name"] or kw in s.get("industry", ""):
                matched.append(kw)
        if matched:
            matches.append({**s, "reasons": [f"资金流入: {','.join(matched[:2])}"],
                           "score": len(matched) * 2})
    return sorted(matches, key=lambda x: -x["score"])[:15]


def generate_pick(name: str, profile: dict, review: str, candidates: list) -> dict:
    """Call LLM to generate 5 picks for one bigshot."""
    display = DISPLAY.get(name, name)

    # Merge: screener candidates + slow leaders from fund flow
    seen_codes = set()
    merged = []
    for c in candidates[:20]:
        seen_codes.add(c["code"])
        merged.append(c)

    # Add slow leaders (not already in candidates)
    flow_leaders = generate_pick.flow_cache.get(name, [])
    for s in flow_leaders:
        if s["code"] not in seen_codes:
            merged.append(s)
            seen_codes.add(s["code"])
            if len(merged) >= 30:
                break

    # Build candidate summary
    cand_text = ""
    for c in merged[:25]:
        reasons = " · ".join(c.get("reasons", [])[:3])
        price = f" 现价{c['close']:.2f}" if c.get('close', 0) > 0 else ""
        source = "💰" if "资金流入" in str(c.get("reasons",[])) else ""
        cand_text += f"- {source}{c['name']}({c['code']}) {c['pct']:+.1f}%{price} 换手{c.get('turnover',0):.1f}% {reasons}\n"
    if not cand_text:
        cand_text = "（今日无候选）"

    # Profile summary
    prof_text = f"""风格: {profile.get('style','')}
交易体系: {profile.get('trading_system',{}).get('name','') if isinstance(profile.get('trading_system'), dict) else profile.get('trading_system','')}
核心领域: {', '.join(s['name'] if isinstance(s,dict) else s for s in profile.get('sectors',[])[:4])}
入场逻辑: {'; '.join(profile.get('entry_logic',[])[:3])}
风控: {'; '.join(profile.get('risk_management',[])[:3]) if profile.get('risk_management') else profile.get('risk_system',{}).get('limits','')}
"""

    system = f"""你是{display}（{prof_text.strip()}）

根据今日收盘复盘数据和海选候选池，选出你最可能操作的5只股票。

输出JSON:
{{"picks": [
  {{"name":"股票简称","code":"6位代码","action":"买入/加仓/关注/减仓",
    "confidence":"高/中/低","reason":"选股理由(40字内)",
    "entry_timing":"入场时机: 明天什么条件/什么价位可以进, 必须包含具体价格或均线位(30字内)",
    "risk":"风险提示(20字内)"}}
],
 "bias":"整体偏多/偏空/中性",
 "comment":"一句话总结(50字内)"
}}

要求:
- 严格按画像的交易体系和入场逻辑选股, 不符合画像风格的不选
- 优先从海选候选池里选, 候选池没有合适的再从复盘数据里找
- 每只票的理由要体现画像的选股逻辑, 不能是泛泛的"看好"
- entry_timing必须写清楚: 明天什么条件触发才入场。候选池里有现价(收盘价)的, 基于现价说出具体入场价位。比如"回踩20日线约120元缩量"或"放量突破125元确认"或"现价132元附近开盘+2%内可追"。不能只写"等待回踩"这种没价位没条件的。
- 只输出JSON"""

    user = f"""## 今日复盘摘要

{review[:6000]}

## 海选候选池（按画像方法论初筛）

{cand_text}

请按你的交易体系选出5只。"""

    r = requests.post(LLM_URL,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"model":"deepseek-chat","messages":[
            {"role":"system","content":system},
            {"role":"user","content":user}
        ],"temperature":0.3,"max_tokens":2000,"response_format":{"type":"json_object"}},
        timeout=120)
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def render_report(today: str, all_picks: dict) -> str:
    """Generate markdown report from all picks."""
    L = [f"# 大佬每日选股 · {today}", "",
         "*基于画像×今日复盘×全市场海选的LLM精选*", "", "---", ""]

    for name, result in all_picks.items():
        display = DISPLAY.get(name, name)
        L.append(f"## {display}")
        L.append(f"> {result.get('comment','')}")
        L.append(f"> 整体判断：{result.get('bias','')}")
        L.append("")
        L.append("| # | 股票 | 代码 | 操作 | 信心 | 理由 | 入场时机 | 风险 |")
        L.append("|---|------|------|------|------|------|----------|------|")
        for i, p in enumerate(result.get("picks", [])[:5], 1):
            L.append(f"| {i} | {p['name']} | {p['code']} | {p.get('action','')} | "
                     f"{p.get('confidence','')} | {p.get('reason','')} | "
                     f"{p.get('entry_timing','')} | {p.get('risk','')} |")
        L.append("")
        L.append("---")
        L.append("")

    L.append(f"*生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 仅供参考*")
    return "\n".join(L)


def main():
    if not API_KEY:
        print("无 API key，跳过")
        return

    today = date.today().isoformat()
    print(f"每日选股 · {today}")

    review = load_review(today)
    print(f"复盘: {len(review)} 字符")

    # Pre-load slow leaders from fund flow (institutional buying, not limit-up)
    print("加载资金流慢牛...", end=" ", flush=True)
    flow_stocks = load_fund_flow_leaders()
    print(f"{len(flow_stocks)} 只")

    # Cache per-bigshot slow leaders
    generate_pick.flow_cache = {}
    for name in DISPLAY:
        profile = load_profile(name)
        if profile:
            generate_pick.flow_cache[name] = match_profile(name, profile, flow_stocks)

    screener = load_screener()
    save_keys = {
        "幸运阿sai": "sai", "灰兔尾": "tl", "文驹": "wj",
        "-阿狼-": "wolf", "F佬": "fl", "喜帖街QAQ": "xjt", "猫指导": "mao",
    }

    all_picks = {}
    for name in DISPLAY:
        profile = load_profile(name)
        if not profile:
            print(f"  {DISPLAY[name]}: 无画像, 跳过")
            continue

        key = save_keys.get(name, name)
        candidates = screener.get(key, [])
        print(f"  {DISPLAY[name]}: {len(candidates)} 候选 → LLM ...", end=" ", flush=True)
        try:
            result = generate_pick(name, profile, review, candidates)
            all_picks[name] = result
            n = len(result.get("picks", []))
            print(f"{n}只")
        except Exception as e:
            print(f"失败: {e}")

    if not all_picks:
        print("无结果")
        return

    report = render_report(today, all_picks)
    out_dir = PROJ / "output" / "daily_picks"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{today}.md"
    report_path.write_text(report)
    # Also save structured JSON for verification
    json_path = out_dir / f"{today}.json"
    json_path.write_text(json.dumps(all_picks, ensure_ascii=False, indent=2))
    print(f"\n报告: {report_path} + {json_path}")


if __name__ == "__main__":
    main()
