def screen(stocks):
    """F佬 - 超短情绪+板块梯队+量化跟随"""
    candidates = []
    for s in stocks:
        score = 0
        reasons = []
        name = s.get('name', '')
        pct = s.get('pct', 0)
        turnover = s.get('turnover', 0)
        net_flow = s.get('net_flow', 0)
        
        # 标的匹配
        core_stocks = ['航天电子', '张江高科', '光模块龙头']
        satellite_stocks = ['利欧股份', '南兴股份', '创新医疗']
        watch_stocks = ['雷科防务', '海格通信', '金风科技', '天通股份', '万向钱潮', '五洲新春', '大业股份', '泰尔股份']
        if name in core_stocks:
            score += 30
            reasons.append('核心标的')
        elif name in satellite_stocks:
            score += 20
            reasons.append('卫星标的')
        elif name in watch_stocks:
            score += 10
            reasons.append('关注标的')
        else:
            continue
        
        # 入场条件：量化资金流入方向，板块分化日低吸核心，大盘放量反弹平铺
        # 模拟：放量上涨或缩量调整抗跌
        if pct > 3 and turnover > 5 and net_flow > 0:
            score += 25
            reasons.append('放量上涨，资金流入')
        elif -3 <= pct <= 0 and turnover < 8 and net_flow > -1e7:
            score += 20
            reasons.append('缩量调整，抗跌')
        else:
            continue
        
        # 风控过滤：不追高后排（十点后涨停不碰，这里用pct>9过滤）
        if pct > 9:
            continue
        if turnover > 30:
            continue
        
        if score >= 30:
            candidates.append({**s, 'score': score, 'reasons': reasons})
    return sorted(candidates, key=lambda x: -x['score'])[:20]