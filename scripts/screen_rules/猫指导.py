def screen(stocks):
    """猫指导 - 情绪周期+机构趋势"""
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
        core_stocks = ['长川科技', '润泽科技', '寒武纪', '美的集团']
        satellite_stocks = ['卫星化学', '信维通信', '利通电子', '中科曙光']
        watch_stocks = ['恒瑞医药', '药明康德', '沪硅产业', '中芯国际']
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
        
        # 入场条件：短线分歧回踩均线，机构票放量站上60日线，低吸模式
        # 模拟：pct在-3到3之间，换手率适中，净流入为正
        if -3 <= pct <= 3 and turnover < 10 and net_flow > 0:
            score += 25
            reasons.append('回踩企稳，资金流入')
        elif pct > 3 and turnover > 5 and net_flow > 0:
            score += 20
            reasons.append('放量突破')
        else:
            continue
        
        # 风控过滤：不追高，短线试错仓位小
        if pct > 8:
            continue
        if turnover > 30:
            continue
        
        if score >= 30:
            candidates.append({**s, 'score': score, 'reasons': reasons})
    return sorted(candidates, key=lambda x: -x['score'])[:20]