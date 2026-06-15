def screen(stocks):
    """sai佬 - 产业趋势+价值波段"""
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
        core_stocks = ['中际旭创', '新易盛', '沪电股份']
        satellite_stocks = ['沪硅产业', '长飞光纤', '拓荆科技']
        watch_stocks = ['北方华创', '中微公司', '长电科技', '通富微电', '兆易创新', '澜起科技', '寒武纪']
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
        
        # 入场条件：主线龙头回调至20日线附近缩量企稳，低位有催化
        # 模拟：pct在-3到3之间，换手率低，净流入为正
        if -3 <= pct <= 3 and turnover < 8 and net_flow > 0:
            score += 25
            reasons.append('缩量企稳，资金流入')
        elif -5 <= pct <= -2 and turnover < 10:
            score += 20
            reasons.append('回调至支撑位')
        else:
            continue
        
        # 风控过滤：不追高
        if pct > 5:
            continue
        if turnover > 30:
            continue
        
        if score >= 30:
            candidates.append({**s, 'score': score, 'reasons': reasons})
    return sorted(candidates, key=lambda x: -x['score'])[:20]