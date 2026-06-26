"""
全局选股器 - 统一入口

每日运行流程:
1. 采集市场数据 (指数/情绪/板块/资金)
2. 采集个股因子 (价量+基本面)
3. 因子评分 (多维度加权)
4. 策略筛选 (5策略并行)
5. 信号合并 (加权+覆盖加分)
6. 虚拟账户交易 (止损/止盈/买入)
7. 生成报告 (Markdown)
"""
import os
import sys
import json
import logging
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
KB_DIR = os.path.join(BASE_DIR, "knowledge_base")
os.makedirs(KB_DIR, exist_ok=True)

logger = logging.getLogger(__name__)


class JSONEncoder(json.JSONEncoder):
    """Handle numpy types for JSON serialization"""
    def default(self, obj):
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.ndarray,)):
            return obj.tolist()
        return super().default(obj)


def sanitize_for_json(obj):
    """Recursively convert numpy types to native Python types"""
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    return obj


def _should_allow_buy(market_overview: Dict, capital_data: Dict) -> bool:
    """强化市场状态过滤"""
    regime = market_overview.get("regime", "中性")
    if regime in ("偏弱下跌", "弱势下跌"):
        return False

    sentiment = market_overview.get("sentiment", {})
    if sentiment.get("sentiment_score", 50) < 35:
        return False

    indices = market_overview.get("indices", {})
    for key in ("上证指数", "sh000001"):
        if key in indices and indices[key].get("change_pct", 0) < -1.5:
            return False

    north_total = capital_data.get("north_total_5d", 0)
    if north_total < -50:
        return False

    return True


def _get_dl_scores(scored: List[Dict], sector_data: Dict, market_overview: Dict) -> Dict[str, float]:
    """DL 因子模型批量推理"""
    try:
        from dl_factor_model import DLFactorSelector
        sel = DLFactorSelector()
        if not sel.is_trained():
            logger.info("DL模型未训练，跳过推理 (运行 scripts/train_dl_factor.py)")
            return {}
        ctx = {
            "sentiment": market_overview.get("sentiment", {}).get("sentiment_score", 50),
            "index_change": 0.0,
        }
        for key in ("上证指数", "sh000001"):
            if key in market_overview.get("indices", {}):
                ctx["index_change"] = market_overview["indices"][key].get("change_pct", 0)
                break
        return sel.predict_proba_map(scored, sector_data, ctx)
    except Exception as e:
        logger.warning(f"DL推理跳过: {e}")
        return {}


def _build_factor_watchlist(scored: List[Dict], top_n: int,
                            dl_scores: Dict[str, float] = None) -> List[Dict]:
    """策略无信号时：按综合因子分输出观察名单，保证每日有推荐可看"""
    if not scored:
        return []
    rows = []
    for s in scored:
        code = s.get("code")
        if not code:
            continue
        total = s.get("total_score", 0) or 0
        dl = (dl_scores or {}).get(code)
        bonus = float(dl) * 12 if dl is not None else 0
        dims = s.get("dimensions", {}) or {}
        top_dim = max(
            ((k, v.get("score", 0) if isinstance(v, dict) else v) for k, v in dims.items()),
            key=lambda x: x[1],
            default=("综合", total),
        )
        rows.append({
            "code": code,
            "price": s.get("price", 0),
            "strategy_score": int(min(99, total + bonus)),
            "final_score": round(total + bonus, 1),
            "strategy_id": "factor_watchlist",
            "strategy_name": "因子观察",
            "pick_mode": "factor_watchlist",
            "reason": f"[因子观察] 综合分{total:.0f} 领先维度:{top_dim[0]}",
            "confidence": min(95, int(total)),
            "dl_score": round(dl, 4) if dl is not None else None,
            "source_strategy_id": "factor_watchlist",
            "strategies": {
                "factor_watchlist": {
                    "strategy_score": int(total),
                    "reason": f"综合因子 Top，{top_dim[0]}={top_dim[1]:.0f}",
                    "confidence": int(total),
                }
            },
        })
    rows.sort(key=lambda x: x.get("strategy_score", 0), reverse=True)
    return rows[:top_n]


def _ensure_daily_picks(merged: List[Dict], scored: List[Dict],
                        strategy_results: Dict[str, List],
                        top_n: int, dl_scores: Dict[str, float] = None) -> List[Dict]:
    """保证每日至少 top_n 条推荐（强信号优先，不足用因子观察补齐）"""
    if len(merged) >= top_n:
        for p in merged:
            p.setdefault("pick_mode", "alpha_signal")
        return merged[:top_n]

    out = list(merged)
    seen = {p["code"] for p in out}

    if len(out) < top_n:
        flat = []
        for picks in (strategy_results or {}).values():
            flat.extend(picks or [])
        flat.sort(key=lambda x: x.get("strategy_score", 0), reverse=True)
        for p in flat:
            if p["code"] in seen:
                continue
            item = dict(p)
            item.setdefault("pick_mode", "strategy_fallback")
            item.setdefault("strategy_id", item.get("strategy_id", "strategy_fallback"))
            out.append(item)
            seen.add(p["code"])
            if len(out) >= top_n:
                break

    if len(out) < top_n:
        for p in _build_factor_watchlist(scored, top_n * 2, dl_scores):
            if p["code"] in seen:
                continue
            out.append(p)
            seen.add(p["code"])
            if len(out) >= top_n:
                break

    for p in out:
        p.setdefault("pick_mode", p.get("pick_mode", "alpha_signal"))
    if len(merged) < top_n and len(out) >= len(merged):
        logger.info(
            f"每日保底推荐: 策略信号 {len(merged)} -> 展示 {len(out[:top_n])} "
            f"(含因子观察 {sum(1 for x in out if x.get('pick_mode')=='factor_watchlist')} 只)"
        )
    return out[:top_n]


def _apply_dl_rerank(merged: List[Dict], dl_scores: Dict[str, float]) -> List[Dict]:
    """对扁平竞技结果叠加 DL 分数"""
    if not merged or not dl_scores:
        return merged
    for item in merged:
        ds = dl_scores.get(item["code"], 0)
        item["dl_score"] = round(ds, 4)
        item["final_score"] = round(item.get("final_score", 0) + ds * 12, 1)
    merged.sort(key=lambda x: x.get("final_score", 0), reverse=True)
    return merged


def _apply_ml_rerank(merged: List[Dict], scored: List[Dict]) -> List[Dict]:
    """使用 ML/因子排名对候选股重排"""
    if not merged:
        return merged
    try:
        from ml_stock_selector import MLStockSelector

        selector = MLStockSelector()
        score_map = {s["code"]: s for s in scored}
        factors_dict = {}
        for item in merged[:50]:
            code = item["code"]
            src = score_map.get(code, {})
            dims = src.get("dimensions", {})
            factors_dict[code] = {
                name: (info.get("score", 50) if isinstance(info, dict) else info)
                for name, info in dims.items()
            }

        meta_path = os.path.join(selector.model_dir, "model_meta.json")
        if os.path.exists(meta_path):
            selector.load_model()
            predictions = selector.predict(factors_dict)
            pred_map = {p["code"]: p.get("combined_score", 0) for p in predictions}
        else:
            rank_results = selector.ranker.score_stocks(factors_dict)
            pred_map = {r["code"]: r["score"] for r in rank_results}

        for item in merged:
            boost = pred_map.get(item["code"], 0) * 10
            item["final_score"] = item.get("final_score", 0) + boost
            item["ml_boost"] = round(boost, 2)

        merged.sort(key=lambda x: x.get("final_score", 0), reverse=True)
        logger.info("ML重排完成")
    except Exception as e:
        logger.warning(f"ML重排跳过: {e}")
    return merged


def run_picker(date: str = None, top_n: int = 10, min_score: int = 40,
               pool_top: int = 500, pool_mode: str = "mainline",
               sector_top: int = 10, per_sector: int = 10,
               progress_cb=None) -> Dict:
    """
    运行选股流程
    
    Args:
        date: 日期 (YYYY-MM-DD), 默认今天
        top_n: 输出Top N
        min_score: 最低综合分
        pool_mode: mainline=主线放量强势股(~80); sector=热门板块Top10×10; liquidity=成交额Top500
        pool_top: liquidity 模式下的预筛数量，0=全池
        sector_top: 热门板块数量
        per_sector: 每个板块选取个股数
        progress_cb: 可选回调 (progress:int, message:str)
    
    Returns:
        选股结果
    """
    def _progress(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    if pool_mode in ("sector", "mainline") and min_score > 35:
        min_score = 35

    logger.info(f"=== 开始选股: {date} ===")

    # 1. 导入模块
    from factor_data import get_stock_pool, select_pool_top_liquidity, FactorCollector, SectorFactors, CapitalFactors, SentimentFactors
    from factor_engine_v2 import FactorEngine
    from strategies_v2.manager import StrategyManager
    from trade_engine_v2 import get_account

    # 2. 采集市场/板块数据（板块模式需先知道热门板块）
    _progress(8, "采集市场与板块数据...")
    logger.info("采集市场数据...")
    market_overview = SentimentFactors.get_market_overview()
    sector_data = SectorFactors.get_sector_summary()
    capital_data = CapitalFactors.get_capital_summary()
    pool_meta = {}

    # 3. 构建扫描池
    pool = get_stock_pool()
    full_pool_size = len(pool)
    if pool_mode == "mainline":
        from mainline_pool import select_mainline_pool
        _progress(10, "主线主题 × 放量强势股...")
        pool, pool_meta = select_mainline_pool(pool)
        sector_data = {
            **sector_data,
            "hot_sectors": pool_meta.get("mainlines", sector_data.get("hot_sectors", [])),
            "theme_ctx": pool_meta.get("theme_ctx", {}),
            "keywords": pool_meta.get("keywords", []),
            "leader_theme": pool_meta.get("leader_theme", ""),
        }
        logger.info(f"主线选股池: {full_pool_size} -> {len(pool)} 只")
    elif pool_mode == "sector":
        from sector_pool import select_sector_pool
        _progress(10, f"热门板块 Top{sector_top} × 每板块 Top{per_sector}...")
        pool, pool_meta = select_sector_pool(
            pool,
            top_sectors=sector_top,
            per_sector=per_sector,
            hot_sectors=sector_data.get("hot_sectors"),
        )
        logger.info(f"板块选股池: {full_pool_size} -> {len(pool)} 只")
    elif pool_top and pool_top < full_pool_size:
        _progress(10, f"流动性预筛 Top{pool_top} / {full_pool_size}...")
        pool = select_pool_top_liquidity(pool, pool_top)
        pool_meta = {"pool_mode": "liquidity", "pool_top": pool_top}
        logger.info(f"流动性预筛: {full_pool_size} -> {len(pool)} 只")
    else:
        pool_meta = {"pool_mode": "full"}
    logger.info(f"股票池: {len(pool)} 只")

    # 4. 采集个股因子 + 评分
    _progress(15, f"因子评分 0/{len(pool)}...")
    logger.info("采集个股因子+评分...")
    engine = FactorEngine()
    scored = []
    total = len(pool)

    for i, code in enumerate(pool):
        if (i + 1) % 100 == 0 or i + 1 == total:
            pct = 15 + int((i + 1) / total * 55)
            _progress(pct, f"因子评分 {i+1}/{total}...")
        if (i + 1) % 200 == 0:
            logger.info(f"  进度: {i+1}/{total}")

        try:
            factors = FactorCollector.collect_for_stock(code)
            if not factors:
                continue

            pv = factors.get("price_volume", {})
            fund = factors.get("fundamental", {})

            r = engine.score_stock(
                code=code, pv=pv, fund=fund,
                sector_data=sector_data, capital_data=capital_data,
            )
            # Attach extra data for strategy filtering
            r['extra'] = factors.get('extra', {})
            r['fundamental'] = fund
            scored.append(r)
        except Exception as e:
            if i < 5:
                logger.warning(f"处理失败 {code}: {e}")

    scored.sort(key=lambda x: x["total_score"], reverse=True)
    scored = [s for s in scored if s["total_score"] >= min_score]
    logger.info(f"评分完成: {len(scored)} 只 (>= {min_score}分)")

    # 消息面/财报筛选
    try:
        from message_screener import get_screener
        today = datetime.now().strftime("%Y-%m-%d")
        get_screener().score_batch(scored, sector_data, today)
        logger.info("消息面评分完成")
    except Exception as e:
        logger.warning(f"消息面评分失败: {e}")

    # 5. DL 因子推理 + 策略筛选
    _progress(72, "DL推理 + 组合策略选股...")
    dl_scores = _get_dl_scores(scored, sector_data, market_overview)
    if dl_scores:
        logger.info(f"DL推理: {len(dl_scores)} 只")
        for s in scored:
            c = s.get("code")
            if c in dl_scores:
                s["dl_score"] = dl_scores[c]

    logger.info("运行策略筛选 (组合正收益池加权)...")
    mgr = StrategyManager()
    market_ctx = {
        "index_change": 0.0,
        "index_mom_5d": 0.0,
        "index_mom_20d": 0.0,
        "index_bull": True,
        "sector_pool": pool_mode in ("sector", "mainline"),
        "mainline_pool": pool_mode == "mainline",
    }
    for key in ("上证指数", "sh000001"):
        if key in market_overview.get("indices", {}):
            idx = market_overview["indices"][key]
            market_ctx["index_change"] = idx.get("change_pct", 0) or 0
            market_ctx["index_mom_5d"] = idx.get("mom_5d", 0) or 0
            market_ctx["index_mom_20d"] = idx.get("mom_20d", 0) or 0
            market_ctx["index_bull"] = idx.get("above_ma20", True)
            break
    strategy_results = mgr.run_all(
        scored, sector_data, dl_scores=dl_scores or None, market_ctx=market_ctx,
    )
    weight_alloc = mgr.weight_allocation(min(top_n, 5))
    buy_picks = mgr.build_composite_picks(
        strategy_results, total=min(top_n, 5), min_score=55, allocation=weight_alloc,
    )
    buy_picks = _apply_dl_rerank(buy_picks, dl_scores)
    enabled_cnt = sum(1 for v in strategy_results.values() if v)
    alloc_str = ", ".join(f"{mgr.strategies[n].metadata.get('name', n)}×{c}" for n, c in weight_alloc)
    logger.info(f"组合买入: {len(buy_picks)} 只 | 策略信号 {enabled_cnt} | 权重配额 [{alloc_str}]")

    watchlist = []
    if len(buy_picks) < top_n:
        seen = {p["code"] for p in buy_picks}
        for p in _build_factor_watchlist(scored, top_n * 2, dl_scores):
            if p["code"] in seen:
                continue
            watchlist.append(p)
            seen.add(p["code"])
            if len(watchlist) >= top_n - len(buy_picks):
                break
        if watchlist:
            logger.info(f"因子观察名单: {len(watchlist)} 只 (非实盘买入)")

    merged = list(buy_picks)

    # 刷新 Top 候选实时价格 (iFind/新浪 Provider)
    try:
        from market_data import refresh_realtime_on_picks, get_realtime_prices
        refresh_codes = [p['code'] for p in merged[:top_n * 2]]
        rt_prices = get_realtime_prices(refresh_codes)
        for pick in merged[:top_n * 2]:
            if pick['code'] in rt_prices:
                pick['price'] = round(rt_prices[pick['code']], 2)
        merged = refresh_realtime_on_picks(merged[:top_n * 2]) + merged[top_n * 2:]
        logger.info(f"实时价格刷新: {len(rt_prices)} 只")
    except Exception as e:
        logger.warning(f"实时价格刷新失败: {e}")

    # 盘中交易：强信号即买，不做时段/涨跌家数过滤
    allow_buy = True

    # 6. 虚拟账户
    acct = get_account()

    # 实时价格：持仓 + 候选
    current_prices = {}
    try:
        from market_data import get_realtime_prices
        codes = set(acct.positions.keys())
        for s in scored[:80]:
            if s.get("code"):
                codes.add(s["code"])
        for p in buy_picks[:10]:
            codes.add(p.get("code"))
        rt = get_realtime_prices(list(codes))
        current_prices.update({k: v for k, v in rt.items() if v and v > 0})
    except Exception as e:
        logger.warning(f"批量实时价失败: {e}")

    for s in scored[:50]:
        if s.get("price") and s["code"] not in current_prices:
            current_prices[s["code"]] = s["price"]

    from factor_data import PriceVolumeFactors
    for code in list(acct.positions.keys()):
        if code not in current_prices or current_prices[code] <= 0:
            try:
                pv = PriceVolumeFactors.compute(code)
                if pv and pv.get("price"):
                    current_prices[code] = pv["price"]
            except Exception:
                pass

    acct.advance_hold_days(date)
    stop_actions = acct.check_stop_loss_take_profit(current_prices, date)

    # 买入信号
    buy_actions = []
    if allow_buy:
        for pick in buy_picks[:min(top_n, 5)]:
            if not acct.can_buy():
                break
            if pick["code"] in acct.positions:
                continue

            reason_parts = []
            sid = pick.get("strategy_id") or pick.get("strategy_name", "")
            if sid:
                reason_parts.append(str(sid))
            for sn, sd in pick.get("strategies", {}).items():
                reason_parts.append(sd.get("reason", ""))

            price = current_prices.get(pick["code"]) or pick["price"]
            result = acct.buy(
                code=pick["code"],
                price=price,
                amount=acct.get_buy_amount(pick["price"]),
                date=date,
                reason=" | ".join([r for r in reason_parts[:2] if r]),
            )
            if result.get("ok"):
                buy_actions.append(result)

    acct.save()

    # 6b. 分策略纸面账户 (各 10 万独立)
    paper_buys = {}
    try:
        from paper_trading_v2 import init_paper_accounts, run_paper_buy, run_paper_sell
        init_paper_accounts()
        run_paper_sell(date)
        for picks in strategy_results.values():
            for p in picks[:10]:
                if p.get("price"):
                    current_prices[p["code"]] = p["price"]
        paper_results = dict(strategy_results)
        paper_buys = run_paper_buy(date, paper_results, allow_buy, current_prices)
        logger.info(f"纸面交易: {sum(len(v) for v in paper_buys.values())} 笔买入")
    except Exception as e:
        logger.warning(f"纸面交易跳过: {e}")

    # 7. 生成报告
    _progress(88, "虚拟账户交易+生成报告...")
    sector_report = dict(sector_data)
    sector_report["pool_meta"] = pool_meta
    scored_by_code = {s["code"]: s for s in scored if s.get("code")}
    report = generate_report(
        date=date,
        market_overview=market_overview,
        sector_data=sector_report,
        capital_data=capital_data,
        merged=merged[:top_n],
        buy_picks=buy_picks,
        watchlist=watchlist,
        strategy_results=strategy_results,
        weight_allocation=weight_alloc,
        scored_by_code=scored_by_code,
        stop_actions=stop_actions,
        buy_actions=buy_actions,
        account=acct,
        current_prices=current_prices,
        total_scored=len(scored),
        total_pool=full_pool_size,
    )

    # 保存报告
    report_file = os.path.join(KB_DIR, f"daily_pick_{date}.md")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)

    report_json = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": date,
        "total_pool": full_pool_size,
        "scanned_pool": len(pool),
        "pool_mode": pool_meta.get("pool_mode", pool_mode),
        "pool_top": pool_top if pool_mode == "liquidity" else None,
        "sector_top": sector_top if pool_mode == "sector" else None,
        "per_sector": per_sector if pool_mode == "sector" else None,
        "sector_picks": pool_meta.get("sector_picks", pool_meta.get("line_picks", {})),
        "sector_counts": pool_meta.get("sector_counts", pool_meta.get("line_counts", {})),
        "mainlines": pool_meta.get("mainlines", []),
        "keywords": pool_meta.get("keywords", []),
        "leader_theme": pool_meta.get("leader_theme", ""),
        "switched_in": pool_meta.get("switched_in", []),
        "hot_sectors": pool_meta.get("hot_sectors", pool_meta.get("mainlines", sector_data.get("hot_sectors", []))),
        "total_scored": len(scored),
        "top_picks": merged[:top_n],
        "buy_picks": buy_picks,
        "watchlist": watchlist,
        "buy_actions": buy_actions,
        "stop_actions": stop_actions,
        "account_value": round(acct.get_total_value(current_prices), 2),
        "paper_buys": paper_buys,
        "strategy_results_count": {k: len(v) for k, v in strategy_results.items()},
        "weight_allocation": {n: c for n, c in weight_alloc},
    }
    json_file = os.path.join(KB_DIR, f"daily_pick_{date}.json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(sanitize_for_json(report_json), f, ensure_ascii=False, indent=2)

    _progress(100, "完成")
    logger.info(f"报告已保存: {report_file}")
    return report_json


def _pick_evidence_lines(pick: Dict, scored_by_code: Dict) -> List[str]:
    """从因子数据生成个股证据链"""
    stock = scored_by_code.get(pick.get("code", ""), {})
    pv = stock.get("price_volume", {}) or {}
    fund = stock.get("fundamental", {}) or {}
    lines = []
    if pv:
        mom5 = pv.get("mom_5d", 0) or 0
        mom20 = pv.get("mom_20d", 0) or 0
        chg = pv.get("change_pct", 0) or 0
        vol_r = pv.get("vol_ratio", 1) or 1
        rsi = pv.get("rsi", 0) or 0
        gene = pv.get("limit_up_count_180d", 0) or 0
        lines.append(
            f"价量: 5日{mom5:+.1f}% | 20日{mom20:+.1f}% | 当日{chg:+.1f}% | 量比{vol_r:.2f} | RSI{rsi:.0f}"
        )
        if pv.get("has_limit_up_180d"):
            lines.append(f"涨停基因: 近180日 {gene} 次涨停 ✓")
        else:
            lines.append("涨停基因: 无 ✗")
        if pv.get("break_60d"):
            lines.append("形态: 60日新高")
        if pv.get("ma_bull"):
            lines.append("趋势: 多头排列")
    msg = stock.get("message_score")
    if msg is not None:
        lines.append(f"消息面: {msg:.0f}/100")
    ind = stock.get("industry") or fund.get("industry", "")
    if ind:
        lines.append(f"行业: {ind}")
    dl = pick.get("dl_score") or stock.get("dl_score")
    if dl is not None:
        lines.append(f"DL因子: {float(dl):.3f}")
    return lines


def generate_report(date, market_overview, sector_data, capital_data,
                    merged, stop_actions, buy_actions, account,
                    current_prices, total_scored, total_pool,
                    buy_picks=None, watchlist=None, strategy_results=None,
                    weight_allocation=None, scored_by_code=None) -> str:
    """生成Markdown报告"""
    from strategies_v2.trade_config import BUY_WEIGHTS, AGGRESSIVE_RULES

    buy_picks = buy_picks or merged or []
    watchlist = watchlist or []
    strategy_results = strategy_results or {}
    weight_allocation = weight_allocation or []
    scored_by_code = scored_by_code or {}

    from strategies_v2.manager import StrategyManager
    strat_meta = {n: m.metadata for n, m in StrategyManager().strategies.items()}

    lines = []
    lines.append("# 📊 A股量化选股日报")
    lines.append(f"**日期**: {date}")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("**策略架构**: 8策略全部启用独立跟踪 | 组合=回测正收益策略 weight 合并")
    from strategies_v2.composite_config import load_composite_pool, load_benchmark_returns
    pool = load_composite_pool()
    returns = load_benchmark_returns()
    if pool:
        pool_desc = ", ".join(
            f"{strat_meta.get(s, {}).get('name', s)}({returns.get(s, 0):+.1f}%)"
            for s in pool
        )
        lines.append(f"**组合策略池**: {pool_desc}")
    if weight_allocation:
        alloc_parts = []
        for sid, cap in weight_allocation:
            meta = strat_meta.get(sid, {})
            alloc_parts.append(f"{meta.get('name', sid)}×{cap}(w{meta.get('weight', 1)})")
        lines.append(f"**组合权重配额**: {', '.join(alloc_parts)}")
    lines.append("")

    # 回测基准引用
    bench_path = os.path.join(BASE_DIR, "reports", "backtest_v2", "summary_benchmark.json")
    if os.path.isfile(bench_path):
        try:
            with open(bench_path, encoding="utf-8") as f:
                bench = json.load(f)
            for s in bench.get("strategies", []):
                if s.get("name") == "oversold_reversal":
                    lines.append(
                        f"**回测基准** (2024-2025 主线池): 总收益{s.get('return_pct', 0):+.1f}% | "
                        f"CAGR {s.get('cagr_pct', 0):+.1f}% | Sharpe {s.get('sharpe', 0):.2f} | "
                        f"胜率{s.get('win_rate', 0):.1f}% | 190笔"
                    )
                    break
            lines.append("")
        except Exception:
            pass

    # 市场概览
    lines.append("## 一、市场概览")
    lines.append("")

    indices = market_overview.get("indices", {})
    if indices:
        lines.append("| 指数 | 收盘 | 涨跌幅 | 趋势 |")
        lines.append("|------|------|--------|------|")
        for name, data in indices.items():
            arrow = "📈" if data["change_pct"] >= 0 else "📉"
            lines.append(f"| {name} | {data['close']} | {data['change_pct']:+.2f}% {arrow} | {data['trend']} |")
        lines.append("")

    sentiment = market_overview.get("sentiment", {})
    if sentiment:
        lines.append(f"**市场情绪**: {sentiment.get('sentiment_label', 'N/A')} (评分: {sentiment.get('sentiment_score', 0)}/100)")
        lines.append(f"上涨: {sentiment.get('up_count', 0)} | 下跌: {sentiment.get('down_count', 0)} | 涨停: {sentiment.get('limit_up', 0)} | 跌停: {sentiment.get('limit_down', 0)}")
        lines.append("")

    regime = market_overview.get("regime", "中性")
    suggestion = market_overview.get("suggestion", "")
    lines.append(f"**市场状态**: {regime}")
    lines.append(f"**操作建议**: {suggestion}")
    lines.append("")

    # 板块热点
    lines.append("## 二、板块与扫描池")
    lines.append("")
    hot_sectors = sector_data.get("hot_sectors", [])[:8]
    if hot_sectors:
        lines.append("| 板块 | 涨跌幅 | 领涨股 |")
        lines.append("|------|--------|--------|")
        for s in hot_sectors:
            chg = s.get("change_pct", s.get("mom20", s.get("mom60", 0)))
            lines.append(f"| {s.get('name', 'N/A')} | {chg:+.2f}% | {s.get('lead_stock', 'N/A')} |")
        lines.append("")

    hot_concepts = sector_data.get("hot_concepts", [])[:5]
    if hot_concepts:
        lines.append("**热门概念**: ")
        lines.append(", ".join(f"{c['name']}({c['change_pct']:+.2f}%)" for c in hot_concepts))
        lines.append("")

    pool_meta = sector_data.get("pool_meta") or {}
    if pool_meta.get("pool_mode") == "mainline":
        lines.append("### 主线主题扫描池 (季度主线 × 放量强势股)")
        lines.append("")
        kw = pool_meta.get("keywords") or []
        if kw:
            lines.append(f"**当日关键词**: {', '.join(kw)}")
        lt = pool_meta.get("leader_theme", "")
        if lt:
            lines.append(f"**领涨主线**: {lt}")
        sw = pool_meta.get("switched_in") or []
        if sw:
            lines.append(f"**新切换主线**: {', '.join(sw)}")
        lines.append("")
        for line in (pool_meta.get("mainlines") or [])[:8]:
            lines.append(
                f"- **{line.get('name', '')}** "
                f"60日{line.get('mom60', 0):+.1f}% | 20日{line.get('mom20', 0):+.1f}% | 量能{line.get('vol_trend', 0):.2f}x"
            )
        lines.append("")
        for sname, picks in (pool_meta.get("line_picks") or {}).items():
            if str(sname).startswith("_"):
                continue
            codes = ", ".join(
                f"{p['code']}(量{p.get('vol_surge', 0):.1f}x)" if p.get("vol_surge") else p["code"]
                for p in picks[:8]
            )
            lines.append(f"- **{sname}** ({len(picks)}只): {codes}")
        lines.append(f"\n合计候选: **{pool_meta.get('candidate_total', 0)}** 只 | 排除大盘蓝筹/银行")
        lines.append("")
    elif pool_meta.get("pool_mode") == "sector":
        lines.append("### 板块扫描池 (Top10板块 × 每板块Top10)")
        lines.append("")
        for sname, picks in (pool_meta.get("sector_picks") or {}).items():
            if str(sname).startswith("_"):
                continue
            codes = ", ".join(p["code"] for p in picks[:10])
            lines.append(f"- **{sname}** ({len(picks)}只): {codes}")
        lines.append(f"\n合计候选: **{pool_meta.get('candidate_total', 0)}** 只")
        lines.append("")

    north = capital_data.get("north_flow_5d", [])
    if north:
        lines.append(f"**北向资金** (近{len(north)}日): ")
        north_str = " | ".join(f"{n['date']}: {n['net_flow']:+.0f}" for n in north)
        lines.append(north_str)
        lines.append(f"趋势: {capital_data.get('north_trend', 'unknown')}")
        lines.append("")

    # 策略竞技
    lines.append("## 三、策略竞技")
    lines.append(f"股票池: {total_pool}只 | 因子评分: {total_scored}只")
    lines.append("")

    lines.append("### 各策略信号 (全部启用，独立纸面账户跟踪)")
    live_any = False
    for sname, picks in sorted(strategy_results.items()):
        meta = strat_meta.get(sname, {})
        if meta.get("enabled", True) is False:
            continue
        live_any = True
        label = meta.get("name", sname)
        w = meta.get("weight", 1.0)
        ce = "" if meta.get("composite_eligible", True) else " | 不进组合"
        lines.append(f"**[{label}]** w={w}{ce} — {len(picks)} 只信号")
        if not picks:
            lines.append("- 今日无符合条件的信号")
        else:
            for j, p in enumerate(picks[:5], 1):
                lines.append(
                    f"{j}. **{p['code']}** @ {p.get('price', 0)} | 分{p.get('strategy_score', 0)} | {p.get('reason', '')}"
                )
        lines.append("")

    if not live_any:
        lines.append("- 无启用策略")
        lines.append("")

    if not buy_picks:
        lines.append("> ⚠️ 实盘策略今日无强信号，组合账户不强行买入")
        lines.append("")

    # 组合买入计划
    sl = AGGRESSIVE_RULES.get("stop_loss", -0.08)
    tp = AGGRESSIVE_RULES.get("take_profit", 0.72)
    trail = AGGRESSIVE_RULES.get("trailing_stop", 0.12)
    max_hold = AGGRESSIVE_RULES.get("max_hold_days", 32)

    lines.append("## 四、组合买入计划 (实盘)")
    lines.append(
        f"规则: 硬止损{sl*100:.0f}% | 止盈{tp*100:.0f}% | 移动止盈{trail*100:.0f}% | 最长{max_hold}日 | 涨停继续持股"
    )
    lines.append(f"**今日买入**: {len(buy_picks)} 只 (目标最多5只)")
    lines.append("")

    if not buy_picks:
        lines.append("> 无强信号，今日空仓观望")
        lines.append("")
    else:
        for i, pick in enumerate(buy_picks[:5]):
            wt = BUY_WEIGHTS[i] if i < len(BUY_WEIGHTS) else BUY_WEIGHTS[-1]
            sname = pick.get("strategy_name") or pick.get("strategy_id", "")
            lines.append(f"### {i+1}. {pick['code']} @ {pick.get('price', 0)} — 仓位{wt*100:.0f}%")
            lines.append(f"- **策略**: {sname}")
            lines.append(f"- **得分**: {pick.get('strategy_score', 0)} | 覆盖策略: {pick.get('coverage', 1)}个")
            lines.append(f"- **买入逻辑**: {pick.get('reason', 'N/A')}")
            for ev in _pick_evidence_lines(pick, scored_by_code):
                lines.append(f"- {ev}")
            lines.append("")

    # 因子观察 (非买入)
    if watchlist:
        lines.append("## 五、因子观察名单 (仅供参考，不自动买入)")
        lines.append("")
        for i, pick in enumerate(watchlist[:5], 1):
            lines.append(f"{i}. **{pick['code']}** @ {pick.get('price', 0)} | {pick.get('reason', '')}")
        lines.append("")

    section_trade = "六" if watchlist else "五"
    section_acct = "七" if watchlist else "六"

    # 交易记录
    if stop_actions or buy_actions:
        lines.append(f"## {section_trade}、交易记录")
        lines.append("")
        if stop_actions:
            lines.append("### 自动卖出")
            for sa in stop_actions:
                lines.append(f"- {sa['code']} @ {sa['price']}: {sa.get('reason', '')} (盈亏: {sa.get('profit_pct', 0):+.1f}%)")
            lines.append("")
        if buy_actions:
            lines.append("### 自动买入")
            for ba in buy_actions:
                lines.append(f"- {ba['code']} @ {ba['price']} x {ba['shares']}股 = {ba['amount']:.0f}元")
            lines.append("")

    # 账户状态
    lines.append(f"## {section_acct}、账户状态")
    lines.append("")
    total_value = account.get_total_value(current_prices)
    lines.append(f"- **现金**: {account.cash:,.2f}元")
    lines.append(f"- **持仓市值**: {total_value - account.cash:,.2f}元")
    lines.append(f"- **总资产**: {total_value:,.2f}元")
    lines.append(f"- **总盈亏**: {account.total_profit:+,.2f}元")
    lines.append(f"- **总收益率**: {account.total_profit / 100000 * 100:+.2f}%")
    lines.append(f"- **持仓数**: {len(account.positions)}/5")
    lines.append("")

    positions = account.get_positions_summary(current_prices)
    if positions:
        lines.append("| 代码 | 持仓 | 成本 | 现价 | 盈亏 | 持仓天数 |")
        lines.append("|------|------|------|------|------|----------|")
        for p in positions:
            lines.append(f"| {p['code']} | {p['shares']}股 | {p['avg_price']:.2f} | {p['current_price']:.2f} | {p['profit_pct']:+.1f}% | {p['hold_days']}天 |")
        lines.append("")

    lines.append("---")
    lines.append("*本报告由AI量化系统自动生成，仅供参考，不构成投资建议。*")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="全局选股器")
    parser.add_argument("--date", default=None, help="日期 (YYYY-MM-DD)")
    parser.add_argument("--top", type=int, default=10, help="输出Top N")
    parser.add_argument("--min-score", type=int, default=45, help="最低综合分")
    args = parser.parse_args()

    result = run_picker(
        date=args.date,
        top_n=args.top,
        min_score=args.min_score,
    )

    # 终端输出摘要
    print(f"\n{'='*50}")
    print(f"选股完成: {result['date']}")
    print(f"股票池: {result['total_pool']} | 评分: {result['total_scored']}")
    print(f"总资产: {result['account_value']:,.2f}元")
    print(f"\nTop 10 推荐:")
    for i, pick in enumerate(result["top_picks"][:10]):
        print(f"  #{i+1} {pick['code']} @ {pick['price']} 得分={pick.get('final_score', pick.get('total_score', 0))}")
    if result.get("buy_actions"):
        print(f"\n买入:")
        for ba in result["buy_actions"]:
            print(f"  {ba['code']} @ {ba['price']} x {ba['shares']}股")
    if result.get("stop_actions"):
        print(f"\n卖出:")
        for sa in result["stop_actions"]:
            print(f"  {sa['code']} @ {sa['price']} 盈亏={sa.get('profit_pct', 0):+.1f}%")
