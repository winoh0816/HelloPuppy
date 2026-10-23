
/* =========================================
   HelloPuppy 공통 설정
   ========================================= */

const SHOP_POINTS_KEY = "helloPuppyPoints";
const SHOP_HISTORY_KEY = "helloPuppyRedemptionHistory";

const LEGACY_SHOP_POINTS_KEY = "hellopuppy_points";
const LEGACY_SHOP_HISTORY_KEY = "hellopuppy_exchange_history";
const VERIFICATION_API_BASE = window.HELLOPUPPY_API_BASE || "http://127.0.0.1:8000";
const VERIFIED_ACTIVITY_KEY = "helloPuppyVerifiedActivityLog";

let isBuyingItem = false;
let shopToastTimer = null;


/* =========================================
   공통 로딩 모달
   ========================================= */

function showLoading(message, callback, delay = 2500) {
    const modal = document.getElementById("loading-modal");
    const msgEl = document.getElementById("loading-msg");
    const spinner = document.getElementById("loading-spinner");

    if (!modal || !msgEl || !spinner) {
        if (callback.action) {
            callback.action();
        }
        return;
    }

    modal.style.display = "flex";
    msgEl.innerHTML = message;
    spinner.style.display = "block";

    setTimeout(() => {
        spinner.style.display = "none";
        msgEl.innerHTML = callback.message;

        setTimeout(() => {
            modal.style.display = "none";

            if (callback.action) {
                callback.action();
            }
        }, 1500);
    }, delay);
}


/* =========================================
   포인트 조회 및 저장
   ========================================= */

// 현재 보유 포인트 조회
function getShopPoints() {
    let savedPoints = localStorage.getItem(SHOP_POINTS_KEY);

    // 이전 버전의 포인트 데이터가 있으면 가져옵니다.
    if (savedPoints === null) {
        const legacyPoints = localStorage.getItem(
            LEGACY_SHOP_POINTS_KEY
        );

        if (legacyPoints !== null) {
            const parsedPoints = Number(legacyPoints);

            savedPoints =
                Number.isFinite(parsedPoints) && parsedPoints >= 0
                    ? String(Math.floor(parsedPoints))
                    : "0";

            localStorage.setItem(SHOP_POINTS_KEY, savedPoints);
        }
    }

    // 최초 실행 시 시연용 포인트 1,500P 지급
    if (savedPoints === null) {
        localStorage.setItem(SHOP_POINTS_KEY, "1500");
        return 1500;
    }

    const points = Number(savedPoints);

    return Number.isFinite(points) && points >= 0
        ? Math.floor(points)
        : 0;
}


// 포인트 저장
function setShopPoints(points) {
    const safePoints = Math.max(
        0,
        Math.floor(Number(points) || 0)
    );

    localStorage.setItem(
        SHOP_POINTS_KEY,
        String(safePoints)
    );
}


// 산책·급여·영수증 인증 공통 포인트 적립 함수
function addShopPoints(amount, reason) {
    const safeAmount = Number(amount);

    if (
        !Number.isSafeInteger(safeAmount) ||
        safeAmount <= 0
    ) {
        console.error("잘못된 포인트 적립 금액:", amount);
        return false;
    }

    try {
        const currentPoints = getShopPoints();
        const updatedPoints = currentPoints + safeAmount;

        setShopPoints(updatedPoints);

        console.log(
            `${reason}: ${safeAmount}P 적립 완료. 현재 잔액: ${updatedPoints}P`
        );

        return true;
    } catch (error) {
        console.error("포인트 적립 실패:", error);

        alert(
            "포인트 저장에 실패했습니다. 브라우저 저장 공간을 확인해 주세요."
        );

        return false;
    }
}


// 인증 성공 활동의 시각만 건강 요약에 기록합니다. 사진 원본은 저장하지 않습니다.
function recordVerifiedActivity(activity, confidence) {
    try {
        const saved = JSON.parse(localStorage.getItem(VERIFIED_ACTIVITY_KEY) || "[]");
        const activities = Array.isArray(saved) ? saved : [];
        activities.push({
            activity,
            recordedAt: new Date().toISOString(),
            confidence: Number.isFinite(Number(confidence)) ? Number(confidence) : null
        });
        localStorage.setItem(VERIFIED_ACTIVITY_KEY, JSON.stringify(activities.slice(-5000)));
    } catch (error) {
        console.error("인증 활동 기록을 저장하지 못했습니다.", error);
    }
}


/* =========================================
   산책 인증
   ========================================= */

function startCameraAuth() {
    return verifyActivityPhoto("walk", "walk-photo", "walk-photo-status", 100);
}


/* =========================================
   영수증 인증
   ========================================= */

function startOCR() {
    const receiptImage = document.getElementById("receipt-img");

    if (receiptImage) {
        receiptImage.style.filter = "brightness(0.5)";
    }

    showLoading(
        "영수증 품목 텍스트를<br>추출하고 있습니다...",
        {
            message:
                "🎉 분석 완료!<br>" +
                "로얄캐닌 사료 외 1건 (15,000원)<br>" +
                "영수증 인증 포인트 30P가 적립되었습니다.",

            action: () => {
                if (receiptImage) {
                    receiptImage.style.filter = "none";
                }

                // 영수증 분석 완료 시 30P 적립
                addShopPoints(30, "영수증 인증");
            }
        }
    );
}


/* =========================================
   HelloPuppy 포인트 상점
   ========================================= */

// 시연용 상품 데이터
const shopProducts = [
    {
        id: "snack-001",
        name: "조인트 덴탈 츄 샘플팩",
        category: "영양제",
        description: "관절 관리용 샘플 상품",
        price: 500,
        icon: "assets/images/brand/icon-bone.png"
    },
    {
        id: "food-001",
        name: "프리미엄 연어 화식 100g",
        category: "사료",
        description: "연어 레시피 체험팩",
        price: 1000,
        icon: "assets/images/brand/emoji-drink.png"
    },
    {
        id: "snack-002",
        name: "수제 트릿 체험팩",
        category: "간식",
        description: "반려견 간식 샘플",
        price: 300,
        icon: "assets/images/brand/emoji-best.png"
    },
    {
        id: "food-002",
        name: "소형견 맞춤 사료 샘플",
        category: "사료",
        description: "사료 체험용 소포장",
        price: 700,
        icon: "assets/images/brand/emoji-start.png"
    },
    {
        id: "health-001",
        name: "반려견 영양 케어 샘플",
        category: "영양제",
        description: "영양제 체험용 샘플",
        price: 800,
        icon: "assets/images/brand/icon-paw.png"
    },
    {
        id: "goods-001",
        name: "산책 배변봉투 세트",
        category: "용품",
        description: "산책에 필요한 기본 용품",
        price: 400,
        icon: "assets/images/brand/icon-bone.png"
    }
];


// HTML에 표시할 문자열 안전 처리
function escapeShopText(value) {
    return String(value).replace(/[&<>"']/g, function (char) {
        const entities = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        };

        return entities[char];
    });
}


// 교환 내역 조회
function getRedemptionHistory() {
    try {
        let savedHistory = localStorage.getItem(
            SHOP_HISTORY_KEY
        );

        if (savedHistory === null) {
            savedHistory = localStorage.getItem(
                LEGACY_SHOP_HISTORY_KEY
            );
        }

        const history = JSON.parse(savedHistory || "[]");

        return Array.isArray(history) ? history : [];
    } catch (error) {
        console.error("교환 내역을 읽지 못했습니다.", error);
        return [];
    }
}


// 상점 알림 표시
function showShopToast(message) {
    const toast = document.getElementById("shopToast");

    if (!toast) {
        console.info(message);
        return;
    }

    toast.textContent = message;
    toast.hidden = false;

    clearTimeout(shopToastTimer);

    shopToastTimer = setTimeout(() => {
        toast.hidden = true;
    }, 2500);
}


// 현재 선택된 카테고리 조회
function getActiveShopCategory() {
    const activeButton = document.querySelector(
        ".shop-filter-btn.active"
    );

    return activeButton?.dataset.category || "all";
}


// 보유 포인트 표시
function renderShopBalance() {
    const pointsElement = document.getElementById("pointBalance");

    if (!pointsElement) {
        return;
    }

    pointsElement.textContent =
        getShopPoints().toLocaleString("ko-KR");
}


// 상품 목록 표시
function renderShopProducts(category = "all") {
    const grid = document.getElementById("productGrid");

    if (!grid) {
        return;
    }

    const points = getShopPoints();

    const filteredProducts = category === "all"
        ? shopProducts
        : shopProducts.filter(function (product) {
            return product.category === category;
        });

    if (filteredProducts.length === 0) {
        grid.innerHTML = `
            <div class="shop-empty-history">
                해당 카테고리에 상품이 없습니다.
            </div>
        `;

        return;
    }

    grid.innerHTML = filteredProducts.map(function (product) {
        const canAfford = points >= product.price;
        const disabled = !canAfford || isBuyingItem;

        return `
            <article class="shop-product-card">
                <div class="shop-product-visual" aria-hidden="true">
                    <img src="${escapeShopText(product.icon)}" alt="">
                </div>

                <div class="shop-product-info">
                    <div class="shop-product-category">
                        ${escapeShopText(product.category)}
                    </div>

                    <h3 class="shop-product-name">
                        ${escapeShopText(product.name)}
                    </h3>

                    <p class="shop-product-description">
                        ${escapeShopText(product.description)}
                    </p>

                    <div class="shop-product-price">
                        ${product.price.toLocaleString("ko-KR")} P
                    </div>

                    <button
                        type="button"
                        class="shop-buy-btn"
                        data-buy-id="${escapeShopText(product.id)}"
                        ${disabled ? "disabled" : ""}
                    >
                        ${
                            isBuyingItem
                                ? "처리 중..."
                                : canAfford
                                    ? "포인트로 교환"
                                    : "포인트 부족"
                        }
                    </button>
                </div>
            </article>
        `;
    }).join("");
}


// 교환 내역 표시
function renderRedemptionHistory() {
    const container = document.getElementById("exchangeHistory");

    if (!container) {
        return;
    }

    const history = getRedemptionHistory();

    if (history.length === 0) {
        container.innerHTML = `
            <div class="shop-empty-history">
                아직 교환한 상품이 없어요.<br>
                마음에 드는 상품을 교환해 보세요! 🐾
            </div>
        `;

        return;
    }

    container.innerHTML = history.map(function (item) {
        const name = escapeShopText(item.name || "상품");
        const date = escapeShopText(item.date || "");
        const icon = escapeShopText(item.icon || "🎁");
        const iconMarkup = icon.startsWith("assets/images/brand/")
            ? `<img src="${icon}" alt="">`
            : icon;

        const cost = Number(item.cost ?? item.price ?? 0);
        const safeCost = Number.isFinite(cost) && cost >= 0
            ? cost
            : 0;

        return `
            <div class="shop-history-item">
                <div class="shop-history-icon" aria-hidden="true">
                    ${iconMarkup}
                </div>

                <div class="shop-history-details">
                    <div class="shop-history-name">
                        ${name}
                    </div>

                    <div class="shop-history-date">
                        ${date}
                    </div>
                </div>

                <div class="shop-history-price">
                    -${safeCost.toLocaleString("ko-KR")} P
                </div>
            </div>
        `;
    }).join("");
}


// 상점 화면 갱신
function renderShop() {
    renderShopBalance();
    renderShopProducts(getActiveShopCategory());
    renderRedemptionHistory();
}


// 상품 교환
function buyItem(productId, cost, productName) {
    if (isBuyingItem) {
        return;
    }

    const product = shopProducts.find(function (item) {
        return item.id === productId;
    });

    if (!product) {
        showShopToast("상품 정보를 찾을 수 없습니다.");
        return;
    }

    const purchaseCost = cost === undefined
        ? product.price
        : Number(cost);

    const purchaseName = productName === undefined
        ? product.name
        : productName;

    if (
        !Number.isSafeInteger(purchaseCost) ||
        purchaseCost <= 0 ||
        typeof purchaseName !== "string"
    ) {
        showShopToast("상품 정보가 올바르지 않습니다.");
        return;
    }

    const currentPoints = getShopPoints();

    if (currentPoints < purchaseCost) {
        showShopToast("포인트가 부족해요. 미션에 참여해 보세요!");
        return;
    }

    const confirmed = confirm(
        `${purchaseName}\n\n` +
        `교환 포인트: ${purchaseCost.toLocaleString("ko-KR")} P\n` +
        `교환 후 잔액: ${(currentPoints - purchaseCost).toLocaleString("ko-KR")} P\n\n` +
        "교환하시겠어요?"
    );

    if (!confirmed) {
        return;
    }

    isBuyingItem = true;

    renderShopProducts(getActiveShopCategory());

    showShopToast("🎁 상품 교환을 처리하고 있습니다...");

    setTimeout(function () {
        completeShopPurchase();
    }, 700);

    function completeShopPurchase() {
        try {
            const latestPoints = getShopPoints();

            if (latestPoints < purchaseCost) {
                showShopToast(
                    "포인트가 부족하여 교환을 완료하지 못했습니다."
                );

                return;
            }

            const history = getRedemptionHistory();

            history.unshift({
                id: product.id,
                name: purchaseName,
                icon: product.icon,
                cost: purchaseCost,
                date: new Date().toLocaleString("ko-KR")
            });

            // 교환 내역을 저장한 후 포인트를 차감합니다.
            localStorage.setItem(
                SHOP_HISTORY_KEY,
                JSON.stringify(history)
            );

            setShopPoints(latestPoints - purchaseCost);

            showShopToast(
                `${purchaseName} 교환이 완료되었어요! 🐶`
            );
        } catch (error) {
            console.error("상품 교환 처리 오류:", error);

            showShopToast(
                "저장에 실패했습니다. 브라우저 저장 공간을 확인해 주세요."
            );
        } finally {
            isBuyingItem = false;
            renderShop();
        }
    }
}


// 상점 페이지 이벤트 등록
function initPointShop() {
    const productGrid = document.getElementById("productGrid");

    // 상점 요소가 없는 페이지에서는 실행하지 않습니다.
    if (!productGrid) {
        return;
    }

    // 카테고리 필터
    document.querySelectorAll(".shop-filter-btn").forEach(function (button) {
        button.addEventListener("click", function () {
            document.querySelectorAll(".shop-filter-btn").forEach(
                function (item) {
                    item.classList.remove("active");
                    item.setAttribute("aria-pressed", "false");
                }
            );

            button.classList.add("active");
            button.setAttribute("aria-pressed", "true");

            renderShopProducts(button.dataset.category);
        });
    });

    // 상품 교환 버튼
    productGrid.addEventListener("click", function (event) {
        const button = event.target.closest("[data-buy-id]");

        if (!button || button.disabled) {
            return;
        }

        buyItem(button.dataset.buyId);
    });

    renderShop();
}


/* =========================================
   식사/급여 인증
   ========================================= */

// 촬영한 급여 사진 미리보기
function previewFeedingPhoto(event) {
    previewVerificationPhoto(event, "feeding");
}


// 사진 미리보기 및 파일 형식 확인
function previewVerificationPhoto(event, activity) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;

    const statusId = activity === "walk" ? "walk-photo-status" : "feeding-photo-status";
    const previewId = activity === "walk" ? "walk-preview" : "feeding-img";
    const status = document.getElementById(statusId);
    const preview = document.getElementById(previewId);

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
        const objectUrl = URL.createObjectURL(file);
        preview.dataset.objectUrl = objectUrl;
        preview.src = objectUrl;
    }
    if (status) status.textContent = "사진이 선택되었습니다. AI 검증을 진행해 주세요.";
}


// 서버 판별 결과로만 인증을 완료하고 포인트를 적립
async function verifyActivityPhoto(activity, inputId, statusId, points) {
    const input = document.getElementById(inputId);
    const status = document.getElementById(statusId);
    const file = input && input.files && input.files[0];
    if (!file) {
        if (status) status.textContent = "먼저 인증할 사진을 촬영해 주세요.";
        return;
    }

    const modal = document.getElementById("loading-modal");
    const message = document.getElementById("loading-msg");
    const spinner = document.getElementById("loading-spinner");
    const scanLine = document.querySelector(".scan-line");
    if (modal && message && spinner) {
        message.textContent = "백엔드 AI가 사진을 판별하고 있습니다...";
        spinner.style.display = "block";
        modal.style.display = "flex";
    }
    if (scanLine) scanLine.style.display = "block";

    try {
        const form = new FormData();
        form.append("photo", file, file.name);
        const response = await fetch(
            `${VERIFICATION_API_BASE}/api/verify/${activity}`,
            { method: "POST", body: form }
        );
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(result.detail || "인증 서버에 연결할 수 없습니다.");
        }

        if (!result.verified) {
            const note = result.message || "요청한 활동을 사진에서 확인하지 못했습니다.";
            if (status) status.textContent = `${note} 포인트는 적립되지 않았습니다.`;
            if (message) message.textContent = note;
            return;
        }

        const earned = addShopPoints(points, activity === "walk" ? "산책 인증" : "급여 인증");
        if (earned) recordVerifiedActivity(activity, result.confidence);
        const success = earned
            ? `인증 성공! ${points}P가 적립되었습니다. (AI 신뢰도 ${(result.confidence * 100).toFixed(1)}%)`
            : "인증은 성공했지만 포인트 저장에 실패했습니다.";
        if (status) status.textContent = success;
        if (message) message.textContent = success;
        if (earned) {
            window.setTimeout(() => { window.location.href = "feed.html"; }, 1400);
        }
    } catch (error) {
        const note = error instanceof Error ? error.message : "인증 중 오류가 발생했습니다.";
        if (status) status.textContent = `${note} 포인트는 적립되지 않았습니다.`;
        if (message) message.textContent = note;
    } finally {
        if (scanLine) scanLine.style.display = "none";
        if (spinner) spinner.style.display = "none";
        if (modal) {
            window.setTimeout(() => { modal.style.display = "none"; }, 1200);
        }
    }
}


// 급여 사진 인증
function startFeedingAuth() {
    return verifyActivityPhoto("feeding", "feeding-photo", "feeding-photo-status", 50);
}


/* =========================================
   페이지 초기화
   ========================================= */

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initPointShop);
} else {
    initPointShop();
}
