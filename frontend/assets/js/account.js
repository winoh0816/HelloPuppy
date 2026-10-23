(function () {
    "use strict";
    const form = document.getElementById("accountForm");
    const tabs = [...document.querySelectorAll(".account-tab")];
    const displayNameRow = document.getElementById("displayNameRow");
    const submit = document.getElementById("accountSubmit");
    const logout = document.getElementById("logoutButton");
    const status = document.getElementById("accountStatus");
    let mode = "login";

    function setMode(nextMode) {
        mode = nextMode;
        tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.mode === mode));
        displayNameRow.hidden = mode !== "register";
        form.elements.password.autocomplete = mode === "register" ? "new-password" : "current-password";
        form.elements.display_name.required = mode === "register";
        submit.textContent = mode === "register" ? "계정 만들기" : "로그인";
        status.textContent = "";
    }

    tabs.forEach((tab) => tab.addEventListener("click", () => setMode(tab.dataset.mode)));
    setMode("login");
    logout.addEventListener("click", () => window.HelloPuppyAPI.logout());
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        submit.disabled = true;
        status.textContent = "계정을 확인하고 있습니다…";
        const data = Object.fromEntries(new FormData(form).entries());
        try {
            const result = mode === "register"
                ? await window.HelloPuppyAPI.register(data)
                : await window.HelloPuppyAPI.login(data);
            window.HelloPuppyAPI.setToken(result.access_token);
            status.textContent = `로그인되었습니다. 현재 포인트 ${result.points ?? ""}P`;
            window.setTimeout(() => { window.location.href = "mypage.html"; }, 500);
        } catch (error) {
            status.textContent = error.message;
        } finally {
            submit.disabled = false;
        }
    });

    if (window.HelloPuppyAPI.isLoggedIn()) {
        form.hidden = true;
        tabs.forEach((tab) => { tab.hidden = true; });
        logout.hidden = false;
        window.HelloPuppyAPI.me().then(({ user, points }) => {
            status.textContent = `${user.display_name}님 로그인 중 · 포인트 ${points}P`;
        }).catch((error) => {
            status.textContent = error.message;
            form.hidden = false;
            tabs.forEach((tab) => { tab.hidden = false; });
            logout.hidden = true;
        });
    }
})();
