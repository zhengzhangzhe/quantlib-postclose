#!/usr/bin/env python3
"""Post-close daily review report for A-shares.

每日收盘复盘报告生成器 — 抓取涨停数据、资金流向、指数，LLM分类+规则四分层，输出Markdown。

Usage:
    python3 scripts/postclose_review.py                        # Today
    python3 scripts/postclose_review.py --date 2026-05-21      # Specific date
    python3 scripts/postclose_review.py --dry-run              # Skip LLM

Requirements: pip install akshare pandas requests
    Set env: ANTHROPIC_AUTH_TOKEN (DeepSeek API key) for LLM features.
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

# ── Paths ──
PROJ = Path(__file__).resolve().parent.parent
OUTPUT = PROJ / "output" / "postclose"
DATA_SNAPSHOTS = PROJ / "data" / "postclose"

# ── LLM config ──
LLM_URL = "https://api.deepseek.com/v1/chat/completions"
LLM_MODEL = "deepseek-chat"

SYSTEM_PROMPT = """你是A股涨停板复盘分析师。根据今日涨停数据、资金流向，完成主题归类和深度分析。

## 核心：主题归类（非行业归类！）
涨停股按「市场主题/概念」聚合，而非按原始行业归类。同主题可跨越多个行业。

### 归类铁律
1. 只有当入选理由、新闻、行业共识明确指向某概念时，才能归入该主题
2. 无法确定概念归属的股票，用原始行业名作为主题名（如"橡胶""化学制药"）
3. 不要把不相关的股票强行塞进热门主题——橡胶股≠机器人，纺织股≠AI
4. "other_stocks"最多放5只真正无法归类的股票，剩下的用各自行业名独立成主题

### 正确示例
- 京东方A(光学光电)+华映科技(光学光电)+纬达光电(光学光电)+龙腾光电(光学光电) → 概念明确 → "玻璃基板"
- 联创电子(光学光电)+索菱股份(汽车零部件)+浙江世宝(汽车零部件)+德赛西威(汽车零部件) → 概念明确 → "智能驾驶"

### 错误示例（禁止！）
- 龙星科技(橡胶)+北投科技(IT服务) → "机器人" ❌ 橡胶和IT服务跟机器人无关！
- 华升股份(纺织制造)+直真科技(软件开发) → "AI硬件" ❌ 纺织和软件跟AI硬件无关！

## 主题类型
- 主线：多股涨停(≥4只)+板块资金配合+早盘封板+有容量标的
- 次主线：涨停股较多但资金配合不全、或容量确认但前排分歧
- 活口：仅个别涨停(≤2只)、行业整体退潮或资金流出
- 失败轮动：昨日强势主题今日全面退潮
- 资金撤退方向：持续大幅流出、仅剩个别活口

## 输出JSON
{
  "opening_observations": [{"theme":"主题","observation":"现象(含资金数据)","sector_flow_note":"板块资金情况"}],
  "risk_boundary": "一句话风险边界(30字内)",
  "one_sentence": "一句话总收口(30字内)",
  "sentiment_stage": "情绪运行阶段判断(50字内)",
  "previous_day_review": [{"theme":"昨日主题","yesterday_samples":["股1","股2"],"today_status":"今日状态","classification":"局部活口/资金撤退方向/个股事件活口/高度活口/高度链延续"}],
  "themes": [{"name":"主题名","type":"主线/次主线/活口/失败轮动/资金撤退方向","member_stocks":["简称"],"sector_flow_note":"资金情况","verdict":"综合判定(60字内)"}],
  "other_stocks": ["无法归类的股票，尽量≤8只"],
  "old_strength_failures": ["昨日强势今日失败股票"],
  "causal_breakdown": "各主题分类理由(200字内)",
  "intraday_narrative": "早盘→盘中→午后 过程描述(200字内)",
  "role_summary": "角色层总收口(100字内)",
  "next_day_outlook": "次日观察要点(200字内)",
  "risk_participation": "市场风险与参与边界(150字内)"
}
只输出JSON，不用markdown代码块。股票名只用简称。所有文字简洁准确。"""


# ═══════════════════════════════════════════════════════════
# UTILS
# ═══════════════════════════════════════════════════════════

def _prev_trading_day(date_str: str) -> str:
    d = date.fromisoformat(date_str) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def _to_akshare_date(date_str: str) -> str:
    return date_str.replace("-", "")


def _retry(func, max_retries=3, delay=1.5):
    for attempt in range(max_retries):
        try:
            return func()
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)


def _code_normalize(code) -> str:
    """Normalize to 6-digit string, handling int64 truncation."""
    s = str(code).split(".")[0] if "." in str(code) else str(code)
    return s.zfill(6)


def _fmt_flow(amount: float) -> str:
    if amount is None or pd.isna(amount):
        return "N/A"
    v = float(amount)
    if abs(v) >= 1e8:
        return f"{v/1e8:+.1f}亿"
    elif abs(v) >= 1e4:
        return f"{v/1e4:+.0f}万"
    return f"{v:+.0f}"


def _parse_flow_str(val) -> float:
    if pd.isna(val) or val in ("-", ""):
        return 0.0
    s = str(val).strip()
    if s == "0.00":
        return 0.0
    try:
        if "亿" in s:
            return float(s.replace("亿", "")) * 1e8
        elif "万" in s:
            return float(s.replace("万", "")) * 1e4
        return float(s)
    except ValueError:
        return 0.0


def _parse_time_to_minutes(t) -> int:
    if pd.isna(t) or t is None:
        return 1440
    s = str(int(t)) if isinstance(t, (int, float)) else str(t)
    s = s.zfill(6)
    return int(s[:2]) * 60 + int(s[2:4])


def _pct_str(v: float) -> str:
    return f"{v:+.2f}%"


# ═══════════════════════════════════════════════════════════
# DATA LAYER
# ═══════════════════════════════════════════════════════════

def fetch_limit_up_pool(trade_date: str) -> pd.DataFrame:
    import akshare as ak
    df = _retry(lambda: ak.stock_zt_pool_em(date=_to_akshare_date(trade_date)))
    if df.empty:
        return pd.DataFrame()
    df = df.rename(columns={
        "代码": "code", "名称": "name", "涨跌幅": "pct_chg", "最新价": "close",
        "成交额": "amount", "流通市值": "float_mkt", "总市值": "total_mkt",
        "换手率": "turnover", "封板资金": "lock_amt", "首次封板时间": "first_time",
        "最后封板时间": "last_time", "炸板次数": "break_cnt", "涨停统计": "zt_stat",
        "连板数": "consecutive", "所属行业": "industry",
    })
    for c in ["pct_chg", "turnover", "amount", "lock_amt", "float_mkt", "break_cnt"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "consecutive" in df.columns:
        df["consecutive"] = pd.to_numeric(df["consecutive"], errors="coerce").fillna(1).astype(int)
    return df


def fetch_failed_pool(trade_date: str) -> pd.DataFrame:
    import akshare as ak
    df = _retry(lambda: ak.stock_zt_pool_zbgc_em(date=_to_akshare_date(trade_date)))
    if df.empty:
        return pd.DataFrame()
    df = df.rename(columns={
        "代码": "code", "名称": "name", "涨跌幅": "pct_chg", "最新价": "close",
        "成交额": "amount", "换手率": "turnover", "振幅": "amplitude",
        "封板时间": "first_time", "炸板时间": "break_time", "所属行业": "industry",
    })
    for c in ["pct_chg", "turnover", "amount"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def fetch_limit_down_pool(trade_date: str) -> pd.DataFrame:
    import akshare as ak
    df = _retry(lambda: ak.stock_zt_pool_dtgc_em(date=_to_akshare_date(trade_date)))
    if df.empty:
        return pd.DataFrame()
    df = df.rename(columns={
        "代码": "code", "名称": "name", "涨跌幅": "pct_chg", "最新价": "close",
        "成交额": "amount", "换手率": "turnover", "所属行业": "industry",
    })
    for c in ["pct_chg", "turnover", "amount"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def fetch_strong_pool(trade_date: str) -> pd.DataFrame:
    import akshare as ak
    df = _retry(lambda: ak.stock_zt_pool_strong_em(date=_to_akshare_date(trade_date)))
    if df.empty:
        return pd.DataFrame()
    df = df.rename(columns={
        "代码": "code", "名称": "name", "涨跌幅": "pct_chg", "最新价": "close",
        "涨停价": "zt_price", "成交额": "amount", "流通市值": "float_mkt",
        "换手率": "turnover", "量比": "vol_ratio", "涨停统计": "zt_stat",
        "入选理由": "reason", "所属行业": "industry",
    })
    for c in ["pct_chg", "turnover", "amount", "float_mkt"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def fetch_individual_fund_flow() -> pd.DataFrame:
    """Fetch all-stock fund flow (total net flow per stock)."""
    import akshare as ak
    try:
        df = _retry(lambda: ak.stock_fund_flow_individual(symbol="即时"), max_retries=2, delay=2.0)
    except Exception:
        print("    [warn] 个股资金流向获取失败")
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    df = df.rename(columns={
        "股票代码": "code", "股票简称": "name",
        "最新价": "close", "涨跌幅": "pct_chg",
        "净额": "net_flow_raw", "换手率": "turnover_raw",
        "流入资金": "inflow", "流出资金": "outflow",
    })
    if "code" in df.columns:
        df["code"] = df["code"].astype(str).str.zfill(6)
    if "pct_chg" in df.columns:
        df["pct_chg"] = df["pct_chg"].astype(str).str.replace("%", "", regex=False)
        df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
    for col in ["net_flow_raw", "inflow", "outflow"]:
        if col in df.columns:
            df[col] = df[col].apply(_parse_flow_str)
    df["net_flow"] = df["net_flow_raw"]
    if "close" in df.columns:
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df


def fetch_sector_fund_flow() -> pd.DataFrame:
    """Try stock_fund_flow_industry (HTML scrape), fallback to push API."""
    import akshare as ak
    try:
        df = _retry(lambda: ak.stock_fund_flow_industry(), max_retries=1, delay=1.0)
        if not df.empty and "净额" in df.columns:
            df = df.rename(columns={
                "行业": "sector", "净额": "net_flow",
                "流入资金": "inflow", "流出资金": "outflow",
                "行业-涨跌幅": "sector_pct", "领涨股": "leader",
            })
            for c in ["net_flow", "inflow", "outflow", "sector_pct"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            if "net_flow" in df.columns:
                df["net_flow"] = df["net_flow"] * 1e8
            return df
    except Exception:
        pass
    try:
        df = _retry(lambda: ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流"), max_retries=1, delay=1.0)
        if not df.empty:
            df = df.rename(columns={"名称": "sector", "今日主力净流入-净额": "net_flow"})
            if "net_flow" in df.columns:
                df["net_flow"] = pd.to_numeric(df["net_flow"], errors="coerce")
            return df
    except Exception:
        pass
    print("    [warn] 行业资金流向获取失败，将从个股聚合")
    return pd.DataFrame()


def _build_sector_flow_from_individual(ind_flow: pd.DataFrame) -> pd.DataFrame:
    """Aggregate individual stock flows by industry for a rough sector view."""
    if ind_flow.empty or "net_flow" not in ind_flow.columns or "code" not in ind_flow.columns:
        return pd.DataFrame()
    # Use code prefix to infer broad sectors
    def _infer_sector(code_str):
        c = str(code_str).zfill(6)
        if c.startswith("600") or c.startswith("601") or c.startswith("603") or c.startswith("605"):
            return "沪市主板"
        elif c.startswith("000") or c.startswith("001") or c.startswith("002") or c.startswith("003"):
            return "深市主板"
        elif c.startswith("300") or c.startswith("301"):
            return "创业板"
        elif c.startswith("688") or c.startswith("689"):
            return "科创板"
        elif c.startswith("4") or c.startswith("8"):
            return "北交所"
        return "其他"

    rows = []
    for _, r in ind_flow.iterrows():
        sector = _infer_sector(r["code"])
        net = float(r.get("net_flow", 0)) if pd.notna(r.get("net_flow")) else 0.0
        rows.append({"sector": sector, "net_flow": net})
    if not rows:
        return pd.DataFrame()
    agg = pd.DataFrame(rows).groupby("sector")["net_flow"].sum().reset_index()
    agg = agg.sort_values("net_flow", ascending=False)
    return agg


def fetch_index_pct(trade_date: str, symbol: str = "sh000001") -> float | None:
    """Fetch index daily % change via Sina API."""
    import akshare as ak
    try:
        df = _retry(lambda: ak.stock_zh_index_daily(symbol=symbol), max_retries=2, delay=2.0)
        if df.empty or "close" not in df.columns:
            return None
        df = df.sort_values("date")
        df["date"] = df["date"].astype(str)
        mask = df["date"] <= trade_date
        relevant = df[mask]
        if len(relevant) < 2:
            return None
        today_c = float(relevant.iloc[-1]["close"])
        prev_c = float(relevant.iloc[-2]["close"])
        return (today_c / prev_c - 1) * 100 if prev_c != 0 else None
    except Exception:
        return None


def fetch_market_breadth() -> dict:
    """Placeholder — breadth is computed from ind_flow pct_chg after load."""
    return {"advancing": None, "declining": None, "flat": None}


def _compute_breadth_from_flow(ind_flow: pd.DataFrame) -> dict:
    """Compute advancing/declining from individual fund flow pct_chg column."""
    if ind_flow.empty or "pct_chg" not in ind_flow.columns:
        return {"advancing": None, "declining": None, "flat": None}
    pct = ind_flow["pct_chg"].dropna()
    if pct.empty:
        return {"advancing": None, "declining": None, "flat": None}
    return {
        "advancing": int((pct > 0).sum()),
        "declining": int((pct < 0).sum()),
        "flat": int((pct == 0).sum()),
    }


def fetch_prev_limit_up_pool(trade_date: str) -> pd.DataFrame:
    return fetch_limit_up_pool(_prev_trading_day(trade_date))


# ── Snapshot persistence ──

def load_snapshot(trade_date: str) -> dict | None:
    path = DATA_SNAPSHOTS / trade_date / "snapshot.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def save_snapshot(trade_date: str, data: dict):
    path = DATA_SNAPSHOTS / trade_date
    path.mkdir(parents=True, exist_ok=True)
    with open(path / "snapshot.json", "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def load_prev_snapshot(trade_date: str) -> dict | None:
    return load_snapshot(_prev_trading_day(trade_date))


# ═══════════════════════════════════════════════════════════
# ANALYSIS LAYER
# ═══════════════════════════════════════════════════════════

def _compute_stock_metrics(
    limit_up: pd.DataFrame, ind_flow: pd.DataFrame, prev_limit_up: pd.DataFrame
) -> dict:
    """Per-stock metrics dict for rule-based classification."""
    flow_lookup = {}
    if not ind_flow.empty:
        for _, r in ind_flow.iterrows():
            flow_lookup[_code_normalize(r["code"])] = {
                "net_flow": float(r.get("net_flow", 0)) if pd.notna(r.get("net_flow")) else 0.0,
            }
    prev_lookup = {}
    if not prev_limit_up.empty:
        for _, r in prev_limit_up.iterrows():
            prev_lookup[_code_normalize(r["code"])] = {
                "turnover": float(r["turnover"]) if pd.notna(r.get("turnover")) else None,
                "consecutive": int(r["consecutive"]) if pd.notna(r.get("consecutive")) else 0,
            }
    metrics = {}
    for _, row in limit_up.iterrows():
        code = row["code"]
        name = _normalize_name(row["name"])
        code_short = _code_normalize(code)
        flow = flow_lookup.get(code_short, {})
        prev = prev_lookup.get(code_short, {})
        metrics[name] = {
            "code": code, "name": name,
            "pct_chg": float(row["pct_chg"]) if pd.notna(row["pct_chg"]) else 0.0,
            "turnover": float(row["turnover"]) if pd.notna(row["turnover"]) else 0.0,
            "prev_turnover": prev.get("turnover"),
            "net_flow": flow.get("net_flow", 0.0),
            "first_time": row.get("first_time"),
            "last_time": row.get("last_time"),
            "break_cnt": int(row.get("break_cnt", 0)) if pd.notna(row.get("break_cnt", 0)) else 0,
            "consecutive": int(row["consecutive"]) if pd.notna(row["consecutive"]) else 1,
            "prev_consecutive": prev.get("consecutive", 0),
            "lock_amt": float(row["lock_amt"]) if pd.notna(row.get("lock_amt")) else 0.0,
            "float_mkt": float(row["float_mkt"]) if pd.notna(row.get("float_mkt")) else 0.0,
            "amount": float(row["amount"]) if pd.notna(row["amount"]) else 0.0,
            "industry": row.get("industry", ""),
        }
    return metrics


def volume_price_ruling(m: dict) -> str:
    """量价裁定 based on turnover comparison and fund flow."""
    pct = m["pct_chg"]
    turnover = m["turnover"]
    prev_t = m.get("prev_turnover")
    net_flow = m["net_flow"]
    break_cnt = m["break_cnt"]
    is_zt = pct >= 9.5
    if pct <= -9.5:
        return "跌停资金/量价证伪"
    if pct < -3:
        return "收跌且资金流出"
    if break_cnt > 0 and not is_zt and net_flow < -1e6:
        return "炸板后资金流出"
    if break_cnt > 0 and not is_zt:
        return "炸板分化"
    if not is_zt:
        if net_flow < -1e6:
            return "收跌且资金流出" if pct <= 0 else "价格承接但资金流出"
        return "收跌掉队" if pct <= 0 else "价格承接但资金流出"
    if prev_t and prev_t > 0:
        vol_ratio = turnover / prev_t
        if vol_ratio < 0.8 and break_cnt == 0 and turnover < 10:
            return "缩量锁筹"
        if turnover > 25:
            return "封板强但资金流出" if net_flow < 0 else "高换手封板"
        if vol_ratio >= 0.8:
            if net_flow < 0 and abs(net_flow) > 1e7:
                return "封板强但资金流出"
            return "放量/温和封板"
        return "放量/温和封板"
    if turnover > 25:
        return "封板强但资金流出" if net_flow < 0 else "高换手封板"
    return "放量/温和封板"


def _normalize_name(name: str) -> str:
    """Convert full-width ASCII chars to half-width for consistent matching."""
    result = []
    for ch in str(name):
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        elif code == 0x3000:
            result.append(' ')
        else:
            result.append(ch)
    return ''.join(result)


def four_layer_classify(theme_stocks: list[str], all_metrics: dict) -> list[dict]:
    """Assign four-layer roles within a theme."""
    # Build normalized lookup from all_metrics
    norm_lookup = {_normalize_name(k): (k, v) for k, v in all_metrics.items()}
    members = []
    for name in theme_stocks:
        key = _normalize_name(name)
        if key in norm_lookup:
            orig_name, m = norm_lookup[key]
            m = m.copy()
            m["ruling"] = volume_price_ruling(m)
            members.append(m)
    if not members:
        return []
    members.sort(key=lambda m: (
        _parse_time_to_minutes(m["first_time"]),
        -m["consecutive"],
        -(m["lock_amt"] or 0),
    ))
    assigned = []
    remaining = list(members)
    total = len(members)

    def _qualifies_anchor(m):
        """情绪锚/强度锚质量门槛：换手>2%且(资金正流入或大市值)"""
        return m["turnover"] > 2 and (m["net_flow"] > 0 or m["float_mkt"] > 1e11)

    def _assign(role: str, count: int):
        nonlocal remaining
        if role in ("情绪锚", "强度锚"):
            qualified = [m for m in remaining if _qualifies_anchor(m)]
            take = qualified[:count]
            for m in take:
                m["role"] = role
                remaining.remove(m)
            assigned.extend(take)
        else:
            take = [m for i, m in enumerate(remaining) if i < count]
            for m in take:
                m["role"] = role
            assigned.extend(take)
            remaining = remaining[count:]

    _assign("情绪锚", min(2, max(1, total // 4)))
    _assign("强度锚", min(2, max(1, total // 4)))
    capacity = [m for m in remaining if m["float_mkt"] > 1e10 and m["net_flow"] > 5e7]
    for m in capacity:
        m["role"] = "容量验证锚"
        assigned.append(m)
        remaining.remove(m)
    n_core = max(1, len(remaining) - min(1, len(remaining)))
    _assign("次核心", n_core)
    if remaining:
        _assign("活口", len(remaining))
    role_order = {"情绪锚": 0, "强度锚": 1, "容量验证锚": 2, "次核心": 3, "活口": 4}
    assigned.sort(key=lambda m: (role_order.get(m.get("role", ""), 9), _parse_time_to_minutes(m["first_time"])))
    return assigned


def consecutive_height_table(limit_up: pd.DataFrame, all_metrics: dict) -> list[dict]:
    """Build连板高度单元."""
    high = limit_up[limit_up["consecutive"] >= 2].copy()
    if high.empty:
        return []
    results = []
    for _, r in high.iterrows():
        name = _normalize_name(r["name"])
        m = all_metrics.get(name, {})
        results.append({
            "name": name,
            "pct_chg": float(r["pct_chg"]),
            "consecutive": int(r["consecutive"]),
            "turnover": float(r["turnover"]),
            "prev_turnover": m.get("prev_turnover"),
            "first_time": r.get("first_time"),
            "break_cnt": int(r.get("break_cnt", 0)) if pd.notna(r.get("break_cnt", 0)) else 0,
            "lock_status": "回封" if r.get("break_cnt", 0) > 0 else "封板",
            "industry": r.get("industry", ""),
        })
    results.sort(key=lambda x: -x["consecutive"])
    return results


# ═══════════════════════════════════════════════════════════
# LLM CONTEXT BUILDER
# ═══════════════════════════════════════════════════════════

def prepare_llm_context(
    trade_date: str,
    limit_up: pd.DataFrame,
    failed: pd.DataFrame,
    limit_down: pd.DataFrame,
    strong: pd.DataFrame,
    sector_flow: pd.DataFrame,
    ind_flow: pd.DataFrame,
    prev_snapshot: dict | None,
    index_sh: float | None,
    index_sz: float | None,
    breadth: dict,
) -> str:
    lines = [f"## 今日市场数据", f"日期：{trade_date}"]
    if index_sh is not None:
        lines.append(f"上证指数：{index_sh:+.2f}%")
    if index_sz is not None:
        lines.append(f"深证成指：{index_sz:+.2f}%")
    if breadth.get("advancing"):
        lines.append(f"上涨家数：{breadth['advancing']}")
    if breadth.get("declining"):
        lines.append(f"下跌家数：{breadth['declining']}")
    lines.append(f"涨停封板数：{len(limit_up)}")
    lines.append(f"炸板数：{len(failed)}")
    lines.append(f"跌停数：{len(limit_down)}")
    if len(limit_up) + len(failed) > 0:
        lines.append(f"破板率：{len(failed)/(len(limit_up)+len(failed))*100:.1f}%")

    # Sector flows (from individual aggregation if primary failed)
    if not sector_flow.empty and "net_flow" in sector_flow.columns:
        inflows = sector_flow.nlargest(5, "net_flow")
        lines.append("\n## 行业资金净流入Top5")
        for _, r in inflows.iterrows():
            lines.append(f"{r['sector']}：{_fmt_flow(r['net_flow'])}")
        outflows = sector_flow.nsmallest(5, "net_flow")
        lines.append("\n## 行业资金净流出Top5")
        for _, r in outflows.iterrows():
            lines.append(f"{r['sector']}：{_fmt_flow(r['net_flow'])}")

    # Individual top flows
    if not ind_flow.empty:
        top_in = ind_flow.nlargest(5, "net_flow")
        lines.append("\n## 个股资金净流入Top5")
        for _, r in top_in.iterrows():
            lines.append(f"{r['name']}({r['code']})：涨跌幅{r.get('pct_chg', 'N/A')}%，净流入{_fmt_flow(r['net_flow'])}")
        top_out = ind_flow.nsmallest(5, "net_flow")
        lines.append("\n## 个股资金净流出Top5")
        for _, r in top_out.iterrows():
            lines.append(f"{r['name']}({r['code']})：涨跌幅{r.get('pct_chg', 'N/A')}%，净流出{_fmt_flow(r['net_flow'])}")

    # Limit-up stocks with strong pool enrichment
    lines.append(f"\n## 今日涨停股列表({len(limit_up)}只)")
    for _, r in limit_up.iterrows():
        bonus = ""
        if not strong.empty:
            sp = strong[strong["code"] == r["code"]]
            if not sp.empty:
                reason = sp.iloc[0].get("reason", "")
                if reason and pd.notna(reason):
                    bonus = f"，入选理由：{reason}"
        lines.append(
            f"{r['name']}({r['code']})：{r['pct_chg']:+.2f}%，"
            f"换手{r['turnover']:.2f}%，封板时间{r.get('first_time','?')}，"
            f"连板{r['consecutive']}板，{r['industry']}{bonus}"
        )

    # Previous day themes
    if prev_snapshot and prev_snapshot.get("themes"):
        lines.append(f"\n## 上一交易日主题回顾")
        for t in prev_snapshot["themes"]:
            stocks_str = "、".join(s[:6] for s in t.get("member_stocks", []))
            lines.append(f"{t['name']}({t.get('type','')})：{stocks_str}")

    # Failed stocks
    if not failed.empty:
        lines.append(f"\n## 今日炸板股({len(failed)}只，显示前20)")
        for _, r in failed.head(20).iterrows():
            lines.append(f"{r['name']}：{r.get('pct_chg',0):+.2f}%，{r.get('industry','')}")

    return "\n".join(lines)


def call_llm_classification(context: str, api_key: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        "temperature": 0.2,
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
    }
    r = requests.post(LLM_URL, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


# ═══════════════════════════════════════════════════════════
# REPORT GENERATION
# ═══════════════════════════════════════════════════════════

_ROLE_LABELS = {
    "情绪锚": "🎯 情绪锚", "强度锚": "💪 强度锚",
    "容量验证锚": "📊 容量验证锚", "次核心": "🔸 次核心", "活口": "🔹 活口",
}


def render_markdown(
    trade_date: str,
    limit_up: pd.DataFrame,
    failed: pd.DataFrame,
    limit_down: pd.DataFrame,
    sector_flow: pd.DataFrame,
    ind_flow: pd.DataFrame,
    index_sh: float | None,
    index_sz: float | None,
    breadth: dict,
    llm_result: dict,
    all_metrics: dict,
    prev_snapshot: dict | None,
) -> str:
    L = []
    a = lambda s="": L.append(s)

    # Title
    a(f"# YANJIUYUAN POSTCLOSE REVIEW · {trade_date}")
    a()
    a(f"## {trade_date} 正式收盘复盘")
    a()
    a("*自动同步自正式复盘 Markdown · 供手机查看与分享*")
    a()

    # Section 0: Opening observations
    observations = llm_result.get("opening_observations", [])
    if observations:
        a("---")
        a()
        for obs in observations:
            a(f"- **{obs.get('theme', '')}**：{obs.get('observation', '')}")
            if obs.get("sector_flow_note"):
                a(f"  - {obs['sector_flow_note']}")
        risk = llm_result.get("risk_boundary", "")
        if risk:
            a()
            a(f"> **风险边界**：{risk}")
        a()

    # Section 1
    a("## 1. 一句话总收口")
    a()
    a(llm_result.get("one_sentence", "（待生成）"))
    a()

    # Section 2: Market environment
    a("## 2. 盘型 / 环境")
    a()
    a("| 指标 | 数值 |")
    a("|------|------|")
    a(f"| 上证指数 | {index_sh:+.2f}% |" if index_sh is not None else "| 上证指数 | N/A |")
    a(f"| 深证成指 | {index_sz:+.2f}% |" if index_sz is not None else "| 深证成指 | N/A |")
    if breadth.get("advancing"):
        a(f"| 上涨家数 | {breadth['advancing']} |")
    if breadth.get("declining"):
        a(f"| 下跌家数 | {breadth['declining']} |")
    a(f"| 涨停封板数 | {len(limit_up)} |")
    a(f"| 炸板数 | {len(failed)} |")
    a(f"| 跌停数 | {len(limit_down)} |")
    if len(limit_up) + len(failed) > 0:
        a(f"| 破板率 | {len(failed)/(len(limit_up)+len(failed))*100:.1f}% |")
    a()

    # Section 2.5: Fund flow evidence
    a("### 2.5 资金流证据")
    a()
    if not sector_flow.empty and "net_flow" in sector_flow.columns:
        a("**行业净流入 Top 5：**")
        a()
        for _, r in sector_flow.nlargest(5, "net_flow").iterrows():
            a(f"- {r['sector']}：{_fmt_flow(r['net_flow'])}")
        a()
        a("**行业净流出 Top 5：**")
        a()
        for _, r in sector_flow.nsmallest(5, "net_flow").iterrows():
            a(f"- {r['sector']}：{_fmt_flow(r['net_flow'])}")
        a()

    if not ind_flow.empty:
        a("**个股净流入 Top 5：**")
        a()
        for i, (_, r) in enumerate(ind_flow.nlargest(5, "net_flow").iterrows(), 1):
            a(f"{i}. {r['name']}：{r.get('pct_chg', 0):+.2f}%，{_fmt_flow(r['net_flow'])}")
        a()
        a("**个股净流出 Top 5：**")
        a()
        for i, (_, r) in enumerate(ind_flow.nsmallest(5, "net_flow").iterrows(), 1):
            a(f"{i}. {r['name']}：{r.get('pct_chg', 0):+.2f}%，{_fmt_flow(r['net_flow'])}")
        a()

    # Section 2.6
    a("### 2.6 情绪运行阶段")
    a()
    a(llm_result.get("sentiment_stage", "（待生成）"))
    a()

    # Section 3: Previous day review
    a("## 3. 上一交易日重点轮动支线现状")
    a()
    prev_review = llm_result.get("previous_day_review", [])
    if prev_review:
        for i, p in enumerate(prev_review, 1):
            samples = "、".join(p.get("yesterday_samples", []))
            a(f"{i}. **{p.get('theme', '')}**：昨日样本 {samples} → 今日 {p.get('today_status', '')} → 归类为「{p.get('classification', '')}」")
            a()
    else:
        a("（无上一交易日数据）")
        a()

    # Section 4: Theme classification
    a("## 4. 主线 / 次主线 / 活口 / 失败轮动 / 资金撤退方向")
    a()
    themes = llm_result.get("themes", [])
    for theme in themes:
        name = theme.get("name", "")
        ttype = theme.get("type", "")
        stocks = theme.get("member_stocks", [])
        sector_note = theme.get("sector_flow_note", "")
        verdict = theme.get("verdict", "")
        a(f"### {name}")
        a()
        if sector_note:
            a(f"**板块数据**：{sector_note}")
            a()
        a(f"**成员池**（{len(stocks)}只）：")
        a()
        layered = four_layer_classify(stocks, all_metrics)
        for m in layered:
            role_tag = _ROLE_LABELS.get(m.get("role", ""), "")
            a(f"- **{role_tag} {m['name']}**：{_pct_str(m['pct_chg'])}，"
              f"换手{m['turnover']:.2f}%，净流入{_fmt_flow(m['net_flow'])}，"
              f"封板时间{m.get('first_time','?')}，连板{m['consecutive']}板 → {m.get('ruling','')}")
        a()
        if verdict:
            a(f"> **判定**：{verdict}")
        a()

    # Other stocks
    other = llm_result.get("other_stocks", [])
    if other:
        a("### 其他（杂项）")
        a()
        a(f"**成员池**（{len(other)}只）：")
        a()
        for name in other:
            m = all_metrics.get(_normalize_name(name), {})
            if m:
                a(f"- {m['name']}：{_pct_str(m['pct_chg'])}，换手{m['turnover']:.2f}%，{m.get('industry','')}")
        a()
        a("> 判定：高度个股存在但主题过于分散，仅做全市场映射与高度观察")
        a()

    # Old strength failures
    failures = llm_result.get("old_strength_failures", [])
    if failures:
        a("### 旧强失败锚补充池")
        a()
        a(f"以下 {len(failures)} 只标的今日收跌/炸板/资金流出，移出弱转强关注列表：")
        a()
        a("、".join(failures))
        a()

    # Section 4.5: Consecutive height
    a("### 4.5 连板高度单元")
    a()
    height_data = consecutive_height_table(limit_up, all_metrics)
    if height_data:
        a("| 股票 | 状态 | 换手(今/昨) | 方向 | 风险 |")
        a("|------|------|-------------|------|------|")
        for h in height_data:
            prev_t_str = f"{h['prev_turnover']:.2f}%" if h.get("prev_turnover") else "?"
            risk = "高位分歧接力" if h["consecutive"] >= 3 else "分歧接力"
            a(f"| {h['name']} | {_pct_str(h['pct_chg'])}，{h['lock_status']} | "
              f"{h['turnover']:.2f}%/{prev_t_str} | {h['industry']} | {risk} |")
        a()

    # Section 5: Intraday narrative
    a("## 5. 过程状态分层")
    a()
    a(llm_result.get("intraday_narrative", "（待生成）"))
    a()

    # Section 6: Four-layer detail
    a("## 6. 四分层")
    a()
    for theme in themes:
        name = theme.get("name", "")
        stocks = theme.get("member_stocks", [])
        layered = four_layer_classify(stocks, all_metrics)
        if not layered:
            continue
        a(f"### {name}")
        a()
        for m in layered:
            prev_t_str = f"{m.get('prev_turnover', 0):.2f}%" if m.get('prev_turnover') else "N/A"
            a(f"- **{m.get('role','')} {m['name']}**（{_pct_str(m['pct_chg'])}，"
              f"换手{m['turnover']:.2f}%/{prev_t_str}，{_fmt_flow(m['net_flow'])}）→ {m.get('ruling','')}")
        a()

    # Old strength failure detail
    if failures:
        a("### 旧强失败锚补充池详细")
        a()
        for fname in failures:
            m = all_metrics.get(_normalize_name(fname), {})
            if m:
                prev_t_str = f"{m.get('prev_turnover', 0):.2f}%" if m.get('prev_turnover') else "N/A"
                a(f"- {m['name']}（{_pct_str(m['pct_chg'])}，换手{m['turnover']:.2f}%/{prev_t_str}，"
                  f"{_fmt_flow(m['net_flow'])}，前{m.get('prev_consecutive',0)}板）→ {m.get('ruling','')}")
        a()

    # Section 7
    a("## 7. 角色层总收口")
    a()
    a(llm_result.get("role_summary", "（待生成）"))
    a()

    # Section 8: Factual basis
    a("## 8. 事实依据")
    a()
    idx_sh_str = f"上证{index_sh:+.2f}%" if index_sh is not None else "上证N/A"
    idx_sz_str = f"深证{index_sz:+.2f}%" if index_sz is not None else "深证N/A"
    a(f"指数层面：{idx_sh_str}，{idx_sz_str}，"
      f"上涨{breadth.get('advancing', '?')}家，下跌{breadth.get('declining', '?')}家")
    a(f"涨停层面：封板{len(limit_up)}只，炸板{len(failed)}只，跌停{len(limit_down)}只")
    theme_summary = "、".join(f"{t['name']}{len(t.get('member_stocks',[]))}只" for t in themes)
    a(f"方向层面：{theme_summary}")
    a()

    # Section 9
    a("## 9. 原因拆解")
    a()
    a(llm_result.get("causal_breakdown", "（待生成）"))
    a()

    # Section 10
    a("## 10. 盘中判断修正 + 次日观察与证伪")
    a()
    a("今日修正：昨日强势方向今日无法线性外推，退潮市场须优先考虑资金流向而非连板惯性。")
    a()
    a(llm_result.get("next_day_outlook", "（待生成）"))
    a()

    # Section 11
    a("## 11. 次日市场观察摘要")
    a()
    for theme in themes:
        name = theme.get("name", "")
        stocks = theme.get("member_stocks", [])
        a(f"- **{name}**：{'、'.join(stocks[:4])}")
    a()

    # Section 12 — dynamic based on actual volume-price rulings
    a("## 12. 股票池更新")
    a()
    a("| 操作 | 详细 |")
    a("|------|------|")
    new_entries = []
    downgrade = []
    retain = []
    for theme in themes:
        for name in theme.get("member_stocks", []):
            m = all_metrics.get(_normalize_name(name), {})
            ruling = m.get("ruling", "")
            net_flow = m.get("net_flow", 0)
            role = m.get("role", "")
            if ruling == "封板强但资金流出" and abs(net_flow) > 5e7:
                downgrade.append(f"{name}({ruling},{_fmt_flow(net_flow)})")
            elif role in ("容量验证锚",) and net_flow > 0:
                retain.append(name)
            elif ruling not in ("封板强但资金流出",):
                new_entries.append(name)
    new_uniq = list(dict.fromkeys(new_entries))  # dedup preserving order
    a(f"| 新补录 | {', '.join(new_uniq[:12])}{' 等' if len(new_uniq) > 12 else ''} 进入次日观察 |")
    if downgrade:
        a(f"| ⚠️ 降级 | {', '.join(downgrade[:8])} → 高位风险，移出核心观察池 |")
    else:
        a("| 降级 | 无触发降级条件的标的 |")
    if retain:
        a(f"| 保留 | {', '.join(retain[:8])} → 容量验证，资金配合 |")
    else:
        a("| 保留 | 容量验证标的，若同步资金撤退则降级 |")
    a()

    # Section 13
    a("## 13. 市场风险与参与边界")
    a()
    a(llm_result.get("risk_participation", "（待生成）"))
    a()

    # Section 14
    a("## 14. 数据口径与限制")
    a()
    a("1. 涨停宽度数据来源于AkShare封板名册接口，含封板/炸板/跌停计数")
    a("2. 行业及个股资金流向来源于东方财富资金批次数据")
    a("3. 换手率采用双日事实口径对比")
    a("4. 连板名册基于当日AkShare涨停股池接口更新")
    a("5. 主题归类与叙事分析由LLM辅助生成，仅供参考")
    a()

    a("---")
    a()
    a("*自动生成于 " + datetime.now().strftime("%Y-%m-%d %H:%M") + " · 供手机查看与分享*")

    return "\n".join(L)


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Post-close daily review report")
    parser.add_argument("--date", default=date.today().isoformat(), help="Trade date YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM call")
    parser.add_argument("--api-key", default=None, help="DeepSeek API key (or env ANTHROPIC_AUTH_TOKEN)")
    args = parser.parse_args()

    trade_date = args.date
    api_key = args.api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")

    print(f"{'='*60}")
    print(f"  Postclose Review · {trade_date}")
    print(f"{'='*60}")

    # ── 1. Fetch data ──
    print("\n[1/5] 抓取数据...")
    print("  - 涨停股池...", end=" ", flush=True)
    limit_up = fetch_limit_up_pool(trade_date)
    print(f"{len(limit_up)}只")

    print("  - 炸板股池...", end=" ", flush=True)
    failed = fetch_failed_pool(trade_date)
    print(f"{len(failed)}只")

    print("  - 跌停股池...", end=" ", flush=True)
    limit_down = fetch_limit_down_pool(trade_date)
    print(f"{len(limit_down)}只")

    print("  - 强势股池...", end=" ", flush=True)
    strong = fetch_strong_pool(trade_date)
    print(f"{len(strong)}只")

    print("  - 行业资金流向...", end=" ", flush=True)
    sector_flow = fetch_sector_fund_flow()
    print(f"{len(sector_flow)}个行业" if not sector_flow.empty else "N/A")

    print("  - 个股资金流向...", end=" ", flush=True)
    ind_flow = fetch_individual_fund_flow()
    print(f"{len(ind_flow)}只")

    if limit_up.empty:
        print("\n 今日无涨停数据，可能非交易日或数据未更新")
        sys.exit(0)

    # Compute market breadth from individual flow data
    breadth = _compute_breadth_from_flow(ind_flow)
    print(f"  涨跌家数(自算): 涨{breadth.get('advancing','?')}/跌{breadth.get('declining','?')}/平{breadth.get('flat','?')}")

    # Aggregate sector flows from individual data if primary failed
    if sector_flow.empty and not ind_flow.empty:
        sector_flow = _build_sector_flow_from_individual(ind_flow)
        if not sector_flow.empty:
            print(f"  行业资金(从个股聚合): {len(sector_flow)}个板块")

    print("  - 上证指数...", end=" ", flush=True)
    index_sh = fetch_index_pct(trade_date)
    print(f"{index_sh:+.2f}%" if index_sh else "N/A")

    print("  - 深证成指...", end=" ", flush=True)
    index_sz = fetch_index_pct(trade_date, "sz399001")
    print(f"{index_sz:+.2f}%" if index_sz else "N/A")

    print("  - 前日涨停池...", end=" ", flush=True)
    prev_limit_up = fetch_prev_limit_up_pool(trade_date)
    print(f"{len(prev_limit_up)}只")

    print("  - 前日快照...", end=" ", flush=True)
    prev_snapshot = load_prev_snapshot(trade_date)
    print("有" if prev_snapshot else "无(首次运行)")

    # ── 2. Compute metrics ──
    print("\n[2/5] 计算指标...")
    all_metrics = _compute_stock_metrics(limit_up, ind_flow, prev_limit_up)
    print(f"  共 {len(all_metrics)} 只涨停股指标计算完成")

    # ── 3. LLM Classification ──
    llm_default = {
        "opening_observations": [], "risk_boundary": "", "one_sentence": "（无LLM）",
        "sentiment_stage": "", "previous_day_review": [], "other_stocks": [],
        "old_strength_failures": [], "causal_breakdown": "", "intraday_narrative": "",
        "role_summary": "", "next_day_outlook": "", "risk_participation": "",
        "themes": [{"name": "全市场", "type": "活口", "member_stocks": limit_up["name"].tolist(),
                      "sector_flow_note": "", "verdict": "LLM未启用"}],
    }

    if args.dry_run:
        print("\n[3/5] LLM 分类 (--dry-run 跳过)")
        llm_result = llm_default
    elif not api_key:
        print("\n[3/5] 无 API key，跳过 LLM。设置 ANTHROPIC_AUTH_TOKEN 环境变量以启用")
        llm_result = llm_default
    else:
        print("\n[3/5] LLM 主题分类与分析...")
        context = prepare_llm_context(
            trade_date, limit_up, failed, limit_down, strong,
            sector_flow, ind_flow, prev_snapshot, index_sh, index_sz, breadth,
        )
        print(f"  上下文长度: {len(context)} 字符")
        print("  调用 DeepSeek API...", end=" ", flush=True)
        try:
            llm_result = call_llm_classification(context, api_key)
            print("完成")
        except Exception as e:
            print(f"\n  失败: {e}")
            llm_result = llm_default

    # ── 4. Generate report ──
    print("\n[4/5] 生成报告...")
    markdown = render_markdown(
        trade_date, limit_up, failed, limit_down,
        sector_flow, ind_flow, index_sh, index_sz, breadth,
        llm_result, all_metrics, prev_snapshot,
    )
    out_dir = OUTPUT / trade_date
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "review.md"
    with open(report_path, "w") as f:
        f.write(markdown)
    print(f"  报告已保存: {report_path}")

    # ── 5. Save snapshot ──
    print("\n[5/5] 保存快照...")
    # Build enriched stock records for morning briefing
    stock_records = []
    for _, r in limit_up.iterrows():
        code = r["code"]
        name = _normalize_name(r["name"])
        code_short = code.split(".")[0] if "." in str(code) else str(code).zfill(6)
        m = all_metrics.get(_normalize_name(name), {})
        stock_records.append({
            "code": code_short,
            "name": name,
            "industry": r.get("industry", ""),
            "pct_chg": float(r["pct_chg"]) if pd.notna(r.get("pct_chg")) else 0.0,
            "turnover": float(r["turnover"]) if pd.notna(r.get("turnover")) else 0.0,
            "float_mkt": float(r["float_mkt"]) if pd.notna(r.get("float_mkt")) else 0.0,
            "net_flow": m.get("net_flow", 0.0),
            "first_time": str(r.get("first_time", "")),
            "consecutive": int(r["consecutive"]) if pd.notna(r.get("consecutive")) else 1,
            "break_cnt": int(r.get("break_cnt", 0)) if pd.notna(r.get("break_cnt", 0)) else 0,
        })
    snapshot = {
        "date": trade_date,
        "limit_up_count": len(limit_up),
        "failed_count": len(failed),
        "limit_down_count": len(limit_down),
        "index_sh": index_sh,
        "index_sz": index_sz,
        "themes": [{"name": t.get("name", ""), "type": t.get("type", ""),
                     "member_stocks": t.get("member_stocks", [])}
                   for t in llm_result.get("themes", [])],
        "limit_up_stocks": stock_records,
    }
    save_snapshot(trade_date, snapshot)
    print(f"  快照已保存: {DATA_SNAPSHOTS / trade_date / 'snapshot.json'}")

    print(f"\n{'='*60}")
    print(f"  完成! 报告: {report_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
