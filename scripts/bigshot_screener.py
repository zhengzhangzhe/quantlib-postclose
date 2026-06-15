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
        sc += _sai_bonus(s["name"])
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

# ── 猫指导: 存储芯片/半导体设备, 低吸+趋势 (标的池由LLM从591帖中提取) ──
MAO_KW = {
    "存储芯片": ["兆易创新","江波龙","德明利","佰维存储","澜起科技","普冉股份","聚辰股份"],
    "半导体设备": ["长川科技","北方华创","拓荆科技","盛美上海","至纯科技","中微公司"],
    "半导体材料": ["沪硅产业","立昂微","上海新阳","晶瑞电材","TCL中环"],
    "封装测试": ["中芯国际","长电科技","通富微电","华虹公司"],
    "AI算力": ["海光信息","寒武纪","中科曙光"],
    "光通信": ["长飞光纤","亨通光电","光迅科技","中际旭创","天孚通信","新易盛","中兴通讯","烽火通信","华工科技"],
    "PCB": ["生益科技","生益电子","沪电股份","胜宏科技","鹏鼎控股","深南电路","方正科技"],
    "航天军工": ["中国卫星","信维通信","铖昌科技","航发动力","中航沈飞","航天彩虹","华力创通","中国卫通","上海瀚讯"],
}
def screen_mao(stocks):
    cand = []
    for s in stocks:
        sec = match_sector(s["name"], MAO_KW)
        if not sec: continue
        sc = 0; rs = [sec]
        # 猫指导: 低吸为主, 偏好温和上涨/回踩
        if -3 <= s["pct"] <= 0: sc += 4; rs.append("低吸窗口")
        elif 0 < s["pct"] <= 3: sc += 3; rs.append("企稳筑底")
        elif 3 < s["pct"] <= 6: sc += 2; rs.append("温和启动")
        elif s["pct"] > 6: sc += 1  # 强势但不追
        else: continue
        if 1 <= s["turnover"] <= 8: sc += 2; rs.append("缩量控盘")
        elif 8 < s["turnover"] <= 15: sc += 1
        if s["net_flow"] > 1e7: sc += 1; rs.append("资金流入")
        if s["float_mkt"] > 50e8: sc += 2; rs.append("容量标的")
        if sc >= 5: cand.append({**s,"score":sc,"reasons":rs,"sector":sec})
    return sorted(cand, key=lambda x: -x["score"])

# ── sai佬主题加成（AI算力/光模块/半导体国产化） ──
SAI_THEME = ["光模块","光通信","中际旭创","天孚通信","新易盛","太辰光","剑桥科技",
             "中芯国际","寒武纪","海光信息","北方华创","中微公司","长电科技",
             "通富微电","华天科技","沪硅产业","立昂微","士兰微","澜起科技",
             "兆易创新","卓胜微","韦尔股份","圣邦股份","长川科技","精测电子",
             "浪潮信息","中科曙光","工业富联","中兴通讯","烽火通信"]
def _sai_bonus(name):
    return 2 if name in SAI_THEME else 0

# ── Main ──
def main():
    print(f"全量海选 · {datetime.now().strftime('%H:%M')}")
    stocks = fetch_stocks()
    print(f"数据: {len(stocks)} 只\n")

    for name, fn in [("文驹(钨/有色)",screen_wj),
        ("兔佬(有色/半导)",screen_tl),
        ("sai佬(半导材料)",screen_sai),("狼大(科技)",screen_wolf),
        ("猫指导(存储/设备)",screen_mao)]:
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
        "wj": pack(screen_wj(stocks)),
        "tl": pack(screen_tl(stocks)),
        "sai": pack(screen_sai(stocks)), "wolf": pack(screen_wolf(stocks)),
        "mao": pack(screen_mao(stocks)),
    }
    for path in [out, out_latest]:
        with open(path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Saved: {out} & {out_latest}")

if __name__ == "__main__":
    main()
