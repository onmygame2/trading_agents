(function (window) {
    const api = window.DashboardAPI;
    const ui = window.DashboardUI;

    const taskButtons = [
        { type: 'bootstrap_runtime', label: '初始化真实运行态（无模拟成交）', params: { run_first_day: true }, kind: 'primary' },
        { type: 'daily_picker', label: '盘中交易（主线，先卖后买）', params: { pool_mode: 'mainline' }, kind: 'primary' },
        { type: 'daily_picker', label: '盘中交易（板块，先卖后买）', params: { pool_mode: 'sector' }, kind: 'secondary' },
        { type: 'daily_sell', label: '卖出检查', params: {}, kind: 'warning' },
        { type: 'agent_review', label: '生成 Agent 复盘', params: {}, kind: 'primary' },
        { type: 'update_kline', label: '更新全市场日 K 快照', params: { top: 0, snapshot: true }, kind: 'secondary' },
        { type: 'init_kline_missing', label: '初始化缺失 K 线 Top200', params: { top: 200, offset: 0, days: 180, backend: 'akshare' }, kind: 'secondary' },
        { type: 'backtest_v2', label: '快速 v2 回测', params: { quick: true }, kind: 'secondary' }
    ];

    function renderTaskButtons() {
        ui.setHtml('opsTaskButtons', taskButtons.map(function (t) {
            return '<button class="btn btn-' + t.kind + '" data-task-type="' + ui.escapeHtml(t.type) + '" data-task-params="' + ui.escapeHtml(JSON.stringify(t.params || {})) + '">' + ui.escapeHtml(t.label) + '</button>';
        }).join(''));
        document.querySelectorAll('#opsTaskButtons button').forEach(function (btn) {
            btn.addEventListener('click', function () {
                let params = {};
                try {
                    params = JSON.parse(btn.dataset.taskParams || '{}');
                } catch (err) {
                    params = {};
                }
                runTask(btn.dataset.taskType, params);
            });
        });
    }

    async function runTask(type, params) {
        const status = ui.byId('opsTaskStatus');
        if (status) status.innerHTML = '<div class="list-item">正在提交任务...</div>';
        try {
            const result = await api.post('/api/tasks/run', { type: type, params: params || {} });
            if (status) status.innerHTML = '<div class="list-item">任务已提交：' + ui.escapeHtml(result.task_id || result.id || type) + '</div>';
            await loadOpsCenter();
            if (result.task_id || result.id) pollTask(result.task_id || result.id);
        } catch (err) {
            if (status) status.innerHTML = '<div class="list-item text-red">' + ui.escapeHtml(err.message) + '</div>';
        }
    }

    async function pollTask(taskId) {
        if (window.DashboardState.taskPoll) clearInterval(window.DashboardState.taskPoll);
        window.DashboardState.taskPoll = setInterval(async function () {
            try {
                const task = await api.get('/api/tasks/' + taskId);
                renderTaskStatus(task);
                if (['done', 'error', 'success', 'failed', 'cancelled', 'completed'].includes(task.status)) {
                    clearInterval(window.DashboardState.taskPoll);
                    window.DashboardState.taskPoll = null;
                    loadOpsCenter();
                    loadWorkspace();
                    if (window.loadMemoryCenter) loadMemoryCenter();
                }
            } catch (err) {
                clearInterval(window.DashboardState.taskPoll);
                window.DashboardState.taskPoll = null;
            }
        }, 2500);
    }

    function renderTaskStatus(task) {
        const isError = ['error', 'failed'].includes(task.status);
        const isDone = ['done', 'success', 'completed'].includes(task.status);
        const logText = task.output || task.error_detail || (task.result ? JSON.stringify(task.result, null, 2) : '');
        const progress = Math.max(0, Math.min(100, Number(task.progress || 0)));
        const body = '<div class="list-item">' +
            '<div class="list-item-title">' + ui.escapeHtml(task.label || task.type || task.id) + ' · ' + ui.badge(task.status || 'running', isError ? 'red' : isDone ? 'green' : 'blue') + '</div>' +
            '<div class="muted">开始：' + ui.escapeHtml(task.started_at || task.created_at || '--') + ' · 结束：' + ui.escapeHtml(task.finished_at || '--') + '</div>' +
            '<div class="muted">进度：' + progress + '% ' + ui.escapeHtml(task.message || '') + '</div>' +
            (task.error ? '<div class="text-red">' + ui.escapeHtml(task.error) + '</div>' : '') +
            (logText ? '<pre class="task-log">' + ui.escapeHtml(String(logText).slice(-3000)) + '</pre>' : '') +
            '</div>';
        ui.setHtml('opsTaskStatus', body);
    }

    function renderScheduler(data) {
        if (data.error) {
            ui.setHtml('opsScheduler', '<div class="list-item text-red">' + ui.escapeHtml(data.error) + '</div>');
            return;
        }
        const items = [];
        if (data.in_session != null) items.push('<div class="metric"><div class="metric-label">交易时段</div><div class="metric-value">' + (data.in_session ? '是' : '否') + '</div></div>');
        if (data.session_label) items.push('<div class="metric"><div class="metric-label">状态</div><div class="metric-value">' + ui.escapeHtml(data.session_label) + '</div></div>');
        if (data.cron_installed != null) items.push('<div class="metric"><div class="metric-label">Cron</div><div class="metric-value">' + (data.cron_installed ? '已安装' : '未检测') + '</div></div>');
        if (data.windows_tasks_installed != null) items.push('<div class="metric"><div class="metric-label">Windows任务</div><div class="metric-value">' + (data.windows_tasks_installed ? '已安装' : '未检测') + '</div></div>');
        const jobRows = (data.jobs || []).map(function (j) {
            const err = j.last_error ? '<div class="text-red">' + ui.escapeHtml(j.last_error) + '</div>' : '';
            const tail = (j.log_tail || []).slice(-3).join('\n');
            return '<div class="list-item"><div class="list-item-title">' + ui.escapeHtml(j.label || j.id) + ' · ' + ui.escapeHtml(j.cron || '') + '</div>' +
                '<div class="muted">最近运行：' + ui.escapeHtml(j.last_run || '无记录') + '</div>' +
                err +
                (tail ? '<pre class="task-log">' + ui.escapeHtml(tail) + '</pre>' : '') +
                '</div>';
        }).join('');
        ui.setHtml('opsScheduler', '<div class="metric-grid">' + (items.join('') || '<div class="muted">暂无调度信息</div>') + '</div>' + (jobRows || ''));
    }

    function renderTasks(data) {
        const rows = (data.tasks || []).map(function (t) {
            return '<tr>' +
                '<td>' + ui.escapeHtml(t.label || t.type || '') + '</td>' +
                '<td>' + ui.badge(t.status || '', ['error', 'failed'].includes(t.status) ? 'red' : ['done', 'success', 'completed'].includes(t.status) ? 'green' : 'blue') + '</td>' +
                '<td>' + ui.escapeHtml(t.created_at || t.started_at || '') + '</td>' +
                '<td>' + ui.escapeHtml(t.finished_at || '') + '</td>' +
                '<td>' + ui.escapeHtml(t.error || '') + '</td>' +
                '</tr>';
        }).join('');
        ui.setHtml('opsTaskList', rows ? '<div class="table-wrap"><table><thead><tr><th>任务</th><th>状态</th><th>开始</th><th>结束</th><th>错误</th></tr></thead><tbody>' + rows + '</tbody></table></div>' : ui.empty('暂无任务记录'));
    }

    async function loadOpsCenter() {
        renderTaskButtons();
        const results = await Promise.allSettled([
            api.get('/api/scheduler/status'),
            api.get('/api/tasks?limit=20')
        ]);
        renderScheduler(results[0].value || { error: results[0].reason && results[0].reason.message });
        renderTasks(results[1].value || {});
    }

    async function loadHistoryCenter() {
        ui.loading('historyTrades');
        const results = await Promise.allSettled([
            api.get('/api/trades?per_page=80'),
            api.get('/api/historical_picks')
        ]);
        const trades = results[0].value || {};
        let picks = results[1].value || {};
        if ((picks.dates || []).length) {
            try {
                picks = await api.get('/api/historical_picks?date=' + encodeURIComponent(picks.dates[0]));
            } catch (err) {
                picks = results[1].value || {};
            }
        }
        renderTrades(trades);
        renderHistoricalPicks(picks);
    }

    function renderTrades(data) {
        const rows = (data.trades || []).slice(0, 80).map(function (t) {
            const pnl = Number(t.pnl || t.profit || t.profit_pct || 0);
            return '<tr>' +
                '<td>' + ui.escapeHtml(t.date || t.time || t.created_at || '') + '</td>' +
                '<td>' + ui.escapeHtml(t.agent || t.strategy || '') + '</td>' +
                '<td>' + ui.badge(t.side || t.action || '', (t.side || t.action) === 'sell' ? 'yellow' : 'blue') + '</td>' +
                '<td>' + ui.escapeHtml(t.code || t.stock_code || '') + '</td>' +
                '<td>' + ui.escapeHtml(t.name || t.stock_name || '') + '</td>' +
                '<td>' + Number(t.price || 0).toFixed(2) + '</td>' +
                '<td>' + (t.shares || t.qty || 0) + '</td>' +
                '<td class="' + ui.pctClass(pnl) + '">' + ui.escapeHtml(t.pnl != null || t.profit != null ? ui.formatMoney(pnl) : '') + '</td>' +
                '<td>' + ui.escapeHtml(t.reason || t.message || '').slice(0, 60) + '</td>' +
                '</tr>';
        }).join('');
        ui.setHtml('historyTrades', rows ? '<div class="table-wrap"><table><thead><tr><th>时间</th><th>策略</th><th>操作</th><th>代码</th><th>名称</th><th>价格</th><th>数量</th><th>盈亏</th><th>原因</th></tr></thead><tbody>' + rows + '</tbody></table></div>' : ui.empty('暂无交易记录'));
    }

    function renderHistoricalPicks(data) {
        const dates = data.dates || [];
        const records = data.picks || data.selections || data.buys || [];
        const rows = records.slice(0, 50).map(function (p, idx) {
            return '<tr>' +
                '<td>' + (idx + 1) + '</td>' +
                '<td>' + ui.escapeHtml(p.date || data.date || '') + '</td>' +
                '<td>' + ui.escapeHtml(p.code || p.stock_code || '') + '</td>' +
                '<td>' + ui.escapeHtml(p.name || p.stock_name || '') + '</td>' +
                '<td>' + Number(p.final_score || p.total_score || p.score || 0).toFixed(1) + '</td>' +
                '<td>' + ui.escapeHtml(p.strategy || p.strategy_name || '') + '</td>' +
                '</tr>';
        }).join('');
        const status = data.execution_status === 'preview_only'
            ? '<div class="muted" style="margin-bottom:8px">' + ui.badge('研究推荐', 'yellow') + ' ' + ui.escapeHtml(data.execution_message || '该日仅生成研究预览，没有成交。') + '</div>'
            : '';
        ui.setHtml('historyPicks', status + (rows ? '<div class="table-wrap"><table><thead><tr><th>#</th><th>日期</th><th>代码</th><th>名称</th><th>分数</th><th>策略</th></tr></thead><tbody>' + rows + '</tbody></table></div>' : ui.empty(dates.length ? '请选择历史日期查看选股' : '暂无历史选股')));
    }

    window.runTask = runTask;
    window.loadOpsCenter = loadOpsCenter;
    window.loadHistoryCenter = loadHistoryCenter;
})(window);
