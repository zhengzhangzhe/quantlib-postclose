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
        core = ["中钨高新", "德明利", "胜宏科技"]
        satellite = ["兆龙互连", "利通电子", "欢瑞世纪"]
        watch = ["掌阅科技", "芒果超媒", "沃尔核材", "神宇股份", "瑞可达"]
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
            "钨矿/有色金属": ["中钨高新", "翔鹭钨业", "章源钨业", "厦门钨业", "洛阳钼业", "华友钴业", "寒锐钴业", "金钼股份", "西部矿业", "铜陵有色", "江西铜业", "云南铜业"],
            "存储芯片": ["德明利", "佰维存储", "江波龙", "兆易创新", "澜起科技", "北京君正", "长鑫存储", "紫光国微", "复旦微电", "国科微", "东芯股份", "普冉股份"],
            "PCB": ["胜宏科技", "沪电股份", "深南电路", "鹏鼎控股", "东山精密", "景旺电子", "方正科技", "生益科技", "华正新材", "超声电子", "兴森科技", "中京电子"],
            "铜缆高速连接": ["兆龙互连", "沃尔核材", "神宇股份", "瑞可达", "金信诺", "中航光电", "航天电器", "永贵电器", "鼎通科技", "意华股份"],
            "seedance/AI应用": ["欢瑞世纪", "掌阅科技", "芒果超媒", "中文在线", "昆仑万维", "蓝色光标", "利欧股份", "南兴股份", "因赛集团", "元隆雅图"],
            "算力租赁": ["利通电子", "中科曙光", "浪潮信息", "紫光股份", "中兴通讯", "烽火通信", "星网锐捷", "锐捷网络", "菲菱科思", "共进股份"]
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