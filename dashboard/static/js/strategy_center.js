(function (window) {
    const api = window.DashboardAPI;
    const ui = window.DashboardUI;

    function strategyName(row) {
        return row.display_name || row.name || row.strategy || row.strategy_id || '未知策略';
    }

    function renderStrategyCards(stats, arena, memory) {
        const statRows = stats.strategies || [];
        const arenaRows = arena.rows || [];
        const memRows = memory.strategies || [];
        const names = {};
        statRows.forEach(function (s) { names[s.strategy_id || s.id || s.name || s.strategy] = true; });
        arenaRows.forEach(function (s) { names[s.strategy_id || s.name] = true; });
        memRows.forEach(function (s) { names[s.strategy || s.name] = true; });

        const cards = Object.keys(names).map(function (key) {
            const stat = statRows.find(function (s) { return [s.strategy_id, s.id, s.name, s.strategy].includes(key); }) || {};
            const ar = arenaRows.find(function (s) { return [s.strategy_id, s.name].includes(key); }) || {};
            const mem = memRows.find(function (s) { return [s.strategy, s.name].includes(key); }) || {};
            const display = strategyName(stat) !== '未知策略' ? strategyName(stat) : strategyName(ar) !== '未知策略' ? strategyName(ar) : strategyName(mem);
            const hasPaper = ar.paper_return !== null && ar.paper_return !== undefined;
            const paperReturn = hasPaper ? Number(ar.paper_return) : null;
            const backtestReturn = Number(ar.backtest_return || 0);
            const winRate = Number(ar.paper_win_rate || mem.win_rate || stat.win_rate || 0);
            return '<div class="strategy-card">' +
                '<h3>' + ui.escapeHtml(display) + '</h3>' +
                '<div class="metric-grid">' +
                '<div class="metric"><div class="metric-label">纸面收益</div><div class="metric-value ' + (hasPaper ? ui.pctClass(paperReturn) : '') + '">' + (hasPaper ? ui.formatPct(paperReturn) : '<span class="muted">样本不足</span>') + '</div></div>' +
                '<div class="metric"><div class="metric-label">回测收益</div><div class="metric-value ' + ui.pctClass(backtestReturn) + '">' + ui.formatPct(backtestReturn) + '</div></div>' +
                '<div class="metric"><div class="metric-label">胜率</div><div class="metric-value">' + Number(winRate || 0).toFixed(1) + '%</div></div>' +
                '<div class="metric"><div class="metric-label">交易数</div><div class="metric-value">' + (ar.paper_trades || stat.total_trades || mem.total_signals || mem.signals || 0) + '</div></div>' +
                '</div>' +
                '<div class="tag-row">' +
                ui.badge(hasPaper ? (Math.abs(paperReturn - backtestReturn) <= 5 ? '偏差可控' : '需复核偏差') : '等待纸面成交', hasPaper && Math.abs(paperReturn - backtestReturn) <= 5 ? 'green' : 'yellow') +
                ui.badge((stat.enabled === false) ? '停用' : '启用', (stat.enabled === false) ? 'red' : 'blue') +
                '</div>' +
                '</div>';
        }).join('');
        ui.setHtml('strategyCards', cards || ui.empty('暂无策略数据'));
    }

    function renderStrategyCompare(arena) {
        const rows = (arena.rows || []).map(function (r) {
            const hasPaperReturn = r.paper_return !== null && r.paper_return !== undefined;
            const hasGap = r.gap !== null && r.gap !== undefined;
            const gap = hasGap ? Number(r.gap) : null;
            return '<tr>' +
                '<td>' + ui.escapeHtml(strategyName(r)) + '</td>' +
                '<td class="' + (hasPaperReturn ? ui.pctClass(r.paper_return) : '') + '">' + (hasPaperReturn ? ui.formatPct(r.paper_return) : '<span class="muted">未开始</span>') + '</td>' +
                '<td class="' + ui.pctClass(r.backtest_return) + '">' + ui.formatPct(r.backtest_return) + '</td>' +
                '<td class="' + (hasGap ? ui.pctClass(gap) : '') + '">' + (hasGap ? ui.formatPct(gap) : '<span class="muted">样本不足</span>') + '</td>' +
                '<td>' + Number(r.backtest_sharpe || 0).toFixed(2) + '</td>' +
                '<td>' + (r.paper_trades || 0) + ' / ' + (r.backtest_trades || 0) + '</td>' +
                '</tr>';
        }).join('');
        ui.setHtml('strategyCompare', rows ? '<div class="table-wrap"><table><thead><tr><th>策略</th><th>纸面收益</th><th>回测收益</th><th>偏差</th><th>Sharpe</th><th>交易数(纸面/回测)</th></tr></thead><tbody>' + rows + '</tbody></table></div>' : ui.empty('暂无纸面与回测对比'));
    }

    function renderStrategyExplanation(memory) {
        const summary = memory.summary || {};
        const rows = (memory.strategies || []).slice(0, 8).map(function (r) {
            const avgReturn = r.avg_return != null ? r.avg_return : (r.avg_pnl_pct || 0);
            return '<tr>' +
                '<td>' + ui.escapeHtml(r.strategy || r.name || '') + '</td>' +
                '<td>' + (r.total_signals || r.signals || 0) + '</td>' +
                '<td>' + Number(r.win_rate || 0).toFixed(1) + '%</td>' +
                '<td class="' + ui.pctClass(avgReturn) + '">' + ui.formatPct(avgReturn) + '</td>' +
                '<td>' + ui.escapeHtml(r.conclusion || r.note || '等待 Agent 归因') + '</td>' +
                '</tr>';
        }).join('');
        ui.setHtml('strategyMemorySummary', '<div class="metric-grid">' +
            '<div class="metric"><div class="metric-label">记忆信号数</div><div class="metric-value">' + (summary.total_signals || summary.signals || 0) + '</div></div>' +
            '<div class="metric"><div class="metric-label">经验条目</div><div class="metric-value">' + (summary.total_lessons || summary.lessons || 0) + '</div></div>' +
            '</div>');
        ui.setHtml('strategyMemoryTable', rows ? '<div class="table-wrap"><table><thead><tr><th>策略</th><th>信号</th><th>胜率</th><th>均值收益</th><th>Agent 解释</th></tr></thead><tbody>' + rows + '</tbody></table></div>' : ui.empty('暂无策略记忆'));
    }

    async function loadStrategyCenter() {
        ui.loading('strategyCards');
        try {
            const data = await api.get('/api/dashboard/strategy_center');
            const stats = data.stats || {};
            const arena = data.arena || {};
            const memory = data.memory || {};
            renderStrategyCards(stats, arena, memory);
            renderStrategyCompare(arena);
            renderStrategyExplanation(memory);
        } catch (err) {
            ui.setHtml('strategyCards', ui.empty(err.message));
        }
    }

    window.loadStrategyCenter = loadStrategyCenter;
})(window);
