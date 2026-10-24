(function () {
    "use strict";
    const summary = document.getElementById("accountSummary");
    const status = document.getElementById("accountDashboardStatus");
    const headerAction = document.getElementById("accountHeaderAction");
    if (!window.HelloPuppyAPI?.isLoggedIn()) {
        summary.innerHTML = '<div class="health-empty"><strong>로그인이 필요합니다.</strong><span>계정을 만들거나 로그인하면 내 데이터와 포인트를 확인할 수 있습니다.</span><a class="health-primary-btn" href="account.html">로그인 / 계정 만들기</a></div>';
        return;
    }
    headerAction.textContent = "로그아웃";
    headerAction.href = "#";
    headerAction.addEventListener("click", (event) => {
        event.preventDefault();
        window.HelloPuppyAPI.logout();
    });
    Promise.all([window.HelloPuppyAPI.me(), window.HelloPuppyAPI.request("/api/pet/profile")])
        .then(([account, petResult]) => {
            const pet = petResult.profile || {};
            summary.innerHTML = `<img class="account-logo" src="assets/images/brand/puppy-app-icon.png" alt=""><h2>${escapeHtml(account.user.display_name)}</h2><p>${escapeHtml(account.user.email)}</p><div class="shop-balance-number">${Number(account.points).toLocaleString("ko-KR")} P</div><div class="account-pet-summary">반려견: ${escapeHtml(pet.name || "정보 미입력")} · ${escapeHtml(pet.breed || "견종 미입력")}</div>`;
        })
        .catch((error) => { status.textContent = error.message; });

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
    }
})();
