def screen(stocks):
    """兔佬 - 技术划线+多情景预案+仓位管控"""
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
        core_stocks = ['中钨高新']
        satellite_stocks = ['半导体设备ETF', '封测ETF']
        watch_stocks = ['沪电股份', '风华高科', '电池ETF']
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
        
        # 入场条件：C浪走完后外围企稳+大盘冰点，关键支撑位缩量企稳
        # 模拟：pct在-3到3之间，换手率低，净流入为正
        if -3 <= pct <= 3 and turnover < 8 and net_flow > 0:
            score += 25
            reasons.append('缩量企稳，资金流入')
        elif -5 <= pct <= -2 and turnover < 10:
            score += 20
            reasons.append('回调至支撑位')
        else:
            continue
        
        # 风控过滤：不追高，利润垫不足不追
        if pct > 5:
            continue
        if turnover > 30:
            continue
        
        if score >= 30:
            candidates.append({**s, 'score': score, 'reasons': reasons})
    return sorted(candidates, key=lambda x: -x['score'])[:20]