def screen(stocks):
    """文驹 - 低位挖掘+产业催化多线布局"""
    candidates = []
    for s in stocks:
        score = 0
        reasons = []
        name = s.get('name', '')
        pct = s.get('pct', 0)
        turnover = s.get('turnover', 0)
        net_flow = s.get('net_flow', 0)
        float_mkt = s.get('float_mkt', 0)
        
        # 标的匹配
        core_stocks = ['中钨高新', '德明利', '胜宏科技']
        satellite_stocks = ['兆龙互连', '利通电子', '欢瑞世纪']
        watch_stocks = ['掌阅科技', '芒果超媒', '沃尔核材', '神宇股份', '瑞可达']
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
        
        # 入场条件：低位介入，回调至严重低估时，市场分歧时勇敢介入
        # 模拟：pct在-5到2之间，换手率低，净流入为正或小幅流出
        if -5 <= pct <= 2 and turnover < 10 and net_flow > -5e6:
            score += 25
            reasons.append('低位企稳')
        elif pct > 3 and turnover > 5 and net_flow > 0:
            score += 15
            reasons.append('市场分歧时上涨')
        else:
            continue
        
        # 风控过滤：不追高
        if pct > 8:
            continue
        if turnover > 30:
            continue
        
        if score >= 30:
            candidates.append({**s, 'score': score, 'reasons': reasons})
    return sorted(candidates, key=lambda x: -x['score'])[:20]