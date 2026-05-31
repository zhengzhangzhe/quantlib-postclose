#!/usr/bin/env python3
"""Data-driven stock screener using bigshot methodologies."""

import json, re
from pathlib import Path
from datetime import datetime

PROJ = Path(__file__).resolve().parent.parent

# ── d佬: 小市值连板加速 ──
def screen_dl(stocks):
    candidates = []
    for s in stocks:
        score = 0; reasons = []
        if s["pct"] >= 9.5: score += 3; reasons.append("涨停")
        elif s["pct"] >= 5: score += 2; reasons.append("大阳线")
        elif s["pct"] >= 3: score += 1; reasons.append("中阳")
        else: continue
        if 5 <= s["turnover"] <= 30: score += 2; reasons.append(f"换手{s['turnover']:.0f}%")
        else: continue
        if s["net_flow"] > 0: score += 1; reasons.append("资金流入")
        if score >= 4: candidates.append({**s, "score": score, "reasons": reasons})
    return sorted(candidates, key=lambda x: -x["score"])

# ── 文驹: 钨/有色/PCB ──
WJ_KEYWORDS = {
    "钨矿": ["中钨","翔鹭","厦钨","章源","钨"],
    "铜铝": ["铜陵","紫金","江铜","中铝","华峰","和胜"],
    "PCB": ["鹏鼎","景旺","博敏","方正","沪电","深南","生益","胜宏","东山","鼎泰","博杰"],
    "锂钴": ["天齐","赣锋","华友","华钴","盛新","雅化"],
    "稀土": ["北方稀土","盛和","广晟","中科"],
    "光通信": ["亨通","中际","旭创","光迅","长飞","烽火","华工","兆龙"],
}
def screen_wj(stocks):
    candidates = []
    for s in stocks:
        sector = ""; name = s["name"]
        for kw_group, keywords in WJ_KEYWORDS.items():
            for kw in keywords:
                if kw in name: sector = kw_group; break
            if sector: break
        if not sector: continue
        score = 0; reasons = [sector]
        if 0 <= s["pct"] <= 5: score += 3; reasons.append("温和上涨")
        elif 5 < s["pct"] <= 9.5: score += 2
        elif s["pct"] > 9.5: score += 1
        else: score += 1
        if 1 <= s["turnover"] <= 8: score += 2
        elif 8 < s["turnover"] <= 15: score += 1
        if s["net_flow"] > 0: score += 1
        if score >= 3: candidates.append({**s, "score": score, "reasons": reasons, "sector": sector})
    return sorted(candidates, key=lambda x: -x["score"])

# ── 兔佬: 有色/半导体, 中长线低位建仓 ──
TL_KW = {"有色":["中钨","钨","铜陵","紫金","东方钽","锗","锡","镍","锂业","锆","厦门钨"],
         "半导体":["士兰微","中芯","华虹","北方华创","中微","韦尔","兆易","卓胜微","闻泰","三安","长电"],
         "光通信":["亨通","中际","旭创","光迅","长飞","烽火","天孚","新易盛"]}
def screen_tl(stocks):
    cand = []
    for s in stocks:
        sec = ""; n = s["name"]
        for g, ks in TL_KW.items():
            for k in ks:
                if k in n: sec = g; break
            if sec: break
        if not sec: continue
        sc = 0; rs = [sec]
        if -3 <= s["pct"] <= 3: sc += 4; rs.append("横盘低位")
        elif -5 <= s["pct"] < -3: sc += 3; rs.append("回调低吸")
        elif 3 < s["pct"] <= 6: sc += 2
        else: continue
        if 1 <= s["turnover"] <= 6: sc += 2; rs.append("缩量蓄力")
        if s["net_flow"] > 0: sc += 1
        if sc >= 4: cand.append({**s,"score":sc,"reasons":rs,"sector":sec})
    return sorted(cand, key=lambda x: -x["score"])

# ── 鸭佬: 航天/新能源/科技, 打板+低吸 ──
YL_KW = {"航天军工":["航发","中航","航天","沈飞","西飞","洪都","中国卫","光电","北斗"],
         "新能源":["宁德","比亚迪","阳光","隆基","通威","天合","亿纬","国轩","赣锋","华友"],
         "科技":["中芯","寒武","海光","科大","浪潮","中科曙光","金山","广联达"],
         "汽车":["潍柴","德赛","拓普","赛力","江淮","长城","长安"]}
def screen_yl(stocks):
    cand = []
    for s in stocks:
        sec = ""; n = s["name"]
        for g, ks in YL_KW.items():
            for k in ks:
                if k in n: sec = g; break
            if sec: break
        if not sec: continue
        sc = 0; rs = [sec]
        if s["pct"] >= 9.5: sc += 3; rs.append("涨停")
        elif s["pct"] >= 5: sc += 1; rs.append("大阳")
        elif -3 <= s["pct"] <= 0: sc += 2; rs.append("回调低吸")
        else: continue
        if 5 <= s["turnover"] <= 25: sc += 2
        if s["net_flow"] > 0: sc += 1
        if sc >= 3: cand.append({**s,"score":sc,"reasons":rs,"sector":sec})
    return sorted(cand, key=lambda x: -x["score"])

# ── sai佬: 半导体材料, 低位+逻辑催化 ──
SAI_KW = {"半导体材料":["沪硅","立昂微","TCL中环","有研","江丰","雅克","南大","上海新阳","晶瑞","容大"],
          "设备":["北方华创","中微","盛美","拓荆","长川","精测","至纯"],
          "封装":["长电","通富","华天","晶方","甬矽"],
          "硅片":["中环","立昂微","沪硅","中晶","神工"]}
def screen_sai(stocks):
    cand = []
    for s in stocks:
        sec = ""; n = s["name"]
        for g, ks in SAI_KW.items():
            for k in ks:
                if k in n: sec = g; break
            if sec: break
        if not sec: continue
        sc = 0; rs = [sec]
        if -5 <= s["pct"] <= 2: sc += 4; rs.append("低位建仓区")
        elif 2 < s["pct"] <= 5: sc += 3; rs.append("温和启动")
        else: continue
        if 1 <= s["turnover"] <= 8: sc += 2; rs.append("缩量酝酿")
        if s["net_flow"] > 0: sc += 1
        if sc >= 4: cand.append({**s,"score":sc,"reasons":rs,"sector":sec})
    return sorted(cand, key=lambda x: -x["score"])

# ── 狼大: 科技/军工/半导体 ──
WOLF_KEYWORDS = {
    "半导体": ["中芯","华虹","北方华创","中微","寒武","海光","士兰微","闻泰"],
    "AI算力": ["浪潮","中科曙光","科大讯飞","海康"],
    "航天军工": ["航发","中航","航天","中国卫","沈飞","西飞"],
    "通信5G": ["中兴","烽火","光迅","长飞","亨通","中际","天孚","新易盛"],
}
def screen_wolf(stocks):
    candidates = []
    for s in stocks:
        sector = ""; name = s["name"]
        for kw_group, keywords in WOLF_KEYWORDS.items():
            for kw in keywords:
                if kw in name: sector = kw_group; break
            if sector: break
        if not sector: continue
        score = 0; reasons = [sector]
        if -3 <= s["pct"] <= 3: score += 3; reasons.append("横盘可入")
        elif 3 < s["pct"] <= 7: score += 2
        elif s["pct"] > 7: score += 1
        if 2 <= s["turnover"] <= 12: score += 2
        if s["net_flow"] > 1e7: score += 1
        if score >= 4: candidates.append({**s, "score": score, "reasons": reasons, "sector": sector})
    return sorted(candidates, key=lambda x: -x["score"])

def main():
    import akshare as ak
    print(f"全量海选 · {datetime.now().strftime('%H:%M')}")
    df = ak.stock_fund_flow_individual(symbol="即时")
    
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
        stocks.append({"code":code,"name":name,"pct":pct,"turnover":turnover,"net_flow":net_flow})
    
    print(f"数据: {len(stocks)} 只\n")
    
    screens = [("d佬(超短)",screen_dl),("文驹(钨/有色)",screen_wj),
               ("兔佬(有色/半导)",screen_tl),("鸭佬(航天/新能源)",screen_yl),
               ("sai佬(半导材料)",screen_sai),("狼大(科技)",screen_wolf)]
    for name, fn in screens:
        results = fn(stocks)
        print(f"=== {name}: {len(results)} 只 ===")
        for i, c in enumerate(results[:8], 1):
            print(f"  {i}. {c['name']}({c['code']}) {c['pct']:+.1f}% {c.get('sector','')}")
        print()
    
    # Save
    out = PROJ / "data" / "nga" / "screen_results.json"
    with open(out, "w") as f:
        json.dump({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "d_candidates": [{"name":c["name"],"code":c["code"],"pct":c["pct"]} for c in screen_dl(stocks)[:20]],
            "wj_candidates": [{"name":c["name"],"code":c["code"],"pct":c["pct"]} for c in screen_wj(stocks)[:20]],
            "tl_candidates": [{"name":c["name"],"code":c["code"],"pct":c["pct"]} for c in screen_tl(stocks)[:20]],
            "yl_candidates": [{"name":c["name"],"code":c["code"],"pct":c["pct"]} for c in screen_yl(stocks)[:20]],
            "sai_candidates": [{"name":c["name"],"code":c["code"],"pct":c["pct"]} for c in screen_sai(stocks)[:20]],
            "wolf_candidates": [{"name":c["name"],"code":c["code"],"pct":c["pct"]} for c in screen_wolf(stocks)[:20]],
        }, f, ensure_ascii=False, indent=2)
    print(f"Saved: {out}")

if __name__ == "__main__":
    main()
