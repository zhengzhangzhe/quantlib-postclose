#!/usr/bin/env python3
"""LLM-generated bigshot screen rules. Rules live in screen_rules/ and are regenerated
from profile JSONs when profiles change."""

import json, re, requests, importlib, sys
from pathlib import Path
from datetime import datetime

PROJ = Path(__file__).resolve().parent.parent

# ── Stock data fetch ──
def fetch_stocks():
    import akshare as ak
    df = ak.stock_fund_flow_individual(symbol="即时")

    # Market cap from Eastern Money (paginated)
    try:
        url = 'http://82.push2.eastmoney.com/api/qt/clist/get'
        mkt = {}
        for page in range(1, 57):
            params = {'pn':page,'pz':100,'po':1,'np':1,'fltt':2,'invt':2,'fid':'f20',
                      'fs':'m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23','fields':'f12,f21'}
            r = requests.get(url, params=params, headers={'User-Agent':'Mozilla/5.0'}, timeout=15)
            data = r.json()
            if not data.get('data') or not data['data'].get('diff'): break
            for item in data['data']['diff']:
                mkt[item['f12']] = float(item.get('f21',0) or 0)
            if len(data['data']['diff']) < 100: break
        print(f"市值数据: {len(mkt)} 只")
    except Exception as e:
        print(f"市值获取失败: {e}")
        mkt = {}

    stocks = []
    for _, r in df.iterrows():
        code = str(r["股票代码"]).zfill(6)
        name = r["股票简称"]
        pct = float(str(r["涨跌幅"]).replace("%","")) if r["涨跌幅"] else 0
        turnover = float(str(r["换手率"]).replace("%","")) if r["换手率"] else 0
        nf = str(r["净额"])
        if "亿" in nf: net_flow = float(nf.replace("亿","")) * 1e8
        elif "万" in nf: net_flow = float(nf.replace("万","")) * 1e4
        else: net_flow = float(nf) if nf else 0
        stocks.append({"code":code,"name":name,"pct":pct,"turnover":turnover,
                       "net_flow":net_flow,"float_mkt":mkt.get(code,1e15)})
    return stocks


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


# ── Main ──
def main():
    _build_mapping()
    print(f"全量海选 · {datetime.now().strftime('%H:%M')}")
    stocks = fetch_stocks()
    print(f"数据: {len(stocks)} 只\n")

    rules = load_screen_rules()
    print(f"加载 {len(rules)} 个画像规则\n")

    all_results = {}

    for name, fn in sorted(rules.items()):
        display = SCREEN_KEYS.get(name, name)
        results = fn(stocks)
        print(f"=== {display}: {len(results)} 只 ===")
        for i, c in enumerate(results[:8], 1):
            mkt_str = f" {c['float_mkt']/1e8:.0f}亿" if c.get('float_mkt',0) < 1e14 else ""
            reasons_str = " · ".join(c.get("reasons", [])[:3])
            print(f"  {i}. {c['name']}({c['code']}) {c['pct']:+.1f}%{mkt_str} {reasons_str}")
        print()

        def pack(cands, n=20):
            return [{"name":c["name"],"code":c["code"],"pct":c["pct"],
                     "reasons":c.get("reasons",[]),"sector":c.get("sector",""),
                     "score":c.get("score",0)} for c in cands[:n]]

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
