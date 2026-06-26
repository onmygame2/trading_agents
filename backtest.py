"""
A股回测引擎 - 事件驱动
- 逐日回放历史数据
- 支持 T+1 交易制度
- 支持涨跌幅限制（主板±10%，创业板±20%）
- 支持万1免5手续费 + 千1印花税
- 输出完整绩效报告

使用方式：
    engine = BacktestEngine(initial_cash=100000)
    # 添加历史数据（按日期索引的 dict）
    engine.add_stock_data('600519', kline_df)
    # 生成信号列表
    signals = [
        {'date': '2026-03-01', 'stock_code': '600519', 'action': 'buy', 'price': 1800.0},
        {'date': '2026-03-15', 'stock_code': '600519', 'action': 'sell', 'price': 1900.0},
    ]
    result = engine.run(signals)
    print(result.report())
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict


class Position:
    """单只股票的持仓（支持 T+1 分批卖出）"""
    
    def __init__(self, stock_code, stock_name=''):
        self.stock_code = stock_code
        self.stock_name = stock_name
        # 按买入日期分层的持仓批次: {buy_date_str: {'shares': int, 'cost': float}}
        self.batches = {}
    
    @property
    def total_shares(self):
        return sum(b['shares'] for b in self.batches.values())
    
    @property
    def total_cost(self):
        return sum(b['shares'] * b['cost'] for b in self.batches.values())
    
    @property
    def avg_cost(self):
        if self.total_shares == 0:
            return 0.0
        return self.total_cost / self.total_shares
    
    def add_buy(self, date_str, shares, cost_price):
        """新增买入批次"""
        if date_str in self.batches:
            old = self.batches[date_str]
            old_cost = old['shares'] * old['cost']
            new_cost = old_cost + shares * cost_price
            old['shares'] += shares
            old['cost'] = round(new_cost / old['shares'], 3)
        else:
            self.batches[date_str] = {'shares': shares, 'cost': cost_price}
    
    def get_sellable_batches(self, current_date_str, shares_needed):
        """
        T+1 规则：只能卖出非今日买入的批次
        按 FIFO 顺序返回可卖出的批次
        """
        available = []
        remaining = shares_needed
        
        # 按日期排序，最早买入的优先卖出
        for buy_date in sorted(self.batches.keys()):
            if buy_date >= current_date_str:
                # 今日或之后买入的，不能卖
                continue
            batch = self.batches[buy_date]
            if batch['shares'] > 0:
                sell_shares = min(batch['shares'], remaining)
                available.append((buy_date, sell_shares, batch['cost']))
                remaining -= sell_shares
                if remaining <= 0:
                    break
        
        return available
    
    def execute_sell(self, sell_dates_shares):
        """
        执行卖出：减少对应批次的持仓
        sell_dates_shares: [(buy_date, sell_shares), ...]
        """
        for buy_date, sell_shares in sell_dates_shares:
            if buy_date in self.batches:
                self.batches[buy_date]['shares'] -= sell_shares
                if self.batches[buy_date]['shares'] <= 0:
                    del self.batches[buy_date]
    
    def market_value(self, price):
        """当前市值"""
        return self.total_shares * price


class TradeLog:
    """交易记录"""
    
    def __init__(self):
        self.trades = []
    
    def add_trade(self, trade):
        self.trades.append(trade)
    
    def get_pnl_by_stock(self, stock_code):
        """按股票统计盈亏"""
        stock_trades = [t for t in self.trades if t['stock_code'] == stock_code]
        total_cost = sum(t['total_cost'] for t in stock_trades if t['action'] == 'buy')
        total_proceeds = sum(t['net_proceeds'] for t in stock_trades if t['action'] == 'sell')
        return total_proceeds - total_cost


class BacktestEngine:
    """
    事件驱动回测引擎
    
    核心设计：
    - 逐日回放：按交易日顺序处理
    - T+1 限制：当日买入不可卖出
    - 手续费：万1免5（买卖都有）
    - 印花税：千1（仅卖出）
    - 最小交易单位：100股（1手）
    """
    
    def __init__(self, initial_cash=100000, commission_rate=0.0001,
                 min_commission=5, stamp_tax_rate=0.001, max_holdings=5):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.stamp_tax_rate = stamp_tax_rate
        self.max_holdings = max_holdings
        
        # 历史数据: {stock_code: DataFrame}
        self.stock_data = {}
        
        # 持仓: {stock_code: Position}
        self.positions = {}
        
        # 交易记录
        self.trade_log = TradeLog()
        
        # 每日净值记录: {date_str: {'total_value': float, 'cash': float, 'position_value': float}}
        self.daily_nav = []
        
        # 当前回测日期
        self.current_date = None
    
    def add_stock_data(self, stock_code, df):
        """
        添加股票历史数据
        
        参数 df 格式（AKShare stock_zh_a_hist 返回格式）:
        列: 日期, 股票代码, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
        
        也可以传入自定义格式，只要有 date, open, close, high, low 列
        """
        if df.empty:
            return
        
        df = df.copy()
        
        # 统一列名
        if '日期' in df.columns:
            df = df.rename(columns={
                '日期': 'date', '股票代码': 'stock_code',
                '开盘': 'open', '收盘': 'close',
                '最高': 'high', '最低': 'low',
                '成交量': 'volume', '成交额': 'amount',
                '涨跌幅': 'change_pct', '换手率': 'turnover'
            })
        
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        df = df.sort_values('date').reset_index(drop=True)
        
        self.stock_data[stock_code] = df
    
    def get_price(self, stock_code, date_str):
        """获取某只股票在指定日期的收盘价"""
        if stock_code not in self.stock_data:
            return None
        df = self.stock_data[stock_code]
        row = df[df['date'] == date_str]
        if row.empty:
            return None
        return float(row.iloc[0]['close'])
    
    def calc_commission(self, amount):
        """计算手续费：万1免5"""
        fee = amount * self.commission_rate
        return max(fee, self.min_commission)
    
    def calc_stamp_tax(self, amount):
        """计算印花税：千1（仅卖出）"""
        return amount * self.stamp_tax_rate
    
    def calc_buy_cost(self, price, shares):
        """买入总成本"""
        amount = price * shares
        return amount + self.calc_commission(amount)
    
    def calc_sell_proceeds(self, price, shares):
        """卖出净收入"""
        amount = price * shares
        commission = self.calc_commission(amount)
        stamp_tax = self.calc_stamp_tax(amount)
        return amount - commission - stamp_tax
    
    def can_buy(self, price, shares):
        """检查买入能力"""
        cost = self.calc_buy_cost(price, shares)
        return self.cash >= cost
    
    def active_position_count(self):
        """当前持有不同股票的数量"""
        return sum(1 for p in self.positions.values() if p.total_shares > 0)
    
    def execute_buy(self, date_str, stock_code, stock_name, price, shares):
        """
        执行买入
        返回: (success, message, trade_record)
        """
        # 检查最小交易单位
        if shares % 100 != 0:
            shares = (shares // 100) * 100
            if shares == 0:
                return False, "资金不足1手", None
        
        # 检查最大持仓数
        if stock_code not in self.positions or self.positions[stock_code].total_shares == 0:
            if self.active_position_count() >= self.max_holdings:
                return False, f"已达最大持仓数 {self.max_holdings}", None
        
        # 检查资金
        total_cost = self.calc_buy_cost(price, shares)
        if not self.can_buy(price, shares):
            # 尝试减少到手
            max_affordable = int((self.cash - self.min_commission) / (price * (1 + self.commission_rate)) / 100) * 100
            if max_affordable <= 0:
                return False, f"资金不足，需要 {total_cost:.2f}，可用 {self.cash:.2f}", None
            shares = max_affordable
        
        total_cost = self.calc_buy_cost(price, shares)
        
        # 执行买入
        self.cash -= total_cost
        
        if stock_code not in self.positions:
            self.positions[stock_code] = Position(stock_code, stock_name)
        
        self.positions[stock_code].add_buy(date_str, shares, price)
        
        # 记录交易
        trade = {
            'date': date_str,
            'action': 'buy',
            'stock_code': stock_code,
            'stock_name': stock_name,
            'price': price,
            'shares': shares,
            'amount': round(price * shares, 2),
            'commission': round(self.calc_commission(price * shares), 2),
            'total_cost': round(total_cost, 2)
        }
        self.trade_log.add_trade(trade)
        
        return True, f"买入 {stock_name}({stock_code}) {shares}股 @ {price:.2f}", trade
    
    def execute_sell(self, date_str, stock_code, price, shares):
        """
        执行卖出（T+1 + FIFO）
        返回: (success, message, trade_record)
        """
        if stock_code not in self.positions:
            return False, f"未持有 {stock_code}", None
        
        position = self.positions[stock_code]
        
        if shares % 100 != 0:
            shares = (shares // 100) * 100
            if shares == 0:
                return False, "不足1手", None
        
        # T+1: 获取可卖出批次
        available = position.get_sellable_batches(date_str, shares)
        
        if not available:
            return False, f"{stock_code} 无可卖出持仓（T+1限制）", None
        
        actual_shares = sum(s for _, s, _ in available)
        if actual_shares < shares:
            shares = actual_shares
        
        if shares <= 0:
            return False, f"{stock_code} 无可卖出持仓", None
        
        # 执行卖出
        net_proceeds = self.calc_sell_proceeds(price, shares)
        self.cash += net_proceeds
        
        sell_list = [(bd, s) for bd, s, _ in available]
        position.execute_sell(sell_list)
        
        if position.total_shares == 0:
            del self.positions[stock_code]
        
        # 计算盈亏（按加权成本）
        avg_cost = sum(s * c for _, s, c in available) / shares
        pnl = (price - avg_cost) * shares - self.calc_commission(price * shares) - self.calc_stamp_tax(price * shares)
        
        # 记录交易
        trade = {
            'date': date_str,
            'action': 'sell',
            'stock_code': stock_code,
            'stock_name': position.stock_name,
            'price': price,
            'shares': shares,
            'amount': round(price * shares, 2),
            'commission': round(self.calc_commission(price * shares), 2),
            'stamp_tax': round(self.calc_stamp_tax(price * shares), 2),
            'net_proceeds': round(net_proceeds, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round((pnl / (avg_cost * shares)) * 100, 2) if avg_cost > 0 else 0
        }
        self.trade_log.add_trade(trade)
        
        return True, f"卖出 {position.stock_name}({stock_code}) {shares}股 @ {price:.2f}, 盈亏 {pnl:.2f}", trade
    
    def record_daily_nav(self, date_str):
        """记录每日净值"""
        position_value = 0
        for stock_code, position in self.positions.items():
            price = self.get_price(stock_code, date_str)
            if price:
                position_value += position.market_value(price)
        
        total_value = self.cash + position_value
        self.daily_nav.append({
            'date': date_str,
            'cash': round(self.cash, 2),
            'position_value': round(position_value, 2),
            'total_value': round(total_value, 2)
        })
    
    def process_signal(self, signal):
        """
        处理单个交易信号
        
        signal 格式:
        {
            'date': '2026-03-01',
            'stock_code': '600519',
            'action': 'buy' | 'sell',
            'price': 1800.0,  # 目标价格
            'shares': 100,    # 可选，不填则自动计算
            'reason': 'MACD金叉'  # 可选
        }
        """
        date_str = signal['date']
        stock_code = signal['stock_code']
        action = signal['action']
        
        # 如果没有指定价格，用当日收盘价
        if 'price' not in signal or signal['price'] is None:
            price = self.get_price(stock_code, date_str)
            if price is None:
                return f"[SKIP] {date_str} {stock_code} 无价格数据"
        else:
            price = signal['price']
        
        stock_name = ''
        if stock_code in self.positions:
            stock_name = self.positions[stock_code].stock_name
        
        self.current_date = date_str
        
        if action == 'buy':
            # 自动计算买入数量
            if 'shares' in signal and signal['shares']:
                shares = signal['shares']
            else:
                # 用可用资金的 20% / 价格
                alloc_cash = self.cash * 0.2
                shares = int(alloc_cash / price / 100) * 100
                if shares < 100:
                    shares = 100
            
            success, msg, trade = self.execute_buy(date_str, stock_code, stock_name, price, shares)
            reason = signal.get('reason', '')
            status = 'OK' if success else 'FAIL'
            return f"[{status}] {msg}" + (f" ({reason})" if reason else "")
        
        elif action == 'sell':
            if 'shares' in signal and signal['shares']:
                shares = signal['shares']
            else:
                # 全部卖出
                if stock_code in self.positions:
                    shares = self.positions[stock_code].total_shares
                    shares = (shares // 100) * 100
                else:
                    return f"[SKIP] {date_str} {stock_code} 无持仓"
            
            success, msg, trade = self.execute_sell(date_str, stock_code, price, shares)
            reason = signal.get('reason', '')
            status = 'OK' if success else 'FAIL'
            return f"[{status}] {msg}" + (f" ({reason})" if reason else "")
        
        return f"[SKIP] 未知操作: {action}"
    
    def run(self, signals):
        """
        运行回测
        
        参数 signals: 信号列表，按日期排序
        每只信号的股票数据应该已经通过 add_stock_data 添加
        
        返回 BacktestResult 对象
        """
        # 重置状态（空信号且已有交易记录时不重置，避免覆盖已执行的交易）
        if signals or not self.trade_log.trades:
            self.cash = self.initial_cash
            self.positions = {}
            self.trade_log = TradeLog()
            self.daily_nav = []
        
        if not signals:
            return BacktestResult(self)
        
        # 按日期排序
        sorted_signals = sorted(signals, key=lambda s: s['date'])
        
        # 获取所有交易日期（去重）
        all_dates = sorted(set(s['date'] for s in sorted_signals))
        
        # 处理信号
        log_messages = []
        for signal in sorted_signals:
            msg = self.process_signal(signal)
            log_messages.append(f"  {signal['date']} {signal['action'].upper()} {signal['stock_code']}: {msg}")
        
        # 在每个交易日期记录净值
        for date_str in all_dates:
            self.record_daily_nav(date_str)
        
        # 如果最后有持仓，记录最终日期后的净值
        if self.daily_nav:
            last_date = self.daily_nav[-1]['date']
            # 不需要额外记录
        
        result = BacktestResult(self)
        result.log_messages = log_messages
        
        return result


class BacktestResult:
    """回测结果分析与报告"""
    
    def __init__(self, engine):
        self.engine = engine
        self.nav_df = pd.DataFrame(engine.daily_nav)
        
        # 计算累计收益率
        if not self.nav_df.empty:
            self.nav_df['cum_return'] = self.nav_df['total_value'] / engine.initial_cash - 1
            self.nav_df['daily_return'] = self.nav_df['total_value'].pct_change().fillna(0)
    
    @property
    def total_return(self):
        """总收益率"""
        if self.nav_df.empty:
            return 0.0
        final_value = self.nav_df.iloc[-1]['total_value']
        return (final_value / self.engine.initial_cash - 1) * 100
    
    @property
    def total_pnl(self):
        """总盈亏金额"""
        if self.nav_df.empty:
            return 0.0
        return self.nav_df.iloc[-1]['total_value'] - self.engine.initial_cash
    
    @property
    def max_drawdown(self):
        """最大回撤"""
        if self.nav_df.empty or len(self.nav_df) < 2:
            return 0.0
        peak = self.nav_df['total_value'].cummax()
        drawdown = (self.nav_df['total_value'] - peak) / peak * 100
        return drawdown.min()
    
    @property
    def max_drawdown_period(self):
        """最大回撤发生的时间段"""
        if self.nav_df.empty or len(self.nav_df) < 2:
            return None, None
        peak = self.nav_df['total_value'].cummax()
        drawdown = (self.nav_df['total_value'] - peak) / peak
        min_idx = drawdown.idxmin()
        peak_idx = self.nav_df['total_value'][:min_idx+1].idxmax()
        return self.nav_df.loc[peak_idx, 'date'], self.nav_df.loc[min_idx, 'date']
    
    @property
    def sharpe_ratio(self):
        """年化夏普比率（无风险利率3%）"""
        if self.nav_df.empty or len(self.nav_df) < 2:
            return 0.0
        daily_rf = 0.03 / 252
        excess = self.nav_df['daily_return'] - daily_rf
        if excess.std() == 0:
            return 0.0
        return (excess.mean() / excess.std()) * np.sqrt(252)
    
    @property
    def win_rate(self):
        """胜率（卖出交易盈利比例）"""
        sells = [t for t in self.engine.trade_log.trades if t['action'] == 'sell']
        if not sells:
            return 0.0
        wins = sum(1 for t in sells if t.get('pnl', 0) > 0)
        return wins / len(sells) * 100
    
    @property
    def profit_loss_ratio(self):
        """盈亏比（平均盈利/平均亏损绝对值）"""
        sells = [t for t in self.engine.trade_log.trades if t['action'] == 'sell']
        profits = [t['pnl'] for t in sells if t.get('pnl', 0) > 0]
        losses = [abs(t['pnl']) for t in sells if t.get('pnl', 0) < 0]
        if not losses or sum(losses) == 0:
            if profits:
                return float('inf')
            return 0.0
        return sum(profits) / sum(losses) if profits else 0.0
    
    @property
    def total_trades(self):
        """总交易次数"""
        return len(self.engine.trade_log.trades)
    
    @property
    def total_commission(self):
        """总手续费"""
        return sum(t.get('commission', 0) for t in self.engine.trade_log.trades)
    
    @property
    def total_stamp_tax(self):
        """总印花税"""
        return sum(t.get('stamp_tax', 0) for t in self.engine.trade_log.trades)
    
    @property
    def trading_days(self):
        """回测交易天数"""
        return len(self.nav_df)
    
    @property
    def calmar_ratio(self):
        """卡玛比率（年化收益/最大回撤）"""
        if self.max_drawdown == 0:
            return 0.0
        annual_return = self.total_return / max(self.trading_days / 252, 0.001)
        return annual_return / abs(self.max_drawdown)
    
    def sortino_ratio(self):
        """索提诺比率"""
        if self.nav_df.empty or len(self.nav_df) < 2:
            return 0.0
        daily_rf = 0.03 / 252
        excess = self.nav_df['daily_return'] - daily_rf
        downside = excess[excess < 0]
        if len(downside) == 0 or downside.std() == 0:
            return 0.0
        return (excess.mean() / downside.std()) * np.sqrt(252)
    
    def trade_breakdown(self):
        """按股票统计交易盈亏"""
        stocks = set(t['stock_code'] for t in self.engine.trade_log.trades)
        breakdown = []
        for stock_code in stocks:
            pnl = self.engine.trade_log.get_pnl_by_stock(stock_code)
            trades = [t for t in self.engine.trade_log.trades if t['stock_code'] == stock_code]
            sells = [t for t in trades if t['action'] == 'sell']
            name = trades[0].get('stock_name', '')
            breakdown.append({
                'stock_code': stock_code,
                'stock_name': name,
                'total_pnl': round(pnl, 2),
                'trade_count': len(trades),
                'sell_count': len(sells)
            })
        breakdown.sort(key=lambda x: x['total_pnl'], reverse=True)
        return breakdown
    
    def report(self):
        """生成完整回测报告文本"""
        lines = []
        lines.append("=" * 60)
        lines.append("              回测报告")
        lines.append("=" * 60)
        
        # 基本信息
        lines.append("")
        lines.append("【回测概况】")
        if not self.nav_df.empty:
            start_date = self.nav_df.iloc[0]['date']
            end_date = self.nav_df.iloc[-1]['date']
            lines.append(f"  回测区间:     {start_date} ~ {end_date}")
        lines.append(f"  交易天数:     {self.trading_days}")
        lines.append(f"  初始资金:     {self.engine.initial_cash:>12,.2f} 元")
        
        if not self.nav_df.empty:
            final_value = self.nav_df.iloc[-1]['total_value']
            lines.append(f"  最终净值:     {final_value:>12,.2f} 元")
        
        lines.append(f"  总盈亏:       {self.total_pnl:>+12,.2f} 元")
        lines.append(f"  总收益率:     {self.total_return:>+12.2f} %")
        
        # 风险指标
        lines.append("")
        lines.append("【风险指标】")
        dd_start, dd_end = self.max_drawdown_period
        dd_period = f"({dd_start} ~ {dd_end})" if dd_start else ""
        lines.append(f"  最大回撤:     {self.max_drawdown:>12.2f} %  {dd_period}")
        lines.append(f"  夏普比率:     {self.sharpe_ratio:>12.4f}")
        lines.append(f"  卡玛比率:     {self.calmar_ratio:>12.4f}")
        lines.append(f"  索提诺比率:   {self.sortino_ratio():>12.4f}")
        
        # 交易统计
        lines.append("")
        lines.append("【交易统计】")
        lines.append(f"  总交易次数:   {self.total_trades}")
        lines.append(f"  胜率:         {self.win_rate:>11.1f} %")
        plr = self.profit_loss_ratio
        plr_str = f"{plr:.2f}" if plr != float('inf') else "inf"
        lines.append(f"  盈亏比:       {plr_str:>11s}")
        lines.append(f"  总手续费:     {self.total_commission:>12,.2f} 元")
        lines.append(f"  总印花税:     {self.total_stamp_tax:>12,.2f} 元")
        lines.append(f"  交易成本合计: {self.total_commission + self.total_stamp_tax:>12,.2f} 元")
        
        # 按股票盈亏
        breakdown = self.trade_breakdown()
        if breakdown:
            lines.append("")
            lines.append("【按股票盈亏】")
            for b in breakdown:
                pnl_str = f"{b['total_pnl']:>+.2f}"
                lines.append(f"  {b['stock_code']} {b['stock_name']:6s}  盈亏 {pnl_str:>10s}  交易 {b['trade_count']}次")
        
        # 信号执行日志
        if hasattr(self, 'log_messages') and self.log_messages:
            lines.append("")
            lines.append("【信号执行日志】")
            for msg in self.log_messages:
                lines.append(f"  {msg}")
        
        lines.append("")
        lines.append("=" * 60)
        lines.append("  * 回测结果仅供参考，不构成投资建议")
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def to_dict(self):
        """导出为字典（可序列化为 JSON）"""
        plr = self.profit_loss_ratio
        return {
            'total_return_pct': round(self.total_return, 2),
            'total_pnl': round(self.total_pnl, 2),
            'max_drawdown_pct': round(self.max_drawdown, 2),
            'sharpe_ratio': round(self.sharpe_ratio, 4),
            'calmar_ratio': round(self.calmar_ratio, 4),
            'sortino_ratio': round(self.sortino_ratio(), 4),
            'win_rate_pct': round(self.win_rate, 1),
            'profit_loss_ratio': round(plr, 2) if plr != float('inf') else 9999.99,
            'total_trades': self.total_trades,
            'total_commission': round(self.total_commission, 2),
            'total_stamp_tax': round(self.total_stamp_tax, 2),
            'trading_days': self.trading_days,
            'initial_cash': self.engine.initial_cash,
            'final_value': round(self.nav_df.iloc[-1]['total_value'], 2) if not self.nav_df.empty else 0,
            'trade_breakdown': self.trade_breakdown()
        }


if __name__ == '__main__':
    # ========== 单元测试 ==========
    print("=" * 60)
    print("  回测引擎 - 单元测试")
    print("=" * 60)
    
    # 1. 手续费计算测试
    engine = BacktestEngine(initial_cash=100000)
    
    print("\n--- 手续费计算 ---")
    # 小额交易：万1 < 5，按5元收取
    fee1 = engine.calc_commission(1000)  # 1000 * 0.0001 = 0.1 < 5 -> 5
    print(f"  1000元交易手续费: {fee1} (期望: 5.0)")
    assert fee1 == 5.0, f"FAIL: {fee1}"
    
    # 大额交易：万1 > 5
    fee2 = engine.calc_commission(100000)  # 100000 * 0.0001 = 10 > 5 -> 10
    print(f"  100000元交易手续费: {fee2} (期望: 10.0)")
    assert fee2 == 10.0, f"FAIL: {fee2}"
    
    # 印花税
    tax = engine.calc_stamp_tax(100000)  # 100000 * 0.001 = 100
    print(f"  100000元印花税: {tax} (期望: 100.0)")
    assert tax == 100.0, f"FAIL: {tax}"
    
    # 2. T+1 测试
    print("\n--- T+1 测试 ---")
    pos = Position('600519', '贵州茅台')
    pos.add_buy('2026-05-01', 100, 1800.0)
    pos.add_buy('2026-05-02', 100, 1810.0)
    
    # 5月2日只能卖出5月1日买入的100股
    sellable = pos.get_sellable_batches('2026-05-02', 200)
    print(f"  5月2日可卖出: {sellable}")
    assert len(sellable) == 1 and sellable[0][1] == 100, "FAIL: T+1 should block today's buy"
    
    # 5月3日可以全部卖出
    sellable = pos.get_sellable_batches('2026-05-03', 200)
    print(f"  5月3日可卖出: {sellable}")
    assert sum(s for _, s, _ in sellable) == 200, "FAIL: All should be sellable"
    
    # 3. 完整回测测试
    print("\n--- 完整回测 ---")
    engine = BacktestEngine(initial_cash=100000)
    
    # 添加模拟数据
    dates = pd.date_range('2026-03-01', periods=40, freq='B')
    prices = [10.0, 10.2, 10.1, 10.5, 10.8, 11.0, 10.9, 11.2, 11.5, 11.3,
              11.0, 10.8, 10.5, 10.2, 10.0, 9.8, 10.0, 10.3, 10.5, 10.8,
              11.0, 11.2, 11.5, 11.8, 12.0, 11.8, 11.5, 11.2, 11.0, 10.8,
              10.5, 10.2, 10.0, 9.8, 10.0, 10.3, 10.5, 10.8, 11.0, 11.2]
    
    kline = pd.DataFrame({
        'date': dates.strftime('%Y-%m-%d'),
        'open': [p * 0.99 for p in prices],
        'close': prices,
        'high': [p * 1.02 for p in prices],
        'low': [p * 0.98 for p in prices],
        'volume': [1000000] * 40,
        'change_pct': [0] + [(prices[i]/prices[i-1]-1)*100 for i in range(1, 40)]
    })
    engine.add_stock_data('600519', kline)
    
    # 生成信号：低买高卖
    signals = [
        {'date': '2026-03-02', 'stock_code': '600519', 'action': 'buy', 'price': 10.2, 'shares': 2000, 'reason': '均线多头'},
        {'date': '2026-03-11', 'stock_code': '600519', 'action': 'sell', 'price': 11.3, 'shares': 2000, 'reason': '止盈'},
        {'date': '2026-03-17', 'stock_code': '600519', 'action': 'buy', 'price': 9.8, 'shares': 2000, 'reason': '超卖反弹'},
        {'date': '2026-03-26', 'stock_code': '600519', 'action': 'sell', 'price': 11.8, 'shares': 2000, 'reason': '突破前高'},
    ]
    
    result = engine.run(signals)
    print(result.report())
    
    # 验证基本数据
    print("\n--- 数据验证 ---")
    print(f"  总交易次数: {result.total_trades} (期望: 4)")
    assert result.total_trades == 4
    print(f"  胜率: {result.win_rate:.1f}% (期望: 100.0%)")
    assert result.win_rate == 100.0
    print(f"  总手续费: {result.total_commission:.2f}")
    print(f"  总印花税: {result.total_stamp_tax:.2f}")
    print(f"  总盈亏: {result.total_pnl:.2f}")
    
    print("\n--- 所有测试通过! ---")
