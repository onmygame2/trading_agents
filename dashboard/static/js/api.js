(function (window) {
    async function request(path, options) {
        const response = await fetch(path, options || {});
        const data = await response.json().catch(function () { return {}; });
        if (!response.ok) {
            throw new Error(data.error || data.message || ('请求失败: ' + path));
        }
        return data;
    }

    function get(path) {
        return request(path);
    }

    function post(path, body) {
        return request(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {})
        });
    }

    window.DashboardAPI = {
        get: get,
        post: post
    };
})(window);
