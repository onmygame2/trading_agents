"""
A股数据获取模块 - BaoStock 版本

功能:
1. 获取股票池（主板+创业板，排除科创板/北交所/ST）
2. 获取个股日线K线（前复权）
3. 计算技术指标
4. 个股综合评分
5. 全市场扫描选股

用法:
    from baostock_fetcher import BaoStockFetcher
    fetcher = BaoStockFetcher()
    fetcher.login()
    stocks = fetcher.get_stock_pool()
    kline = fetcher.get_daily_kline('sh.600519', days=120)
    fetcher.logout()
"""

import os
import json
import time
import logging
import pandas as pd
import numpy as np
import baostock as bs
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)


class BaoStockFetcher:
    """BaoStock 数据获取器"""
    
    # 允许的股票前缀（含科创板，排除北交所）
    ALLOWED_PREFIXES = ('sh.600', 'sh.601', 'sh.603', 'sh.605', 'sh.688', 'sh.689',
                        'sz.000', 'sz.001', 'sz.002', 'sz.003',
                        'sz.300', 'sz.301')
    
    def __init__(self):
        self._stock_pool = None
        self._logged_in = False
    
    def login(self):
        """登录 BaoStock"""
        if self._logged_in:
            return
        lg = bs.login()
        if lg.error_code != '0':
            logger.error(f"BaoStock 登录失败: {lg.error_msg}")
            return
        self._logged_in = True
        logger.info("BaoStock 登录成功")
    
    def logout(self):
        """退出 BaoStock"""
        if self._logged_in:
            bs.logout()
            self._logged_in = False
            logger.info("BaoStock 已退出")
    
    def get_stock_pool(self, date=None, refresh=False):
        """
        获取A股股票池
        过滤：排除科创板、北交所、指数、基金、ST股
        
        返回: DataFrame with columns: code, code_name, trade_status
        """
        if not refresh and self._stock_pool is not None:
            return self._stock_pool
        
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        try:
            rs = bs.query_all_stock(day=date)
            if rs.error_code != '0':
                logger.error(f"获取股票列表失败: {rs.error_msg}")
                return pd.DataFrame()
            
            all_stocks = []
            while rs.error_code == '0' and rs.next():
                all_stocks.append(rs.get_row_data())
            
            if not all_stocks:
                return pd.DataFrame()
            
            df = pd.DataFrame(all_stocks, columns=rs.fields)
            
            # 过滤：只保留允许的前缀
            mask = df['code'].apply(lambda x: any(x.startswith(p) for p in self.ALLOWED_PREFIXES))
            df = df[mask].copy()
            
            # 排除ST股
            if 'code_name' in df.columns:
                df = df[~df['code_name'].str.contains('ST', case=False, na=False)]
            
            # 标准化代码格式（去掉 sh./sz. 前缀，变成纯数字）
            df['code'] = df['code'].str.replace('sh.', '').str.replace('sz.', '')
            df['name'] = df['code_name']
            
            self._stock_pool = df
            logger.info(f"股票池: {len(df)} 只 (基准日: {date})")
            return df
            
        except Exception as e:
            logger.error(f"获取股票池失败: {e}")
            return pd.DataFrame()
    
    def get_daily_kline(self, stock_code, days=120):
        """
        获取个股日线K线（前复权）
        
        参数:
            stock_code: 可以是 '600519' 或 'sh.600519'
            days: 获取最近N天
        
        返回: DataFrame with standard columns
        """
        if not self._logged_in:
            self.login()
        
        # 标准化代码格式
        if '.' not in stock_code:
            if stock_code.startswith('6'):
                stock_code = f'sh.{stock_code}'
            elif stock_code.startswith(('0', '2', '3')):
                stock_code = f'sz.{stock_code}'
        
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime('%Y-%m-%d')
        
        try:
            rs = bs.query_history_k_data_plus(
                stock_code,
                "date,code,open,high,low,close,volume,amount,turn,pctChg",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2"  # 前复权
            )
            
            if rs.error_code != '0':
                logger.error(f"获取K线失败 {stock_code}: {rs.error_msg}")
                return pd.DataFrame()
            
            data = []
            while rs.error_code == '0' and rs.next():
                data.append(rs.get_row_data())
            
            if not data:
                return pd.DataFrame()
            
            df = pd.DataFrame(data, columns=rs.fields)
            
            # 转换类型
            for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'pctChg']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            
            df = df.sort_values('date').tail(days).reset_index(drop=True)
            
            # 重命名为标准格式
            df = df.rename(columns={
                'code': 'stock_code',
                'pctChg': 'change_pct',
                'turn': 'turnover'
            })
            
            return df
            
        except Exception as e:
            logger.error(f"获取 {stock_code} K线失败: {e}")
            return pd.DataFrame()
    
    def get_stock_name(self, stock_code):
        """获取股票名称"""
        pool = self.get_stock_pool()
        if pool.empty:
            return ''
        row = pool[pool['code'] == stock_code]
        if row.empty:
            return ''
        return row.iloc[0]['name']
    
    def get_current_price(self, stock_code):
        """获取最新收盘价"""
        df = self.get_daily_kline(stock_code, days=5)
        if df.empty:
            return None
        return float(df.iloc[-1]['close'])
    
    def get_market_benchmark(self, index_code='sh.000001', days=30):
        """获取大盘指数走势"""
        if not self._logged_in:
            self.login()
        
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        try:
            rs = bs.query_history_k_data_plus(
                index_code,
                "date,close,volume",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="3"
            )
            
            if rs.error_code != '0':
                return pd.DataFrame()
            
            data = []
            while rs.error_code == '0' and rs.next():
                data.append(rs.get_row_data())
            
            if not data:
                return pd.DataFrame()
            
            df = pd.DataFrame(data, columns=rs.fields)
            for col in ['close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df['date'] = pd.to_datetime(df['date'])
            return df
            
        except Exception as e:
            logger.error(f"获取指数失败: {e}")
            return pd.DataFrame()
    
    def save_stock_pool_manifest(self, stock_pool=None):
        """保存股票池清单"""
        if stock_pool is None:
            stock_pool = self.get_stock_pool()
        
        if stock_pool.empty:
            return
        
        manifest_path = os.path.join(DATA_DIR, 'stock_pool.json')
        records = stock_pool[['code', 'name']].to_dict('records')
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        logger.info(f"股票池清单: {len(records)} 只 -> {manifest_path}")
    
    def get_top_stocks_by_amount(self, top_n=100, date=None):
        """
        获取最近交易日成交额最大的N只股票
        作为回测股票池
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        pool = self.get_stock_pool(date=date)
        if pool.empty:
            return pd.DataFrame()
        
        # 获取每只股票的最近成交额
        stocks_with_amount = []
        for _, row in pool.iterrows():
            code = row['code']
            kline = self.get_daily_kline(code, days=5)
            if not kline.empty:
                amount = float(kline.iloc[-1].get('amount', 0))
                close = float(kline.iloc[-1].get('close', 0))
                change = float(kline.iloc[-1].get('change_pct', 0))
                stocks_with_amount.append({
                    'code': code,
                    'name': row['name'],
                    'amount': amount,
                    'price': close,
                    'change_pct': change
                })
            
            time.sleep(0.1)  # 限速
        
        if not stocks_with_amount:
            return pd.DataFrame()
        
        df = pd.DataFrame(stocks_with_amount)
        df = df.sort_values('amount', ascending=False).head(top_n)
        return df.reset_index(drop=True)


def calculate_technical_indicators(df):
    """
    计算技术指标
    
    输入：K线DataFrame（标准格式）
    返回：添加指标后的DataFrame
    """
    if df.empty or len(df) < 30:
        return df
    
    df = df.copy()
    
    # 移动平均线
    df['MA5'] = df['close'].rolling(5).mean()
    df['MA10'] = df['close'].rolling(10).mean()
    df['MA20'] = df['close'].rolling(20).mean()
    df['MA60'] = df['close'].rolling(60).mean()
    
    # MACD
    ema12 = df['close'].ewm(span=12).mean()
    ema26 = df['close'].ewm(span=26).mean()
    df['MACD_DIF'] = ema12 - ema26
    df['MACD_DEA'] = df['MACD_DIF'].ewm(span=9).mean()
    df['MACD_HIST'] = 2 * (df['MACD_DIF'] - df['MACD_DEA'])
    
    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.inf)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 布林带
    df['BOLL_MID'] = df['close'].rolling(20).mean()
    boll_std = df['close'].rolling(20).std()
    df['BOLL_UP'] = df['BOLL_MID'] + 2 * boll_std
    df['BOLL_DOWN'] = df['BOLL_MID'] - 2 * boll_std
    
    # 成交量均线
    df['VOL_MA5'] = df['volume'].rolling(5).mean()
    df['VOL_MA20'] = df['volume'].rolling(20).mean()
    
    # 成交量异动比
    df['VOL_RATIO'] = df['volume'] / df['VOL_MA5'].replace(0, np.inf)
    
    # 波动率
    df['VOLATILITY_20'] = df['change_pct'].rolling(20).std()
    
    # 最高/最低20日
    df['HIGH_20'] = df['high'].rolling(20).max()
    df['LOW_20'] = df['low'].rolling(20).min()
    
    # 换手率均值
    df['TURN_MA5'] = df['turnover'].rolling(5).mean()
    df['TURN_MA20'] = df['turnover'].rolling(20).mean()
    
    return df


def get_stock_score(stock_code, fetcher, stock_name=None):
    """
    对单只股票进行综合评分（100分制）
    
    评分维度:
    - 技术面 (0-40分): 均线排列, MACD, RSI, 布林带
    - 成交量 (0-30分): 放量程度, 换手率
    - 动量 (0-30分): 近期涨幅, 突破新高
    
    返回: 评分字典
    """
    try:
        df = fetcher.get_daily_kline(stock_code, days=120)
        if df.empty or len(df) < 30:
            return None
        
        df = calculate_technical_indicators(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        if stock_name is None:
            stock_name = fetcher.get_stock_name(stock_code)
        
        score = {
            'code': stock_code,
            'name': stock_name,
            'price': round(float(latest['close']), 2),
            'change_pct': round(float(latest['change_pct']), 2),
            'technical_score': 0,
            'volume_score': 0,
            'momentum_score': 0,
            'total_score': 0,
            'signals': [],
            'indicators': {}
        }
        
        # ============ 技术面评分 (0-40分) ============
        tech = 0
        
        # 均线多头排列
        ma5 = latest['MA5']
        ma10 = latest['MA10']
        ma20 = latest['MA20']
        ma60 = latest['MA60']
        
        if ma5 > ma10 > ma20 > ma60:
            tech += 20
            score['signals'].append('均线完全多头')
        elif ma5 > ma10 > ma20:
            tech += 15
            score['signals'].append('均线多头排列')
        elif ma5 > ma10:
            tech += 8
            score['signals'].append('短期均线向上')
        elif ma5 < ma10 < ma20:
            tech -= 5
            score['signals'].append('均线空头排列')
        
        # MACD
        if prev['MACD_DIF'] <= prev['MACD_DEA'] and latest['MACD_DIF'] > latest['MACD_DEA']:
            tech += 15
            score['signals'].append('MACD金叉')
        elif latest['MACD_DIF'] > latest['MACD_DEA'] and latest['MACD_HIST'] > 0:
            tech += 8
            score['signals'].append('MACD红柱')
        elif latest['MACD_HIST'] > prev['MACD_HIST']:
            tech += 5
            score['signals'].append('MACD柱状放大')
        
        # RSI
        rsi = latest['RSI']
        if 40 < rsi < 60:
            tech += 8
            score['signals'].append(f'RSI中性({rsi:.0f})')
        elif rsi < 30:
            tech += 10
            score['signals'].append(f'RSI超卖({rsi:.0f})')
        elif rsi > 80:
            tech -= 8
            score['signals'].append(f'RSI超买({rsi:.0f})')
        
        # 布林带
        boll_pos = (latest['close'] - latest['BOLL_DOWN']) / (latest['BOLL_UP'] - latest['BOLL_DOWN'])
        if latest['close'] > latest['BOLL_MID'] and boll_pos < 0.8:
            tech += 5
        elif boll_pos < 0.1:
            tech += 8
            score['signals'].append('接近布林下轨')
        
        score['technical_score'] = max(0, min(40, tech))
        
        # ============ 成交量评分 (0-30分) ============
        vol_score = 0
        
        vol_ratio = latest.get('VOL_RATIO', 1)
        if vol_ratio > 3:
            vol_score += 15
            score['signals'].append(f'急剧放量({vol_ratio:.1f}x)')
        elif vol_ratio > 2:
            vol_score += 12
            score['signals'].append(f'显著放量({vol_ratio:.1f}x)')
        elif vol_ratio > 1.5:
            vol_score += 8
        elif vol_ratio < 0.5:
            vol_score += 3
            score['signals'].append('缩量整理')
        
        turnover = latest.get('turnover', 0)
        turn_ma20 = latest.get('TURN_MA20', 0)
        if 3 < turnover < 15 and turnover > turn_ma20 * 1.5:
            vol_score += 15
            score['signals'].append(f'换手活跃({turnover:.1f}%)')
        elif turnover > turn_ma20:
            vol_score += 8
        
        score['volume_score'] = max(0, min(30, vol_score))
        
        # ============ 动量评分 (0-30分) ============
        mom_score = 0
        
        if len(df) >= 5:
            ret_5d = (latest['close'] / df.iloc[-5]['close'] - 1) * 100
            if 3 < ret_5d < 20:
                mom_score += 15
                score['signals'].append(f'5日涨{ret_5d:.1f}%')
            elif ret_5d > 20:
                mom_score += 5
                score['signals'].append(f'5日涨{ret_5d:.1f}%过热')
            elif -10 < ret_5d < -3:
                mom_score += 5
                score['signals'].append(f'5日跌{abs(ret_5d):.1f}%回调')
        
        if len(df) >= 20:
            high_20 = df.iloc[-20:-1]['high'].max() if len(df) > 21 else df.iloc[-20]['high']
            if latest['close'] > high_20 * 1.01:
                mom_score += 15
                score['signals'].append('突破20日新高')
            
            low_20 = df.iloc[-20:-1]['low'].min() if len(df) > 21 else df.iloc[-20]['low']
            if latest['close'] < low_20 * 1.05:
                mom_score += 5
                score['signals'].append('接近20日低点')
        
        # 波动率适中
        volatility = latest.get('VOLATILITY_20', 999)
        if 1.5 < volatility < 4:
            mom_score += 5
            score['signals'].append(f'波动适中({volatility:.1f}%)')
        elif volatility > 6:
            mom_score -= 3
            score['signals'].append(f'波动剧烈({volatility:.1f}%)')
        
        score['momentum_score'] = max(0, min(30, mom_score))
        
        # 总分
        score['total_score'] = score['technical_score'] + score['volume_score'] + score['momentum_score']
        
        # 保存指标快照
        score['indicators'] = {
            'rsi': round(float(rsi), 2),
            'vol_ratio': round(float(vol_ratio), 2),
            'turnover': round(float(turnover), 2),
            'volatility': round(float(volatility), 2),
            'macd_hist': round(float(latest['MACD_HIST']), 4),
            'boll_pos': round(float(boll_pos), 3)
        }
        
        return score
        
    except Exception as e:
        logger.error(f"评分 {stock_code} 失败: {e}")
        return None


def scan_stocks(fetcher, top_n=10, stock_pool=None):
    """
    扫描股票池，返回评分最高的N只
    
    参数:
        fetcher: BaoStockFetcher 实例
        top_n: 返回Top N
        stock_pool: 股票池DataFrame。None则自动获取前100只按成交额
    
    返回: 评分列表
    """
    if stock_pool is None:
        pool = fetcher.get_stock_pool()
        if pool.empty:
            return []
        # 默认取前200只
        stock_pool = pool.head(200)
    
    scores = []
    total = len(stock_pool)
    
    for i, (_, row) in enumerate(stock_pool.iterrows()):
        code = str(row['code'])
        name = str(row.get('name', ''))
        
        if (i + 1) % 20 == 0:
            print(f"  扫描进度: {i+1}/{total}")
        
        score = get_stock_score(code, fetcher, name)
        if score:
            scores.append(score)
        
        time.sleep(0.1)  # 限速
    
    # 按总分排序
    scores.sort(key=lambda x: x['total_score'], reverse=True)
    
    print(f"\n  扫描完成! {len(scores)} 只有评分, 返回Top {top_n}")
    return scores[:top_n]


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    print("=" * 60)
    print("  BaoStock 数据模块测试")
    print("=" * 60)
    
    fetcher = BaoStockFetcher()
    fetcher.login()
    
    # 测试股票池
    print("\n--- 股票池 ---")
    pool = fetcher.get_stock_pool()
    print(f"  股票池: {len(pool)} 只")
    if not pool.empty:
        print(pool.head(5).to_string(index=False))
    
    # 测试K线
    print("\n--- K线测试 ---")
    kline = fetcher.get_daily_kline('600519', days=30)
    print(f"  茅台K线: {len(kline)} 条")
    if not kline.empty:
        print(kline.tail(3).to_string(index=False))
    
    # 测试评分
    print("\n--- 评分测试 ---")
    score = get_stock_score('600519', fetcher, '贵州茅台')
    if score:
        print(f"  茅台评分: {score['total_score']}")
        print(f"  信号: {', '.join(score['signals'])}")
    
    fetcher.logout()
    print("\n测试完成!")
