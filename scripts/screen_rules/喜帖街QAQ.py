def screen(stocks):
    """喜帖街 - 产业周期+供需缺口+基本面定价"""
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
        core_stocks = ['德明利', '佰维存储', '江波龙']
        watch_stocks = ['SK海力士', '三星电子', '兆易创新', '澜起科技', '北京君正']
        if name in core_stocks:
            score += 30
            reasons.append('核心标的')
        elif name in watch_stocks:
            score += 15
            reasons.append('关注标的')
        else:
            continue
        
        # 入场条件：低位分批建仓，借助恐慌买入
        # 模拟：股价处于低位（流通市值较小），换手率低，净流入为正
        if -5 <= pct <= 2 and turnover < 8 and net_flow > 0:
            score += 25
            reasons.append('低位企稳，资金流入')
        elif pct < -5 and turnover > 10:
            score += 20
            reasons.append('恐慌下跌，可能机会')
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