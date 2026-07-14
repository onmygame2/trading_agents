(function (window) {
    const api = window.DashboardAPI;
    const ui = window.DashboardUI;

    function renderAgentJournal(signals, lessons, agentEvents, agent) {
        const latestSignal = (signals.signals || [])[0];
        const latestLesson = (lessons.lessons || [])[0];
        const latestEvent = (agentEvents || [])[0];
        const brief = (agent && agent.brief) || {};
        const latestLessonText = latestLesson ? (latestLesson.summary || latestLesson.content || latestLesson.lesson || latestLesson.description || latestLesson.title || '') : '';
        const riskFlags = (brief.risk_flags || []).slice(0, 3).join('；');
        const actionItems = (brief.action_items || []).slice(0, 3).join('；');
        const items = [
            '<div class="list-item"><div class="list-item-title">今日 Agent 工作摘要</div><div class="muted">已读取信号 ' + (signals.total || 0) + ' 条，经验 ' + (lessons.total || 0) + ' 条，Agent 事件 ' + (agentEvents || []).length + ' 条。</div></div>',
            brief.summary ? '<div class="list-item"><div class="list-item-title">最新 Agent 日报</div><div class="muted">' + ui.escapeHtml(brief.summary) + '</div>' +
                '<div class="muted">风险：' + ui.escapeHtml(riskFlags || '暂无') + '</div>' +
                '<div class="muted">下一步：' + ui.escapeHtml(actionItems || '暂无') + '</div></div>' : '',
            latestEvent ? '<div class="list-item"><div class="list-item-title">最新 Agent 事件</div><div class="muted">' + ui.escapeHtml(latestEvent.ts || latestEvent.date || '') + ' · ' + ui.escapeHtml(latestEvent.agent || '') + ' · ' + ui.escapeHtml(latestEvent.title || latestEvent.event_type || '') + '</div></div>' : '',
            latestSignal ? '<div class="list-item"><div class="list-item-title">最新信号</div><div class="muted">' + ui.escapeHtml(latestSignal.created_at || latestSignal.date || '') + ' · ' + ui.escapeHtml(latestSignal.strategy || '') + ' · ' + ui.escapeHtml(latestSignal.code || latestSignal.stock_code || '') + ' · ' + ui.escapeHtml(latestSignal.signal || '') + '</div></div>' : '',
            latestLesson ? '<div class="list-item"><div class="list-item-title">最新经验</div><div class="muted">' + ui.escapeHtml(latestLessonText) + '</div></div>' : ''
        ].filter(Boolean).join('');
        ui.setHtml('agentJournal', items);
    }

    function renderMarketRegime(market) {
        const dist = market.sentiment_dist || {};
        const history = market.history || [];
        const latest = history[0] || {};
        ui.setHtml('marketRegime', '<div class="metric-grid">' +
            '<div class="metric"><div class="metric-label">当前情绪</div><div class="metric-value">' + ui.escapeHtml(latest.sentiment || 'unknown') + '</div></div>' +
            '<div class="metric"><div class="metric-label">样本天数</div><div class="metric-value">' + history.length + '</div></div>' +
            '<div class="metric"><div class="metric-label">偏多天数</div><div class="metric-value">' + (dist.bullish || 0) + '</div></div>' +
            '<div class="metric"><div class="metric-label">偏空天数</div><div class="metric-value">' + (dist.bearish || 0) + '</div></div>' +
            '</div>');
    }

    function renderLessons(lessons) {
        const items = (lessons.lessons || []).slice(0, 12).map(function (l) {
            const type = l.lesson_type || l.type || 'lesson';
            return '<div class="list-item">' +
                '<div class="list-item-title">' + ui.badge(type, type.indexOf('fail') >= 0 || type.indexOf('risk') >= 0 ? 'yellow' : 'blue') + ' ' + ui.escapeHtml(l.created_at || l.date || '') + '</div>' +
                '<div class="muted">' + ui.escapeHtml(l.description || l.summary || l.content || l.lesson || l.pattern || '') + '</div>' +
                '</div>';
        }).join('');
        ui.setHtml('memoryLessons', items || ui.empty('暂无经验教训'));
    }

    function renderExperimentShelf(strategy) {
        const rows = (strategy.strategies || []).slice(0, 8).map(function (s) {
            const avgReturn = s.avg_return != null ? s.avg_return : (s.avg_pnl_pct || 0);
            const verdict = Number(avgReturn || 0) >= 0 ? '保留观察' : '降权复核';
            return '<tr>' +
                '<td>' + ui.escapeHtml(s.strategy || s.name || '') + '</td>' +
                '<td>' + (s.total_signals || s.signals || 0) + '</td>' +
                '<td>' + Number(s.win_rate || 0).toFixed(1) + '%</td>' +
                '<td class="' + ui.pctClass(avgReturn) + '">' + ui.formatPct(avgReturn) + '</td>' +
                '<td>' + ui.badge(verdict, verdict === '保留观察' ? 'green' : 'yellow') + '</td>' +
                '</tr>';
        }).join('');
        ui.setHtml('experimentShelf', rows ? '<div class="table-wrap"><table><thead><tr><th>策略</th><th>记忆信号</th><th>胜率</th><th>均值收益</th><th>Agent 建议</th></tr></thead><tbody>' + rows + '</tbody></table></div>' : ui.empty('暂无策略实验记录'));
    }

    async function loadMemoryCenter() {
        ui.loading('agentJournal');
        try {
            const data = await api.get('/api/dashboard/memory_center');
            const signals = data.signals || {};
            const market = data.market || {};
            const strategy = data.strategy || {};
            const lessons = data.lessons || {};
            const agentEvents = data.agent_events || [];
            const agent = data.agent || {};
            renderAgentJournal(signals, lessons, agentEvents, agent);
            renderMarketRegime(market);
            renderLessons(lessons);
            renderExperimentShelf(strategy);
        } catch (err) {
            ui.setHtml('agentJournal', ui.empty(err.message));
        }
    }

    window.loadMemoryCenter = loadMemoryCenter;
})(window);
