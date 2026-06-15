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
        core = ["中钨高新"]
        satellite = ["半导体设备ETF", "封测ETF"]
        watch = ["沪电股份", "风华高科", "电池ETF"]
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
            "钨矿/PCB钻针": ["中钨高新", "翔鹭钨业", "章源钨业", "厦门钨业", "金洲精工", "鼎泰高科", "沃尔德", "华锐精密", "欧科亿", "恒锋工具"],
            "半导体设备/封测": ["北方华创", "中微公司", "拓荆科技", "长川科技", "华峰测控", "盛美上海", "芯源微", "万业企业", "至纯科技", "精测电子", "长电科技", "通富微电", "华天科技", "晶方科技", "太极实业"],
            "电池/新能源": ["宁德时代", "比亚迪", "亿纬锂能", "国轩高科", "欣旺达", "鹏辉能源", "孚能科技", "派能科技", "德方纳米", "当升科技", "容百科技", "华友钴业"],
            "PCB": ["沪电股份", "深南电路", "鹏鼎控股", "东山精密", "景旺电子", "胜宏科技", "方正科技", "生益科技", "华正新材", "超声电子", "兴森科技", "中京电子"]
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
        
        # 风控过滤
        
        if score >= 20:
            candidates.append({**s, "score": score, "reasons": reasons})
    return sorted(candidates, key=lambda x: -x["score"])[:20]