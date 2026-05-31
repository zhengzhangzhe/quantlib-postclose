#!/usr/bin/env python3
"""Data-driven stock screener using bigshot methodologies. Full market + market cap."""

import json, re, requests
from pathlib import Path
from datetime import datetime

PROJ = Path(__file__).resolve().parent.parent

# ── Fetch ──
def fetch_stocks():
    import akshare as ak
    df = ak.stock_fund_flow_individual(symbol="即时")

    # Market cap from Eastern Money (paginated)
    try:
        url = 'http://82.push2.eastmoney.com/api/qt/clist/get'
        mkt = {}
        for page in range(1, 57):  # ~56 pages x 100 = 5600 stocks
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

# ── Helpers ──
def match_sector(name, keywords):
    for sector, kws in keywords.items():
        for kw in kws:
            if kw in name: return sector
    return ""

# ── d佬: uses snapshot limit-up pool (has float_mkt + consecutive) ──
def screen_dl(stocks):
    # Load snapshot for detail data
    try:
        snap = json.loads(sorted((PROJ/"data"/"postclose").glob("*/snapshot.json"))[-1].read_text())
        lu = {str(s["code"]).split(".")[0].zfill(6): s for s in snap["limit_up_stocks"]}
    except: lu = {}

    candidates = []
    for s in stocks:
        code = s["code"]
        sd = lu.get(code, {})
        if not sd: continue  # must be in limit-up pool

        score = 0; reasons = []
        pct = sd.get("pct_chg",0)
        turnover = sd.get("turnover",0)
        f_mkt = sd.get("float_mkt",0)
        net_flow = sd.get("net_flow",0)
        consecutive = sd.get("consecutive",0)
        break_cnt = sd.get("break_cnt",0)
        first_time = str(sd.get("first_time",""))

        # 连板
        if consecutive >= 2: score += 3; reasons.append(f"{consecutive}连板")
        elif consecutive == 1: score += 1; reasons.append("首板")
        # 市值 <100亿
        if f_mkt < 30e8: score += 3; reasons.append(f"市值{f_mkt/1e8:.0f}亿")
        elif f_mkt < 60e8: score += 2; reasons.append(f"市值{f_mkt/1e8:.0f}亿")
        elif f_mkt < 100e8: score += 1
        else: continue
        # 换手
        if 5 <= turnover <= 15: score += 2; reasons.append(f"换手{turnover:.1f}%")
        elif 3 <= turnover <= 25: score += 1
        else: continue
        # 封板时间
        try:
            ft = int(str(first_time).zfill(6))
            if ft <= 94000: score += 2; reasons.append("早盘封板")
        except: pass
        # 非一字板
        if break_cnt == 0 and turnover < 3: continue
        # 资金
        if net_flow > 0: score += 1; reasons.append("资金流")

        if score >= 5: candidates.append({**s,"score":score,"reasons":reasons,"float_mkt":f_mkt})
    return sorted(candidates, key=lambda x: -x["score"])

# ── 文驹: 钨/有色/PCB ──
WJ_KW = {
    "钨矿": ["中钨高新","翔鹭钨业","厦门钨业","章源钨业","江钨装备"],
    "铜铝": ["铜陵有色","紫金矿业","江西铜业","中国铝业","华峰铝业","和胜股份"],
    "PCB": ["鹏鼎控股","景旺电子","博敏电子","方正科技","沪电股份","深南电路","生益科技","胜宏科技","东山精密","鼎泰高科","博杰股份"],
    "锂钴": ["天齐锂业","赣锋锂业","华友钴业","盛新锂能","雅化集团"],
    "稀土": ["北方稀土","盛和资源","广晟有色","中科三环"],
    "光通信": ["亨通光电","中际旭创","光迅科技","长飞光纤","烽火通信","华工科技","兆龙互连"],
}
def screen_wj(stocks):
    # 钨板块趋势信号 (ETF proxy)
    WU_PROXIES = {"厦门钨业","中钨高新","章源钨业","翔鹭钨业","江钨装备"}
    wu_pcts = [s["pct"] for s in stocks if s["name"] in WU_PROXIES]
    wu_pos = sum(1 for p in wu_pcts if p > 0)
    wu_avg = sum(wu_pcts)/len(wu_pcts) if wu_pcts else 0
    wu_signal = wu_avg > 1 and wu_pos >= len(wu_pcts)//2

    cand = []
    for s in stocks:
        sec = match_sector(s["name"], WJ_KW)
        if not sec: continue
        sc = 0; rs = [sec]
        # 文驹: 行业拐点重仓
        if 0 <= s["pct"] <= 5: sc += 3; rs.append("温和上涨")
        elif 5 < s["pct"] <= 8: sc += 1; rs.append(f"+{s['pct']:.1f}%")
        else: continue
        if 1 <= s["turnover"] <= 5: sc += 3; rs.append(f"换手{s['turnover']:.1f}%")
        elif 5 < s["turnover"] <= 8: sc += 1
        else: continue
        if s["float_mkt"] > 50e8: sc += 2; rs.append(f"容量{s['float_mkt']/1e8:.0f}亿")
        if s["net_flow"] > 0: sc += 1
        # 钨板块趋势加分
        if wu_signal and sec == "钨矿": sc += 3; rs.append("钨板块走强")
        if sc >= 6: cand.append({**s,"score":sc,"reasons":rs,"sector":sec})
    return sorted(cand, key=lambda x: -x["score"])

# ── 兔佬: 有色/半导体, 中长线低位 ──
TL_KW = {
    "有色": ["中钨高新","厦门钨业","章源钨业","铜陵有色","紫金矿业","东方钽业","江钨装备"],
    "半导体": ["士兰微","中芯国际","华虹公司","北方华创","中微公司","韦尔股份","兆易创新","闻泰科技","三安光电","长电科技"],
    "光通信": ["亨通光电","中际旭创","光迅科技","长飞光纤","烽火通信","天孚通信","新易盛"],
}
def screen_tl(stocks):
    cand = []
    for s in stocks:
        sec = match_sector(s["name"], TL_KW)
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
YL_KW = {
    "航天军工": ["航发动力","中航沈飞","航天彩虹","中国卫星","光电股份","北斗星通","中国卫通"],
    "新能源": ["宁德时代","比亚迪","阳光电源","隆基绿能","通威股份","天合光能","亿纬锂能","国轩高科","赣锋锂业","华友钴业"],
    "科技": ["中芯国际","寒武纪","海光信息","科大讯飞","浪潮信息","中科曙光","金山办公","广联达"],
    "汽车": ["潍柴动力","德赛西威","拓普集团","赛力斯","江淮汽车","长城汽车","长安汽车"],
}
def screen_yl(stocks):
    cand = []
    for s in stocks:
        sec = match_sector(s["name"], YL_KW)
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
SAI_KW = {
    "半导体材料": ["沪硅产业","立昂微","有研新材","江丰电子","雅克科技","南大光电","上海新阳","晶瑞电材","容大感光"],
    "设备": ["北方华创","中微公司","盛美上海","拓荆科技","长川科技","精测电子","至纯科技"],
    "封装": ["长电科技","通富微电","华天科技","晶方科技","甬矽电子"],
    "硅片": ["TCL中环","立昂微","沪硅产业","中晶科技"],
}
def screen_sai(stocks):
    cand = []
    for s in stocks:
        sec = match_sector(s["name"], SAI_KW)
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
WOLF_KW = {
    "半导体": ["中芯国际","华虹公司","北方华创","中微公司","寒武纪","海光信息","士兰微","闻泰科技"],
    "AI算力": ["浪潮信息","中科曙光","科大讯飞","海康威视"],
    "航天军工": ["航发动力","中航沈飞","航天彩虹","中国卫星","中国卫通"],
    "通信5G": ["中兴通讯","烽火通信","光迅科技","长飞光纤","亨通光电","中际旭创","天孚通信","新易盛"],
}
def screen_wolf(stocks):
    cand = []
    for s in stocks:
        sec = match_sector(s["name"], WOLF_KW)
        if not sec: continue
        sc = 0; rs = [sec]
        if -3 <= s["pct"] <= 3: sc += 3; rs.append("横盘可入")
        elif 3 < s["pct"] <= 7: sc += 2
        elif s["pct"] > 7: sc += 1
        if 2 <= s["turnover"] <= 12: sc += 2
        if s["net_flow"] > 1e7: sc += 1
        if sc >= 4: cand.append({**s,"score":sc,"reasons":rs,"sector":sec})
    return sorted(cand, key=lambda x: -x["score"])

# ── Main ──
def main():
    print(f"全量海选 · {datetime.now().strftime('%H:%M')}")
    stocks = fetch_stocks()
    print(f"数据: {len(stocks)} 只\n")

    for name, fn in [("d佬(超短)",screen_dl),("文驹(钨/有色)",screen_wj),
        ("兔佬(有色/半导)",screen_tl),("鸭佬(航天/新能源)",screen_yl),
        ("sai佬(半导材料)",screen_sai),("狼大(科技)",screen_wolf)]:
        results = fn(stocks)
        print(f"=== {name}: {len(results)} 只 ===")
        for i, c in enumerate(results[:8], 1):
            mkt_str = f" {c['float_mkt']/1e8:.0f}亿" if c.get('float_mkt',0) < 1e14 else ""
            print(f"  {i}. {c['name']}({c['code']}) {c['pct']:+.1f}%{mkt_str} {c.get('sector','')}")
        print()

    today = datetime.now().strftime("%Y-%m-%d")
    out = PROJ / "data" / "nga" / "screen_results" / f"{today}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Also save as latest for report generator
    out_latest = PROJ / "data" / "nga" / "screen_results.json"
    def pack(cands, n=20):
        return [{"name":c["name"],"code":c["code"],"pct":c["pct"],
                 "reasons":c.get("reasons",[]),"sector":c.get("sector",""),
                 "score":c.get("score",0)} for c in cands[:n]]
    result = {"date": today,
        "d": pack(screen_dl(stocks)), "wj": pack(screen_wj(stocks)),
        "tl": pack(screen_tl(stocks)), "yl": pack(screen_yl(stocks)),
        "sai": pack(screen_sai(stocks)), "wolf": pack(screen_wolf(stocks)),
    }
    for path in [out, out_latest]:
        with open(path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Saved: {out} & {out_latest}")

if __name__ == "__main__":
    main()
