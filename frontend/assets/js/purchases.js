/* Pet-supply purchase log: spending summary, monthly and category charts, most bought products, and per-receipt items
   that the user can correct (corrections also improve the OCR training labels) plus the training-data consent toggle.
   Item names come from OCR and from the user, so all text is set with textContent. */
(function () {
    "use strict";

    const api = window.HelloPuppyAPI;
    const $ = (id) => document.getElementById(id);
    const status = $("purchaseStatus");
    const REASONS = { duplicate: "이미 기록한 영수증", not_pet: "반려용품 없음", no_amount: "금액을 못 읽음" };
    let categories = [];

    const won = (value) => `${Number(value || 0).toLocaleString("ko-KR")}원`;
    const shortWon = (value) => {
        const n = Number(value || 0);
        return n >= 10000 ? `${(n / 10000).toFixed(n % 10000 === 0 ? 0 : 1)}만` : n.toLocaleString("ko-KR");
    };

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }

    function renderSummary(summary) {
        $("spendTotal").textContent = won(summary.total_spent);
        $("spendRange").textContent = summary.first_date
            ? `영수증 ${summary.receipt_count}장, ${summary.first_date.replaceAll("-", ".")} ~ ${summary.last_date.replaceAll("-", ".")}`
            : "";
        $("spendThisMonth").textContent = won(summary.this_month_spent);
        $("spendPerMonth").textContent = won(summary.average_per_month);
        $("spendPerReceipt").textContent = won(summary.average_per_receipt);

        // 월별 막대: 한 가지 색, 지출이 있는 달만 값 라벨 (이번 달은 진하게)
        const bars = $("monthlyBars");
        bars.replaceChildren();
        const max = Math.max(...summary.monthly.map((m) => m.amount), 1);
        summary.monthly.forEach((month, index) => {
            const isLast = index === summary.monthly.length - 1;
            const item = el("div", `month-bar${isLast ? " is-current" : ""}`);
            item.setAttribute("role", "listitem");
            const label = `${Number(month.month.slice(5))}월 ${won(month.amount)}`;
            item.title = label;
            item.setAttribute("aria-label", label);
            item.tabIndex = 0;
            const value = el("span", "month-bar-value", month.amount ? shortWon(month.amount) : "");
            const track = el("span", "month-bar-track");
            const fill = el("span", "month-bar-fill");
            fill.style.height = `${month.amount ? Math.max(4, (month.amount / max) * 100) : 0}%`;
            track.append(fill);
            item.append(value, track, el("span", "month-bar-label", `${Number(month.month.slice(5))}월`));
            bars.append(item);
        });

        const list = $("categoryBars");
        list.replaceChildren();
        const top = summary.categories[0]?.amount || 1;
        summary.categories.forEach((category) => {
            const row = el("li");
            row.title = `${category.category} ${won(category.amount)} (${Math.round(category.share * 100)}%)`;
            const head = el("div", "category-bar-head");
            head.append(el("strong", "", category.category), el("span", "", `${won(category.amount)}  ${Math.round(category.share * 100)}%`));
            const track = el("div", "category-bar-track");
            const fill = el("span");
            fill.style.width = `${Math.max(3, (category.amount / top) * 100)}%`;
            track.append(fill);
            row.append(head, track);
            list.append(row);
        });

        const items = $("topItems");
        items.replaceChildren();
        if (!summary.top_items.length) items.append(el("li", "muted", "품목을 읽은 영수증이 아직 없어요."));
        summary.top_items.forEach((product) => {
            const row = el("li");
            const name = el("div", "top-item-name");
            name.append(el("strong", "", product.name), el("span", "chip", product.category));
            row.append(name, el("small", "muted", `${product.purchases}번 구매, 모두 ${product.count}개, ${won(product.amount)}`));
            items.append(row);
        });
    }

    function itemEditor(item = { name: "", quantity: 1, amount: 0, category: "기타 용품" }) {
        const row = el("div", "item-edit-row");
        const name = el("input"); name.value = item.name; name.placeholder = "상품명"; name.maxLength = 60; name.setAttribute("aria-label", "상품명");
        const quantity = el("input"); quantity.type = "number"; quantity.min = "1"; quantity.value = item.quantity || 1; quantity.setAttribute("aria-label", "수량");
        const amount = el("input"); amount.type = "number"; amount.min = "0"; amount.value = item.amount; amount.setAttribute("aria-label", "금액");
        const category = el("select"); category.setAttribute("aria-label", "분류");
        categories.forEach((value) => { const option = el("option", "", value); option.value = value; category.append(option); });
        category.value = item.category;
        const remove = el("button", "item-remove", "✕"); remove.type = "button"; remove.setAttribute("aria-label", "이 품목 삭제");
        remove.addEventListener("click", () => row.remove());
        row.append(name, quantity, amount, category, remove);
        return row;
    }

    function renderReceipt(receipt) {
        const card = el("article", `receipt-log-card${receipt.in_log ? "" : " is-excluded"}`);
        const head = el("div", "receipt-log-head");
        const title = el("div");
        title.append(el("strong", "", receipt.store_name || "매장 이름 없음"),
            el("small", "muted", [receipt.purchased_date, receipt.purchased_time].filter(Boolean).join(" ") || receipt.created_at.slice(0, 10)));
        const right = el("div", "receipt-log-amount");
        right.append(el("strong", "", receipt.in_log ? won(receipt.pet_amount) : "기록 제외"),
            el("small", "muted", receipt.in_log ? `결제 ${won(receipt.total_amount)}` : (REASONS[receipt.log_reason] || "")));
        head.append(title, right);

        const list = el("ul", "receipt-items");
        if (!receipt.items.length) list.append(el("li", "muted", "읽은 품목이 없어요. 수정에서 직접 넣을 수 있어요."));
        receipt.items.forEach((item) => {
            const row = el("li", item.category === "반려용품 아님" ? "is-not-pet" : "");
            const name = el("span", "receipt-item-name");
            name.append(el("span", "", item.name), el("span", "chip", item.category));
            row.append(name, el("span", "receipt-item-amount", `${item.quantity && item.quantity > 1 ? `${item.quantity}개 ` : ""}${won(item.amount)}`));
            list.append(row);
        });

        const actions = el("div", "receipt-log-actions");
        const edit = el("button", "btn-ghost", "수정");
        edit.type = "button";
        const consent = el("label", "consent-toggle");
        const box = el("input"); box.type = "checkbox"; box.checked = Boolean(receipt.dataset_consent);
        consent.append(box, el("span", "", "OCR 개선에 사진 제공"));
        if (receipt.items_corrected) actions.append(el("span", "chip chip-ok", "직접 확인함"));
        actions.append(consent, edit);
        card.append(head, list, actions);

        box.addEventListener("change", async () => {
            box.disabled = true;
            try {
                await api.request(`/api/receipts/${receipt.id}/dataset-consent`, { method: "PUT", body: JSON.stringify({ consent: box.checked }) });
                status.textContent = box.checked ? "이 영수증 사진을 OCR 개선에 쓰는 데 동의했어요." : "동의를 철회했어요. 다음 학습 데이터부터 빠져요.";
            } catch (error) {
                box.checked = !box.checked;
                status.textContent = error.message;
            } finally { box.disabled = false; }
        });

        edit.addEventListener("click", () => {
            const editor = el("div", "item-editor");
            const rows = el("div");
            (receipt.items.length ? receipt.items : [undefined]).forEach((item) => rows.append(itemEditor(item)));
            const add = el("button", "btn-ghost", "+ 품목 추가"); add.type = "button";
            add.addEventListener("click", () => rows.append(itemEditor()));
            const save = el("button", "btn", "저장"); save.type = "button";
            const cancel = el("button", "btn-ghost", "취소"); cancel.type = "button";
            const buttons = el("div", "item-editor-buttons");
            buttons.append(add, cancel, save);
            editor.append(el("div", "item-edit-legend", "상품명 / 수량 / 금액 / 분류"), rows, buttons);
            list.replaceWith(editor);
            actions.hidden = true;
            cancel.addEventListener("click", () => { editor.replaceWith(list); actions.hidden = false; });
            save.addEventListener("click", async () => {
                const items = [...rows.querySelectorAll(".item-edit-row")].map((row) => {
                    const [name, quantity, amount, category] = row.querySelectorAll("input, select");
                    return { name: name.value.trim(), quantity: Number(quantity.value) || null, amount: Number(amount.value) || 0, category: category.value };
                }).filter((item) => item.name);
                save.disabled = true;
                try {
                    const result = await api.request(`/api/receipts/${receipt.id}/items`, { method: "PUT", body: JSON.stringify({ items }) });
                    card.replaceWith(renderReceipt(result.receipt));
                    status.textContent = "고친 내용을 저장했어요. 통계에도 반영됐어요.";
                    loadSummary();
                } catch (error) {
                    status.textContent = error.message;
                    save.disabled = false;
                }
            });
        });
        return card;
    }

    async function loadSummary() {
        const summary = await api.request("/api/receipts/summary");
        renderSummary(summary);
        return summary;
    }

    async function load() {
        if (!api?.isLoggedIn()) {
            window.location.href = "account.html";
            return;
        }
        try {
            const [summary, receipts] = await Promise.all([loadSummary(), api.request("/api/receipts?limit=100")]);
            categories = receipts.categories;
            const list = $("receiptList");
            list.replaceChildren(...receipts.items.map(renderReceipt));
            const empty = !receipts.items.length;
            $("purchaseEmpty").hidden = !empty;
            $("purchaseBody").hidden = empty;
            status.textContent = summary.receipt_count ? "" : (empty ? "" : "아직 기록에 들어간 영수증이 없어요. 아래에서 품목 분류를 고치면 기록에 넣을 수 있어요.");
        } catch (error) {
            status.textContent = error.message;
        }
    }

    load();
}());
