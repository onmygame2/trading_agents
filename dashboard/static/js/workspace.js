(function (window) {
    const api = window.DashboardAPI;
    const ui = window.DashboardUI;

    function firstReason(pick) {
        const parts = [];
        if (pick.strategy_name || pick.strategy) parts.push(pick.strategy_name || pick.strategy);
        if (pick.sector) parts.push(pick.sector);
        if (pick.reason) parts.push(pick.reason);
        if (Array.isArray(pick.reasons)) parts.push(pick.reasons.slice(0, 2).join(' / '));
        return parts.filter(Boolean).join(' / ') || '等待 Agent 复盘补充原因';
    }

    function renderStats(summary, monitor, picks, demoState) {
        const positions = (monitor.positions || monitor.watchlist || []);
        const stale = !summary.date || summary.date === 'N/A';
        const risk = [];
        if (stale) risk.push('账户日期缺失');
        if ((picks.picks || []).length === 0) risk.push('今日无候选');
        if (monitor.alerts && monitor.alerts.length) risk.push(monitor.alerts.length + ' 条持仓预警');
        if (demoState && demoState.is_demo) risk.push('当前为演示数据');

        ui.setHtml('workspaceStats', [
            '<div class="stat-card"><div class="stat-label">组合资产</div><div class="stat-value">' + ui.formatMoney(summary.total_equity) + '</div><div class="stat-sub">累计收益 <span class="' + ui.pctClass(summary.total_return_pct) + '">' + ui.formatPct(summary.total_return_pct) + '</span></div></div>',
            '<div class="stat-card"><div class="stat-label">持仓数量</div><div class="stat-value">' + positions.length + '</div><div class="stat-sub">来自持仓监控与候选列表</div></div>',
            '<div class="stat-card"><div class="stat-label">今日候选</div><div class="stat-value">' + (picks.picks || []).length + '</div><div class="stat-sub">最新报告 ' + ui.escapeHtml(picks.date || summary.date || '--') + '</div></div>',
            '<div class="stat-card"><div class="stat-label">系统健康</div><div class="stat-value">' + (demoState && demoState.is_demo ? ui.badge('演示态', 'yellow') : risk.length ? ui.badge('需关注', 'yellow') : ui.badge('正常', 'green')) + '</div><div class="stat-sub">' + ui.escapeHtml((demoState && demoState.message) || risk.join('、') || '数据与任务状态正常') + '</div></div>'
        ].join(''));
    }

    function renderTradePlan(picks, monitor) {
        const previewOnly = picks.execution_status === 'preview_only';
        const recommendationRows = (picks.picks || picks.top_picks || []).slice(0, 8).map(function (p, idx) {
            const score = p.final_score || p.total_score || p.score || p.strategy_score || 0;
            const buy = p.buy_price || p.price || p.close || 0;
            return '<tr>' +
                '<td>' + (idx + 1) + '</td>' +
                '<td><span class="stock-code">' + ui.escapeHtml(p.code || p.stock_code || '') + '</span></td>' +
                '<td>' + ui.escapeHtml(p.name || p.stock_name || '') + '</td>' +
                '<td>' + ui.escapeHtml(p.strategy_name || p.strategy || p.source_strategy || '组合') + '</td>' +
                '<td>' + Number(score || 0).toFixed(1) + '</td>' +
                '<td>' + Number(buy || 0).toFixed(2) + '</td>' +
                '<td>' + ui.escapeHtml(firstReason(p)).slice(0, 80) + '</td>' +
                '</tr>';
        }).join('');
        const planRows = (picks.buy_picks || []).slice(0, 5).map(function (p, idx) {
            return '<tr><td>' + (idx + 1) + '</td><td><span class="stock-code">' + ui.escapeHtml(p.code || '') + '</span></td><td>' + ui.escapeHtml(p.name || '') + '</td><td>' + ui.escapeHtml(p.strategy || p.strategy_name || '组合') + '</td><td>' + Number(p.buy_price || p.price || 0).toFixed(2) + '</td></tr>';
        }).join('');
        const actionRows = (picks.buy_actions || []).slice(0, 5).map(function (a, idx) {
            return '<tr><td>' + (idx + 1) + '</td><td><span class="stock-code">' + ui.escapeHtml(a.code || '') + '</span></td><td>' + Number(a.price || 0).toFixed(2) + '</td><td>' + (a.shares || 0) + '</td><td>' + ui.formatMoney(a.amount || 0) + '</td></tr>';
        }).join('');

        const sellRows = (monitor.alerts || monitor.positions || []).filter(function (p) {
            const flag = p.status || p.alert || '';
            return flag && flag !== 'normal';
        }).slice(0, 5).map(function (p) {
            return '<div class="list-item"><div class="list-item-title">' + ui.escapeHtml(p.code) + ' ' + ui.escapeHtml(p.name || '') + '</div><div class="muted">' + ui.escapeHtml(p.status || p.alert || '需要复核') + ' · 当前价 ' + Number(p.current_price || 0).toFixed(2) + '</div></div>';
        }).join('');

        const blocks = [
            '<div class="muted" style="margin-bottom:8px">' +
                (previewOnly ? ui.badge('研究预览', 'yellow') + ' ' + ui.escapeHtml(picks.execution_message || '非交易时段生成，不产生实际成交。') : '今日推荐不等于实际成交；实际成交以买入/卖出动作和账户日志为准。') +
            '</div>',
            recommendationRows ? '<h4>今日推荐</h4><div class="table-wrap"><table><thead><tr><th>#</th><th>代码</th><th>名称</th><th>触发策略</th><th>分数</th><th>参考价</th><th>Agent 可读理由</th></tr></thead><tbody>' + recommendationRows + '</tbody></table></div>' : ui.empty('暂无今日推荐'),
            planRows ? '<h4>组合计划买入</h4><div class="table-wrap"><table><thead><tr><th>#</th><th>代码</th><th>名称</th><th>策略</th><th>参考价</th></tr></thead><tbody>' + planRows + '</tbody></table></div>' : '',
            actionRows ? '<h4>实际买入成交</h4><div class="table-wrap"><table><thead><tr><th>#</th><th>代码</th><th>价格</th><th>股数</th><th>金额</th></tr></thead><tbody>' + actionRows + '</tbody></table></div>' : ''
        ];
        ui.setHtml('workspaceTradePlan', blocks.filter(Boolean).join(''));
        ui.setHtml('workspaceSellPlan', sellRows || ui.empty('暂无明确卖出预警'));
    }

    function renderRiskAndAgent(summary, market, tasks, lessons, agent) {
        const latestTask = (tasks.tasks || [])[0];
        const brief = (agent && agent.brief) || {};
        const marketText = market.sentiment || market.market_sentiment || 'neutral';
        const hotSectors = (market.hot_sectors || market.sector_hot || market.sectors || []).slice(0, 6).map(function (s) {
            return ui.badge(s.name || s.industry || s.sector || s, 'blue');
        }).join(' ');
        const lesson = (lessons.lessons || [])[0];
        const fallbackBrief = [
            '当前市场状态：' + marketText + '。',
            latestTask ? ('最近任务：' + (latestTask.label || latestTask.type) + '，状态 ' + latestTask.status + '。') : '暂无后台任务记录。',
            lesson ? ('最新经验：' + (lesson.summary || lesson.content || lesson.lesson || '').slice(0, 80)) : '记忆库暂无最新经验。'
        ].join(' ');

        ui.setHtml('workspaceMarket', '<div class="metric-grid">' +
            '<div class="metric"><div class="metric-label">市场状态</div><div class="metric-value">' + ui.escapeHtml(marketText) + '</div></div>' +
            '<div class="metric"><div class="metric-label">热点主题</div><div class="metric-value">' + (hotSectors || '<span class="muted">暂无</span>') + '</div></div>' +
            '</div>');
        ui.setHtml('workspaceAgentBrief', '<div class="list-item"><div class="list-item-title">Agent 摘要</div><div class="muted">' + ui.escapeHtml(brief.summary || fallbackBrief) + '</div></div>');
    }

    async function loadWorkspace() {
        ui.loading('workspaceStats');
        ui.loading('workspaceTradePlan');
        try {
            const data = await api.get('/api/dashboard/workspace');
            const summary = data.summary || {};
            const picks = data.picks || {};
            const monitor = data.monitor || {};
            const market = data.market || {};
            const tasks = data.tasks || {};
            const lessons = data.lessons || {};
            const agent = data.agent || {};
            renderStats(summary, monitor, picks, data.demo_state || summary.demo_state || {});
            renderTradePlan(picks, monitor);
            renderRiskAndAgent(summary, market, tasks, lessons, agent);
        } catch (err) {
            ui.setHtml('workspaceStats', ui.empty(err.message));
        }
    }

    window.loadWorkspace = loadWorkspace;
})(window);
