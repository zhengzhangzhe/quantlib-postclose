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
        core = ["鼎龙股份", "江丰电子", "中船特气"]
        watch = ["沪硅产业", "沪电股份", "中际旭创", "新易盛", "长飞光纤", "神工股份", "风华高科"]
        if name in core:
            score += 25
            reasons.append("核心标的")
        elif name in watch:
            score += 15
            reasons.append("关注标的")
        
        # 行业扩展
        sectors_keywords = {
            "半导体材料": ["鼎龙", "江丰", "中船特气", "沪硅", "神工", "华特气体", "雅克科技", "晶瑞电材", "南大光电", "彤程新材", "上海新阳", "安集科技", "金宏气体", "昊华科技", "巨化股份"],
            "光模块/CPO": ["中际旭创", "新易盛", "天孚通信", "光迅科技", "华工科技", "博创科技", "太辰光", "德科立", "联特科技", "剑桥科技", "铭普光磁", "光库科技"],
            "PCB": ["沪电股份", "深南电路", "鹏鼎控股", "东山精密", "景旺电子", "胜宏科技", "方正科技", "生益科技", "华正新材", "超声电子", "兴森科技", "中京电子"],
            "光纤光缆": ["长飞光纤", "亨通光电", "中天科技", "烽火通信", "通鼎互联", "永鼎股份", "富通信息", "特发信息"]
        }
        for sector, keywords in sectors_keywords.items():
            for kw in keywords:
                if kw in name:
                    score += 8
                    reasons.append(f"{sector}板块")
                    break
        
        # 入场条件：低吸风格
        if -3 <= pct <= 3 and turnover < 8:
            score += 10
            reasons.append("低吸条件满足")
        
        # 风控过滤：无特殊
        
        if score >= 20:
            candidates.append({**s, "score": score, "reasons": reasons})
    return sorted(candidates, key=lambda x: -x["score"])[:20]