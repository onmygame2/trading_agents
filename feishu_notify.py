"""
飞书通知模块 - DISABLED (公司不允许使用)
所有函数为 no-op，日志输出到 stdout
"""
import sys
import datetime

USER_OPEN_ID = ''  # disabled
FEISHU_DISABLED = True

def send_message(user_id, text, **kwargs):
    """No-op: 飞书已禁用"""
    print(f"[FEISHU-DISABLED] {user_id}: {text[:100]}", file=sys.stderr)

def send_interactive_card(user_id, card_data, **kwargs):
    """No-op: 飞书已禁用"""
    print(f"[FEISHU-DISABLED] card to {user_id}", file=sys.stderr)

def build_stock_picks_card(picks, date=None, **kwargs):
    """No-op: 飞书已禁用"""
    return {}

def format_daily_report(report_data, **kwargs):
    """No-op: 飞书已禁用"""
    return '', ''

def send_stock_picks(picks, user_id=None, **kwargs):
    """No-op: 飞书已禁用"""
    pass

def send_daily_report(report_data, user_id=None, **kwargs):
    """No-op: 飞书已禁用"""
    pass

def get_tenant_access_token():
    """No-op: 飞书已禁用"""
    return None
