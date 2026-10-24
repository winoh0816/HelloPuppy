/* Shared UI behavior. Durable user data is stored through the authenticated SQLite API. */
const VERIFICATION_API_BASE = window.HELLOPUPPY_API_BASE || "http://127.0.0.1:8000";
let isBuyingItem = false;
let shopToastTimer = null;
let shopBalance = 0;
let shopHistory = [];

const shopProducts = [
    { id: "snack-001", name: "조인트 덴탈 츄 샘플팩", category: "영양제", description: "관절 관리용 샘플 상품", price: 500, icon: "assets/images/brand/icon-bone.png" },
    { id: "food-001", name: "프리미엄 연어 화식 100g", category: "사료", description: "연어 레시피 체험팩", price: 1000, icon: "assets/images/brand/emoji-drink.png" },
    { id: "snack-002", name: "수제 트릿 체험팩", category: "간식", description: "반려견 간식 샘플", price: 300, icon: "assets/images/brand/emoji-best.png" },
    { id: "food-002", name: "소형견 맞춤 사료 샘플", category: "사료", description: "사료 체험용 소포장", price: 700, icon: "assets/images/brand/emoji-start.png" },
    { id: "health-001", name: "반려견 영양 케어 샘플", category: "영양제", description: "영양제 체험용 샘플", price: 800, icon: "assets/images/brand/icon-paw.png" },
    { id: "goods-001", name: "산책 배변봉투 세트", category: "용품", description: "산책에 필요한 기본 용품", price: 400, icon: "assets/images/brand/icon-bone.png" }
];

function requireAccount() {
    if (!window.HelloPuppyAPI?.isLoggedIn()) {
        window.location.href = "account.html";
        return false;
    }
    return true;
}

function apiRequest(path, options) {
    if (!window.HelloPuppyAPI) throw new Error("API 클라이언트가 로드되지 않았습니다.");
    return window.HelloPuppyAPI.request(path, options);
}

function setSessionPoints(balance) {
    const parsed = Number(balance);
    if (Number.isFinite(parsed)) shopBalance = Math.max(0, parsed);
    renderShopBalance();
}

function showLoading(message, callback, delay = 1800) {
    const modal = document.getElementById("loading-modal");
    const messageElement = document.getElementById("loading-msg");
    const spinner = document.getElementById("loading-spinner");
    if (!modal || !messageElement || !spinner) {
        callback?.action?.();
        return;
    }
    modal.style.display = "flex";
    messageElement.innerHTML = message;
    spinner.style.display = "block";
    window.setTimeout(() => {
        spinner.style.display = "none";
        messageElement.innerHTML = callback.message || "";
        window.setTimeout(() => {
            modal.style.display = "none";
            callback?.action?.();
        }, 1400);
    }, delay);
}

function escapeShopText(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);
}

function showShopToast(message) {
    const toast = document.getElementById("shopToast");
    if (!toast) { window.alert(message); return; }
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(shopToastTimer);
    shopToastTimer = window.setTimeout(() => { toast.hidden = true; }, 3000);
}

function getActiveShopCategory() {
    return document.querySelector(".shop-filter-btn.active")?.dataset.category || "all";
}

function renderShopBalance() {
    const element = document.getElementById("pointBalance");
    if (element) element.textContent = shopBalance.toLocaleString("ko-KR");
}

function renderShopProducts(category = "all") {
    const grid = document.getElementById("productGrid");
    if (!grid) return;
    const products = category === "all" ? shopProducts : shopProducts.filter((product) => product.category === category);
    grid.innerHTML = products.map((product) => {
        const canAfford = shopBalance >= product.price;
        return `<article class="shop-product-card">
            <div class="shop-product-visual" aria-hidden="true"><img src="${escapeShopText(product.icon)}" alt=""></div>
            <div class="shop-product-info"><div class="shop-product-category">${escapeShopText(product.category)}</div>
            <h3 class="shop-product-name">${escapeShopText(product.name)}</h3>
            <p class="shop-product-description">${escapeShopText(product.description)}</p>
            <div class="shop-product-price">${product.price.toLocaleString("ko-KR")} P</div>
            <button type="button" class="shop-buy-btn" data-buy-id="${escapeShopText(product.id)}" ${!canAfford || isBuyingItem ? "disabled" : ""}>${isBuyingItem ? "처리 중..." : canAfford ? "포인트로 교환" : "포인트 부족"}</button>
            </div></article>`;
    }).join("");
}

function renderRedemptionHistory() {
    const container = document.getElementById("exchangeHistory");
    if (!container) return;
    if (!shopHistory.length) {
        container.innerHTML = '<div class="shop-empty-history">아직 교환한 상품이 없어요.<br>마음에 드는 상품을 교환해 보세요!</div>';
        return;
    }
    container.innerHTML = shopHistory.map((item) => {
        const product = shopProducts.find((entry) => entry.id === item.product_id);
        const iconPath = product?.icon || "assets/images/brand/icon-bone.png";
        return `<div class="shop-history-item"><div class="shop-history-icon" aria-hidden="true"><img src="${escapeShopText(iconPath)}" alt=""></div>
            <div class="shop-history-details"><div class="shop-history-name">${escapeShopText(item.product_name)}</div>
            <div class="shop-history-date">${escapeShopText(new Date(item.created_at).toLocaleString("ko-KR"))}</div></div>
            <div class="shop-history-price">-${Number(item.cost).toLocaleString("ko-KR")} P</div></div>`;
    }).join("");
}

async function loadShopData() {
    try {
        const [points, history] = await Promise.all([apiRequest("/api/points"), apiRequest("/api/shop/redemptions")]);
        setSessionPoints(points.balance);
        shopHistory = history.items || [];
        renderShopProducts(getActiveShopCategory());
        renderRedemptionHistory();
    } catch (error) { showShopToast(error.message); }
}

async function buyItem(productId) {
    if (isBuyingItem || !requireAccount()) return;
    const product = shopProducts.find((item) => item.id === productId);
    if (!product) { showShopToast("상품 정보를 찾을 수 없습니다."); return; }
    if (shopBalance < product.price) { showShopToast("포인트가 부족해요. 미션에 참여해 보세요!"); return; }
    if (!window.confirm(`${product.name}\n\n교환 포인트: ${product.price.toLocaleString("ko-KR")} P\n교환하시겠어요?`)) return;
    isBuyingItem = true;
    renderShopProducts(getActiveShopCategory());
    try {
        const result = await apiRequest("/api/shop/redeem", { method: "POST", body: JSON.stringify({ product_id: productId }) });
        setSessionPoints(result.balance);
        showShopToast(`${result.redemption.product_name} 교환이 완료되었어요!`);
        await loadShopData();
    } catch (error) { showShopToast(error.message); }
    finally { isBuyingItem = false; renderShopProducts(getActiveShopCategory()); }
}

function initPointShop() {
    const grid = document.getElementById("productGrid");
    if (!grid) return;
    if (!requireAccount()) return;
    document.querySelectorAll(".shop-filter-btn").forEach((button) => button.addEventListener("click", () => {
        document.querySelectorAll(".shop-filter-btn").forEach((item) => {
            item.classList.remove("active"); item.setAttribute("aria-pressed", "false");
        });
        button.classList.add("active"); button.setAttribute("aria-pressed", "true");
        renderShopProducts(button.dataset.category);
    }));
    grid.addEventListener("click", (event) => {
        const button = event.target.closest("[data-buy-id]");
        if (button && !button.disabled) buyItem(button.dataset.buyId);
    });
    loadShopData();
}

async function initHomeAccountSummary() {
    const points = document.getElementById("homePoints");
    if (!points) return;
    if (!window.HelloPuppyAPI?.isLoggedIn()) {
        points.innerHTML = '<a href="account.html">로그인</a> 후 포인트 확인';
        return;
    }
    try {
        const result = await apiRequest("/api/points");
        points.textContent = `🐾 ${Number(result.balance).toLocaleString("ko-KR")} P`;
    } catch (_) { points.innerHTML = '<a href="account.html">다시 로그인</a>'; }
}

function startCameraAuth() {
    return verifyActivityPhoto("walk", "walk-photo", "walk-photo-status");
}

function startOCR() {
    const receiptImage = document.getElementById("receipt-img");
    if (receiptImage) receiptImage.style.filter = "brightness(0.5)";
    showLoading("영수증을 분석하는 중입니다...", {
        message: "OCR 기능은 아직 데모 상태입니다.<br>실제 영수증 검증 전에는 포인트가 적립되지 않습니다.",
        action: () => { if (receiptImage) receiptImage.style.filter = "none"; }
    });
}

function previewFeedingPhoto(event) { previewVerificationPhoto(event, "feeding"); }

function previewVerificationPhoto(event, activity) {
    const file = event.target.files?.[0];
    if (!file) return;
    const status = document.getElementById(activity === "walk" ? "walk-photo-status" : "feeding-photo-status");
    const preview = document.getElementById(activity === "walk" ? "walk-preview" : "feeding-img");
    if (!file.type.startsWith("image/")) {
        if (status) status.textContent = "이미지 파일을 선택해 주세요.";
        event.target.value = "";
        return;
    }
    if (file.size > 12 * 1024 * 1024) {
        if (status) status.textContent = "사진은 12MB 이하로 선택해 주세요.";
        event.target.value = "";
        return;
    }
    if (preview) {
        if (preview.dataset.objectUrl) URL.revokeObjectURL(preview.dataset.objectUrl);
        preview.dataset.objectUrl = URL.createObjectURL(file);
        preview.src = preview.dataset.objectUrl;
    }
    if (status) status.textContent = "사진이 선택되었습니다. AI 검증을 진행해 주세요.";
}

async function verifyActivityPhoto(activity, inputId, statusId) {
    const input = document.getElementById(inputId);
    const status = document.getElementById(statusId);
    const file = input?.files?.[0];
    if (!file) { if (status) status.textContent = "먼저 인증할 사진을 촬영해 주세요."; return; }
    if (!requireAccount()) return;
    const modal = document.getElementById("loading-modal");
    const message = document.getElementById("loading-msg");
    const spinner = document.getElementById("loading-spinner");
    const scanLine = document.querySelector(".scan-line");
    if (modal && message && spinner) {
        message.textContent = "백엔드 AI가 사진을 판별하고 있습니다...";
        spinner.style.display = "block"; modal.style.display = "flex";
    }
    if (scanLine) scanLine.style.display = "block";
    try {
        const form = new FormData(); form.append("photo", file, file.name);
        const token = window.HelloPuppyAPI.token();
        const response = await fetch(`${VERIFICATION_API_BASE}/api/verify/${activity}`, {
            method: "POST", body: form, headers: { Authorization: `Bearer ${token}` }
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.detail || "인증 서버에 연결할 수 없습니다.");
        if (result.demo) {
            const note = result.message || "시연 모드 판정이 완료되었습니다. 실제 포인트는 적립되지 않았습니다.";
            if (status) status.textContent = note;
            if (message) message.textContent = note;
            return;
        }
        if (!result.verified) {
            const note = result.message || "요청한 활동을 사진에서 확인하지 못했습니다.";
            if (status) status.textContent = `${note} 포인트는 적립되지 않았습니다.`;
            if (message) message.textContent = note;
            return;
        }
        const success = `인증 성공! ${result.points_awarded}P가 DB에 적립되었습니다. (현재 ${Number(result.balance).toLocaleString("ko-KR")}P)`;
        if (status) status.textContent = success;
        if (message) message.textContent = success;
        window.setTimeout(() => { window.location.href = "feed.html"; }, 1400);
    } catch (error) {
        const note = error instanceof Error ? error.message : "인증 중 오류가 발생했습니다.";
        if (status) status.textContent = `${note} 포인트는 적립되지 않았습니다.`;
        if (message) message.textContent = note;
    } finally {
        if (scanLine) scanLine.style.display = "none";
        if (spinner) spinner.style.display = "none";
        if (modal) window.setTimeout(() => { modal.style.display = "none"; }, 1200);
    }
}

function startFeedingAuth() { return verifyActivityPhoto("feeding", "feeding-photo", "feeding-photo-status"); }

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => { initPointShop(); initHomeAccountSummary(); });
} else {
    initPointShop(); initHomeAccountSummary();
}
