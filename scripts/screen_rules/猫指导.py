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
        core = ["长川科技", "润泽科技", "寒武纪", "美的集团"]
        satellite = ["卫星化学", "信维通信", "利通电子", "中科曙光"]
        watch = ["恒瑞医药", "药明康德", "沪硅产业", "中芯国际"]
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
            "半导体（存储/设备/材料）": ["长川科技", "寒武纪", "沪硅产业", "中芯国际", "北方华创", "中微公司", "拓荆科技", "兆易创新", "澜起科技", "北京君正", "佰维存储", "江波龙", "德明利", "长鑫存储", "紫光国微"],
            "数据中心/AIDC": ["润泽科技", "中科曙光", "浪潮信息", "紫光股份", "中兴通讯", "烽火通信", "星网锐捷", "锐捷网络", "菲菱科思", "共进股份", "奥飞数据", "光环新网", "宝信软件", "数据港"],
            "航天/商业航天": ["航天电子", "中国卫星", "航天发展", "航天电器", "航天科技", "航天晨光", "航天长峰", "航天动力", "航天机电", "航天彩虹", "航天宏图", "航天环宇"],
            "创新药": ["恒瑞医药", "药明康德", "百济神州", "信达生物", "君实生物", "康龙化成", "泰格医药", "凯莱英", "昭衍新药", "药石科技", "美迪西", "博腾股份"],
            "化工": ["卫星化学", "万华化学", "华鲁恒升", "扬农化工", "龙佰集团", "中泰化学", "兴发集团", "合盛硅业", "新安股份", "鲁西化工", "巨化股份", "三美股份"],
            "消费（家电/白酒）": ["美的集团", "格力电器", "海尔智家", "贵州茅台", "五粮液", "泸州老窖", "山西汾酒", "洋河股份", "古井贡酒", "今世缘", "青岛啤酒", "伊利股份"],
            "贵金属": ["紫金矿业", "山东黄金", "中金黄金", "赤峰黄金", "湖南黄金", "银泰黄金", "恒邦股份", "西部黄金", "中润资源", "盛达资源"]
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