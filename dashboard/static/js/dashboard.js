(function (window) {
    const state = window.DashboardState;
    const ui = window.DashboardUI;

    const loaders = {
        workspace: window.loadWorkspace,
        strategy: window.loadStrategyCenter,
        memory: window.loadMemoryCenter,
        history: window.loadHistoryCenter,
        ops: window.loadOpsCenter
    };

    function switchTab(name, force) {
        state.activeTab = name;
        document.querySelectorAll('.nav-tab').forEach(function (tab) {
            tab.classList.toggle('active', tab.dataset.tab === name);
        });
        document.querySelectorAll('.tab-panel').forEach(function (panel) {
            panel.classList.toggle('active', panel.id === 'tab-' + name);
        });
        if (force || !state.loaded[name]) {
            state.loaded[name] = true;
            if (loaders[name]) loaders[name]();
        }
    }

    function updateClock() {
        const now = new Date();
        ui.setHtml('currentTime', now.toLocaleTimeString('zh-CN'));
        ui.setHtml('currentDate', now.toLocaleDateString('zh-CN'));
    }

    function startAutoRefresh() {
        setInterval(function () {
            state.refreshSeconds += 1;
            const pct = Math.min(100, state.refreshSeconds / 60 * 100);
            const progress = ui.byId('refreshProgress');
            if (progress) progress.style.width = pct + '%';
            if (state.refreshSeconds >= 60) {
                state.refreshSeconds = 0;
                if (progress) progress.style.width = '0%';
                if (['workspace', 'ops'].includes(state.activeTab)) {
                    switchTab(state.activeTab, true);
                }
            }
        }, 1000);
    }

    async function refreshDataBanner() {
        const banner = ui.byId('dataSourceBanner');
        if (!banner || !window.DashboardAPI) return;
        try {
            const data = await window.DashboardAPI.get('/api/dashboard/workspace');
            const demo = data.demo_state || {};
            const memory = data.memory_health || {};
            const messages = [];
            if (demo.is_demo) messages.push(demo.message || '当前包含演示数据');
            if (memory.simulated_total > 0) messages.push('记忆库仍有演示记录 ' + memory.simulated_total + ' 条');
            if (messages.length) {
                banner.style.display = 'block';
                banner.textContent = messages.join('；');
            } else {
                banner.style.display = 'none';
                banner.textContent = '';
            }
        } catch (err) {
            banner.style.display = 'block';
            banner.textContent = '数据来源状态检查失败：' + err.message;
        }
    }

    function boot() {
        document.querySelectorAll('.nav-tab').forEach(function (tab) {
            tab.addEventListener('click', function () {
                switchTab(tab.dataset.tab);
            });
        });
        updateClock();
        setInterval(updateClock, 1000);
        startAutoRefresh();
        refreshDataBanner();
        switchTab('workspace', true);
    }

    window.switchTab = switchTab;
    document.addEventListener('DOMContentLoaded', boot);
})(window);
