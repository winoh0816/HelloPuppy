/* Health records are owned by the authenticated user and persisted by the SQLite API. */
(function () {
    "use strict";

    const TYPE_LABELS = { visit: "병원 방문", vaccination: "예방접종", medication: "복용 약", symptom: "증상·관찰", weight: "체중 측정", other: "기타" };
    const profileForm = document.getElementById("petProfileForm");
    const foodForm = document.getElementById("foodForm");
    const recordForm = document.getElementById("healthRecordForm");
    let profile = {};
    let food = {};
    let records = [];
    let activities = [];

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
    }

    function api(path, options) { return window.HelloPuppyAPI.request(path, options); }
    function jsonBody(value) { return JSON.stringify(value); }
    function formData(form) { return Object.fromEntries(new FormData(form).entries()); }

    function formatDate(value) {
        if (!value) return "날짜 미입력";
        const date = new Date(`${value}T00:00:00`);
        return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("ko-KR").format(date);
    }

    function calculateAge(birthDate) {
        if (!birthDate) return "미입력";
        const birth = new Date(`${birthDate}T00:00:00`);
        if (Number.isNaN(birth.getTime()) || birth > new Date()) return "확인 필요";
        let years = new Date().getFullYear() - birth.getFullYear();
        let months = new Date().getMonth() - birth.getMonth();
        if (new Date().getDate() < birth.getDate()) months -= 1;
        if (months < 0) { years -= 1; months += 12; }
        if (years < 1) return `${Math.max(0, months)}개월`;
        return months > 0 ? `${years}세 ${months}개월` : `${years}세`;
    }

    function renderProfile() {
        const summary = document.getElementById("petProfileSummary");
        if (!profile.name) {
            summary.innerHTML = '<div class="health-empty"><strong>아직 기본 정보가 없습니다.</strong><span>반려견 정보를 입력하면 병원에 보여줄 요약이 여기에 표시됩니다.</span></div>';
            return;
        }
        const sex = profile.sex === "female" ? "암컷" : profile.sex === "male" ? "수컷" : "미입력";
        const neutered = profile.neutered === "yes" ? "완료" : profile.neutered === "no" ? "미완료" : "미입력";
        summary.innerHTML = `
            <div class="health-pet-title"><div class="health-pet-avatar"><img src="assets/images/brand/puppy-app-icon.png" alt=""></div><div><h3>${escapeHtml(profile.name)}</h3><span>${escapeHtml(profile.breed || "견종 미입력")} · ${escapeHtml(calculateAge(profile.birth_date))}</span></div><span class="health-demo-tag">계정 저장</span></div>
            <div class="health-profile-grid"><div><span>성별</span><strong>${sex}</strong></div><div><span>중성화</span><strong>${neutered}</strong></div><div><span>체중</span><strong>${profile.weight_kg ? `${escapeHtml(profile.weight_kg)} kg` : "미입력"}</strong></div><div><span>마이크로칩</span><strong>${escapeHtml(profile.microchip_id || "미입력")}</strong></div></div>
            <div class="health-note-grid"><div><span>알레르기·주의사항</span><p>${escapeHtml(profile.allergies || "기록 없음")}</p></div><div><span>만성질환·과거 병력</span><p>${escapeHtml(profile.medical_notes || "기록 없음")}</p></div></div>
            <div class="health-guardian-line">보호자: ${escapeHtml(profile.guardian_name || "미입력")} · 연락처: ${escapeHtml(profile.guardian_phone || "미입력")}</div>`;
    }

    function openForm(form, data) {
        form.reset();
        if (data) {
            Object.entries(data).forEach(([key, value]) => {
                const field = form.elements.namedItem(key);
                if (field) field.value = value ?? "";
            });
        }
        form.hidden = false;
        form.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    function renderFood() {
        document.getElementById("foodSummary").textContent = food.food_name || "아직 입력되지 않았어요";
        const meals = food.meals_per_day ? `하루 ${food.meals_per_day}회` : "급여 횟수 미입력";
        const schedule = food.feeding_schedule || "평소 시간 미입력";
        const notes = food.food_notes ? ` · ${food.food_notes}` : "";
        document.getElementById("feedingScheduleSummary").textContent = `${meals} · ${schedule}${notes}`;
    }

    function renderActivity() {
        const walk = activities.filter((item) => item.activity === "walk" && item.status === "verified");
        const feeding = activities.filter((item) => item.activity === "feeding" && item.status === "verified");
        const walkDays = new Set(walk.map((item) => new Date(item.created_at).toLocaleDateString("ko-KR"))).size;
        document.getElementById("walkFrequency").textContent = walk.length ? `${walk.length}회` : "기록 없음";
        document.getElementById("walkDays").textContent = walk.length ? `주 평균 ${(walk.length / 30 * 7).toFixed(1)}회 · 산책한 날 ${walkDays}일` : "AI 인증 기록이 쌓이면 표시됩니다";
        document.getElementById("feedingFrequency").textContent = feeding.length ? `${feeding.length}회` : "기록 없음";
        if (!feeding.length) {
            document.getElementById("feedingTime").textContent = "AI 인증 기록이 쌓이면 표시됩니다";
            return;
        }
        const counts = new Map();
        feeding.forEach((item) => {
            const hour = new Date(item.created_at).getHours();
            const bucket = hour < 11 ? "오전" : hour < 16 ? "오후" : "저녁";
            counts.set(bucket, (counts.get(bucket) || 0) + 1);
        });
        const [bucket, count] = [...counts.entries()].sort((a, b) => b[1] - a[1])[0];
        document.getElementById("feedingTime").textContent = `주 평균 ${(feeding.length / 30 * 7).toFixed(1)}회 · 주로 ${bucket} ${count}회`;
    }

    function renderRecords() {
        const container = document.getElementById("healthRecordList");
        if (!records.length) {
            container.innerHTML = '<div class="health-empty"><strong>등록된 건강 기록이 없습니다.</strong><span>예방접종, 병원 방문, 복용 약 등을 직접 기록할 수 있습니다.</span></div>';
            return;
        }
        container.innerHTML = records.map((record) => `
            <article class="health-record-card"><div class="health-record-date">${escapeHtml(formatDate(record.record_date))}</div><div class="health-record-main"><span class="health-record-type">${escapeHtml(TYPE_LABELS[record.record_type] || "기타")}</span><h3>${escapeHtml(record.title || TYPE_LABELS[record.record_type] || "건강 기록")}</h3><p>${escapeHtml(record.clinic || "기관 미입력")}${record.notes ? ` · ${escapeHtml(record.notes)}` : ""}</p></div><button type="button" class="health-delete-btn" data-delete-record="${record.id}" aria-label="이 기록 삭제">삭제</button></article>`).join("");
    }

    async function refresh() {
        const [petResult, foodResult, recordResult, activityResult] = await Promise.all([
            api("/api/pet/profile"), api("/api/pet/food"), api("/api/health/records"), api("/api/activity/logs?days=30")
        ]);
        profile = petResult.profile || {};
        food = foodResult.food || {};
        records = recordResult.items || [];
        activities = activityResult.items || [];
        renderProfile(); renderFood(); renderRecords(); renderActivity();
    }

    document.getElementById("editProfileButton").addEventListener("click", () => openForm(profileForm, {
        name: profile.name, breed: profile.breed, birth_date: profile.birth_date, sex: profile.sex,
        weight_kg: profile.weight_kg, neutered: profile.neutered, guardian_name: profile.guardian_name,
        guardian_phone: profile.guardian_phone, microchip_id: profile.microchip_id, allergies: profile.allergies, medical_notes: profile.medical_notes
    }));
    document.getElementById("cancelProfileButton").addEventListener("click", () => { profileForm.hidden = true; });
    document.getElementById("editFoodButton").addEventListener("click", () => openForm(foodForm, food));
    document.getElementById("cancelFoodButton").addEventListener("click", () => { foodForm.hidden = true; });
    document.getElementById("addRecordButton").addEventListener("click", () => openForm(recordForm, { record_date: new Date().toISOString().slice(0, 10) }));
    document.getElementById("cancelRecordButton").addEventListener("click", () => { recordForm.hidden = true; });

    profileForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const data = formData(profileForm);
            const payload = {
                name: data.name, breed: data.breed, birth_date: data.birth_date, sex: data.sex,
                weight_kg: data.weight_kg ? Number(data.weight_kg) : null, neutered: data.neutered,
                guardian_name: data.guardian_name, guardian_phone: data.guardian_phone, microchip_id: data.microchip_id,
                allergies: data.allergies, medical_notes: data.medical_notes
            };
            const result = await api("/api/pet/profile", { method: "PUT", body: jsonBody(payload) });
            profile = result.profile; profileForm.hidden = true; renderProfile();
        } catch (error) { alert(error.message); }
    });

    foodForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const data = formData(foodForm);
            const result = await api("/api/pet/food", { method: "PUT", body: jsonBody({
                food_name: data.food_name, meals_per_day: data.meals_per_day ? Number(data.meals_per_day) : null,
                feeding_schedule: data.feeding_schedule, food_notes: data.food_notes
            }) });
            food = result.food; foodForm.hidden = true; renderFood();
        } catch (error) { alert(error.message); }
    });

    recordForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const result = await api("/api/health/records", { method: "POST", body: jsonBody(formData(recordForm)) });
            records.unshift(result.record); recordForm.hidden = true; renderRecords();
        } catch (error) { alert(error.message); }
    });

    document.getElementById("healthRecordList").addEventListener("click", async (event) => {
        const button = event.target.closest("[data-delete-record]");
        if (!button || !confirm("이 건강 기록을 삭제할까요?")) return;
        try {
            await api(`/api/health/records/${button.dataset.deleteRecord}`, { method: "DELETE" });
            records = records.filter((record) => String(record.id) !== button.dataset.deleteRecord);
            renderRecords();
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
