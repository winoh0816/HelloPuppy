/* 보호자 건강기록(PHR) 화면. 기록은 로그인 계정에 저장되고, 병원별 기한부 링크와 FHIR 파일로 다른 병원에 전달한다. */
(function () {
    "use strict";

    const H = window.HelloPuppyHealth;
    const escapeHtml = H.escapeHtml;
    const profileForm = document.getElementById("petProfileForm");
    const foodForm = document.getElementById("foodForm");
    const recordForm = document.getElementById("healthRecordForm");
    const questionnaireForm = document.getElementById("questionnaireForm");
    const shareForm = document.getElementById("shareForm");
    const recordTypeSelect = document.getElementById("recordTypeSelect");
    let summary = { pet: {}, food: {}, records: [], questionnaires: [], activity: [] };
    let shares = [];

    function api(path, options) { return window.HelloPuppyAPI.request(path, options); }
    function jsonBody(value) { return JSON.stringify(value); }
    function formData(form) { return Object.fromEntries(new FormData(form).entries()); }
    function loadOwnImage(imageId) { return window.HelloPuppyAPI.imageUrl(imageId); }

    async function uploadHealthPhoto(form) {
        const file = form.elements.namedItem("photo")?.files?.[0];
        if (!file) return null;
        const body = new FormData();
        body.append("photo", file);
        const result = await api("/api/uploads?purpose=health", { method: "POST", body });
        return result.image_id;
    }

    function openForm(form, data) {
        form.reset();
        Object.entries(data || {}).forEach(([key, value]) => {
            const field = form.elements.namedItem(key);
            if (!field) return;
            if (field.type === "checkbox") field.checked = Boolean(value);
            else field.value = value ?? "";
        });
        form.hidden = false;
        form.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    function renderAll() {
        const records = summary.records || [];
        document.getElementById("petProfileSummary").innerHTML = H.renderProfile(summary.pet);
        const questionnaireList = document.getElementById("questionnaireList");
        questionnaireList.innerHTML = summary.questionnaires.length
            ? summary.questionnaires.slice(0, 3).map((item) => H.renderQuestionnaire(item, { deletable: true })).join("")
            : H.renderQuestionnaire(null);
        document.getElementById("clinicalAlerts").innerHTML = H.renderClinicalAlerts(records);
        document.getElementById("preventiveSummary").innerHTML = H.renderPreventive(records);
        document.getElementById("foodSummary").innerHTML = H.renderDiet(summary.food);
        const stats = H.activityStats(summary.activity);
        document.getElementById("walkFrequency").textContent = stats.walkCount;
        document.getElementById("walkDays").textContent = stats.walkDetail;
        document.getElementById("feedingFrequency").textContent = stats.feedingCount;
        document.getElementById("feedingTime").textContent = stats.feedingDetail;
        const list = document.getElementById("healthRecordList");
        list.innerHTML = records.length
            ? records.map((record) => H.renderRecordCard(record, { deletable: true })).join("")
            : '<div class="health-empty"><strong>등록된 건강 기록이 없습니다.</strong><span>진료, 예방접종, 복용 약, 알레르기, 체중 등을 기록해 보세요.</span></div>';
        H.hydrateImages(document.querySelector(".health-content"), loadOwnImage);
    }

    function shareUrl(token) {
        const url = new URL("vet-share.html", window.location.href);
        url.hash = `token=${encodeURIComponent(token)}`;
        return url.toString();
    }

    function renderShares() {
        const active = shares.filter((share) => share.status === "active");
        const inactive = shares.filter((share) => share.status !== "active").slice(0, 5);
        const scopeLabel = (scope) => scope === "read_write" ? "열람 + 진료기록 입력" : "열람만";
        const statusLabel = { active: "사용 중", expired: "만료", revoked: "취소됨" };
        const item = (share) => `<li class="is-${share.status}">
            <div><strong>${escapeHtml(share.clinic_name)}</strong><small>${scopeLabel(share.scope)} · ${statusLabel[share.status]} · ${share.status === "active" ? `${escapeHtml(H.formatDateTime(share.expires_at))}까지` : escapeHtml(H.formatDateTime(share.created_at))}</small>
            <small>열람·입력 ${Number(share.access_count)}회${share.last_accessed_at ? ` · 최근 ${escapeHtml(H.formatDateTime(share.last_accessed_at))}` : ""}</small></div>
            ${share.status === "active" ? `<button type="button" class="health-delete-btn" data-revoke-share="${Number(share.id)}">공유 취소</button>` : ""}
        </li>`;
        document.getElementById("shareList").innerHTML = shares.length
            ? `<ul>${active.map(item).join("")}${inactive.map(item).join("")}</ul>`
            : '<p class="health-form-hint">아직 만든 공유 링크가 없어요.</p>';
    }

    async function refresh() {
        const [summaryResult, shareResult] = await Promise.all([api("/api/health/summary"), api("/api/health/shares")]);
        summary = summaryResult.summary;
        shares = shareResult.items || [];
        renderAll();
        renderShares();
    }

    // 기록 종류 선택에 따라 입력 항목을 바꾼다.
    recordTypeSelect.innerHTML = Object.entries(H.RECORD_TYPES).map(([value, type]) => `<option value="${value}">${escapeHtml(type.label)}</option>`).join("");
    recordTypeSelect.addEventListener("change", () => H.renderTypeFields(document.getElementById("recordTypeFields"), recordTypeSelect.value));
    document.getElementById("systemFields").innerHTML = Object.entries(H.QUESTIONNAIRE_SYSTEMS).map(([key, label]) => `
        <label>${escapeHtml(label)}<select name="system.${key}"><option value="">-</option>${Object.entries(H.SYSTEM_VALUES).map(([value, text]) => `<option value="${value}">${escapeHtml(text)}</option>`).join("")}</select></label>`).join("");

    document.getElementById("editProfileButton").addEventListener("click", () => openForm(profileForm, summary.pet));
    document.getElementById("cancelProfileButton").addEventListener("click", () => { profileForm.hidden = true; });
    document.getElementById("editFoodButton").addEventListener("click", () => openForm(foodForm, summary.food));
    document.getElementById("cancelFoodButton").addEventListener("click", () => { foodForm.hidden = true; });
    document.getElementById("addRecordButton").addEventListener("click", () => {
        openForm(recordForm, { record_type: "visit", record_date: H.today() });
        H.renderTypeFields(document.getElementById("recordTypeFields"), "visit");
    });
    document.getElementById("cancelRecordButton").addEventListener("click", () => { recordForm.hidden = true; });
    document.getElementById("addQuestionnaireButton").addEventListener("click", () => openForm(questionnaireForm, { visit_date: H.today() }));
    document.getElementById("cancelQuestionnaireButton").addEventListener("click", () => { questionnaireForm.hidden = true; });
    document.getElementById("addShareButton").addEventListener("click", () => openForm(shareForm, { hours: "24", scope: "read" }));
    document.getElementById("cancelShareButton").addEventListener("click", () => { shareForm.hidden = true; });

    profileForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const data = formData(profileForm);
            const payload = {
                name: data.name, species: data.species, breed: data.breed, coat_features: data.coat_features,
                birth_date: data.birth_date, birth_date_estimated: Boolean(data.birth_date_estimated), sex: data.sex,
                neutered: data.neutered, weight_kg: data.weight_kg ? Number(data.weight_kg) : null, blood_type: data.blood_type,
                microchip_id: data.microchip_id, registration_type: data.registration_type, living_environment: data.living_environment,
                other_pets: data.other_pets, guardian_name: data.guardian_name, guardian_phone: data.guardian_phone,
                allergies: data.allergies, medical_notes: data.medical_notes
            };
            const result = await api("/api/pet/profile", { method: "PUT", body: jsonBody(payload) });
            summary.pet = { ...result.profile, birth_date_estimated: Boolean(result.profile.birth_date_estimated) };
            profileForm.hidden = true;
            renderAll();
        } catch (error) { alert(error.message); }
    });

    foodForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const data = formData(foodForm);
            const result = await api("/api/pet/food", { method: "PUT", body: jsonBody({
                ...data, meals_per_day: data.meals_per_day ? Number(data.meals_per_day) : null
            }) });
            summary.food = result.food;
            foodForm.hidden = true;
            renderAll();
        } catch (error) { alert(error.message); }
    });

    recordForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = recordForm.querySelector("[type=submit]");
        button.disabled = true;
        try {
            const payload = H.collectRecordPayload(recordForm);
            payload.image_id = await uploadHealthPhoto(recordForm);
            await api("/api/health/records", { method: "POST", body: jsonBody(payload) });
            recordForm.hidden = true;
            await refresh();
        } catch (error) { alert(error.message); }
        finally { button.disabled = false; }
    });

    questionnaireForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = questionnaireForm.querySelector("[type=submit]");
        button.disabled = true;
        try {
            const payload = { systems: {} };
            new FormData(questionnaireForm).forEach((value, key) => {
                if (value instanceof File) return;
                if (key.startsWith("system.")) { if (value) payload.systems[key.slice(7)] = value; }
                else payload[key] = String(value).trim();
            });
            payload.image_id = await uploadHealthPhoto(questionnaireForm);
            await api("/api/health/questionnaires", { method: "POST", body: jsonBody(payload) });
            questionnaireForm.hidden = true;
            await refresh();
        } catch (error) { alert(error.message); }
        finally { button.disabled = false; }
    });

    shareForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const data = formData(shareForm);
            const result = await api("/api/health/shares", { method: "POST", body: jsonBody({ ...data, hours: Number(data.hours) }) });
            const link = shareUrl(result.token);
            const box = document.getElementById("shareResult");
            box.hidden = false;
            box.innerHTML = `<strong>${escapeHtml(result.share.clinic_name)} 공유 링크가 만들어졌어요</strong>
                <p>이 링크는 지금 한 번만 보여요. 병원에 바로 전달하세요.</p>
                <input type="text" readonly value="${escapeHtml(link)}" aria-label="공유 링크">
                <div class="health-form-actions"><button type="button" class="health-secondary-btn" id="copyShareLink">링크 복사</button>${navigator.share ? '<button type="button" class="health-primary-btn" id="sendShareLink">보내기</button>' : ""}</div>`;
            box.querySelector("#copyShareLink").addEventListener("click", async () => {
                try { await navigator.clipboard.writeText(link); alert("링크를 복사했어요."); }
                catch (error) { box.querySelector("input").select(); }
            });
            box.querySelector("#sendShareLink")?.addEventListener("click", () => navigator.share({ title: "안녕멍뭉 건강기록", url: link }).catch(() => {}));
            shareForm.hidden = true;
            shares = (await api("/api/health/shares")).items || [];
            renderShares();
        } catch (error) { alert(error.message); }
    });

    document.getElementById("shareList").addEventListener("click", async (event) => {
        const button = event.target.closest("[data-revoke-share]");
        if (!button || !confirm("이 병원 공유 링크를 취소할까요? 병원에서 더 이상 열람할 수 없게 됩니다.")) return;
        try {
            await api(`/api/health/shares/${button.dataset.revokeShare}`, { method: "DELETE" });
            shares = (await api("/api/health/shares")).items || [];
            renderShares();
        } catch (error) { alert(error.message); }
    });

    document.getElementById("exportFhirButton").addEventListener("click", async () => {
        try {
            const bundle = await api("/api/health/export/fhir");
            const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/fhir+json" });
            const link = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `hellopuppy-fhir-${H.today()}.json` });
            link.click();
            URL.revokeObjectURL(link.href);
        } catch (error) { alert(error.message); }
    });

    document.querySelector(".health-content").addEventListener("click", async (event) => {
        const recordButton = event.target.closest("[data-delete-record]");
        const questionnaireButton = event.target.closest("[data-delete-questionnaire]");
        try {
            if (recordButton && confirm("이 건강 기록을 삭제할까요?")) {
                await api(`/api/health/records/${recordButton.dataset.deleteRecord}`, { method: "DELETE" });
                await refresh();
            } else if (questionnaireButton && confirm("이 문진표를 삭제할까요?")) {
                await api(`/api/health/questionnaires/${questionnaireButton.dataset.deleteQuestionnaire}`, { method: "DELETE" });
                await refresh();
            }
        } catch (error) { alert(error.message); }
    });

    if (!window.HelloPuppyAPI?.isLoggedIn()) {
        window.location.href = "account.html";
    } else {
        refresh().catch((error) => {
            document.getElementById("petProfileSummary").textContent = error.message;
        });
    }
})();
