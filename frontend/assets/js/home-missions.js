/* Home: walk and feeding missions first. Shows today's rewards per mission (from /api/missions/today),
   the pet's name and this month's pet-supply spending. Works logged out too (tiles still link to the pages). */
(function () {
    "use strict";

    const api = window.HelloPuppyAPI;
    const note = document.getElementById("missionNote");
    const today = document.getElementById("homeToday");
    const days = ["일", "월", "화", "수", "목", "금", "토"];
    const now = new Date();
    if (today) today.textContent = `${now.getMonth() + 1}월 ${now.getDate()}일 ${days[now.getDay()]}요일`;

    function renderMission(mission) {
        const tile = document.querySelector(`[data-mission="${mission.key}"]`);
        if (!tile) return;
        const dots = tile.querySelector("[data-progress]");
        if (dots) {
            dots.replaceChildren();
            for (let index = 0; index < mission.daily_limit; index += 1) {
                const dot = document.createElement("i");
                if (index < mission.rewarded_today) dot.className = "is-on";
                dots.append(dot);
            }
        }
        const status = tile.querySelector("[data-status]");
        if (status) status.textContent = `오늘 ${mission.rewarded_today} / ${mission.daily_limit}번 적립`;
        const cta = tile.querySelector("[data-cta]");
        tile.classList.toggle("is-done", mission.done);
        if (cta && mission.done) cta.textContent = "✓ 오늘 적립 완료";
        tile.setAttribute("aria-label", `${mission.label}, ${mission.points}포인트, 오늘 ${mission.rewarded_today}번 중 ${mission.daily_limit}번 적립${mission.done ? ", 완료" : ""}`);
    }

    // 받침이 있으면 '과', 없으면 '와' (콩이와, 보리와 / 초코과 X -> 초코와, 밤톨과)
    function withParticle(name) {
        const code = name.charCodeAt(name.length - 1) - 0xac00;
        return code >= 0 && code <= 11171 && code % 28 !== 0 ? "과" : "와";
    }

    function won(value) {
        return `${Number(value || 0).toLocaleString("ko-KR")}원`;
    }

    async function load() {
        if (!api?.isLoggedIn()) {
            if (note) note.innerHTML = '<a href="account.html">로그인</a>하면 오늘 적립 현황을 볼 수 있어요.';
            return;
        }
        const [missions, profile, spending] = await Promise.allSettled([
            api.request("/api/missions/today"), api.request("/api/pet/profile"), api.request("/api/receipts/summary"),
        ]);
        if (missions.status === "fulfilled") {
            const core = missions.value.missions.filter((m) => m.key === "walk" || m.key === "feeding");
            core.forEach(renderMission);
            const left = core.filter((m) => !m.done).map((m) => m.label.replace(" 인증", ""));
            if (note) {
                note.textContent = left.length
                    ? `오늘 ${missions.value.points_today.toLocaleString("ko-KR")}P 받았어요. ${left.join("과 ")} 인증이 남았어요.`
                    : `오늘 산책과 급여 인증을 모두 마쳤어요! 받은 포인트 ${missions.value.points_today.toLocaleString("ko-KR")}P`;
            }
        } else if (note) {
            note.textContent = "적립 현황을 불러오지 못했어요. 인증은 그대로 할 수 있어요.";
        }
        const petName = profile.status === "fulfilled" ? profile.value.profile?.name : "";
        const greeting = document.getElementById("homeGreeting");
        if (greeting && petName) {
            greeting.replaceChildren(`${petName}${withParticle(petName)} 함께`, document.createElement("br"), "오늘도 인증해요");
        }
        const spend = document.getElementById("homeMonthSpend");
        if (spend && spending.status === "fulfilled" && spending.value.receipt_count) {
            spend.textContent = `이번 달 ${won(spending.value.this_month_spent)}`;
        }
    }

    load();
}());
