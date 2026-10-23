/* Central authenticated API client. Only the short-lived bearer token is kept in browser storage. */
(function () {
    "use strict";

    const API_BASE = window.HELLOPUPPY_API_BASE || "http://127.0.0.1:8000";
    const TOKEN_KEY = "helloPuppyAccessToken";

    async function request(path, options = {}) {
        const headers = new Headers(options.headers || {});
        const token = localStorage.getItem(TOKEN_KEY);
        if (token) headers.set("Authorization", `Bearer ${token}`);
        if (options.body && !(options.body instanceof FormData)) {
            headers.set("Content-Type", "application/json");
        }
        let response;
        try {
            response = await fetch(`${API_BASE}${path}`, { ...options, headers });
        } catch (error) {
            throw new Error("백엔드에 연결할 수 없습니다. SQLite API 서버가 실행 중인지 확인하세요.");
        }
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            if (response.status === 401) localStorage.removeItem(TOKEN_KEY);
            throw new Error(payload.detail || `요청에 실패했습니다 (${response.status}).`);
        }
        return payload;
    }

    async function imageUrl(imageId) {
        const token = localStorage.getItem(TOKEN_KEY);
        const response = await fetch(`${API_BASE}/api/images/${encodeURIComponent(imageId)}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {}
        });
        if (!response.ok) throw new Error("사진을 불러오지 못했습니다.");
        return URL.createObjectURL(await response.blob());
    }

    window.HelloPuppyAPI = {
        baseUrl: API_BASE,
        request,
        imageUrl,
        token: () => localStorage.getItem(TOKEN_KEY),
        setToken: (token) => localStorage.setItem(TOKEN_KEY, token),
        clearToken: () => localStorage.removeItem(TOKEN_KEY),
        isLoggedIn: () => Boolean(localStorage.getItem(TOKEN_KEY)),
        register: (data) => request("/api/auth/register", { method: "POST", body: JSON.stringify(data) }),
        login: (data) => request("/api/auth/login", { method: "POST", body: JSON.stringify(data) }),
        me: () => request("/api/auth/me"),
        logout: async () => {
            try { if (localStorage.getItem(TOKEN_KEY)) await request("/api/auth/logout", { method: "POST" }); }
            catch (error) { console.warn("서버 로그아웃 처리:", error.message); }
            localStorage.removeItem(TOKEN_KEY);
            window.location.href = "account.html";
        }
    };
})();
