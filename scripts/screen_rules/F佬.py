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
        core = ["航天电子", "张江高科", "光模块龙头"]
        satellite = ["利欧股份", "南兴股份", "创新医疗"]
        watch = ["雷科防务", "海格通信", "金风科技", "天通股份", "万向钱潮", "五洲新春", "大业股份", "泰尔股份"]
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
            "商业航天": ["航天电子", "雷科防务", "海格通信", "中国卫星", "航天发展", "航天电器", "航天科技", "航天晨光", "航天长峰", "航天动力", "航天机电", "航天彩虹", "航天宏图", "航天环宇", "航天软件"],
            "可控核聚变": ["中核科技", "中国核建", "中国核电", "核能科技", "安泰科技", "西部超导", "联创光电", "国光电气", "永鼎股份", "百利电气", "保变电气", "久立特材", "宝胜股份", "沃尔核材"],
            "光模块/CPO": ["中际旭创", "新易盛", "天孚通信", "光迅科技", "华工科技", "博创科技", "太辰光", "德科立", "联特科技", "剑桥科技", "铭普光磁", "光库科技"],
            "存储/半导体": ["兆易创新", "澜起科技", "北京君正", "佰维存储", "江波龙", "德明利", "长鑫存储", "紫光国微", "复旦微电", "国科微", "东芯股份", "普冉股份", "恒烁股份", "聚辰股份"],
            "AI智能体": ["利欧股份", "南兴股份", "昆仑万维", "科大讯飞", "三六零", "汉王科技", "拓尔思", "中科信息", "云从科技", "格灵深瞳", "虹软科技", "当虹科技"],
            "脑机接口": ["创新医疗", "熊猫乳品", "岩山科技", "三博脑科", "冠昊生物", "复旦复华", "汉威科技", "伟思医疗", "翔宇医疗", "爱朋医疗"],
            "机器人": ["万向钱潮", "五洲新春", "大业股份", "泰尔股份", "埃斯顿", "汇川技术", "绿的谐波", "双环传动", "中大力德", "拓斯达", "新时达", "机器人", "华中数控", "秦川机床"]
        }
        for sector, keywords in sectors_keywords.items():
            for kw in keywords:
                if kw in name:
                    score += 8
                    reasons.append(f"{sector}板块")
                    break
        
        # 入场条件：突破风格
        if pct > 2 and turnover > 4:
            score += 10
            reasons.append("突破条件满足")
        
        # 风控过滤
        
        if score >= 20:
            candidates.append({**s, "score": score, "reasons": reasons})
    return sorted(candidates, key=lambda x: -x["score"])[:20]