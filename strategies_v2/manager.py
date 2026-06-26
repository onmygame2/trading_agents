"""
策略管理器 v2
加载和管理所有 v2 选股策略
"""
import os
import importlib
import logging

logger = logging.getLogger(__name__)

STRATEGIES_DIR = os.path.dirname(os.path.abspath(__file__))


def load_all_strategies():
    """加载所有策略模块"""
    strategies = {}
    for fname in os.listdir(STRATEGIES_DIR):
        if fname.endswith('.py') and fname not in ('__init__.py', 'manager.py', 'trade_config.py'):
            name = fname[:-3]
            try:
                mod = importlib.import_module(f'strategies_v2.{name}')
                if hasattr(mod, 'filter') and hasattr(mod, 'metadata'):
                    strategies[name] = mod
                    logger.info(f"Loaded strategy: {mod.metadata['name']} (weight={mod.metadata['weight']})")
            except Exception as e:
                logger.warning(f"Failed to load strategy {name}: {e}")
    return strategies


class StrategyManager:
    """策略管理器 - 运行多策略选股并合并信号"""

    def __init__(self):
        self.strategies = load_all_strategies()

    def run_all(self, scored_stocks: list, sector_data: dict = None,
                dl_scores: dict = None, market_ctx: dict = None) -> dict:
        """运行已启用策略；可选 DL 分数门控"""
        results = {}
        for name, mod in self.strategies.items():
            meta = mod.metadata
            if meta.get("enabled", True) is False:
                results[name] = []
                continue
            try:
                try:
                    picks = mod.filter(scored_stocks, sector_data, market_ctx=market_ctx) or []
                except TypeError:
                    picks = mod.filter(scored_stocks, sector_data) or []
                if dl_scores and meta.get("use_dl"):
                    from dl_factor_model import DLFactorSelector
                    sel = DLFactorSelector()
                    picks = sel.apply_to_picks(
                        picks, dl_scores,
                        min_dl=meta.get("min_dl_score", 0.5),
                        boost=meta.get("dl_boost", 15.0),
                    )
                results[name] = picks
                logger.info(f"Strategy {meta['name']}: {len(picks)} picks")
            except Exception as e:
                logger.warning(f"Strategy {name} failed: {e}")
                results[name] = []
        return results

    def run_arena(self, scored_stocks: list, sector_data: dict = None,
                  dl_scores: dict = None, market_ctx: dict = None) -> dict:
        """运行全部策略（含未启用），仅供日报竞技展示/纸面对比"""
        results = {}
        for name, mod in self.strategies.items():
            try:
                try:
                    picks = mod.filter(scored_stocks, sector_data, market_ctx=market_ctx) or []
                except TypeError:
                    picks = mod.filter(scored_stocks, sector_data) or []
                results[name] = picks
            except Exception as e:
                logger.debug(f"Arena {name} failed: {e}")
                results[name] = []
        return results

    def merge_signals(self, strategy_results: dict, top_n: int = 20) -> list:
        """合并策略信号 (加权 + 多策略覆盖加分)"""
        merged_map = {}
        for sname, picks in strategy_results.items():
            mod = self.strategies.get(sname)
            if mod and mod.metadata.get("enabled", True) is False:
                continue
            if mod and mod.metadata.get("composite_eligible", True) is False:
                continue
            from strategies_v2.composite_config import load_composite_pool
            if sname not in load_composite_pool():
                continue
            weight = mod.metadata.get('weight', 1.0) if mod else 1.0
            for pick in picks:
                code = pick['code']
                if code not in merged_map:
                    merged_map[code] = {
                        'code': code,
                        'price': pick.get('price', 0),
                        'strategies': {},
                        'final_score': 0,
                        'coverage': 0,
                        'reason': '',
                        'stop_loss': pick.get('stop_loss', 0),
                        'take_profit': pick.get('take_profit', 0),
                        'confidence': pick.get('confidence', 0),
                    }
                merged_map[code]['strategies'][sname] = pick
                merged_map[code]['final_score'] += pick.get('strategy_score', 60) * weight
                merged_map[code]['coverage'] += 1

        for info in merged_map.values():
            cov = info['coverage']
            info['final_score'] = round(info['final_score'] + cov * 6, 1)
            confs = [s.get('confidence', 0) for s in info['strategies'].values()]
            info['confidence'] = min(95, int(max(confs) * 0.85 + cov * 3))
            names = []
            for sn, sp in info['strategies'].items():
                mod = self.strategies.get(sn)
                names.append(mod.metadata.get('name', sn) if mod else sn)
            info['reason'] = ' | '.join(
                s.get('reason', '') for s in info['strategies'].values()
            )[:120]
            info['strategy_name'] = '+'.join(names[:2])
            info['pick_mode'] = 'alpha_signal'
            info['strategy_score'] = int(info['final_score'])

        merged_list = sorted(merged_map.values(), key=lambda x: x['final_score'], reverse=True)
        return merged_list[:top_n]

    def weight_allocation(self, total: int = 5) -> list:
        """按 metadata.weight 计算配额；仅回测正收益策略进组合"""
        from strategies_v2.composite_config import load_composite_pool
        composite_pool = set(load_composite_pool())
        eligible = []
        for name, mod in self.strategies.items():
            meta = mod.metadata
            if meta.get("enabled", True) is False:
                continue
            if meta.get("composite_eligible", True) is False:
                continue
            if name not in composite_pool:
                continue
            eligible.append((name, float(meta.get("weight", 1.0))))
        if not eligible:
            return []
        tw = sum(w for _, w in eligible)
        raw = {n: w / tw * total for n, w in eligible}
        slots = {n: int(v) for n, v in raw.items()}
        assigned = sum(slots.values())
        order = sorted(raw.keys(), key=lambda n: -(raw[n] - slots[n]))
        i = 0
        while assigned < total:
            slots[order[i % len(order)]] += 1
            assigned += 1
            i += 1
        while assigned > total:
            n = min(slots, key=lambda k: (slots[k], -raw[k]))
            if slots[n] <= 0:
                break
            slots[n] -= 1
            assigned -= 1
        return [(n, c) for n, c in slots.items() if c > 0]

    def flatten_picks(self, strategy_results: dict, top_n: int = 10, enabled_only: bool = True) -> list:
        """各策略扁平竞技 — 同股取最高 strategy_score"""
        best_by_code = {}
        for sname, picks in strategy_results.items():
            mod = self.strategies.get(sname)
            if enabled_only and mod and mod.metadata.get("enabled", True) is False:
                continue
            display = mod.metadata.get("name", sname) if mod else sname
            for pick in picks:
                code = pick["code"]
                score = pick.get("strategy_score", 0)
                item = {
                    "code": code,
                    "price": pick.get("price", 0),
                    "strategy_score": score,
                    "final_score": score,
                    "strategy_id": sname,
                    "strategy_name": display,
                    "strategies": {sname: pick},
                    "coverage": 1,
                    "reason": pick.get("reason", ""),
                    "confidence": pick.get("confidence", 0),
                    "dl_score": pick.get("dl_score"),
                    "stop_loss": pick.get("stop_loss", 0),
                    "take_profit": pick.get("take_profit", 0),
                }
                if code not in best_by_code or score > best_by_code[code]["strategy_score"]:
                    best_by_code[code] = item

        ranked = sorted(best_by_code.values(), key=lambda x: x["strategy_score"], reverse=True)
        return ranked[:top_n]

    def build_composite_picks(
        self,
        strategy_results: dict,
        total: int = 5,
        min_score: int = 55,
        allocation: list = None,
    ) -> list:
        """按 weight 配额合并各策略信号；同股多策略命中优先"""
        if allocation is None:
            allocation = self.weight_allocation(total)

        out = []
        seen = set()

        def _append(sname: str, pick: dict, final_score: float = None):
            code = pick["code"]
            mod = self.strategies.get(sname)
            display = mod.metadata.get("name", sname) if mod else sname
            fs = final_score if final_score is not None else pick.get("strategy_score", 0)
            if code in seen:
                for item in out:
                    if item["code"] != code:
                        continue
                    item["strategies"][sname] = dict(pick)
                    item["coverage"] = len(item["strategies"])
                    if fs > item.get("final_score", 0):
                        item["final_score"] = fs
                        item["strategy_score"] = int(fs)
                    return
                return
            out.append({
                "code": code,
                "price": pick.get("price", 0),
                "strategy_score": int(fs),
                "final_score": fs,
                "strategy_id": sname,
                "strategy_name": display,
                "strategies": {sname: dict(pick)},
                "coverage": 1,
                "reason": pick.get("reason", ""),
                "confidence": pick.get("confidence", 0),
                "pick_mode": "alpha_signal",
            })
            seen.add(code)

        # 优先：多策略加权合并分高的股票
        for item in self.merge_signals(strategy_results, top_n=total * 3):
            if item.get("final_score", 0) < min_score:
                continue
            primary = max(
                item["strategies"].items(),
                key=lambda x: x[1].get("strategy_score", 0),
            )
            _append(primary[0], primary[1], item.get("final_score"))

        if len(out) >= total:
            out.sort(key=lambda x: x.get("final_score", 0), reverse=True)
            return out[:total]

        # 补足：按 weight 配额从各策略取 Top
        for sname, cap in allocation:
            mod = self.strategies.get(sname)
            if not mod or mod.metadata.get("enabled", True) is False:
                continue
            picks = sorted(
                strategy_results.get(sname, []),
                key=lambda x: x.get("strategy_score", 0), reverse=True,
            )
            picks = [p for p in picks if p.get("strategy_score", 0) >= min_score]
            taken = sum(1 for x in out if sname in x.get("strategies", {}))
            for p in picks:
                if taken >= cap or len(out) >= total:
                    break
                if p["code"] in seen:
                    continue
                before = len(out)
                _append(sname, p)
                if len(out) > before:
                    taken += 1

        out.sort(key=lambda x: x.get("final_score", 0), reverse=True)
        return out[:total]


def get_strategy_modules():
    return load_all_strategies()


def get_strategy_names():
    return [mod.metadata['name'] for mod in load_all_strategies().values()]
