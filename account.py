"""
虚拟账户管理系统
- 初始资金10万
- 手续费：万1免5（不足5元按5元收取）
- 印花税：千1（仅卖出时）
- 交易单位：100股（1手）
- 记录每笔交易和持仓变化
"""

import json
import os
import yaml
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_config():
    with open(os.path.join(BASE_DIR, 'config', 'settings.yaml'), 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

class VirtualAccount:
    """虚拟交易账户"""
    
    def __init__(self, initial_cash=100000):
        self.account_dir = os.path.join(BASE_DIR, 'account')
        os.makedirs(self.account_dir, exist_ok=True)
        
        self.state_file = os.path.join(self.account_dir, 'account_state.json')
        self.trade_log_file = os.path.join(self.account_dir, 'trade_log.json')
        
        self.account = self._load_account(initial_cash)
        self.trades = self._load_trades()
        
    def _load_account(self, initial_cash):
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            account = {
                'initial_cash': initial_cash,
                'cash': initial_cash,
                'positions': {},  # {stock_code: {'shares': int, 'cost': float, 'name': str}}
                'total_value': initial_cash,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            self._save_account(account)
            return account
    
    def _save_account(self, account=None):
        if account is None:
            account = self.account
        account['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(account, f, indent=2, ensure_ascii=False)
    
    def _load_trades(self):
        if os.path.exists(self.trade_log_file):
            with open(self.trade_log_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            with open(self.trade_log_file, 'w', encoding='utf-8') as f:
                json.dump([], f)
            return []
    
    def _save_trades(self):
        with open(self.trade_log_file, 'w', encoding='utf-8') as f:
            json.dump(self.trades, f, indent=2, ensure_ascii=False)
    
    def calc_commission(self, amount, is_buy=True):
        """计算手续费：万1免5"""
        fee = amount * 0.0001
        return max(fee, 5)
    
    def calc_stamp_tax(self, amount):
        """计算印花税：千1（仅卖出）"""
        return amount * 0.001
    
    def calc_total_buy_cost(self, price, shares):
        """计算买入总成本（含手续费）"""
        amount = price * shares
        commission = self.calc_commission(amount, True)
        return amount + commission
    
    def calc_total_sell_proceeds(self, price, shares):
        """计算卖出净收入（扣除手续费和印花税）"""
        amount = price * shares
        commission = self.calc_commission(amount, False)
        stamp_tax = self.calc_stamp_tax(amount)
        return amount - commission - stamp_tax
    
    def can_buy(self, price, shares):
        """检查是否可以买入"""
        total_cost = self.calc_total_buy_cost(price, shares)
        return self.account['cash'] >= total_cost
    
    def buy(self, stock_code, stock_name, price, shares):
        """
        买入股票
        返回：成功/失败, 消息
        """
        # 检查是否为100的整数倍
        if shares % 100 != 0:
            return False, "买入数量必须是100股的整数倍"
        
        # 检查是否持仓过多
        num_positions = len(self.account['positions'])
        config = load_config()
        max_holdings = config.get('strategy', {}).get('max_holdings', 5)
        if stock_code not in self.account['positions'] and num_positions >= max_holdings:
            return False, f"已达最大持仓数 {max_holdings}"
        
        total_cost = self.calc_total_buy_cost(price, shares)
        if not self.can_buy(price, shares):
            return False, f"资金不足，需要 {total_cost:.2f} 元，可用 {self.account['cash']:.2f} 元"
        
        # 执行买入
        self.account['cash'] -= total_cost
        
        if stock_code in self.account['positions']:
            # 加仓
            old = self.account['positions'][stock_code]
            old_cost = old['shares'] * old['cost']
            new_cost = old_cost + price * shares
            old['shares'] += shares
            old['cost'] = round(new_cost / old['shares'], 3)
        else:
            self.account['positions'][stock_code] = {
                'shares': shares,
                'cost': price,
                'name': stock_name
            }
        
        # 更新总价值
        self._update_total_value(price, stock_code)
        self._save_account()
        
        # 记录交易
        trade = {
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'type': 'buy',
            'stock_code': stock_code,
            'stock_name': stock_name,
            'price': price,
            'shares': shares,
            'amount': round(price * shares, 2),
            'commission': round(self.calc_commission(price * shares), 2),
            'total_cost': round(total_cost, 2)
        }
        self.trades.append(trade)
        self._save_trades()
        
        return True, f"买入 {stock_name}({stock_code}) {shares}股 @ {price}元，花费 {total_cost:.2f}元"
    
    def can_sell(self, stock_code):
        """检查是否可以卖出"""
        return stock_code in self.account['positions'] and self.account['positions'][stock_code]['shares'] > 0
    
    def sell(self, stock_code, price, shares):
        """
        卖出股票
        返回：成功/失败, 消息
        """
        if not self.can_sell(stock_code):
            return False, f"未持有 {stock_code}"
        
        position = self.account['positions'][stock_code]
        if shares > position['shares']:
            return False, f"持仓不足，持有 {position['shares']}股"
        
        if shares % 100 != 0:
            return False, "卖出数量必须是100股的整数倍"
        
        # 执行卖出
        net_proceeds = self.calc_total_sell_proceeds(price, shares)
        self.account['cash'] += net_proceeds
        
        stock_name = position['name']
        position['shares'] -= shares
        if position['shares'] == 0:
            del self.account['positions'][stock_code]
        
        # 更新总价值
        self._update_total_value(price, stock_code)
        self._save_account()
        
        # 记录交易
        trade = {
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'type': 'sell',
            'stock_code': stock_code,
            'stock_name': stock_name,
            'price': price,
            'shares': shares,
            'amount': round(price * shares, 2),
            'commission': round(self.calc_commission(price * shares), 2),
            'stamp_tax': round(self.calc_stamp_tax(price * shares), 2),
            'net_proceeds': round(net_proceeds, 2)
        }
        self.trades.append(trade)
        self._save_trades()
        
        pnl = (price - position['cost']) * shares if stock_code in self.account['positions'] else 0
        return True, f"卖出 {stock_name}({stock_code}) {shares}股 @ {price}元，净收入 {net_proceeds:.2f}元"
    
    def _update_total_value(self, latest_price=None, stock_code=None):
        """更新账户总价值"""
        positions_value = 0
        for code, pos in self.account['positions'].items():
            if code == stock_code and latest_price:
                positions_value += pos['shares'] * latest_price
            else:
                positions_value += pos['shares'] * pos['cost']
        self.account['total_value'] = round(self.account['cash'] + positions_value, 2)
    
    def get_pnl(self):
        """计算总盈亏"""
        return self.account['total_value'] - self.account['initial_cash']
    
    def get_pnl_pct(self):
        """计算总收益率"""
        return (self.account['total_value'] / self.account['initial_cash'] - 1) * 100
    
    def get_position_pnl(self, stock_code):
        """计算某只股票的持仓盈亏"""
        if stock_code not in self.account['positions']:
            return 0
        pos = self.account['positions'][stock_code]
        # 这里只是成本价，实时盈亏需要从市场数据获取
        return 0
    
    def reset(self):
        """重置账户到初始状态"""
        initial_cash = self.account['initial_cash']
        self.account = {
            'initial_cash': initial_cash,
            'cash': initial_cash,
            'positions': {},
            'total_value': initial_cash,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        self.trades = []
        self._save_account()
        self._save_trades()
    
    def summary(self):
        """获取账户摘要"""
        return {
            'initial_cash': self.account['initial_cash'],
            'cash': self.account['cash'],
            'total_value': self.account['total_value'],
            'pnl': self.get_pnl(),
            'pnl_pct': f"{self.get_pnl_pct():.2f}%",
            'positions': len(self.account['positions']),
            'total_trades': len(self.trades)
        }
    
    def display(self):
        """格式化显示账户信息"""
        s = self.summary()
        lines = [
            "=" * 50,
            "           虚拟账户信息",
            "=" * 50,
            f"  初始资金:  {s['initial_cash']:>12,.2f} 元",
            f"  当前现金:  {s['cash']:>12,.2f} 元",
            f"  账户总值:  {s['total_value']:>12,.2f} 元",
            f"  总盈亏:    {s['pnl']:>+12,.2f} 元 ({s['pnl_pct']})",
            f"  持仓数:    {s['positions']:<12} 只",
            f"  交易次数:  {s['total_trades']:<12} 次",
            "-" * 50,
            "  持仓明细:",
        ]
        
        if self.account['positions']:
            for code, pos in self.account['positions'].items():
                value = pos['shares'] * pos['cost']
                lines.append(f"    {code} {pos['name']:6s}  {pos['shares']:>5}股  "
                           f"成本 {pos['cost']:.2f}  市值 {value:,.2f}")
        else:
            lines.append("    (空仓)")
        
        lines.append("=" * 50)
        return '\n'.join(lines)


if __name__ == '__main__':
    acc = VirtualAccount()
    print(acc.display())
    
    # 测试交易
    print("\n--- 测试买入 ---")
    success, msg = acc.buy('600519', '贵州茅台', 1800.00, 100)
    print(f"  {success}: {msg}")
    
    print("\n--- 测试买入2 ---")
    success, msg = acc.buy('000858', '五粮液', 150.00, 200)
    print(f"  {success}: {msg}")
    
    print("\n--- 账户状态 ---")
    print(acc.display())
    
    print("\n--- 测试卖出 ---")
    success, msg = acc.sell('600519', 1850.00, 100)
    print(f"  {success}: {msg}")
    
    print("\n--- 最终状态 ---")
    print(acc.display())
