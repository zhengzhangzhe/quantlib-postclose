def screen(stocks):
    candidates = []
    for s in stocks:
        score = 0
        reasons = []
        name = s["name"]
        pct = s["pct"]
        turnover = s["turnover"]
        net_flow = s["net_flow"]
        float_mkt = s["float_mkt"]
        
        # 标的匹配
        core = ["中际旭创", "新易盛", "沪电股份"]
        satellite = ["沪硅产业", "长飞光纤", "拓荆科技"]
        watch = ["北方华创", "中微公司", "长电科技", "通富微电", "兆易创新", "澜起科技", "寒武纪"]
        if name in core:
            score += 25
            reasons.append("核心标的")
        elif name in satellite:
            score += 15
            reasons.append("卫星标的")
        elif name in watch:
            score += 8
            reasons.append("观察标的")
        
        # 行业扩展
        sectors_keywords = {
            "光模块/CPO": ["中际旭创", "新易盛", "天孚通信", "光迅科技", "华工科技", "博创科技", "太辰光", "德科立", "联特科技", "剑桥科技", "铭普光磁", "光库科技"],
            "PCB/高速板材": ["沪电股份", "深南电路", "鹏鼎控股", "东山精密", "景旺电子", "胜宏科技", "方正科技", "生益科技", "华正新材", "超声电子", "兴森科技", "中京电子"],
            "半导体设备/材料": ["北方华创", "中微公司", "拓荆科技", "沪硅产业", "长川科技", "华峰测控", "盛美上海", "芯源微", "万业企业", "至纯科技", "精测电子", "华兴源创"],
            "存储芯片": ["兆易创新", "澜起科技", "北京君正", "佰维存储", "江波龙", "德明利", "长鑫存储", "紫光国微", "复旦微电", "国科微", "东芯股份", "普冉股份"],
            "算力硬件": ["寒武纪", "中科曙光", "浪潮信息", "紫光股份", "中兴通讯", "烽火通信", "星网锐捷", "锐捷网络", "菲菱科思", "共进股份"]
        }
        for sector, keywords in sectors_keywords.items():
            for kw in keywords:
                if kw in name:
                    score += 8
                    reasons.append(f"{sector}板块")
                    break
        
        # 入场条件：趋势跟随
        if -1 <= pct <= 5 and 3 <= turnover <= 15:
            score += 10
            reasons.append("趋势跟随条件满足")
        
        # 风控过滤
        
        if score >= 20:
            candidates.append({**s, "score": score, "reasons": reasons})
    return sorted(candidates, key=lambda x: -x["score"])[:20]