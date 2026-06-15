#!/usr/bin/env python3
"""LLM-generated bigshot screen rules. Rules live in screen_rules/ and are regenerated
from profile JSONs when profiles change."""

import json, importlib, sys
from pathlib import Path
from datetime import datetime

PROJ = Path(__file__).resolve().parent.parent

from market_data import fetch_fund_flow


# ── Rule discovery ──
SCREEN_KEYS = {}   # module_name → display label
SCREEN_SAVE_KEYS = {} # module_name → save key in results JSON

def _build_mapping():
    """Build name→save_key mapping from profiles."""
    profiles_dir = PROJ / "data" / "nga" / "bigshot_profiles"
    key_map = {
        "幸运阿sai": ("sai", "sai佬"),
        "灰兔尾": ("tl", "兔佬"),
        "文驹": ("wj", "文驹"),
        "-阿狼-": ("wolf", "狼大"),
        "F佬": ("fl", "F佬"),
        "喜帖街QAQ": ("xjt", "喜帖街"),
        "猫指导": ("mao", "猫指导"),
    }
    for name, (save_key, display) in key_map.items():
        if (profiles_dir / f"{name}.json").exists():
            SCREEN_KEYS[name] = display
            SCREEN_SAVE_KEYS[name] = save_key


def load_screen_rules():
    """Dynamically import all screen functions from screen_rules/."""
    rules_dir = PROJ / "scripts" / "screen_rules"
    if str(rules_dir.parent) not in sys.path:
        sys.path.insert(0, str(rules_dir.parent))

    rules = {}
    for f in sorted(rules_dir.glob("*.py")):
        if f.stem == "__init__":
            continue
        try:
            mod = importlib.import_module(f"screen_rules.{f.stem}")
            if hasattr(mod, "screen"):
                rules[f.stem] = mod.screen
                if f.stem not in SCREEN_KEYS:
                    SCREEN_KEYS[f.stem] = f.stem
                    SCREEN_SAVE_KEYS[f.stem] = f.stem
        except Exception as e:
            print(f"  [warn] {f.stem}: {e}")
    return rules


# ── Postclose enrichment ──
def load_postclose_stocks(days=5):
    """Load limit-up stocks from recent postclose snapshots."""
    snap_dir = PROJ / "data" / "postclose"
    if not snap_dir.exists():
        return []
    snaps = sorted(snap_dir.glob("*/snapshot.json"), reverse=True)[:days]
    stocks = {}
    for sf in snaps:
        try:
            d = json.loads(sf.read_text())
            for s in d.get("limit_up_stocks", []):
                code = s.get("code", "")
                if code and code not in stocks:
                    stocks[code] = {
                        "code": code,
                        "name": s.get("name", code),
                        "pct": s.get("pct_chg", 0),
                        "turnover": s.get("turnover", 0),
                        "float_mkt": s.get("float_mkt", 0),
                        "net_flow": s.get("net_flow", 0),
                        "consecutive": s.get("consecutive", 0),
                        "industry": s.get("industry", ""),
                        "theme": [t["name"] for t in d.get("themes", [])
                                  if s.get("name") in t.get("member_stocks", [])],
                    }
        except: pass
    return list(stocks.values())


def enrich_with_postclose(profile_name, candidates, postclose_stocks):
    """Add postclose stocks that match the bigshot's profile but weren't caught by rules."""
    prof_file = PROJ / "data" / "nga" / "bigshot_profiles" / f"{profile_name}.json"
    if not prof_file.exists():
        return candidates
    profile = json.loads(prof_file.read_text())

    # Build keyword list from sectors + stock_preferences
    keywords = set()
    for s in profile.get("sectors", []):
        name = s["name"] if isinstance(s, dict) else s
        # Extract key terms from sector name
        for part in name.replace("/", " ").replace("（", " ").replace("）", " ").split():
            if len(part) >= 2:
                keywords.add(part)
    for sp_list in profile.get("stock_preferences", {}).values():
        for stock in sp_list:
            keywords.add(stock)

    seen_codes = {c["code"] for c in candidates}
    extra = []
    for ps in postclose_stocks:
        if ps["code"] in seen_codes:
            continue
        score = 0
        matched = []
        for kw in keywords:
            if kw in ps.get("industry", "") or kw in ps.get("name", "") or any(kw in t for t in ps.get("theme", [])):
                score += 3
                matched.append(kw)
        if score >= 3:
            extra.append({**ps, "score": score, "reasons": [f"复盘出现: {','.join(matched[:3])}"],
                          "sector": ps.get("industry", "")})

    # Merge and re-sort
    combined = candidates + sorted(extra, key=lambda x: -x["score"])
    return combined[:25]


# ── Main ──
def main():
    _build_mapping()
    print(f"全量海选 · {datetime.now().strftime('%H:%M')}")
    stocks, _ = fetch_fund_flow()
    print(f"数据: {len(stocks)} 只\n")

    print("加载近5日复盘数据...")
    postclose_stocks = load_postclose_stocks(days=5)
    print(f"复盘涨停股: {len(postclose_stocks)} 只\n")

    rules = load_screen_rules()
    print(f"加载 {len(rules)} 个画像规则\n")

    all_results = {}

    for name, fn in sorted(rules.items()):
        display = SCREEN_KEYS.get(name, name)
        results = fn(stocks)
        results = enrich_with_postclose(name, results, postclose_stocks)
        print(f"=== {display}: {len(results)} 只 ===")
        for i, c in enumerate(results[:8], 1):
            mkt_str = f" {c['float_mkt']/1e8:.0f}亿" if c.get('float_mkt',0) < 1e14 else ""
            reasons_str = " · ".join(c.get("reasons", [])[:3])
            print(f"  {i}. {c['name']}({c['code']}) {c['pct']:+.1f}%{mkt_str} {reasons_str}")
        print()

        def pack(cands, n=20):
            return [{"name":c["name"],"code":c["code"],"pct":c["pct"],
                     "reasons":c.get("reasons",[]),"sector":c.get("sector",""),
                     "score":c.get("score",0),"close":c.get("close",0),
                     "turnover":c.get("turnover",0)} for c in cands[:n]]

        all_results[SCREEN_SAVE_KEYS.get(name, name)] = pack(results)

    # Save
    today = datetime.now().strftime("%Y-%m-%d")
    out = PROJ / "data" / "nga" / "screen_results" / f"{today}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out_latest = PROJ / "data" / "nga" / "screen_results.json"

    result = {"date": today, **all_results}
    for path in [out, out_latest]:
        with open(path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Saved: {out} & {out_latest}")


if __name__ == "__main__":
    main()
