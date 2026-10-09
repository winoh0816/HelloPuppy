
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
