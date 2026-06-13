#!/usr/bin/env python3
"""LLM 智能海选：基于大佬画像 + 本周复盘/简报 → 按各自方法论选股。

Usage:
    python3 scripts/llm_screener.py
    python3 scripts/llm_screener.py --date 2026-06-12  # 指定周五日期
"""

import argparse, json, os, re, sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

PROJ = Path(__file__).resolve().parent.parent
OUTPUT = PROJ / "output"
DATA = PROJ / "data" / "nga"
PROFILES_DIR = DATA / "bigshot_profiles"

API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
API_URL = "https://api.deepseek.com/v1/chat/completions"

BIGSHOTS = [
    ("幸运阿sai", "sai佬"),
    ("灰兔尾", "兔佬"),
    ("文驹", "文驹"),
    ("-阿狼-", "狼大"),
    ("F佬", "F佬"),
    ("喜帖街QAQ", "喜帖街"),
]


def call_llm(system: str, user: str) -> str:
    """Call DeepSeek API, return response text."""
    if not API_KEY:
        print("  [warn] 无 API key，跳过 LLM 调用")
        return ""
    try:
        r = requests.post(API_URL, headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        }, json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
            "max_tokens": 4096,
        }, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [warn] LLM 调用失败: {e}")
        return ""


def load_profile(name: str) -> dict | None:
    p = PROFILES_DIR / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def load_week_data(target_date: str) -> tuple[str, str, str]:
    """Load past week's postclose reviews, morning briefings, and last screener."""
    d = date.fromisoformat(target_date)
    mon = d - timedelta(days=d.weekday())  # Monday
    fri = d  # Friday

    reviews, briefings = [], []
    cur = mon
    while cur <= fri:
        rd = OUTPUT / "postclose" / cur.isoformat() / "review.md"
        md = OUTPUT / "morning" / cur.isoformat() / "briefing.md"
        if rd.exists():
            reviews.append(f"## {cur.isoformat()}\n{rd.read_text()[:4000]}")
        if md.exists():
            briefings.append(f"## {cur.isoformat()}\n{md.read_text()[:3000]}")
        cur += timedelta(days=1)

    # Previous week screener
    prev_fri = fri - timedelta(days=7)
    prev_scr = OUTPUT / "bigshot_screener" / f"{prev_fri.isoformat()}.md"
    prev_text = prev_scr.read_text()[:5000] if prev_scr.exists() else "（无上周海选数据）"

    return "\n\n".join(reviews), "\n\n".join(briefings), prev_text


def screen_bigshot(display: str, profile: dict, reviews: str, briefings: str, prev: str) -> str:
    """Generate picks for one bigshot based on their profile."""
    system = f"""你是一位A股投资专家。你的任务是模仿一位特定投资大佬的思维方式和选股逻辑，为他推荐下周值得关注的标的。

大佬画像：
- 投资风格：{profile.get('style','')}
- 风格详述：{profile.get('style_detail','')}
- 交易体系：{json.dumps(profile.get('trading_system',{}), ensure_ascii=False)}
- 投资哲学：{json.dumps(profile.get('philosophy',[]), ensure_ascii=False)}
- 能力圈板块：{json.dumps(profile.get('sectors',[]), ensure_ascii=False)}
- 建仓逻辑：{json.dumps(profile.get('entry_logic',[]), ensure_ascii=False)}
- 离场逻辑：{json.dumps(profile.get('exit_logic',[]), ensure_ascii=False)}
- 风控规则：{json.dumps(profile.get('risk_system',{}), ensure_ascii=False)}
- 关键指标：{json.dumps(profile.get('key_indicators',[]), ensure_ascii=False)}
- 偏好标的：{json.dumps(profile.get('stock_preferences',{}), ensure_ascii=False)}

请你完全代入这位大佬的视角：用他的方法论筛选标的，用他的逻辑判断买卖点，用他的风格描述理由。
对于每个推荐，必须说明：哪个具体的入场条件被满足了，基于什么市场信号。"""

    user = f"""以下是本周市场数据，请按这位大佬的方法论筛选 3-6 只下周值得关注的标的。

【本周盘后复盘】
{reviews[:8000]}

【本周盘前简报】
{briefings[:6000]}

【上周海选结果（如有）】
{prev[:3000]}

请以 JSON 格式输出（不要markdown包裹）：
{{
  "bias": "整体市场判断（一句话）",
  "picks": [
    {{
      "name": "股票名称",
      "code": "6位代码（未知填000000）",
      "action": "buy/watch",
      "confidence": "high/medium",
      "reason": "按大佬方法论解释为什么选这只（100字内）",
      "entry_condition": "触发了哪个具体的建仓条件",
      "risk": "主要风险（30字内）"
    }}
  ]
}}"""
    return call_llm(system, user)


def generate_report(target_date: str, results: list[dict]) -> str:
    lines = [f"# 🎯 大佬海选周报 · {target_date}", "",
             "*基于6位大佬投资画像 + 本周复盘/简报 → LLM按各自方法论智能选股*", "",
             "---", ""]
    for r in results:
        lines.append(f"## {r['display']}（{r['style']}）")
        lines.append(f"> 市场判断：{r.get('bias','')}")
        lines.append("")
        lines.append("| # | 标的 | 代码 | 操作 | 置信度 | 逻辑 | 入场条件 | 风险 |")
        lines.append("|---|------|------|------|--------|------|----------|------|")
        for i, p in enumerate(r.get("picks", []), 1):
            action_emoji = {"buy": "🟢", "watch": "🟡"}.get(p.get("action", ""), "")
            conf = {"high": "高", "medium": "中"}.get(p.get("confidence", ""), "")
            lines.append(f"| {i} | {p.get('name','')} | {p.get('code','')} | {action_emoji} | {conf} | {p.get('reason','')} | {p.get('entry_condition','')} | {p.get('risk','')} |")
        lines.append("")
    lines.append("---")
    lines.append(f"*自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 每周五更新*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not API_KEY:
        print("❌ 请设置 ANTHROPIC_AUTH_TOKEN 环境变量")
        sys.exit(1)

    target = args.date
    print(f"LLM 智能海选 · {target}")
    print(f"{'='*55}")

    # Load week data
    print("\n[1/4] 加载本周复盘/简报...")
    reviews, briefings, prev = load_week_data(target)
    print(f"  复盘: {len(reviews)} 天, 简报: {len(briefings)} 天")

    # Screen each bigshot
    results = []
    for fname, dname in BIGSHOTS:
        profile = load_profile(fname)
        if not profile:
            print(f"\n[跳过] {dname}: 无画像数据")
            continue

        print(f"\n[2/4] {dname} 智能选股中...", end=" ", flush=True)
        resp = screen_bigshot(dname, profile, reviews, briefings, prev)

        try:
            parsed = json.loads(resp.strip().removeprefix("```json").removesuffix("```").strip())
            parsed["display"] = dname
            parsed["style"] = profile.get("style", "")
            parsed["fname"] = fname
            results.append(parsed)
            picks = len(parsed.get("picks", []))
            print(f"{picks}只")
        except Exception as e:
            print(f"解析失败: {e}")

    if not results:
        print("无结果"); return

    # Generate report
    print(f"\n[3/4] 生成海选报告...")
    md = generate_report(target, results)

    scr_dir = OUTPUT / "bigshot_screener"
    scr_dir.mkdir(parents=True, exist_ok=True)
    out_md = scr_dir / f"{target}.md"
    out_md.write_text(md)
    print(f"  {out_md}")

    # Save JSON
    data_dir = DATA / "screen_results"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_json = data_dir / f"{target}.json"
    with open(out_json, "w") as f:
        json.dump({"date": target, "results": results}, f, ensure_ascii=False, indent=2)
    # Also save latest
    with open(data_dir / "screen_results.json", "w") as f:
        json.dump({"date": target, "results": results}, f, ensure_ascii=False, indent=2)
    print(f"  {out_json}")

    if args.dry_run:
        print("\n[Dry-run] 报告预览:")
        print(md[:2000])

    print(f"\n[4/4] 完成!")


if __name__ == "__main__":
    main()
