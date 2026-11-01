/* 동물병원용 공유 화면. 보호자가 보낸 링크의 #token 으로 로그인 없이 열람하고, 입력 권한이 있으면 진료 기록을 남긴다.
 * 토큰은 URL 해시(#)에 있어 서버 접속 로그나 Referer 로 전달되지 않고, API 에는 X-Health-Share-Token 헤더로만 보낸다. */
(function () {
    "use strict";

    const H = window.HelloPuppyHealth;
    const API_BASE = window.HelloPuppyAPI.baseUrl;
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
    const CLINIC_TYPES = ["visit", "vaccination", "parasite", "medication", "condition", "allergy", "surgery", "lab", "weight"];
    const recordForm = document.getElementById("clinicRecordForm");
    const typeSelect = document.getElementById("clinicRecordType");

    async function sharedRequest(path, options = {}) {
        const headers = new Headers(options.headers || {});
        headers.set("X-Health-Share-Token", token);
        if (options.body) headers.set("Content-Type", "application/json");
        let response;
        try {
            response = await fetch(`${API_BASE}${path}`, { ...options, headers });
        } catch (error) {
            throw new Error("서버에 연결할 수 없습니다. 잠시 후 다시 시도하세요.");
        }
        if (path.includes("/images/")) {
            if (!response.ok) throw new Error("사진을 불러오지 못했습니다.");
            return response;
        }
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `요청에 실패했습니다 (${response.status}).`);
        return payload;
    }

    async function loadSharedImage(imageId) {
        const response = await sharedRequest(`/api/shared/health/images/${encodeURIComponent(imageId)}`);
        return URL.createObjectURL(await response.blob());
    }

    function showError(message) {
        const box = document.getElementById("shareError");
        box.textContent = message;
        box.hidden = false;
        document.getElementById("sharedContent").hidden = true;
    }

    function render({ share, summary }) {
        const records = summary.records || [];
        document.getElementById("shareClinic").textContent = `${share.clinic_name} 공유용`;
        document.getElementById("shareMeta").textContent = `${share.scope === "read_write" ? "열람 + 진료기록 입력" : "열람 전용"} · ${H.formatDateTime(share.expires_at)}까지 유효`;
        document.getElementById("vetProfile").innerHTML = H.renderProfile(summary.pet);
        document.getElementById("vetAlerts").innerHTML = H.renderClinicalAlerts(records);
        document.getElementById("vetQuestionnaires").innerHTML = summary.questionnaires.length
            ? summary.questionnaires.slice(0, 3).map((item) => H.renderQuestionnaire(item)).join("")
            : H.renderQuestionnaire(null);
        document.getElementById("vetPreventive").innerHTML = H.renderPreventive(records);
        document.getElementById("vetDiet").innerHTML = H.renderDiet(summary.food);
        const stats = H.activityStats(summary.activity);
        document.getElementById("vetWalkCount").textContent = stats.walkCount;
        document.getElementById("vetWalkDetail").textContent = stats.walkDetail;
        document.getElementById("vetFeedingCount").textContent = stats.feedingCount;
        document.getElementById("vetFeedingDetail").textContent = stats.feedingDetail;
        document.getElementById("vetRecords").innerHTML = records.length
            ? records.map((record) => H.renderRecordCard(record)).join("")
            : '<div class="health-empty"><strong>등록된 건강 기록이 없습니다.</strong></div>';
        document.getElementById("addClinicRecordButton").hidden = share.scope !== "read_write";
        document.getElementById("sharedContent").hidden = false;
        H.hydrateImages(document.getElementById("sharedContent"), loadSharedImage);
    }

    async function refresh() {
        render(await sharedRequest("/api/shared/health"));
    }

    typeSelect.innerHTML = CLINIC_TYPES.map((type) => `<option value="${type}">${H.escapeHtml(H.RECORD_TYPES[type].label)}</option>`).join("");
    typeSelect.addEventListener("change", () => H.renderTypeFields(document.getElementById("clinicRecordFields"), typeSelect.value));

    document.getElementById("addClinicRecordButton").addEventListener("click", () => {
        recordForm.reset();
        recordForm.elements.namedItem("record_date").value = H.today();
        H.renderTypeFields(document.getElementById("clinicRecordFields"), typeSelect.value);
        document.getElementById("clinicRecordSection").hidden = false;
        document.getElementById("clinicRecordSection").scrollIntoView({ behavior: "smooth" });
    });
    document.getElementById("cancelClinicRecordButton").addEventListener("click", () => {
        document.getElementById("clinicRecordSection").hidden = true;
    });

    recordForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = recordForm.querySelector("[type=submit]");
        button.disabled = true;
        try {
            await sharedRequest("/api/shared/health/records", { method: "POST", body: JSON.stringify(H.collectRecordPayload(recordForm)) });
            document.getElementById("clinicRecordSection").hidden = true;
            await refresh();
            alert("진료 기록을 저장했습니다. 보호자 앱에 병원 입력 기록으로 표시됩니다.");
        } catch (error) { alert(error.message); }
        finally { button.disabled = false; }
    });

    document.getElementById("downloadFhirButton").addEventListener("click", async () => {
        try {
            const bundle = await sharedRequest("/api/shared/health/fhir");
            const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/fhir+json" });
            const link = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `hellopuppy-shared-fhir-${H.today()}.json` });
            link.click();
            URL.revokeObjectURL(link.href);
        } catch (error) { alert(error.message); }
    });

    if (!token) {
        showError("공유 링크가 올바르지 않습니다. 보호자에게 받은 링크 전체를 다시 열어 주세요.");
    } else {
        refresh().catch((error) => showError(error.message));
    }
})();
