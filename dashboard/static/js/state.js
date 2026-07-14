(function (window) {
    const state = {
        activeTab: 'workspace',
        loaded: {},
        taskPoll: null,
        refreshSeconds: 0
    };

    function formatMoney(value) {
        const n = Number(value || 0);
        return n.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
    }

    function formatPct(value, digits) {
        const n = Number(value || 0);
        const d = digits == null ? 2 : digits;
        return (n >= 0 ? '+' : '') + n.toFixed(d) + '%';
    }

    function pctClass(value) {
        return Number(value || 0) >= 0 ? 'text-green' : 'text-red';
    }

    function badge(text, type) {
        return '<span class="badge badge-' + (type || 'blue') + '">' + escapeHtml(text) + '</span>';
    }

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function byId(id) {
        return document.getElementById(id);
    }

    function setHtml(id, html) {
        const el = byId(id);
        if (el) el.innerHTML = html;
    }

    function loading(id, text) {
        setHtml(id, '<div class="loading">' + escapeHtml(text || '加载中...') + '</div>');
    }

    function empty(text) {
        return '<div class="empty">' + escapeHtml(text || '暂无数据') + '</div>';
    }

    window.DashboardState = state;
    window.DashboardUI = {
        formatMoney: formatMoney,
        formatPct: formatPct,
        pctClass: pctClass,
        badge: badge,
        escapeHtml: escapeHtml,
        byId: byId,
        setHtml: setHtml,
        loading: loading,
        empty: empty
    };
})(window);
