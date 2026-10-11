
function showLoading(message, callback, delay = 2500) {
    const modal = document.getElementById('loading-modal');
    const msgEl = document.getElementById('loading-msg');
    const spinner = document.getElementById('loading-spinner');
    
    modal.style.display = 'flex';
    msgEl.innerHTML = message;
    spinner.style.display = 'block';
    
    setTimeout(() => {
        spinner.style.display = 'none';
        msgEl.innerHTML = callback.message;
        setTimeout(() => {
            modal.style.display = 'none';
            if(callback.action) callback.action();
        }, 1500);
    }, delay);
}

function startCameraAuth() {
    document.querySelector('.scan-line').style.display = 'block';
    showLoading("AI 비전 및 GPS 데이터<br>교차 검증 중입니다...", {
        message: "✅ 인증 성공!<br>산책 포인트 100P가 적립되었습니다.",
        action: () => { window.location.href = "feed.html"; }
    });
}

function startOCR() {
    document.getElementById('receipt-img').style.filter = "brightness(0.5)";
    showLoading("영수증 품목 텍스트를<br>추출하고 있습니다...", {
        message: "🎉 분석 완료!<br>로얄캐닌 사료 외 1건 (15,000원)",
        action: () => { document.getElementById('receipt-img').style.filter = "none"; }
    });
}

function buyItem() {
    showLoading("포인트를 확인 중입니다...", {
        message: "🎁 교환 완료!<br>쿠폰함으로 발송되었습니다."
    }, 1000);
}


/* ==============================
   식사/급여 인증
============================== */

// 촬영한 급여 사진 미리보기
function previewFeedingPhoto(event) {
    const file = event.target.files[0];

    if (!file) {
        return;
    }

    // 이미지 파일인지 확인
    if (!file.type.startsWith("image/")) {
        alert("이미지 파일을 선택해 주세요.");
        event.target.value = "";
        return;
    }

    const imageUrl = URL.createObjectURL(file);

    document.getElementById("feeding-img").src = imageUrl;

    document.getElementById("feeding-photo-status").textContent =
        "✅ 사진이 선택되었습니다. AI 인증을 진행해 주세요.";
}


// 급여 사진 인증
function startFeedingAuth() {
    const photoInput = document.getElementById("feeding-photo");

    // 사진을 선택하지 않았을 경우
    if (!photoInput.files || photoInput.files.length === 0) {
        alert("먼저 사료 급여 사진을 촬영해 주세요.");
        return;
    }

    // 기존 산책 인증과 같은 로딩 UI 활용
    document.getElementById("feeding-scan-line").style.display = "block";

    showLoading(
        "AI 비전으로 사료 급여 사진을<br>검증하고 있습니다...",
        {
            message: "🎉 급여 인증 성공!<br>식사/급여 포인트 50P가 적립되었습니다.",
            action: () => {
                document.getElementById("feeding-scan-line").style.display = "none";
                window.location.href = "feed.html";
            }
        }
    );
}

