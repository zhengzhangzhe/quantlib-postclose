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
        core = ["德明利", "佰维存储", "江波龙"]
        watch = ["SK海力士", "三星电子", "兆易创新", "澜起科技", "北京君正"]
        if name in core:
            score += 25
            reasons.append("核心标的")
        elif name in watch:
            score += 8
            reasons.append("观察标的")
        
        # 行业扩展
        sectors_keywords = {
            "存储模组": ["德明利", "佰维存储", "江波龙", "朗科科技", "紫晶存储", "同有科技", "中科曙光", "易华录", "银信科技", "天玑科技", "荣联科技", "海量数据"],
            "HBM/先进封装": ["海力士", "三星", "长电科技", "通富微电", "华天科技", "晶方科技", "太极实业", "深科技", "大港股份", "文一科技", "至正股份", "沃格光电"],
            "风电": ["金风科技", "明阳智能", "运达股份", "电气风电", "海力风电", "大金重工", "天顺风能", "泰胜风能", "吉鑫科技", "金雷股份", "日月股份", "禾望电气"],
            "平台经济": ["美团", "拼多多", "阿里巴巴", "京东", "腾讯", "百度", "快手", "哔哩哔哩", "贝壳", "携程"],
            "EUV光刻机国产化": ["张江高科", "上海微电子", "华卓精科", "苏大维格", "福晶科技", "茂莱光学", "腾景科技", "晶方科技", "芯碁微装", "大族激光", "英诺激光", "德龙激光"]
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