/* 보호자 건강기록 화면(health.html)과 동물병원 공유 화면(vet-share.html)이 함께 쓰는 항목 정의·렌더러.
 * 항목은 수의사법 시행규칙 진료부 기재사항, SOAP 진료 기록, 소동물 문진 체크리스트, WSAVA 영양 평가를 참고했다.
 * 서버 검증 규칙은 backend/health.py 의 RECORD_TYPES 와 같아야 한다. */
(function () {
    "use strict";

    const ROUTE_OPTIONS = { oral: "경구(먹는 약)", topical: "바르는 약", eye_ear: "점안·점이", injection: "주사", other: "기타" };
    const SEVERITY_OPTIONS = { mild: "가벼움", moderate: "중간", severe: "심함·응급" };

    const RECORD_TYPES = {
        visit: {
            label: "진료 기록", primary: "diagnosis", hint: "진료 후 받은 설명·진단서·영수증 내용을 SOAP 순서로 적어요.",
            fields: [
                { key: "reason", label: "방문 사유(주 증상)" },
                { key: "vet_name", label: "담당 수의사" },
                { key: "subjective", label: "S · 보호자가 말한 증상·경과", type: "textarea" },
                { key: "findings", label: "O · 신체검사·관찰 소견", type: "textarea" },
                { key: "diagnosis", label: "A · 진단명" },
                { key: "diagnosis_code", label: "표준 질병코드 (선택)", placeholder: "농식품부 권장 표준 코드" },
                { key: "treatment", label: "P · 처치", type: "textarea" },
                { key: "prescription", label: "P · 처방(약 이름·용량·기간)", type: "textarea" },
                { key: "tests", label: "시행한 검사", type: "textarea" },
                { key: "next_visit_date", label: "다음 내원일", type: "date" }
            ]
        },
        vaccination: {
            label: "예방접종", primary: "vaccine_type", hint: "접종 수첩·병원 안내에 적힌 백신명과 다음 접종일을 기록해요.",
            fields: [
                { key: "vaccine_type", label: "백신 종류", type: "select", required: true, options: {
                    dhppl: "종합백신(DHPPL)", corona: "코로나 장염", kennel_cough: "켄넬코프", influenza: "개 인플루엔자", rabies: "광견병", other: "기타 백신" } },
                { key: "dose_number", label: "차수", placeholder: "예: 3차 / 추가접종" },
                { key: "product", label: "제품명 (선택)" },
                { key: "next_due_date", label: "다음 접종 예정일", type: "date" },
                { key: "vet_name", label: "접종 수의사 (선택)" }
            ]
        },
        parasite: {
            label: "기생충 예방", primary: "parasite_type", hint: "약국·온라인에서 산 제품도 꼭 기록하세요. 진료 때 자주 빠지는 정보예요.",
            fields: [
                { key: "parasite_type", label: "예방 종류", type: "select", required: true, options: {
                    heartworm: "심장사상충", external: "외부기생충(진드기·벼룩)", internal: "내부 구충", combined: "복합(올인원)" } },
                { key: "product", label: "제품명" },
                { key: "route", label: "투여 방법", type: "select", options: ROUTE_OPTIONS },
                { key: "next_due_date", label: "다음 투여 예정일", type: "date" }
            ]
        },
        medication: {
            label: "복용 약", primary: "drug_name", hint: "처방약뿐 아니라 영양제가 아닌 일반약도 기록해요.",
            fields: [
                { key: "drug_name", label: "약 이름", required: true },
                { key: "dose", label: "1회 용량", placeholder: "예: 1/2정, 0.5ml" },
                { key: "frequency", label: "복용 횟수", placeholder: "예: 1일 2회" },
                { key: "route", label: "투여 방법", type: "select", options: ROUTE_OPTIONS },
                { key: "start_date", label: "시작일", type: "date" },
                { key: "end_date", label: "종료일", type: "date" },
                { key: "medication_status", label: "현재 상태", type: "select", options: { active: "복용 중", stopped: "중단·완료" } },
                { key: "purpose", label: "복용 목적" }
            ]
        },
        condition: {
            label: "질환·진단", primary: "condition_name", hint: "진단받은 만성질환이나 과거 질병을 기록해요.",
            fields: [
                { key: "condition_name", label: "질환명", required: true },
                { key: "diagnosis_code", label: "표준 질병코드 (선택)" },
                { key: "diagnosed_date", label: "진단일", type: "date" },
                { key: "condition_status", label: "현재 상태", type: "select", options: { active: "관리 중", resolved: "완치", suspected: "의심(확진 전)" } }
            ]
        },
        allergy: {
            label: "알레르기·부작용", primary: "substance", hint: "약·백신 부작용은 다음 진료 때 꼭 필요한 정보예요.",
            fields: [
                { key: "allergy_category", label: "분류", type: "select", options: { medication: "약물", vaccine: "백신", food: "음식", environment: "환경", other: "기타" } },
                { key: "substance", label: "원인 물질", required: true, placeholder: "예: 닭고기, 특정 항생제" },
                { key: "reaction", label: "나타난 반응", placeholder: "예: 얼굴 부종, 구토" },
                { key: "severity", label: "심한 정도", type: "select", options: SEVERITY_OPTIONS }
            ]
        },
        surgery: {
            label: "수술·마취", primary: "procedure", hint: "마취 이력과 이상반응은 다음 마취 계획에 중요해요.",
            fields: [
                { key: "procedure", label: "수술·시술명", required: true, placeholder: "예: 중성화 수술, 스케일링" },
                { key: "anesthesia", label: "마취", type: "select", options: { general: "전신마취", sedation: "진정", local: "국소마취", none: "없음" } },
                { key: "anesthesia_reaction", label: "마취·수술 후 이상반응", type: "textarea" }
            ]
        },
        lab: {
            label: "검사 결과", primary: "test_name", hint: "결과지 사진을 함께 첨부하면 다른 병원에서 수치를 직접 볼 수 있어요.",
            fields: [
                { key: "test_name", label: "검사명", required: true, placeholder: "예: 혈액검사(CBC·생화학), 엑스레이" },
                { key: "result_summary", label: "결과 요약", type: "textarea" },
                { key: "abnormal_findings", label: "이상 소견", type: "textarea" }
            ]
        },
        weight: {
            label: "체중·체형", primary: "weight_kg", hint: "체중은 측정일과 함께 쌓여야 변화를 볼 수 있어요.",
            fields: [
                { key: "weight_kg", label: "체중 (kg)", type: "number", required: true, min: 0.05, max: 150, step: 0.01 },
                { key: "body_condition_score", label: "체형점수 BCS (1~9, 선택)", type: "number", min: 1, max: 9, step: 1, placeholder: "5 = 이상적" }
            ]
        },
        symptom: {
            label: "증상·관찰", primary: "symptom", hint: "언제부터, 얼마나 자주인지 함께 적어요.",
            fields: [
                { key: "symptom", label: "증상", required: true },
                { key: "duration", label: "기간·빈도", placeholder: "예: 3일째, 하루 2회" },
                { key: "severity", label: "심한 정도", type: "select", options: SEVERITY_OPTIONS }
            ]
        },
        other: { label: "기타", primary: "", hint: "", fields: [] }
    };

    const QUESTIONNAIRE_SYSTEMS = {
        energy: "활력·기분", appetite: "식욕", water: "물 마시는 양", urination: "소변(횟수·색)", stool: "대변(설사·혈변·변비)",
        vomiting: "구토", respiratory: "기침·재채기·콧물", breathing: "호흡(빠름·힘듦)", skin: "피부·가려움·털빠짐",
        eyes_ears: "눈·귀", mobility: "걸음걸이·절뚝거림", weight_change: "체중 변화", behavior: "행동 변화·통증 표현"
    };
    const SYSTEM_VALUES = { normal: "평소와 같음", increased: "늘었음", decreased: "줄었음", abnormal: "이상 있음", unknown: "잘 모름" };
    const PROGRESSIONS = { better: "좋아지는 중", same: "비슷함", worse: "나빠지는 중", fluctuating: "좋아졌다 나빠졌다 함" };
    const SPECIES = { dog: "개", cat: "고양이", other: "기타" };
    const REGISTRATION = { internal: "내장형 칩", external: "외장형 인식표", none: "미등록" };
    const LIVING = { indoor: "실내", outdoor: "실외", both: "실내·실외" };

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
    }

    function today() {
        const now = new Date();
        return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    }

    function formatDate(value) {
        if (!value) return "날짜 미입력";
        const date = new Date(`${value}T00:00:00`);
        return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("ko-KR").format(date);
    }

    function formatDateTime(value) {
        if (!value) return "";
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(date);
    }

    function calculateAge(birthDate) {
        if (!birthDate) return "나이 미입력";
        const birth = new Date(`${birthDate}T00:00:00`);
        if (Number.isNaN(birth.getTime()) || birth > new Date()) return "확인 필요";
        const now = new Date();
        let years = now.getFullYear() - birth.getFullYear();
        let months = now.getMonth() - birth.getMonth();
        if (now.getDate() < birth.getDate()) months -= 1;
        if (months < 0) { years -= 1; months += 12; }
        if (years < 1) return `${Math.max(0, months)}개월`;
        return months > 0 ? `${years}세 ${months}개월` : `${years}세`;
    }

    function optionLabel(type, key, value) {
        const field = RECORD_TYPES[type]?.fields.find((item) => item.key === key);
        return field?.options?.[value] || value;
    }

    function recordTitle(record) {
        const type = RECORD_TYPES[record.record_type] || RECORD_TYPES.other;
        if (record.title) return record.title;
        const details = record.details || {};
        if (record.record_type === "visit") return details.diagnosis || details.reason || "진료 기록";
        if (record.record_type === "weight" && details.weight_kg) return `${details.weight_kg} kg`;
        const primary = details[type.primary];
        return primary ? optionLabel(record.record_type, type.primary, primary) : type.label;
    }

    function detailRows(record) {
        const type = RECORD_TYPES[record.record_type];
        if (!type) return [];
        const details = record.details || {};
        return type.fields
            .filter((field) => details[field.key] !== undefined && details[field.key] !== "" && field.key !== type.primary)
            .map((field) => [field.label.replace(/ \(.*\)$/, ""), field.type === "date" ? formatDate(details[field.key]) : optionLabel(record.record_type, field.key, details[field.key])]);
    }

    function sourceBadge(record) {
        if (record.source === "clinic") {
            const author = [record.clinic, record.author_name].filter(Boolean).join(" · ");
            return `<span class="health-source-badge is-clinic" title="공유 링크로 동물병원이 직접 입력">병원 입력${author ? ` · ${escapeHtml(author)}` : ""}</span>`;
        }
        return '<span class="health-source-badge">보호자 입력</span>';
    }

    function renderRecordCard(record, { deletable = false } = {}) {
        const type = RECORD_TYPES[record.record_type] || RECORD_TYPES.other;
        const rows = detailRows(record).map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
        const clinicLine = record.source === "clinic" ? "" : (record.clinic ? `<p class="health-record-clinic">${escapeHtml(record.clinic)}</p>` : "");
        const license = record.source === "clinic" && record.author_license ? `<p class="health-record-clinic">수의사 면허번호 ${escapeHtml(record.author_license)}</p>` : "";
        return `<article class="health-record-card health-record-${escapeHtml(record.record_type)}">
            <div class="health-record-date">${escapeHtml(formatDate(record.record_date))}</div>
            <div class="health-record-main">
                <div class="health-record-badges"><span class="health-record-type">${escapeHtml(type.label)}</span>${sourceBadge(record)}</div>
                <h3>${escapeHtml(recordTitle(record))}</h3>
                ${clinicLine}${license}
                ${rows ? `<dl class="health-detail-list">${rows}</dl>` : ""}
                ${record.notes ? `<p>${escapeHtml(record.notes)}</p>` : ""}
                ${record.image_id ? `<img class="health-record-image" data-health-image="${Number(record.image_id)}" alt="첨부 사진 (진단서·결과지 등)">` : ""}
            </div>
            ${deletable ? `<button type="button" class="health-delete-btn" data-delete-record="${Number(record.id)}" aria-label="이 기록 삭제">삭제</button>` : ""}
        </article>`;
    }

    function renderProfile(pet) {
        if (!pet || !pet.name) {
            return '<div class="health-empty"><strong>아직 기본 정보가 없습니다.</strong><span>반려동물 정보를 입력하면 병원에 보여줄 요약이 여기에 표시됩니다.</span></div>';
        }
        const sex = pet.sex === "female" ? "암컷" : pet.sex === "male" ? "수컷" : "미입력";
        const neutered = pet.neutered === "yes" ? "완료" : pet.neutered === "no" ? "미완료" : "미입력";
        const age = calculateAge(pet.birth_date) + (pet.birth_date && pet.birth_date_estimated ? " (추정)" : "");
        const registration = pet.microchip_id
            ? `${pet.microchip_id}${REGISTRATION[pet.registration_type] ? ` · ${REGISTRATION[pet.registration_type]}` : ""}`
            : (pet.registration_type === "none" ? "미등록" : "미입력");
        const grid = [
            ["성별", sex], ["중성화", neutered], ["체중", pet.weight_kg ? `${pet.weight_kg} kg` : "미입력"],
            ["생활환경", LIVING[pet.living_environment] || "미입력"], ["혈액형", pet.blood_type || "모름"],
            ["함께 사는 동물", pet.other_pets || "없음/미입력"]
        ].map(([label, value]) => `<div><span>${label}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
        return `
            <div class="health-pet-title"><div class="health-pet-avatar"><img src="assets/images/brand/puppy-app-icon.png" alt=""></div><div><h3>${escapeHtml(pet.name)}</h3><span>${escapeHtml(SPECIES[pet.species] || "개")} · ${escapeHtml(pet.breed || "품종 미입력")} · ${escapeHtml(age)}</span></div></div>
            <div class="health-registration-line"><span>동물등록번호</span><strong>${escapeHtml(registration)}</strong></div>
            <div class="health-profile-grid">${grid}</div>
            <div class="health-note-grid">
                <div><span>털색·외형 특징</span><p>${escapeHtml(pet.coat_features || "기록 없음")}</p></div>
                <div><span>진료 시 주의사항·알레르기 메모</span><p>${escapeHtml(pet.allergies || "기록 없음")}</p></div>
                <div class="health-note-wide"><span>기타 병력 메모</span><p>${escapeHtml(pet.medical_notes || "기록 없음")}</p></div>
            </div>
            <div class="health-guardian-line">보호자: ${escapeHtml(pet.guardian_name || "미입력")} · 연락처: ${escapeHtml(pet.guardian_phone || "미입력")}</div>`;
    }

    function renderQuestionnaire(item, { deletable = false } = {}) {
        if (!item) {
            return '<div class="health-empty"><strong>작성한 문진표가 없습니다.</strong><span>병원 가기 전에 증상과 몸 상태를 미리 정리해 두면 진료 시간을 아낄 수 있어요.</span></div>';
        }
        const systems = Object.entries(item.systems || {}).map(([key, value]) => {
            const flagged = value !== "normal" && value !== "unknown";
            return `<li class="${flagged ? "is-flagged" : ""}"><span>${escapeHtml(QUESTIONNAIRE_SYSTEMS[key] || key)}</span><strong>${escapeHtml(SYSTEM_VALUES[value] || value)}</strong></li>`;
        }).join("");
        const rows = [
            ["증상 시작일", item.onset_date ? formatDate(item.onset_date) : ""], ["빈도·지속 시간", item.frequency],
            ["경과", PROGRESSIONS[item.progression] || ""], ["집에서 한 조치·먹인 약", item.home_care],
            ["최근 변화(사료·환경·여행·다른 동물 접촉)", item.recent_changes], ["보호자 질문·걱정", item.concerns]
        ].filter(([, value]) => value).map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
        return `<article class="health-questionnaire-card">
            <div class="health-questionnaire-head"><span>${escapeHtml(formatDate(item.visit_date))} 방문${item.clinic ? ` · ${escapeHtml(item.clinic)}` : ""}</span>
            ${deletable ? `<button type="button" class="health-delete-btn" data-delete-questionnaire="${Number(item.id)}">삭제</button>` : ""}</div>
            <h3>${escapeHtml(item.chief_complaint)}</h3>
            ${rows ? `<dl class="health-detail-list">${rows}</dl>` : ""}
            ${systems ? `<ul class="health-system-list">${systems}</ul>` : ""}
            ${item.image_id ? `<img class="health-record-image" data-health-image="${Number(item.image_id)}" alt="증상 사진">` : ""}
        </article>`;
    }

    function renderDiet(food) {
        food = food || {};
        const rows = [
            ["하루 급여 횟수", food.meals_per_day ? `${food.meals_per_day}회` : ""], ["1회 급여량", food.amount_per_meal],
            ["급여 시간", food.feeding_schedule], ["간식·사람 음식", food.treats], ["영양제", food.supplements],
            ["최근 사료 변경일", food.diet_changed_date ? formatDate(food.diet_changed_date) : ""], ["메모", food.food_notes]
        ].filter(([, value]) => value).map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
        return `<span>현재 먹는 사료 (보호자 입력)</span><strong>${escapeHtml(food.food_name || "아직 입력되지 않았어요")}</strong>${rows ? `<dl class="health-detail-list">${rows}</dl>` : "<small>급여량·간식 정보가 없습니다.</small>"}`;
    }

    function activityStats(activity) {
        const walk = (activity || []).filter((item) => item.activity === "walk");
        const feeding = (activity || []).filter((item) => item.activity === "feeding");
        const walkDays = new Set(walk.map((item) => new Date(item.created_at).toLocaleDateString("ko-KR"))).size;
        const stats = {
            walkCount: walk.length ? `${walk.length}회` : "기록 없음",
            walkDetail: walk.length ? `주 평균 ${(walk.length / 30 * 7).toFixed(1)}회 · 산책한 날 ${walkDays}일` : "AI 인증 기록이 쌓이면 표시됩니다",
            feedingCount: feeding.length ? `${feeding.length}회` : "기록 없음",
            feedingDetail: "AI 인증 기록이 쌓이면 표시됩니다"
        };
        if (feeding.length) {
            const counts = new Map();
            feeding.forEach((item) => {
                const hour = new Date(item.created_at).getHours();
                const bucket = hour < 11 ? "오전" : hour < 16 ? "오후" : "저녁";
                counts.set(bucket, (counts.get(bucket) || 0) + 1);
            });
            const [bucket, count] = [...counts.entries()].sort((a, b) => b[1] - a[1])[0];
            stats.feedingDetail = `주 평균 ${(feeding.length / 30 * 7).toFixed(1)}회 · 주로 ${bucket} ${count}회`;
        }
        return stats;
    }

    function dueState(dueDate) {
        if (!dueDate) return { className: "", label: "예정일 미입력" };
        const days = Math.round((new Date(`${dueDate}T00:00:00`) - new Date(`${today()}T00:00:00`)) / 86400000);
        if (days < 0) return { className: "is-overdue", label: `${formatDate(dueDate)} · ${-days}일 지남` };
        if (days <= 30) return { className: "is-soon", label: `${formatDate(dueDate)} · ${days}일 남음` };
        return { className: "", label: formatDate(dueDate) };
    }

    // 백신·기생충 예방은 종류별 가장 최근 기록만 모아 다음 예정일을 보여준다.
    function renderPreventive(records) {
        const latest = new Map();
        records.filter((record) => record.record_type === "vaccination" || record.record_type === "parasite").forEach((record) => {
            const kind = record.details?.vaccine_type || record.details?.parasite_type || "other";
            const key = `${record.record_type}:${kind}`;
            if (!latest.has(key) || latest.get(key).record_date < record.record_date) latest.set(key, record);
        });
        if (!latest.size) {
            return '<div class="health-empty"><strong>예방접종·기생충 예방 기록이 없습니다.</strong><span>아래 건강 기록에서 “예방접종” 또는 “기생충 예방”으로 추가하세요.</span></div>';
        }
        return `<ul class="health-preventive-list">${[...latest.values()].sort((a, b) => a.record_type.localeCompare(b.record_type)).map((record) => {
            const due = dueState(record.details?.next_due_date);
            return `<li class="${due.className}"><div><span class="health-record-type">${escapeHtml(RECORD_TYPES[record.record_type].label)}</span><strong>${escapeHtml(recordTitle(record))}</strong><small>마지막 ${escapeHtml(formatDate(record.record_date))}${record.details?.product ? ` · ${escapeHtml(record.details.product)}` : ""}</small></div><div class="health-due"><span>다음 예정</span><strong>${escapeHtml(due.label)}</strong></div></li>`;
        }).join("")}</ul>`;
    }

    // 진료 시 먼저 확인하는 알레르기·현재 복용 약·관리 중 질환·수술/마취 이력
    function renderClinicalAlerts(records) {
        const groups = [
            ["allergy", "알레르기·부작용", records.filter((r) => r.record_type === "allergy")],
            ["medication", "현재 복용 약", records.filter((r) => r.record_type === "medication" && r.details?.medication_status !== "stopped")],
            ["condition", "관리 중인 질환", records.filter((r) => r.record_type === "condition" && r.details?.condition_status !== "resolved")],
            ["surgery", "수술·마취 이력", records.filter((r) => r.record_type === "surgery")]
        ];
        return `<div class="health-alert-grid">${groups.map(([type, title, items]) => `
            <div class="health-alert-box health-alert-${type}"><h3>${title}</h3>${items.length ? `<ul>${items.map((record) => {
                const extra = detailRows(record).slice(0, 3).map(([, value]) => value).join(" · ");
                return `<li><strong>${escapeHtml(recordTitle(record))}</strong>${extra ? `<small>${escapeHtml(extra)}</small>` : ""}${record.source === "clinic" ? '<small class="health-clinic-mark">병원 입력</small>' : ""}</li>`;
            }).join("")}</ul>` : '<p>기록 없음</p>'}</div>`).join("")}</div>`;
    }

    function buildFieldHtml(field) {
        const required = field.required ? " required" : "";
        const label = `${escapeHtml(field.label)}${field.required ? " *" : ""}`;
        const placeholder = field.placeholder ? ` placeholder="${escapeHtml(field.placeholder)}"` : "";
        const name = `details.${field.key}`;
        if (field.type === "select") {
            const options = Object.entries(field.options).map(([value, text]) => `<option value="${value}">${escapeHtml(text)}</option>`).join("");
            return `<label>${label}<select name="${name}"${required}><option value="">선택</option>${options}</select></label>`;
        }
        if (field.type === "textarea") return `<label class="health-form-wide">${label}<textarea name="${name}" rows="2" maxlength="1000"${placeholder}${required}></textarea></label>`;
        if (field.type === "number") return `<label>${label}<input name="${name}" type="number" inputmode="decimal" min="${field.min}" max="${field.max}" step="${field.step}"${placeholder}${required}></label>`;
        if (field.type === "date") return `<label>${label}<input name="${name}" type="date"${required}></label>`;
        return `<label>${label}<input name="${name}" maxlength="200"${placeholder}${required}></label>`;
    }

    function renderTypeFields(container, type) {
        const schema = RECORD_TYPES[type] || RECORD_TYPES.other;
        container.innerHTML = (schema.hint ? `<p class="health-form-hint health-form-wide">${escapeHtml(schema.hint)}</p>` : "") + schema.fields.map(buildFieldHtml).join("");
    }

    function collectRecordPayload(form) {
        const payload = { details: {} };
        new FormData(form).forEach((value, key) => {
            if (value instanceof File) return;
            if (key.startsWith("details.")) {
                if (String(value).trim()) payload.details[key.slice(8)] = String(value).trim();
            } else {
                payload[key] = String(value).trim();
            }
        });
        return payload;
    }

    async function hydrateImages(container, loader) {
        const images = container.querySelectorAll("img[data-health-image]:not([src])");
        await Promise.all([...images].map(async (image) => {
            try { image.src = await loader(image.dataset.healthImage); }
            catch (error) { image.replaceWith(Object.assign(document.createElement("small"), { textContent: "첨부 사진을 불러오지 못했습니다." })); }
        }));
    }

    window.HelloPuppyHealth = {
        RECORD_TYPES, QUESTIONNAIRE_SYSTEMS, SYSTEM_VALUES, PROGRESSIONS,
        escapeHtml, today, formatDate, formatDateTime, renderRecordCard, renderProfile, renderQuestionnaire, renderDiet,
        activityStats, renderPreventive, renderClinicalAlerts, renderTypeFields, collectRecordPayload, hydrateImages
    };
})();
