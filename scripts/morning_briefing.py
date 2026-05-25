#!/usr/bin/env python3
"""Pre-market morning briefing — scrapes overnight news + Xueqiu, combines with yesterday's review.

Usage:
    python3 scripts/morning_briefing.py                        # Today
    python3 scripts/morning_briefing.py --date 2026-05-22      # Specific date
    python3 scripts/morning_briefing.py --dry-run              # Skip LLM

Output: output/morning/YYYY-MM-DD/briefing.md
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# Import stable sector leaders mapping
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from scripts.sector_leaders import SECTOR_LEADERS
except ImportError:
    SECTOR_LEADERS = {}

import requests

# ── Paths ──
PROJ = Path(__file__).resolve().parent.parent
OUTPUT = PROJ / "output" / "morning"
DATA_SNAPSHOTS = PROJ / "data" / "postclose"  # reuse postclose snapshot
DATA_INSTITUTE = PROJ / "data" / "institute_attention"

# ── LLM ──
LLM_URL = "https://api.deepseek.com/v1/chat/completions"
LLM_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """你是A股盘前策略分析师。根据隔夜新闻、雪球快讯、股吧散户讨论、前日复盘数据，给出今日操作建议。

## 输出JSON格式
{
  "overnight_summary": "隔夜重大事件总结（150字内）",
  "macro_events": [{"event": "事件名", "impact": "正面/负面/中性", "affected_sectors": ["板块1"], "note": "一句话"}],
  "xueqiu_sentiment": "雪球快讯+股吧散户情绪综合判断（100字内）",
  "sector_recommendations": [
    {"sector": "板块名", "theme_source": "前日主线/次主线/活口/隔夜新催化/隔夜利空", "action": "买入/关注/回避", "confidence": "高/中/低", "reason": "基于具体新闻/数据的理由(50字)", "key_stocks": [{"name":"简称","code":"000001","note":"入选理由或风险提示"}]}
  ],
  "risk_alerts": ["风险提示"],
  "market_stance": "整体仓位建议（50字内）",
  "key_watch": ["重点观察方向"]
}

## 板块分析铁律
1. **必须覆盖前日复盘的所有主线+次主线+活口**，一个都不能漏
2. **必须覆盖隔夜新闻中的利空板块**（如减持、监管、制裁等），标记为🔴回避
3. 从同花顺/新浪/雪球快讯中提取新热点板块，追加为「隔夜新催化」
4. 每个板块基于实际新闻/股吧帖子/资金数据给出判断，不要凭空推测
5. **前日炸板率>50%的主线必须标注追高风险**，说明今日能否修复
6. 最终输出的sector_recommendations至少要有7-10个板块（含买入+关注+回避）

## 🚨 龙头股选股规则（最重要！违反将导致用户无法交易）
- 每个板块必须推荐6-8只龙头，key_stocks数组长度必须≥6
- **只能选沪深主板**，code必须以 60 或 00 开头
- **死都不能选**：30xxxx（创业板）、688xxx（科创板）、4xxxxx/8xxxxx（北交所）
- 检查方法：code第一个数字必须是6或0，第二个数字必须是0
- 优先从前日涨停股池中选，其次从同花顺/雪球快讯中提到的标的
- ⚠️ 严格验证股票与板块的关联性：橡胶股≠机器人，纺织股≠AI，不能硬塞
- 每只股票加note字段，标注入选理由（如"前日涨停""板块龙头""估值低位""隔夜催化"）或风险（如"炸板率高""减持""追高风险"）
- 如果该板块主板标的确实不足6只，有多少列多少并在reason中说明

## 操作分级标准
- 🟢买入：实质政策落地+资金净流入+前日封板早+有连板或容量确认
- 🟡关注：有催化消息但资金配合不足，或前日炸板率高需观察
- 🔴回避：股东减持/监管处罚/板块资金大幅流出/前日炸板未回封

只输出JSON，不用markdown代码块。"""


def _prev_trading_day(date_str: str) -> str:
    d = date.fromisoformat(date_str) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def _to_akshare_date(date_str: str) -> str:
    return date_str.replace("-", "")


# ═══════════════════════════════════════════════════════════
# DATA COLLECTION
# ═══════════════════════════════════════════════════════════

def fetch_cctv_news(trade_date: str) -> list[dict]:
    """Fetch CCTV macro/policy news for context on major government actions."""
    import akshare as ak
    try:
        df = ak.news_cctv(date=_to_akshare_date(trade_date))
        if df.empty:
            return []
        results = []
        for _, r in df.iterrows():
            results.append({
                "title": str(r.get("title", "")),
                "content": str(r.get("content", ""))[:300],
            })
        return results
    except Exception:
        return []


def fetch_10jqka_news() -> list[str]:
    """Fetch 10jqka (同花顺) financial breaking news — market-specific headlines."""
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    all_titles = []
    seen = set()

    # Source 1: main stock page
    try:
        r = requests.get("https://stock.10jqka.com.cn/", headers=headers, timeout=10)
        titles = __import__('re').findall(r'<a[^>]*title="([^"]+)"[^>]*>', r.text)
        for t in titles:
            t = t.strip()
            if len(t) > 8 and t not in seen:
                all_titles.append(t)
                seen.add(t)
    except Exception:
        pass

    # Source 2: yuanchuang (original content, more timely)
    try:
        r2 = requests.get("https://yuanchuang.10jqka.com.cn/", headers=headers, timeout=10)
        titles2 = __import__('re').findall(r'<a[^>]*title="([^"]+)"[^>]*>', r2.text)
        for t in titles2:
            t = t.strip()
            if len(t) > 8 and t not in seen:
                all_titles.append(t)
                seen.add(t)
    except Exception:
        pass

    return all_titles


def fetch_sina_headlines(pages: int = 2) -> list[str]:
    """Fetch Sina Finance headlines."""
    import requests as req
    url = "https://feed.mix.sina.com.cn/api/roll/get"
    params_tpl = {"pageid": "153", "lid": "2509", "k": "", "num": "50"}
    headers = {"User-Agent": "Mozilla/5.0"}
    titles = []
    seen = set()
    for page in range(1, pages + 1):
        try:
            p = {**params_tpl, "page": str(page)}
            r = req.get(url, params=p, headers=headers, timeout=10)
            articles = r.json().get("result", {}).get("data", [])
            for a in articles:
                title = str(a.get("title", ""))
                if title and title not in seen:
                    titles.append(title)
                    seen.add(title)
        except Exception:
            break
    return titles


def fetch_xueqiu_flash(count: int = 50) -> list[dict]:
    """Fetch Xueqiu 7x24 flash news via /statuses/livenews/list.json."""
    try:
        session = requests.Session()
        session.get("https://xueqiu.com/",
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=10)

        results = []
        max_id = ""
        while len(results) < count:
            url = "https://xueqiu.com/statuses/livenews/list.json"
            params = {"count": min(50, count - len(results)), "max_id": max_id}
            r = session.get(url, params=params,
                          headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if r.status_code != 200:
                break
            data = r.json()
            items = data.get("items", [])
            if not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                text = item.get("text", "")
                if text:
                    results.append({
                        "text": str(text)[:300],
                        "view_count": item.get("view_count", item.get("likes", 0)),
                        "created_at": item.get("created_at", 0),
                    })
            max_id = data.get("next_max_id", "")
            if not max_id:
                break
            time.sleep(0.3)
        return results
    except Exception as e:
        print(f"    [warn] Xueqiu fetch error: {e}")
        return []


def fetch_guba_sentiment(postclose: dict | None, max_stocks: int = 10) -> list[dict]:
    """Fetch EastMoney Guba posts for yesterday's hot stocks.

    Scrapes the HTML discussion pages (no API key needed).
    Returns list of {stock_name, stock_code, title, sentiment preview}.
    """
    if not postclose:
        return []

    # Collect top stocks from yesterday's themes
    hot_stocks = []
    seen = set()
    for t in postclose.get("themes", []):
        for s in t.get("member_stocks", [])[:4]:
            if s not in seen:
                hot_stocks.append(s)
                seen.add(s)

    if not hot_stocks:
        return []

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://guba.eastmoney.com/",
    }

    results = []
    for stock_name in hot_stocks[:max_stocks]:
        # Find code from snapshot
        stock_code = None
        for lu in postclose.get("limit_up_stocks", []):
            if lu.get("name") == stock_name:
                stock_code = lu.get("code", "").split(".")[0]
                break
        if not stock_code:
            continue

        try:
            url = f"https://guba.eastmoney.com/list,{stock_code}.html"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            titles = re.findall(r'<a[^>]*class="note"[^>]*title="([^"]*)"[^>]*>', r.text)
            if not titles:
                titles = re.findall(r'"post_title":"([^"]+)"', r.text)

            for title in titles[:5]:
                results.append({
                    "stock": stock_name,
                    "code": stock_code,
                    "title": title.strip(),
                })
            time.sleep(0.2)
        except Exception:
            continue

    return results


def load_postclose_snapshot(trade_date: str) -> dict | None:
    """Load most recent postclose review snapshot before trade_date.

    Monday morning → uses Friday's snapshot.
    """
    td = date.fromisoformat(trade_date)
    # Look back up to 5 days for the most recent postclose snapshot
    for offset in range(1, 6):
        d = td - timedelta(days=offset)
        if d.weekday() >= 5:  # skip weekends for the snapshot lookup chain
            continue
        path = DATA_SNAPSHOTS / d.isoformat() / "snapshot.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
    return None


def load_institute_attention(trade_date: str) -> dict | None:
    """Load most recent institute attention weekly report before trade_date."""
    td = date.fromisoformat(trade_date)
    for offset in range(0, 8):
        d = td - timedelta(days=offset)
        path = DATA_INSTITUTE / f"{d.isoformat()}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
    return None


def _days_since_last_trading(trade_date: str) -> int:
    """How many calendar days since the last trading day closed.

    Monday → 3 (Fri close to Mon morning), Tue-Fri → 1.
    Used to determine how much news history to fetch.
    """
    td = date.fromisoformat(trade_date)
    prev = td - timedelta(days=1)
    days = 1
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
        days += 1
    return days


# ═══════════════════════════════════════════════════════════
# LLM CONTEXT & CALL
# ═══════════════════════════════════════════════════════════

def build_llm_context(
    trade_date: str,
    cctv_news: list[dict],
    tenjqka_news: list[str],
    sina_headlines: list[str],
    xueqiu_flash: list[dict],
    guba_posts: list[dict],
    postclose: dict | None,
    inst_attn: dict | None = None,
) -> str:
    lines = []
    lines.append(f"## 日期：{trade_date} 盘前")
    lines.append(f"目标：基于隔夜信息给出今日板块操作建议")
    lines.append("")

    # 10jqka financial news
    if tenjqka_news:
        lines.append(f"## 同花顺财经快讯（{len(tenjqka_news)}条，市场导向）")
        for h in tenjqka_news[:40]:
            lines.append(f"- {h}")
        lines.append("")

    # Sina headlines
    if sina_headlines:
        lines.append(f"## 新浪财经快讯（{len(sina_headlines)}条）")
        for h in sina_headlines[:30]:
            lines.append(f"- {h}")
        lines.append("")

    # Xueqiu flash
    if xueqiu_flash:
        lines.append(f"## 雪球7×24快讯（{len(xueqiu_flash)}条）")
        for f_item in xueqiu_flash[:40]:
            lines.append(f"- {f_item['text']}")
        lines.append("")

    # Guba sentiment
    if guba_posts:
        lines.append(f"## 东方财富股吧热议（{len(guba_posts)}条，来自昨日热门股）")
        # Group by stock
        by_stock = {}
        for gp in guba_posts:
            by_stock.setdefault(gp["stock"], []).append(gp["title"])
        for stock, titles in by_stock.items():
            lines.append(f"- **{stock}**：")
            for t in titles[:3]:
                lines.append(f"  - {t}")
        lines.append("")

    # CCTV macro (secondary, policy-filtered, max 3)
    if cctv_news:
        key_policies = ["习近平", "国务院", "发改委", "央行", "证监会", "财政部", "政治局", "降准", "降息", "利率", "LPR"]
        policy_items = [n for n in cctv_news if any(kw in n.get("title", "") for kw in key_policies)]
        if policy_items:
            lines.append(f"## 宏观政策参考（次要，{len(policy_items)}条）")
            for n in policy_items[:3]:
                lines.append(f"- {n['title']}")
            lines.append("")

    # Previous day postclose — explicitly tell LLM to cover ALL these themes
    if postclose:
        lines.append("## 前日收盘复盘概况")
        lines.append(f"日期：{postclose.get('date', '?')}")
        lines.append(f"涨停封板：{postclose.get('limit_up_count', '?')}只")
        lines.append(f"炸板：{postclose.get('failed_count', '?')}只")
        lines.append(f"跌停：{postclose.get('limit_down_count', '?')}只")
        if postclose.get("index_sh") is not None:
            lines.append(f"上证指数：{postclose['index_sh']:+.2f}%")
        if postclose.get("index_sz") is not None:
            lines.append(f"深证成指：{postclose['index_sz']:+.2f}%")
        themes = postclose.get("themes", [])
        if themes:
            lines.append("")
            lines.append("⚠️ 你必须对以下**每一个**前日主题给出操作建议（覆盖主线+次主线+活口，一个不能少）：")
            for t in themes:
                stocks = "、".join(t.get("member_stocks", [])[:6])
                lines.append(f"  - {t['name']}（{t.get('type','')}）：{stocks}")
            lines.append("如果隔夜新闻/快讯中有新的热门板块，追加为「隔夜新催化」。")

    # Institute attention — recent research report heat
    if inst_attn:
        lines.append("")
        lines.append("## 机构研报热度（最近一期周报）")
        top_ind = list(inst_attn.get("by_industry", {}).items())[:8]
        lines.append(f"日期：{inst_attn.get('date','?')}，共{inst_attn.get('total','?')}份研报")
        lines.append("机构最密集覆盖的行业：")
        for ind, cnt in top_ind:
            lines.append(f"  - {ind}：{cnt}份研报")
        lines.append("参考以上机构热度，对机构密集覆盖的行业可适当提高操作评级。")
        lines.append("")

    return "\n".join(lines)


def call_llm(context: str, api_key: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        "temperature": 0.2,
        "max_tokens": 8000,
        "response_format": {"type": "json_object"},
    }
    r = requests.post(LLM_URL, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


# ═══════════════════════════════════════════════════════════
# REPORT GENERATION
# ═══════════════════════════════════════════════════════════

def render_briefing(
    trade_date: str,
    cctv_news: list[dict],
    tenjqka_news: list[str],
    sina_headlines: list[str],
    xueqiu_flash: list[dict],
    guba_posts: list[dict],
    postclose: dict | None,
    llm_result: dict,
) -> str:
    L = []
    a = lambda s="": L.append(s)

    a(f"# 盘前简报 · {trade_date}")
    a()
    a(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    a()

    # ── LLM Analysis ──
    a("## 1. 隔夜事件总结")
    a()
    a(llm_result.get("overnight_summary", "（待生成）"))
    a()

    # Macro events
    macro = llm_result.get("macro_events", [])
    if macro:
        a("### 1.1 重大宏观事件")
        a()
        a("| 事件 | 影响 | 受影响的板块 | 备注 |")
        a("|------|------|-------------|------|")
        for m in macro:
            sects = "、".join(m.get("affected_sectors", []))
            a(f"| {m.get('event','')} | {m.get('impact','')} | {sects} | {m.get('note','')} |")
        a()

    a("## 2. 前日复盘回顾")
    a()
    if postclose:
        idx_sh = postclose.get('index_sh')
        idx_str = f"{idx_sh:+.2f}%" if isinstance(idx_sh, (int, float)) and idx_sh is not None else str(idx_sh)
        a(f"- 前日上证：{idx_str}")
        a(f"- 前日涨停：{postclose.get('limit_up_count', '?')}只封板 / 炸板{postclose.get('failed_count', '?')}只 / 跌停{postclose.get('limit_down_count', '?')}只")
        themes = postclose.get("themes", [])
        if themes:
            a("- 前日主线：")
            for t in themes:
                stocks = "、".join(t.get("member_stocks", [])[:4])
                a(f"  - {t['name']}（{t.get('type','')}）：{stocks}")
        a()
    else:
        a("（无前日复盘数据）")
        a()

    a("## 3. 雪球情绪")
    a()
    a(llm_result.get("xueqiu_sentiment", "（待生成）"))
    a()
    a("### 3.0 股吧散户情绪")
    a()
    a(llm_result.get("guba_sentiment", "（待生成）"))
    a()

    # Key flash news
    if xueqiu_flash:
        a("### 3.1 雪球7×24快讯（精选）")
        a()
        sorted_flash = sorted(xueqiu_flash, key=lambda x: x.get("view_count", 0), reverse=True)
        for f_item in sorted_flash[:15]:
            vc = f_item.get("view_count", 0)
            a(f"- [{vc}阅] {f_item['text']}")
        a()

    a("## 4. 今日板块建议")
    a()
    recs = llm_result.get("sector_recommendations", [])
    if recs:
        a("| 板块 | 来源 | 操作 | 信心 | 理由 | 关注标的(代码) |")
        a("|------|------|------|------|------|------|")
        order = {"买入": 0, "回避": 1, "关注": 2}
        recs.sort(key=lambda r: order.get(r.get("action", ""), 9))
        for r in recs:
            action_emoji = {"买入": "🟢", "关注": "🟡", "回避": "🔴"}.get(r.get("action", ""), "⚪")
            stocks_raw = r.get("key_stocks", [])
            if stocks_raw and isinstance(stocks_raw[0], dict):
                stocks = "<br>".join(
                    f"{s.get('name','')}({s.get('code','')})" +
                    (f" — {s.get('note','')}" if s.get('note') else "")
                    for s in stocks_raw[:8]
                )
            else:
                stocks = "、".join(str(s) for s in stocks_raw[:8])
            a(f"| {r.get('sector','')} | {r.get('theme_source','')} | {action_emoji} {r.get('action','')} | {r.get('confidence','')} | {r.get('reason','')} | {stocks} |")
        a()

    a("## 5. 风险提示")
    a()
    risks = llm_result.get("risk_alerts", [])
    if risks:
        for r in risks:
            a(f"- {r}")
    else:
        a("（无特别风险提示）")
    a()

    a("## 6. 整体策略")
    a()
    a(f"> {llm_result.get('market_stance', '（待生成）')}")
    a()

    watch = llm_result.get("key_watch", [])
    if watch:
        a("**重点观察方向**：")
        a()
        for w in watch:
            a(f"- {w}")
        a()

    # ── Raw data appendix ──
    a("---")
    a()
    a(f"### 附录：数据来源")
    a(f"- 央视新闻：{len(cctv_news)}条")
    a(f"- 同花顺财经快讯：{len(tenjqka_news)}条")
    a(f"- 新浪财经快讯：{len(sina_headlines)}条")
    a(f"- 雪球7×24快讯：{len(xueqiu_flash)}条")
    a(f"- 股吧热议：{len(guba_posts)}条")
    a(f"- 前日复盘快照：{'有' if postclose else '无'}")
    a()
    a(f"*本简报由 LLM 辅助生成，仅供参考，不构成投资建议*")

    return "\n".join(L)


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Pre-market morning briefing")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    trade_date = args.date
    api_key = args.api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")

    print(f"{'='*60}")
    print(f"  Morning Briefing · {trade_date}")
    print(f"{'='*60}")

    # How many days of news to cover (Mon → 3 days: Sat+Sun+Mon)
    gap_days = _days_since_last_trading(trade_date)
    news_pages = 2 + gap_days * 2  # 2 pages base + 2 per gap day
    xueqiu_count = 50 + gap_days * 30  # more flash for weekends
    print(f"  距上一交易日: {gap_days}天")

    # ── 1. Collect ──
    print("\n[1/3] 采集信息...")

    print("  - 央视新闻...", end=" ", flush=True)
    cctv = fetch_cctv_news(trade_date)
    # Also fetch for gap days (weekend)
    for offset in range(1, gap_days + 1):
        d = (date.fromisoformat(trade_date) - timedelta(days=offset)).isoformat()
        extra = fetch_cctv_news(d)
        if extra:
            cctv.extend(extra)
    print(f"{len(cctv)}条(含周末)")

    print("  - 同花顺财经快讯...", end=" ", flush=True)
    tenjqka = fetch_10jqka_news()
    print(f"{len(tenjqka)}条")

    print("  - 新浪财经快讯...", end=" ", flush=True)
    sina = fetch_sina_headlines(news_pages)
    print(f"{len(sina)}条")

    print("  - 复盘快照(最近交易日)...", end=" ", flush=True)
    postclose = load_postclose_snapshot(trade_date)
    if postclose:
        print(f"{postclose.get('date', '?')}")
    else:
        print("无")

    print("  - 研报热度(最近一期)...", end=" ", flush=True)
    inst_attn = load_institute_attention(trade_date)
    if inst_attn:
        print(f"{inst_attn.get('date', '?')} ({inst_attn.get('total', '?')}份研报)")
    else:
        print("无")

    print("  - 雪球7×24快讯...", end=" ", flush=True)
    xq_flash = fetch_xueqiu_flash(xueqiu_count)
    print(f"{len(xq_flash)}条")

    print("  - 股吧热议...", end=" ", flush=True)
    guba = fetch_guba_sentiment(postclose)
    print(f"{len(guba)}条")

    # ── 2. LLM Analysis ──
    llm_default = {
        "overnight_summary": "（无LLM分析）",
        "macro_events": [],
        "xueqiu_sentiment": "",
        "sector_recommendations": [],
        "risk_alerts": [],
        "market_stance": "",
        "key_watch": [],
        "guba_sentiment": "",
    }

    if args.dry_run:
        print("\n[2/3] LLM 分析 (--dry-run 跳过)")
        llm_result = llm_default
    elif not api_key:
        print("\n[2/3] 无 API key，跳过 LLM")
        llm_result = llm_default
    else:
        print("\n[2/3] LLM 分析...")
        context = build_llm_context(trade_date, cctv, tenjqka, sina, xq_flash, guba, postclose, inst_attn)
        print(f"  上下文: {len(context)} 字符")
        print("  调用 DeepSeek...", end=" ", flush=True)
        try:
            llm_result = call_llm(context, api_key)
            print("完成")
        except Exception as e:
            print(f"\n  失败: {e}")
            llm_result = llm_default

    # ── Data-driven stock selection ──
    # Build stock database from enriched postclose snapshot
    stock_db = {}  # {code: {name, industry, float_mkt, net_flow, pct_chg, etc}}
    if postclose:
        for s in postclose.get("limit_up_stocks", []):
            code = str(s.get("code", "")).zfill(6)
            stock_db[code] = {
                "name": s.get("name", ""),
                "code": code,
                "industry": s.get("industry", ""),
                "float_mkt": s.get("float_mkt", 0),
                "net_flow": s.get("net_flow", 0),
                "pct_chg": s.get("pct_chg", 0),
                "turnover": s.get("turnover", 0),
                "consecutive": s.get("consecutive", 1),
                "break_cnt": s.get("break_cnt", 0),
                "first_time": s.get("first_time", ""),
            }

    def _is_main_board(code):
        c = str(code).zfill(6)
        return (c.startswith("60") or c.startswith("00")) and not c.startswith("300") and not c.startswith("301")

    def _pick_leaders_by_industry(themes: list[dict], sector_name: str) -> list[str]:
        """Find which industries this sector maps to from postclose themes."""
        for t in themes:
            if t.get("name") == sector_name:
                return t.get("member_stocks", [])
        return []

    def _match_sector_to_leaders(sector_name: str) -> list[tuple]:
        """Fuzzy match sector name to SECTOR_LEADERS keys using keyword overlap."""
        if sector_name in SECTOR_LEADERS:
            return SECTOR_LEADERS[sector_name]
        # Split into keywords and find best matching key
        keywords = set(sector_name.replace("/", " ").replace("、", " ").split())
        best_key, best_score = None, 0
        for key in SECTOR_LEADERS:
            key_words = set(key.replace("/", " ").replace("、", " ").split())
            overlap = len(keywords & key_words)
            if overlap > best_score:
                best_score = overlap
                best_key = key
        if best_key and best_score >= 1:
            return SECTOR_LEADERS[best_key]
        # Secondary: keyword trigger table for edge cases
        triggers = {
            "化工": ["化学", "化工", "化纤", "钛白粉", "氟化工", "磷化工", "煤化工", "化肥"],
            "煤炭": ["煤炭", "焦煤", "焦炭", "煤"],
            "钢铁": ["钢铁", "钢", "特钢", "不锈钢"],
            "农牧": ["农牧", "猪肉", "饲料", "种业", "养殖", "农业"],
        }
        for target, words in triggers.items():
            for w in words:
                if w in sector_name:
                    return SECTOR_LEADERS.get(target, [])
        return []

    def _pick_leaders(sector_name: str, count: int = 6) -> list[dict]:
        """Stable leader picker: SECTOR_LEADERS base (always shown) + ZT annotations.

        - Base leaders ALWAYS appear, regardless of whether they hit limit-up
        - ZT activity adds annotation (🔥) and boosts ranking within base
        - Non-base ZT stocks from the theme's PRIMARY industry appended as 🆕
        """
        active_lookup = {}
        for code, info in stock_db.items():
            active_lookup[code] = info

        # Get theme members to determine the primary industry
        theme_members = set()
        for t in (postclose or {}).get("themes", []):
            if t.get("name") == sector_name:
                theme_members = set(t.get("member_stocks", []))
                break

        # Find the primary (most common) industry among theme members
        industry_counts = {}
        for code, info in active_lookup.items():
            if info["name"] in theme_members and info.get("industry"):
                ind = info["industry"]
                industry_counts[ind] = industry_counts.get(ind, 0) + 1
        primary_industry = max(industry_counts, key=industry_counts.get) if industry_counts else ""

        base_leaders = _match_sector_to_leaders(sector_name)
        result = []
        used_codes = set()

        # Phase 1: base leaders, filtered to main board
        for code, name, desc in base_leaders:
            if not _is_main_board(code):
                continue
            active = active_lookup.get(code, {})
            is_zt = active.get("pct_chg", 0) >= 9.5 if active else False
            consecutive = active.get("consecutive", 1) if active else 0
            break_cnt = active.get("break_cnt", 0) if active else 0

            # Day label: "昨日" on next trading day, else "周五" etc.
            if gap_days <= 1:
                day_tag = "昨日"
            else:
                last_td = date.fromisoformat(trade_date) - timedelta(days=gap_days)
                day_tag = ["周一","周二","周三","周四","周五","周六","周日"][last_td.weekday()]

            if is_zt:
                note = f"🔥 {day_tag}涨停 · {desc}"
                if consecutive > 1:
                    note += f"，{consecutive}连板"
                if break_cnt > 0:
                    note += "，炸板回封"
                score = 1000 + active.get("float_mkt", 0) / 1e8
            else:
                note = f"行业龙头（{day_tag}未涨停）· {desc}"
                score = 0

            result.append({"name": name, "code": code, "score": score, "note": note})
            used_codes.add(code)

        # Sort base: ZT first, then original order
        zt_base = [r for r in result if r["score"] > 0]
        non_zt_base = [r for r in result if r["score"] == 0]
        zt_base.sort(key=lambda x: -x["score"])
        result = zt_base + non_zt_base

        # Fallback: no base leaders matched → use theme members from primary industry
        if not result and primary_industry:
            fallback = []
            for code, info in active_lookup.items():
                if not _is_main_board(code):
                    continue
                if info.get("industry", "") != primary_industry:
                    continue
                is_zt = info.get("pct_chg", 0) >= 9.5
                note = f"{'🔥 前日涨停' if is_zt else '同行业成分'} · 流通{info.get('float_mkt',0)/1e8:.0f}亿"
                fallback.append({
                    "name": info["name"], "code": code,
                    "score": (1000 if is_zt else 0) + info.get("float_mkt", 0) / 1e8,
                    "note": note,
                })
            fallback.sort(key=lambda x: -x["score"])
            for f in fallback[:count]:
                result.append(f)
                used_codes.add(f["code"])

        # Phase 2: supplement with ZT stocks from primary industry not yet in result
        if len(result) < count and primary_industry:
            for code, info in active_lookup.items():
                if code in used_codes:
                    continue
                if len(result) >= count:
                    break
                if not _is_main_board(code):
                    continue
                if info.get("pct_chg", 0) < 9.5:
                    continue
                if info.get("industry", "") != primary_industry:
                    continue
                result.append({
                    "name": info["name"], "code": code,
                    "score": info.get("float_mkt", 0) / 1e8,
                    "note": f"🆕 新晋涨停 · 流通{info.get('float_mkt',0)/1e8:.0f}亿",
                })
                used_codes.add(code)

        return result

    # Replace LLM-picked stocks with data-driven picks
    for rec in llm_result.get("sector_recommendations", []):
        sector = rec.get("sector", "")
        leaders = _pick_leaders(sector)
        if leaders:
            rec["key_stocks"] = leaders
        else:
            # Fallback: keep LLM picks but filter to main board
            stocks = rec.get("key_stocks", [])
            if stocks and isinstance(stocks[0], dict):
                rec["key_stocks"] = [s for s in stocks if _is_main_board(s.get("code", ""))][:6]

    # ── 3. Generate ──
    print("\n[3/3] 生成简报...")
    markdown = render_briefing(trade_date, cctv, tenjqka, sina, xq_flash, guba, postclose, llm_result)

    out_dir = OUTPUT / trade_date
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "briefing.md"
    with open(out_path, "w") as f:
        f.write(markdown)

    print(f"  简报已保存: {out_path}")
    print(f"\n{'='*60}")
    print(f"  完成!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
