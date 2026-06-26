"""
A股数据获取模块
基于AKShare，提供股票行情、技术指标、板块轮动等数据
"""

import akshare as ak
import pandas as pd
import numpy as np
import os
import json
import time
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)


class AStockData:
    """A股数据获取器"""
    
    def __init__(self):
        self.stock_list_cache = None
        self.stock_list_time = None
        
    def get_stock_list(self, refresh=False):
        """
        获取A股股票列表
        过滤掉科创板、北交所、ST股
        """
        if not refresh and self.stock_list_cache is not None:
            return self.stock_list_cache
        
        df = None
        for attempt in range(5):
            try:
                # 获取A股列表
                logger.info(f"获取股票列表(尝试{attempt+1}/5)...")
                df = ak.stock_zh_a_spot_em()
                if df is not None and not df.empty:
                    logger.info(f"成功获取 {len(df)} 只股票")
                    break
            except Exception as e:
                wait_time = 3 * (attempt + 1)
                logger.warning(f"获取股票列表失败(尝试{attempt+1}/5): {e}, {wait_time}秒后重试")
                time.sleep(wait_time)
        
        if df is None or df.empty:
            logger.error("获取股票列表失败，所有重试均失败")
            return pd.DataFrame()
        
        # 过滤条件
        # 排除科创板(688/689开头)、北交所(83/87/43开头)
        def is_excluded(code):
            if code.startswith(('688', '689')):
                return True
            # 北交所: 83xxxx, 87xxxx, 43xxxx
            if len(code) == 6 and code[:2] in ('83', '87', '43'):
                return True
            return False
        
        mask = df['代码'].apply(lambda x: not is_excluded(x))
        # 排除ST股
        if '名称' in df.columns:
            mask &= df['名称'].apply(lambda x: 'ST' not in str(x) and 'st' not in str(x))
        
        df = df[mask].copy()
        
        # 标准化列名
        df['code'] = df['代码']
        df['name'] = df['名称']
        df['price'] = df['最新价']
        df['change_pct'] = df['涨跌幅']
        df['volume'] = df['成交量']
        df['amount'] = df['成交额']
        df['turnover'] = df['换手率']
        
        self.stock_list_cache = df
        self.stock_list_time = datetime.now()
        
        return df
    
    def get_daily_kline(self, stock_code, days=120):
        """
        获取个股日线数据
        """
        try:
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days*2)).strftime('%Y%m%d')
            
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"  # 前复权
            )
            
            if df.empty:
                return pd.DataFrame()
            
            df['日期'] = pd.to_datetime(df['日期'])
            df = df.sort_values('日期').tail(days).reset_index(drop=True)
            
            return df
            
        except Exception as e:
            logger.error(f"获取{stock_code}K线失败: {e}")
            return pd.DataFrame()
    
    def get_market_index(self):
        """获取主要指数行情"""
        try:
            indices = {
                '上证指数': 'sh000001',
                '深证成指': 'sz399001',
                '创业板指': 'sz399006',
                '沪深300': 'sh000300'
            }
            
            result = {}
            for name, code in indices.items():
                try:
                    df = ak.stock_zh_index_daily_em(symbol=code)
                    if df.empty or len(df) < 2:
                        continue
                    latest = df.iloc[-1]
                    prev = df.iloc[-2]
                    close_col = 'close' if 'close' in df.columns else '收盘'
                    close = float(latest.get(close_col, 0))
                    prev_close = float(prev.get(close_col, 0))
                    change_pct = (close / prev_close - 1) * 100 if prev_close > 0 else 0
                    result[name] = {
                        'close': close,
                        'change_pct': round(change_pct, 2)
                    }
                except:
                    pass
            
            return result
            
        except Exception as e:
            logger.error(f"获取指数行情失败: {e}")
            return {}
    
    def get_sector_data(self):
        """获取行业板块数据"""
        try:
            df = ak.stock_board_industry_name_em()
            
            # 获取板块涨跌幅排行
            df = df.sort_values('涨跌幅', ascending=False)
            
            top_gainers = df.head(10)[['板块名称', '涨跌幅', '总市值', '领涨股票']].to_dict('records')
            top_losers = df.tail(10)[['板块名称', '涨跌幅', '总市值', '领涨股票']].to_dict('records')
            
            return {
                'top_gainers': top_gainers,
                'top_losers': top_losers
            }
            
        except Exception as e:
            logger.error(f"获取板块数据失败: {e}")
            return {'top_gainers': [], 'top_losers': []}
    
    def get_concept_data(self):
        """获取概念板块数据"""
        try:
            df = ak.stock_board_concept_name_em()
            
            # 获取热点概念
            df = df.sort_values('涨跌幅', ascending=False)
            top_concepts = df.head(10)[['板块名称', '涨跌幅', '总市值', '领涨股票']].to_dict('records')
            
            return top_concepts
            
        except Exception as e:
            logger.error(f"获取概念板块失败: {e}")
            return []
    
    def get_north_flow(self):
        """获取北向资金流向"""
        try:
            df = ak.stock_hsgt_fund_flow_summary_em()
            if df.empty:
                return []
            
            # Filter for north flow (北向)
            north = df[df['资金方向'] == '北向'].tail(5).copy()
            if north.empty:
                return []
            
            north['日期'] = pd.to_datetime(north['交易日']).dt.strftime('%Y-%m-%d')
            result = []
            for _, row in north.iterrows():
                result.append({
                    '日期': row['日期'],
                    '板块': row['板块'],
                    '成交净买额': float(row['成交净买额']),
                    '资金净流入': float(row['资金净流入']),
                    '相关指数': row['相关指数'],
                    '指数涨跌幅': float(row['指数涨跌幅'])
                })
            return result
        except Exception as e:
            logger.error(f"获取北向资金失败: {e}")
            return []
    
    def get_stock_fundamentals(self, stock_code):
        """获取个股基本面数据"""
        try:
            # 获取个股信息
            df = ak.stock_individual_info_em(symbol=stock_code)
            
            info = {}
            for _, row in df.iterrows():
                key = row.get('item', row.get('key', ''))
                val = row.get('value', row.get('value', ''))
                info[key] = val
            
            return info
            
        except Exception as e:
            logger.error(f"获取{stock_code}基本面失败: {e}")
            return {}
    
    def get_stock_financial(self, stock_code):
        """获取个股财务数据"""
        try:
            df = ak.stock_financial_report_sina(stock=stock_code, symbol="每股指标")
            if not df.empty:
                latest = df.iloc[0]
                return {
                    'eps': latest.get('每股收益', 0),
                    'bps': latest.get('每股净资产', 0),
                    'ops': latest.get('每股经营现金流', 0)
                }
            return {}
        except Exception as e:
            logger.error(f"获取{stock_code}财务数据失败: {e}")
            return {}
    
    def save_market_snapshot(self):
        """保存市场快照到文件"""
        snapshot = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'market_index': self.get_market_index(),
            'sector': self.get_sector_data(),
            'concept': self.get_concept_data(),
            'north_flow': self.get_north_flow()
        }
        
        filepath = os.path.join(DATA_DIR, f"market_{datetime.now().strftime('%Y%m%d')}.json")
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False, default=str)
        
        return snapshot
    
    def get_hot_stocks(self, top_n=20):
        """获取热门股票（按成交额排序）"""
        df = self.get_stock_list()
        if df.empty:
            return pd.DataFrame()
        
        # 按成交额排序，取前N只
        hot = df.nlargest(top_n, 'amount')[['code', 'name', 'price', 'change_pct', 'volume', 'amount', 'turnover']]
        return hot


def calculate_technical_indicators(df):
    """
    计算技术指标
    输入：K线DataFrame
    返回：添加指标后的DataFrame
    """
    if df.empty or len(df) < 30:
        return df
    
    df = df.copy()
    
    # 移动平均线
    df['MA5'] = df['收盘'].rolling(5).mean()
    df['MA10'] = df['收盘'].rolling(10).mean()
    df['MA20'] = df['收盘'].rolling(20).mean()
    df['MA60'] = df['收盘'].rolling(60).mean()
    
    # MACD
    ema12 = df['收盘'].ewm(span=12).mean()
    ema26 = df['收盘'].ewm(span=26).mean()
    df['MACD_DIF'] = ema12 - ema26
    df['MACD_DEA'] = df['MACD_DIF'].ewm(span=9).mean()
    df['MACD_HIST'] = 2 * (df['MACD_DIF'] - df['MACD_DEA'])
    
    # RSI
    delta = df['收盘'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.inf)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 布林带
    df['BOLL_MID'] = df['收盘'].rolling(20).mean()
    boll_std = df['收盘'].rolling(20).std()
    df['BOLL_UP'] = df['BOLL_MID'] + 2 * boll_std
    df['BOLL_DOWN'] = df['BOLL_MID'] - 2 * boll_std
    
    # 成交量均线
    df['VOL_MA5'] = df['成交量'].rolling(5).mean()
    df['VOL_MA20'] = df['成交量'].rolling(20).mean()
    
    # 成交量异动比
    df['VOL_RATIO'] = df['成交量'] / df['VOL_MA5'].replace(0, np.inf)
    
    return df


def get_stock_score(stock_code, data_fetcher, stock_name=None):
    """
    对单只股票进行综合评分
    返回：评分字典
    """
    try:
        df = data_fetcher.get_daily_kline(stock_code, days=120)
        if df.empty or len(df) < 30:
            return None
        
        df = calculate_technical_indicators(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 如果没有传名字，从 stock_list 获取
        if stock_name is None:
            try:
                stock_list = data_fetcher.get_stock_list()
                name_row = stock_list[stock_list['code'] == stock_code]
                if not name_row.empty:
                    stock_name = name_row.iloc[0].get('name', '')
            except:
                stock_name = ''
        
        score = {
            'code': stock_code,
            'name': stock_name,
            'price': latest['收盘'],
            'change_pct': latest['涨跌幅'],
            'technical_score': 0,
            'volume_score': 0,
            'momentum_score': 0,
            'total_score': 0,
            'signals': []
        }
        
        # 技术面评分 (0-40分)
        tech = 0
        # 均线多头排列
        if latest['MA5'] > latest['MA10'] > latest['MA20']:
            tech += 15
            score['signals'].append('均线多头排列')
        elif latest['MA5'] > latest['MA10']:
            tech += 8
        
        # MACD金叉
        if prev['MACD_DIF'] <= prev['MACD_DEA'] and latest['MACD_DIF'] > latest['MACD_DEA']:
            tech += 15
            score['signals'].append('MACD金叉')
        elif latest['MACD_DIF'] > latest['MACD_DEA']:
            tech += 8
        
        # RSI适中
        rsi = latest['RSI']
        if 40 < rsi < 60:
            tech += 10
            score['signals'].append(f'RSI适中({rsi:.1f})')
        elif rsi < 30:
            tech += 10
            score['signals'].append(f'RSI超卖({rsi:.1f})')
        elif rsi > 70:
            tech -= 5
            score['signals'].append(f'RSI超买({rsi:.1f})')
        
        # 布林带
        if latest['收盘'] > latest['BOLL_MID']:
            tech += 5
        elif latest['收盘'] < latest['BOLL_DOWN']:
            tech += 8
            score['signals'].append('触及布林下轨')
        
        score['technical_score'] = max(0, min(40, tech))
        
        # 成交量评分 (0-30分)
        vol_score = 0
        vol_ratio = latest.get('VOL_RATIO', 1)
        if vol_ratio > 2:
            vol_score += 15
            score['signals'].append(f'放量({vol_ratio:.1f}倍)')
        elif vol_ratio > 1.5:
            vol_score += 10
        
        # 换手率
        turnover = latest.get('换手率', 0)
        if 3 < turnover < 10:
            vol_score += 15
            score['signals'].append(f'活跃换手({turnover:.1f}%)')
        elif turnover > 10:
            vol_score += 10
        
        score['volume_score'] = max(0, min(30, vol_score))
        
        # 动量评分 (0-30分)
        mom_score = 0
        # 近期涨幅
        if len(df) >= 5:
            ret_5d = (latest['收盘'] / df.iloc[-5]['收盘'] - 1) * 100
            if 2 < ret_5d < 15:
                mom_score += 15
                score['signals'].append(f'5日涨{ret_5d:.1f}%')
            elif ret_5d > 15:
                mom_score += 5
                score['signals'].append(f'5日涨{ret_5d:.1f}%')
        
        # 突破前期高点
        if len(df) >= 20:
            high_20 = df.iloc[-20:]['最高'].max()
            if latest['收盘'] > high_20:
                mom_score += 15
                score['signals'].append('突破20日高点')
        
        score['momentum_score'] = max(0, min(30, mom_score))
        
        # 总分
        score['total_score'] = score['technical_score'] + score['volume_score'] + score['momentum_score']
        
        return score
        
    except Exception as e:
        logger.error(f"评分{stock_code}失败: {e}")
        return None


def scan_stocks(data_fetcher, top_n=20):
    """
    扫描全市场股票，返回评分最高的N只
    """
    stock_list = data_fetcher.get_stock_list()
    if stock_list.empty:
        return []
    
    scores = []
    total = len(stock_list)
    
    for i, (_, row) in enumerate(stock_list.iterrows()):
        if i % 100 == 0:
            print(f"  扫描进度: {i}/{total}")
        
        code = row['code']
        score = get_stock_score(code, data_fetcher, row.get('name', None))
        if score:
            scores.append(score)
        
        # 限速，避免请求过快
        if i % 50 == 0:
            time.sleep(0.5)
    
    # 按总分排序
    scores.sort(key=lambda x: x['total_score'], reverse=True)
    
    return scores[:top_n]


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("           A股数据获取模块测试")
    print("=" * 60)
    
    fetcher = AStockData()
    
    print("\n--- 获取热门股票 ---")
    hot = fetcher.get_hot_stocks(10)
    print(hot.to_string(index=False))
    
    print("\n--- 获取指数行情 ---")
    indices = fetcher.get_market_index()
    for name, data in indices.items():
        print(f"  {name}: {data}")
    
    print("\n--- 获取板块数据 ---")
    sectors = fetcher.get_sector_data()
    print("  涨幅前3板块:")
    for s in sectors['top_gainers'][:3]:
        print(f"    {s}")
    
    print("\n--- 获取北向资金 ---")
    north = fetcher.get_north_flow()
    for n in north[:3]:
        print(f"  {n}")
    
    print("\n--- 保存市场快照 ---")
    snapshot = fetcher.save_market_snapshot()
    print(f"  已保存，包含 {len(snapshot)} 个字段")
