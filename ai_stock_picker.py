"""
AI Stock Picker - Consolidate agent signals + technical analysis + news sentiment into daily picks.

Outputs structured picks with:
- code, name, price
- consensus_score (how many agents recommend it)
- tech_reasons (technical analysis bullet points)
- news_reasons (related news/sentiment bullet points)
- agents (list of recommending agents)

Usage:
    from ai_stock_picker import generate_picks
    picks = generate_picks(report_data, max_picks=10)
"""

import json
import re
import os
from collections import defaultdict
from datetime import datetime


def parse_tech_reasons(reasons_list):
    """Extract concise technical reasons from agent signal reasons."""
    tech_points = []
    seen = set()
    for reason in (reasons_list or []):
        # Split by semicolons for individual points
        parts = re.split(r';', reason)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # Skip pure numeric scores
            if re.match(r'^[\d.]+$', part):
                continue
            # Extract key signals
            key_signals = []
            if '多头排列' in part:
                key_signals.append('均线多头排列')
            if 'MA5 > MA10' in part or 'MA10 > MA20' in part or 'MA20 > MA60' in part:
                if '均线多头排列' not in key_signals:
                    key_signals.append('均线趋势向上')
            if '金叉' in part:
                key_signals.append('MACD金叉')
            if '红柱放大' in part:
                key_signals.append('MACD多头加速')
            if '放量' in part or '量能趋势向上' in part:
                key_signals.append('量能放大')
            if '量价齐升' in part:
                key_signals.append('量价齐升')
            if '站上MA' in part or '站在MA' in part:
                key_signals.append('股价站上均线')
            if '偏离' in part and '健康' in part:
                key_signals.append('偏离度健康')
            if '动能加速' in part or '发散' in part:
                key_signals.append('动能加速')
            if '零轴上方' in part:
                key_signals.append('MACD零轴上方')
            if re.search(r'\d+d=[\d.]+%', part):
                # Extract return info
                rets = re.findall(r'(\d+)d=([-\d.]+%)', part)
                if rets:
                    ret_str = ' '.join([f'{days}{pct}' for days, pct in rets])
                    key_signals.append(f'短期收益{ret_str}')
            # Clean up the raw reason if no key signal matched
            if not key_signals and len(part) < 120:
                # Strip "Tech: XX - " prefix
                cleaned = re.sub(r'^Tech:\s*[\d.]+\s*-\s*', '', part).strip()
                if cleaned and cleaned not in seen:
                    key_signals.append(cleaned)

            for ks in key_signals:
                if ks not in seen:
                    seen.add(ks)
                    tech_points.append(ks)

    return tech_points[:10]  # Limit to 10 key points


def parse_news_reasons(market_news, stock_code, stock_name, stock_news=None):
    """Find relevant news for a stock and extract concise bullet points.

    Args:
        market_news: list of general market news items
        stock_code: stock code (e.g. '600519')
        stock_name: stock name (e.g. '贵州茅台')
        stock_news: list of stock-specific news items (optional, from get_stock_news)
    """
    news_points = []
    code = stock_code.replace('sh', '').replace('sz', '')

    # Priority 1: Stock-specific news (most relevant)
    if stock_news:
        for item in stock_news[:5]:
            title = item.get('title', '')
            source = item.get('source', item.get('source_name', ''))
            if title:
                point = f"[{source}] {title}" if source else title
                if len(point) > 80:
                    point = point[:77] + '...'
                news_points.append(point)

    # Priority 2: Market news that mentions this stock
    if market_news:
        for item in market_news:
            title = item.get('title', '')
            summary = item.get('summary', '')
            source = item.get('source', item.get('source_name', ''))

            is_relevant = False
            if stock_name and stock_name in title:
                is_relevant = True
            if stock_name and stock_name in summary:
                is_relevant = True
            if len(code) >= 6 and code in title:
                is_relevant = True
            if len(code) >= 6 and code in summary:
                is_relevant = True

            if is_relevant and title:
                point = f"[{source}] {title}" if source else title
                if len(point) > 80:
                    point = point[:77] + '...'
                # Avoid duplicates
                if point not in news_points:
                    news_points.append(point)

    # Priority 3: Fallback to sector/general news
    if len(news_points) < 2 and market_news:
        for item in market_news[:3]:
            title = item.get('title', '')
            source = item.get('source', item.get('source_name', ''))
            if title and len(title) < 80:
                prefix = f"[{source}] " if source else ''
                point = prefix + title
                if point not in news_points:
                    news_points.append(point)
                if len(news_points) >= 3:
                    break

    return news_points[:5] if news_points else ['暂无相关新闻']


def get_sector_context(stock_code, hot_sectors):
    """Check if the stock belongs to a hot sector."""
    code = stock_code.replace('sh', '').replace('sz', '')
    for sector in hot_sectors[:5]:
        top_stocks = sector.get('top_stocks', [])
        for sc, _ in top_stocks:
            if str(sc) == code:
                return {
                    'sector': sector.get('sector', ''),
                    'hot_score': sector.get('hot_score', 0),
                    'avg_return': sector.get('avg_return', 0),
                }
    return None


def generate_picks(report_data, max_picks=10):
    """
    Generate structured stock picks from boss report data.

    Args:
        report_data: dict from boss_report_*.json
        max_picks: maximum number of picks to return

    Returns:
        list of pick dicts with code, name, price, scores, reasons, etc.
    """
    # 1. Collect all signals from all agents
    stock_signals = defaultdict(lambda: {
        'agents': [],
        'total_scores': [],
        'tech_scores': [],
        'fund_scores': [],
        'sentiment_scores': [],
        'reasons': [],
        'name': '',
    })

    for ar in report_data.get('agent_reports', []):
        agent_name = ar.get('agent_name', '')
        for sig in ar.get('top_5_signals', []):
            code = sig.get('code', '')
            name = sig.get('name', '')
            if not code:
                continue
            entry = stock_signals[code]
            entry['agents'].append(agent_name)
            entry['total_scores'].append(sig.get('total_score', 0))
            entry['tech_scores'].append(sig.get('tech_score', 0))
            entry['fund_scores'].append(sig.get('fund_score', 0))
            entry['sentiment_scores'].append(sig.get('sentiment_score', 0))
            entry['reasons'].extend(sig.get('reasons', []))
            if name:
                entry['name'] = name

    # 2. Also pick up consensus holdings
    consensus = report_data.get('consensus_holdings', [])
    if isinstance(consensus, list):
        consensus_dict = {item['code']: item for item in consensus}
    elif isinstance(consensus, dict):
        consensus_dict = consensus
    else:
        consensus_dict = {}
    for code, info in consensus_dict.items():
        if code not in stock_signals:
            agents = info.get('agents', []) if isinstance(info, dict) else []
            stock_signals[code] = {
                'agents': agents,
                'total_scores': [50],  # default score for consensus
                'tech_scores': [50],
                'fund_scores': [50],
                'sentiment_scores': [0],
                'reasons': [f'Consensus: held by {len(agents)} agents'],
                'name': info.get('name', '') if isinstance(info, dict) else '',
            }

    # 3. Score and rank
    scored_picks = []
    hot_sectors = report_data.get('hot_sectors', [])
    market_news = report_data.get('market_news', [])
    index_quotes = report_data.get('index_quotes', [])

    for code, data in stock_signals.items():
        agents = data['agents']
        if not agents:
            continue

        avg_total = sum(data['total_scores']) / len(data['total_scores'])
        avg_tech = sum(data['tech_scores']) / len(data['tech_scores'])
        avg_fund = sum(data['fund_scores']) / len(data['fund_scores'])
        avg_sent = sum(data['sentiment_scores']) / len(data['sentiment_scores'])

        # Consensus bonus: more agents = higher score
        agent_count = len(agents)
        consensus_bonus = min(agent_count * 5, 25)  # Max 25 bonus

        # Sector bonus
        sector_ctx = get_sector_context(code, hot_sectors)
        sector_bonus = 0
        if sector_ctx:
            sector_bonus = sector_ctx['hot_score'] * 10

        # Final composite score
        final_score = avg_total + consensus_bonus + sector_bonus

        # Get current price from index_quotes or consensus
        current_price = None
        stock_name = data['name']

        # Extract tech reasons
        tech_reasons = parse_tech_reasons(data['reasons'])

        # Extract news reasons (fetch stock-specific news if available)
        clean_code = code.replace('sh', '').replace('sz', '')
        sn = []
        try:
            from market_news import MarketNews
            sn = MarketNews().get_stock_news(clean_code, stock_name, max_items=5)
        except Exception:
            pass
        news_reasons = parse_news_reasons(market_news, code, stock_name, stock_news=sn)

        scored_picks.append({
            'code': code,
            'name': stock_name,
            'price': current_price,
            'composite_score': round(final_score, 1),
            'avg_total_score': round(avg_total, 1),
            'avg_tech_score': round(avg_tech, 1),
            'avg_fund_score': round(avg_fund, 1),
            'avg_sentiment_score': round(avg_sent, 1),
            'consensus_bonus': consensus_bonus,
            'sector_bonus': round(sector_bonus, 2),
            'agent_count': agent_count,
            'agents': agents,
            'tech_reasons': tech_reasons,
            'news_reasons': news_reasons,
            'sector': sector_ctx['sector'] if sector_ctx else '',
            'hot_sector_score': sector_ctx['hot_score'] if sector_ctx else 0,
        })

    # 4. Sort by composite score descending
    scored_picks.sort(key=lambda x: x['composite_score'], reverse=True)

    # 5. Add rank
    for i, pick in enumerate(scored_picks):
        pick['rank'] = i + 1

    return scored_picks[:max_picks]


def generate_picks_summary(picks):
    """Generate a human-readable summary of today's picks."""
    if not picks:
        return '今日暂无选股推荐。'

    lines = []
    lines.append(f'今日选股 TOP{len(picks)}:')
    lines.append('')

    for pick in picks:
        agent_str = '/'.join(pick['agents'][:3])
        if pick['agent_count'] > 3:
            agent_str += f' 等{pick["agent_count"]}个Agent'

        lines.append(f'#{pick["rank"]} {pick["code"]} {pick["name"]} 综合评分: {pick["composite_score"]}')
        lines.append(f'   推荐Agent: {agent_str} (共{pick["agent_count"]}个)')
        lines.append(f'   技术评分: {pick["avg_tech_score"]} | 基本面: {pick["avg_fund_score"]} | 情绪: {pick["avg_sentiment_score"]}')

        if pick['tech_reasons']:
            lines.append(f'   技术面:')
            for reason in pick['tech_reasons'][:5]:
                lines.append(f'   - {reason}')

        if pick['news_reasons'] and pick['news_reasons'] != ['暂无相关新闻']:
            lines.append(f'   新闻/情绪:')
            for reason in pick['news_reasons'][:3]:
                lines.append(f'   - {reason}')

        if pick['sector']:
            lines.append(f'   所属热点板块: {pick["sector"]} (热度: {pick["hot_sector_score"]:.3f})')

        lines.append('')

    return '\n'.join(lines)


if __name__ == '__main__':
    # Test: load latest report and generate picks
    import glob
    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'knowledge_base')
    reports = sorted(glob.glob(os.path.join(report_dir, 'boss_report_*.json')))

    if not reports:
        print('No boss reports found.')
    else:
        with open(reports[-1], 'r', encoding='utf-8') as f:
            report = json.load(f)

        picks = generate_picks(report, max_picks=10)
        print(generate_picks_summary(picks))
        print(f'\nTotal picks generated: {len(picks)}')

        # Save to JSON
        picks_path = os.path.join(report_dir, f'today_picks_{report.get("date", datetime.now().strftime("%Y-%m-%d"))}.json')
        with open(picks_path, 'w', encoding='utf-8') as f:
            json.dump({
                'date': report.get('date', ''),
                'generated_at': datetime.now().isoformat(),
                'picks': picks,
                'summary': generate_picks_summary(picks),
            }, f, ensure_ascii=False, indent=2)
        print(f'Saved picks to: {picks_path}')
