def screen(stocks):
    """狼大 - 科技主线+机构行为+大盘择时"""
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
        core_stocks = ['鼎龙股份', '江丰电子', '中船特气']
        watch_stocks = ['沪硅产业', '沪电股份', '中际旭创', '新易盛', '长飞光纤', '神工股份', '风华高科']
        if name in core_stocks:
            score += 30
            reasons.append('核心标的')
        elif name in watch_stocks:
            score += 15
            reasons.append('关注标的')
        else:
            continue
        
        # 入场条件：带量突破后缩量回踩不破，关键支撑位企稳
        # 模拟：pct在-3到3之间，换手率适中，净流入为正
        if -3 <= pct <= 3 and turnover < 10 and net_flow > 0:
            score += 20
            reasons.append('缩量企稳，资金流入')
        elif pct > 3 and turnover > 5 and net_flow > 0:
            score += 15
            reasons.append('带量突破')
        else:
            continue
        
        # 风控过滤：不追高，散户扎堆回避
        if pct > 8:
            continue
        if turnover > 30:
            continue
        
        # 市值偏好：流通市值适中
        if float_mkt < 1e9 or float_mkt > 1e12:
            continue
        
        if score >= 30:
            candidates.append({**s, 'score': score, 'reasons': reasons})
    return sorted(candidates, key=lambda x: -x['score'])[:20]