"""
市场状态追踪器

每日自动采集并记录市场状态到记忆系统。

功能:
- 从新浪API获取大盘指数
- 计算市场广度（上涨/下跌家数占比）
- 识别热点板块
- 判断市场情绪 (bullish/bearish/neutral)
- 记录到 TradingMemory
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core.memory import TradingMemory


def fetch_sina_indices() -> Dict:
    """从新浪API获取大盘指数"""
    import urllib.request

    # 指数代码: 上证50, 上证指数, 中证500, 创业板指, 沪深300, 深证成指
    symbols = [
        ('sh000016', '上证50'),
        ('sh000001', '上证指数'),
        ('sh000905', '中证500'),
        ('sz399006', '创业板指'),
        ('sh000300', '沪深300'),
        ('sz399001', '深证成指')
    ]

    indices = {}
    for code, name in symbols:
        url = f"http://hq.sinajs.cn/list={code}"
        try:
            req = urllib.request.Request(url, headers={
                'Referer': 'http://finance.sina.com.cn',
                'User-Agent': 'Mozilla/5.0'
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                text = resp.read().decode('gbk')
                if '=' in text and '"':
                    data = text.split('"')[1].split(',')
                    if len(data) > 3:
                        current = float(data[3])
                        prev_close = float(data[2])
                        change_pct = (current - prev_close) / prev_close * 100 if prev_close else 0
                        indices[name] = {
                            'price': current,
                            'change_pct': round(change_pct, 2)
                        }
        except Exception as e:
            print(f"  [WARN] Failed to fetch {name}: {e}")

    return indices


def fetch_hot_sectors() -> List[Dict]:
    """获取热点板块（基于行业涨跌幅）"""
    import urllib.request

    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount"
    
    sectors = []
    try:
        # 获取各个行业板块的股票数量
        for node in range(1, 41):  # 申万一级行业
            params = f"?page=1&num=40&sort=changepercent&asc=0&node={node}&_s_r_a=sort"
            full_url = url + params
            req = urllib.request.Request(full_url, headers={
                'Referer': 'http://finance.sina.com.cn',
                'User-Agent': 'Mozilla/5.0'
            })
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    text = resp.read().decode('utf-8')
                    if text.strip():
                        data = json.loads(text)
                        if data and isinstance(data, list):
                            # 计算平均涨跌幅
                            changes = []
                            for item in data:
                                try:
                                    chg = float(item.get('changepercent', 0))
                                    changes.append(chg)
                                except:
                                    pass
                            if changes:
                                # 获取板块名称
                                node_url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount?page=1&num=1&node={node}&_s_r_a=sort"
                                try:
                                    with urllib.request.urlopen(urllib.request.Request(node_url, headers={
                                        'Referer': 'http://finance.sina.com.cn',
                                        'User-Agent': 'Mozilla/5.0'
                                    }), timeout=5) as r2:
                                        name_data = json.loads(r2.read().decode('utf-8'))
                                        sector_name = name_data[0].get('name', f'行业{node}') if name_data else f'行业{node}'
                                except:
                                    sector_name = f'行业{node}'
                                
                                sectors.append({
                                    'industry': sector_name,
                                    'avg_change_pct': round(sum(changes) / len(changes), 2),
                                    'stock_count': len(changes)
                                })
                                time.sleep(0.1)  # Rate limit
            except:
                continue
    except Exception as e:
        print(f"  [WARN] Sector fetch failed: {e}")

    # Sort by avg_change_pct descending, return top 10
    sectors.sort(key=lambda x: x['avg_change_pct'], reverse=True)
    return sectors[:10]


def calculate_sentiment(indices: Dict, sectors: List[Dict]) -> str:
    """
    计算市场情绪
    
    规则:
    - bullish: 上证指数涨 > 0.5% 且 涨幅板块 > 70%
    - bearish: 上证指数跌 > 0.5% 且 跌幅板块 > 70%
    - neutral: 其他情况
    """
    sh_change = indices.get('上证指数', {}).get('change_pct', 0)
    
    if not sectors:
        if sh_change > 0.5:
            return 'bullish'
        elif sh_change < -0.5:
            return 'bearish'
        return 'neutral'
    
    # 板块涨跌比例
    up_sectors = sum(1 for s in sectors if s['avg_change_pct'] > 0)
    up_ratio = up_sectors / len(sectors) if sectors else 0.5
    
    if sh_change > 0.5 and up_ratio > 0.7:
        return 'bullish'
    elif sh_change < -0.5 and up_ratio < 0.3:
        return 'bearish'
    elif sh_change > 0.3 and up_ratio > 0.6:
        return 'bullish'
    elif sh_change < -0.3 and up_ratio < 0.4:
        return 'bearish'
    return 'neutral'


def track_market_state(date: str = None) -> Dict:
    """
    追踪并记录市场状态
    
    返回市场状态字典
    """
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 追踪市场状态: {date}")
    
    # 1. 获取指数
    print("  获取大盘指数...")
    indices = fetch_sina_indices()
    if not indices:
        print("  [WARN] 无法获取指数数据")
        return {}
    
    # 2. 获取热点板块
    print("  获取热点板块...")
    sectors = fetch_hot_sectors()
    
    # 3. 计算情绪
    sentiment = calculate_sentiment(indices, sectors)
    print(f"  市场情绪: {sentiment}")
    
    # 4. 构建市场状态
    state = {
        'date': date,
        'sh_index': indices.get('上证指数', {}).get('price'),
        'sh_change_pct': indices.get('上证指数', {}).get('change_pct'),
        'hs300': indices.get('沪深300', {}).get('price'),
        'hs300_change_pct': indices.get('沪深300', {}).get('change_pct'),
        'cyb': indices.get('创业板指', {}).get('price'),
        'cyb_change_pct': indices.get('创业板指', {}).get('change_pct'),
        'sentiment': sentiment,
        'hot_sectors': [{'industry': s['industry'], 'pct': s['avg_change_pct']} for s in sectors[:5]],
        'all_indices': indices,
        'source': 'live',
    }
    
    # 5. 记录到记忆系统
    mem = TradingMemory(db_path=os.path.join(BASE_DIR, 'knowledge_base', 'trading_memory.db'))
    mem.log_market_state(state)
    print("  市场状态已记录到记忆系统")
    
    return state


def main():
    """独立运行"""
    import argparse
    parser = argparse.ArgumentParser(description='市场状态追踪')
    parser.add_argument('--date', type=str, default=None)
    args = parser.parse_args()
    
    state = track_market_state(args.date)
    
    if state:
        print(f"\n市场状态: {json.dumps(state, ensure_ascii=False, indent=2)}")
    
    # 打印记忆系统概览
    mem = TradingMemory(db_path=os.path.join(BASE_DIR, 'knowledge_base', 'trading_memory.db'))
    summary = mem.get_memory_summary()
    print(f"\n记忆系统概览:")
    print(f"  信号数: {summary['signals']}")
    print(f"  市场快照: {summary['market_snapshots']}")
    print(f"  追踪策略: {summary['strategies_tracked']}")
    print(f"  经验教训: {summary['lessons']}")


if __name__ == '__main__':
    main()
