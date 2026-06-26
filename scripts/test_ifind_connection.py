#!/usr/bin/env python3
"""
iFind HTTP API 连通性测试

用法:
    export IFIND_REFRESH_TOKEN='...'   # 或写入 .env
    python scripts/test_ifind_connection.py

验收: 输出 600519/000001 实时价 + 上证指数
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from market_data import load_env_file, get_market_data_provider, get_provider_name, get_data_config


def main():
    load_env_file()
    token = os.environ.get('IFIND_REFRESH_TOKEN', '')
    configured = get_data_config().get('provider', 'sina')
    provider = get_market_data_provider()
    active = get_provider_name()

    print('=' * 50)
    print(f'Provider 配置: {configured}')
    print(f'Provider 实际: {active}')
    print(f'IFIND_REFRESH_TOKEN: {"已配置" if token else "未配置"}')
    print('=' * 50)

    test_codes = ['600519', '000001', '600000']
    print(f'\n实时行情 ({test_codes}):')
    df = provider.get_realtime_quotes(test_codes)
    if df.empty:
        print('  ❌ 未获取到数据 (检查 token 或网络)')
        return 1

    for _, row in df.iterrows():
        print(
            f"  {row['code']:>6}  "
            f"价={row['close']:.2f}  "
            f"涨跌={row.get('change_pct', 0):+.2f}%  "
            f"高={row.get('high', 0):.2f}  "
            f"低={row.get('low', 0):.2f}  "
            f"量={row.get('volume', 0):.0f}"
        )

    print('\n指数行情:')
    try:
        idx_df = provider.get_index_quotes()
        for _, row in idx_df.iterrows():
            print(f"  {row.get('name', row['code']):>8}  {row['close']:.2f}  {row.get('change_pct', 0):+.2f}%")
    except Exception as e:
        print(f'  指数获取失败: {e}')

    print('\n✅ 连通性测试完成')
    return 0


if __name__ == '__main__':
    sys.exit(main())
