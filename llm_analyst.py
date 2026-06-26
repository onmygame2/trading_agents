"""
大模型每日市场分析层

- OpenAI 兼容协议：一套代码支持 DeepSeek / Kimi / 通义千问 / 智谱GLM / OpenAI
- 配置存 config/llm_config.json（不进 git；API Key 不回显明文）
- 采集当日市场上下文 → 生成结构化研报 → 缓存 knowledge_base/ai_report_{date}.json

研报包含: 大盘择时 / 板块轮动 / 卡脖子主题(serenity) / 点评今日选股 / 持仓诊断
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "llm_config.json")
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge_base")

# 各供应商的 OpenAI 兼容端点与默认模型
PROVIDER_PRESETS: Dict[str, Dict[str, str]] = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "kimi": {
        "label": "Kimi 月之暗面",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-32k",
    },
    "qwen": {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "glm": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
}

DEFAULT_CONFIG = {
    "provider": "deepseek",
    "base_url": PROVIDER_PRESETS["deepseek"]["base_url"],
    "model": PROVIDER_PRESETS["deepseek"]["model"],
    "api_key": "",
    "enabled": False,
    "temperature": 0.4,
    "timeout": 90,
}


# ---------------------------------------------------------------------------
# 配置读写
# ---------------------------------------------------------------------------

def load_llm_config() -> Dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f) or {})
        except Exception as e:
            logger.warning("读取 LLM 配置失败: %s", e)
    # 环境变量兜底（便于 cron / CI）
    env_key = os.environ.get("LLM_API_KEY")
    if env_key and not cfg.get("api_key"):
        cfg["api_key"] = env_key
    return cfg


def save_llm_config(updates: Dict) -> Dict:
    """合并保存；api_key 为空字符串时保留旧值（前端不回显明文）"""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    cfg = load_llm_config()
    incoming = dict(updates or {})

    # provider 切换时若未显式给 base_url/model，用预设填充
    provider = incoming.get("provider")
    if provider and provider in PROVIDER_PRESETS:
        preset = PROVIDER_PRESETS[provider]
        if not incoming.get("base_url"):
            incoming["base_url"] = preset["base_url"]
        if not incoming.get("model"):
            incoming["model"] = preset["model"]

    # 空 api_key 不覆盖已有
    if "api_key" in incoming and not incoming["api_key"]:
        incoming.pop("api_key")

    cfg.update({k: v for k, v in incoming.items() if v is not None})
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


def public_config() -> Dict:
    """给前端展示用：隐去 api_key 明文，只给是否已配置 + 掩码"""
    cfg = load_llm_config()
    key = cfg.get("api_key", "") or ""
    masked = ""
    if key:
        masked = (key[:4] + "****" + key[-4:]) if len(key) > 8 else "****"
    return {
        "provider": cfg.get("provider", "deepseek"),
        "base_url": cfg.get("base_url", ""),
        "model": cfg.get("model", ""),
        "enabled": bool(cfg.get("enabled", False)),
        "temperature": cfg.get("temperature", 0.4),
        "has_key": bool(key),
        "key_masked": masked,
        "providers": {k: {"label": v["label"], "base_url": v["base_url"], "model": v["model"]}
                      for k, v in PROVIDER_PRESETS.items()},
    }


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------

def chat_completion(messages: List[Dict], cfg: Optional[Dict] = None) -> str:
    cfg = cfg or load_llm_config()
    api_key = cfg.get("api_key") or ""
    if not api_key:
        raise RuntimeError("未配置 API Key，请在 Dashboard 设置页填写")
    base_url = (cfg.get("base_url") or "").rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": cfg.get("model") or "deepseek-chat",
        "messages": messages,
        "temperature": float(cfg.get("temperature", 0.4)),
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post(url, json=payload, headers=headers,
                         timeout=int(cfg.get("timeout", 90)))
    if resp.status_code != 200:
        raise RuntimeError(f"LLM 请求失败 {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def test_connection(cfg: Optional[Dict] = None) -> Dict:
    try:
        out = chat_completion(
            [{"role": "user", "content": "回复两个字：在线"}], cfg
        )
        return {"ok": True, "reply": out.strip()[:50]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# 市场上下文采集
# ---------------------------------------------------------------------------

def _latest_pick_report() -> Dict:
    import glob
    files = sorted(glob.glob(os.path.join(KNOWLEDGE_DIR, "daily_pick_*.json")))
    if not files:
        return {}
    try:
        with open(files[-1], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def gather_market_context() -> Dict:
    """聚合大盘/板块/主线/选股/持仓/新闻，作为 LLM 输入"""
    ctx: Dict = {"date": datetime.now().strftime("%Y-%m-%d")}

    # 大盘 + 板块情绪
    try:
        from ai_analyzer import AIAnalyzer
        ov = AIAnalyzer().get_market_overview()
        indices = {}
        raw = ov.get("indices", {})
        if hasattr(raw, "iterrows") and not raw.empty:
            for _, row in raw.iterrows():
                indices[str(row.get("name", row.get("code", "")))] = {
                    "price": round(float(row.get("close", row.get("price", 0))), 2),
                    "change_pct": round(float(row.get("change_pct", 0)), 2),
                }
        elif isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, dict):
                    indices[k] = {
                        "price": round(float(v.get("price", v.get("close", 0))), 2),
                        "change_pct": round(float(v.get("change_pct", v.get("change", 0))), 2),
                    }
        ctx["indices"] = indices
        ctx["market_sentiment"] = ov.get("market_sentiment", "neutral")
        ctx["sector_hot"] = ov.get("sector_hot", [])[:10]
    except Exception as e:
        logger.warning("采集大盘概览失败: %s", e)
        ctx["indices"] = {}
        ctx["sector_hot"] = []

    # 当季主线
    report = _latest_pick_report()
    ctx["mainlines"] = report.get("mainlines", [])[:8]
    ctx["report_date"] = report.get("date", "")

    # 今日选股
    picks = []
    for p in report.get("top_picks", [])[:8]:
        picks.append({
            "code": p.get("code"),
            "score": p.get("strategy_score", p.get("final_score")),
            "reason": p.get("reason", "")[:80],
        })
    ctx["today_picks"] = picks
    ctx["watchlist"] = [
        {"code": w.get("code"), "reason": w.get("reason", "")[:60]}
        for w in report.get("watchlist", [])[:6]
    ]

    # 持仓账户
    try:
        acct_path = os.path.join(BASE_DIR, "account", "account_state_v2.json")
        if os.path.isfile(acct_path):
            with open(acct_path, encoding="utf-8") as f:
                acct = json.load(f)
            pos = []
            for code, p in (acct.get("positions") or {}).items():
                pos.append({
                    "code": code,
                    "avg_price": p.get("avg_price"),
                    "hold_days": p.get("hold_days"),
                    "reason": (p.get("reason") or "")[:60],
                })
            ctx["account"] = {
                "cash": acct.get("cash"),
                "positions": pos,
                "total_profit": acct.get("total_profit"),
            }
    except Exception as e:
        logger.warning("采集账户失败: %s", e)

    # 新闻缓存（如有）
    try:
        news_path = os.path.join(BASE_DIR, "data", "news",
                                 f"news_{ctx['date']}.json")
        if os.path.isfile(news_path):
            with open(news_path, encoding="utf-8") as f:
                nd = json.load(f)
            heads = nd.get("headlines") or nd.get("items") or []
            ctx["news"] = [h.get("title", h) if isinstance(h, dict) else h
                           for h in heads[:15]]
    except Exception:
        pass

    return ctx


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一家A股量化私募的首席策略分析师，每天为基金经理出具一份简明、可执行的早盘研报。
要求：
- 观点鲜明，给明确结论（进攻/防守/观望、加仓/减仓/持有），不要模棱两可
- 基于给定数据说话，数据不足时直说，不编造个股利好
- 中文，专业但口语化，避免空话套话
- 严格按要求的小标题输出 Markdown

你额外掌握一套"卡脖子/供应链瓶颈"选股框架（Serenity 理论）：
沿产业链向上游追溯，找到"一旦断货整个赛道地震"的关键瓶颈环节，
该环节上的小盘股弹性最大（如 InP衬底、CPO激光器、特高压换流变、碳纳米管导电剂等）。
当今日热门板块/主线触及某条产业链时，用此框架点出潜在的卡脖子龙头方向（指出环节与方向即可，不荐具体代码除非数据中已有）。"""

USER_TEMPLATE = """今日日期：{date}

【大盘指数】
{indices}

【市场情绪】{sentiment}

【今日热门板块】
{sectors}

【当季主线】
{mainlines}

【系统今日选股】
{picks}

【因子观察名单】
{watchlist}

【当前持仓账户】
{account}

【近期新闻头条】
{news}

请输出以下结构的早盘研报（用 Markdown 小标题）：

## 一、大盘择时
今天该进攻还是防守？建议仓位区间（如 3-5 成）。一句话给理由。

## 二、板块轮动
哪些主线在加速、哪些在退潮？今天重点关注 / 回避哪些方向。

## 三、卡脖子主题机会
结合今日热门板块/主线，用供应链瓶颈框架点出 1-2 个值得挖掘的卡脖子环节与方向。

## 四、今日选股点评
对系统选出的票做点评：哪些信号扎实、哪些需警惕，整体是否值得跟。

## 五、持仓诊断
对当前持仓逐一给"持有/减仓/止盈/止损"建议（无持仓则说明空仓是否合理）。

## 六、一句话总结
今天最重要的一个判断。"""


def _fmt(ctx: Dict) -> str:
    def block(x):
        return json.dumps(x, ensure_ascii=False, indent=2) if x else "（无数据）"
    sent_map = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}
    return USER_TEMPLATE.format(
        date=ctx.get("date", ""),
        indices=block(ctx.get("indices")),
        sentiment=sent_map.get(ctx.get("market_sentiment", "neutral"), "中性"),
        sectors=block(ctx.get("sector_hot")),
        mainlines=block(ctx.get("mainlines")),
        picks=block(ctx.get("today_picks")),
        watchlist=block(ctx.get("watchlist")),
        account=block(ctx.get("account")),
        news=block(ctx.get("news")),
    )


def generate_daily_analysis(force: bool = False) -> Dict:
    """生成（或读取缓存）当日 AI 研报"""
    date = datetime.now().strftime("%Y-%m-%d")
    out_path = os.path.join(KNOWLEDGE_DIR, f"ai_report_{date}.json")
    if not force and os.path.isfile(out_path):
        try:
            with open(out_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    cfg = load_llm_config()
    ctx = gather_market_context()
    content = chat_completion([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _fmt(ctx)},
    ], cfg)

    result = {
        "date": date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "provider": cfg.get("provider"),
        "model": cfg.get("model"),
        "markdown": content,
        "context_digest": {
            "indices": ctx.get("indices"),
            "sentiment": ctx.get("market_sentiment"),
            "sector_count": len(ctx.get("sector_hot", [])),
            "picks": len(ctx.get("today_picks", [])),
        },
    }
    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def load_latest_report() -> Dict:
    import glob
    files = sorted(glob.glob(os.path.join(KNOWLEDGE_DIR, "ai_report_*.json")))
    if not files:
        return {}
    try:
        with open(files[-1], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="测试连通性")
    ap.add_argument("--run", action="store_true", help="生成今日研报")
    args = ap.parse_args()
    if args.test:
        print(test_connection())
    elif args.run:
        r = generate_daily_analysis(force=True)
        print(r.get("markdown", "（无内容）"))
    else:
        print(json.dumps(public_config(), ensure_ascii=False, indent=2))
