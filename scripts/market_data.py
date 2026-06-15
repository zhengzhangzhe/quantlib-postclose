#!/usr/bin/env python3
"""Shared market data fetcher — used by screener and daily_picks to avoid duplicate API calls."""

import requests
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent


def fetch_fund_flow():
    """Fetch individual stock fund flow + market cap. Returns (stocks, mkt_dict)."""
    import akshare as ak
    df = ak.stock_fund_flow_individual(symbol="即时")

    # Market cap from Eastern Money (paginated)
    mkt = {}
    try:
        url = 'http://82.push2.eastmoney.com/api/qt/clist/get'
        for page in range(1, 57):
            params = {'pn':page,'pz':100,'po':1,'np':1,'fltt':2,'invt':2,'fid':'f20',
                      'fs':'m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23','fields':'f12,f21'}
            r = requests.get(url, params=params, headers={'User-Agent':'Mozilla/5.0'}, timeout=15)
            data = r.json()
            if not data.get('data') or not data['data'].get('diff'): break
            for item in data['data']['diff']:
                mkt[item['f12']] = float(item.get('f21',0) or 0)
            if len(data['data']['diff']) < 100: break
        print(f"市值数据: {len(mkt)} 只")
    except Exception as e:
        print(f"市值获取失败: {e}")

    stocks = []
    for _, r in df.iterrows():
        code = str(r["股票代码"]).zfill(6)
        name = r["股票简称"]
        pct = float(str(r["涨跌幅"]).replace("%","")) if r["涨跌幅"] else 0
        turnover = float(str(r["换手率"]).replace("%","")) if r["换手率"] else 0
        nf = str(r["净额"])
        if "亿" in nf: net_flow = float(nf.replace("亿","")) * 1e8
        elif "万" in nf: net_flow = float(nf.replace("万","")) * 1e4
        else: net_flow = float(nf) if nf else 0
        close = float(str(r["最新价"])) if r["最新价"] and str(r["最新价"]) != "nan" else 0
        stocks.append({"code":code,"name":name,"pct":pct,"turnover":turnover,
                       "net_flow":net_flow,"float_mkt":mkt.get(code,1e15),"close":close})
    return stocks, mkt
