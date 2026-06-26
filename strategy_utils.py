"""
策略工具函数 - 供主程序和模块共享
"""
import importlib

STRATEGY_MAP = {
    'trend_following': 'TrendFollowingStrategy',
    'mean_reversion': 'MeanReversionStrategy',
    'momentum_breakout': 'MomentumBreakoutStrategy',
    'multi_factor': 'MultiFactorStrategy',
    'volume_price': 'VolumePriceStrategy',
    'oversold_bounce': 'OversoldBounceStrategy',
    'dragon_return': 'DragonReturnStrategy',
    'grid_trading': 'GridTradingStrategy',
    'sector_rotation': 'SectorRotationStrategy',
    'closing_strategy': 'ClosingStrategy',
}


def get_strategy_class(strategy_name):
    """根据策略名称获取策略类"""
    class_name = STRATEGY_MAP.get(strategy_name)
    if not class_name:
        return None
    import importlib
    module = importlib.import_module(f'strategies.{strategy_name}')
    return getattr(module, class_name, None)


def get_strategy_config(config, strategy_name):
    """从配置中获取策略配置"""
    strats = config.get('strategies', {})
    if isinstance(strats, dict):
        s = strats.get(strategy_name, {})
        return s if isinstance(s, dict) else {}
    elif isinstance(strats, list):
        for s in strats:
            if isinstance(s, dict) and s.get('name') == strategy_name:
                return s
    return {}
