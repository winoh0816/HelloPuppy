import os

# 1. 폴더 구조 생성
folders = ['assets/css', 'assets/js']
for folder in folders:
    os.makedirs(folder, exist_ok=True)

# 2. 공통 하단 네비게이션 바 HTML
nav_html = '''
<nav class="bottom-nav">
    <a href="index.html" class="nav-item">🏠<br>홈</a>
    <a href="receipt.html" class="nav-item">🧾<br>영수증</a>
    <a href="auth.html" class="nav-item auth-btn">📸<br>인증</a>
    <a href="feed.html" class="nav-item">🐾<br>피드</a>
    <a href="shop.html" class="nav-item">🎁<br>상점</a>
</nav>
'''

# 3. 파일별 내용 정의
files = {}

# --- CSS (애니메이션 및 세련된 UI 적용) ---
files['assets/css/style.css'] = '''
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
body { background-color: #f4f4f5; margin: 0; font-family: 'Pretendard', sans-serif; color: #333; }
.app-container { max-width: 480px; margin: 0 auto; background-color: #ffffff; min-height: 100vh; position: relative; padding-bottom: 70px; box-shadow: 0 0 20px rgba(0,0,0,0.05); overflow-x: hidden; }
header { padding: 15px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #f0f0f0; background: #fff; position: sticky; top: 0; z-index: 10;}
header h1 { margin: 0; font-size: 20px; color: #FF7043; }
.content { padding: 20px; animation: fadeIn 0.4s ease-out; }

/* 애니메이션 */
@keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
@keyframes scan { 0% { top: 0; } 50% { top: 100%; } 100% { top: 0; } }
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
@keyframes pulse { 0% { transform: scale(1); } 50% { transform: scale(1.05); } 100% { transform: scale(1); } }

/* 네비게이션 바 */
.bottom-nav { position: fixed; bottom: 0; max-width: 480px; width: 100%; display: flex; justify-content: space-around; align-items: center; background: #fff; padding: 10px 0; border-top: 1px solid #eee; z-index: 1000; left: 50%; transform: translateX(-50%); box-shadow: 0 -2px 10px rgba(0,0,0,0.03); }
.nav-item { text-decoration: none; color: #999; font-size: 12px; text-align: center; }
.nav-item.active { color: #FF7043; font-weight: bold; }
.auth-btn { background: #FF7043; color: white !important; padding: 10px 20px; border-radius: 20px; box-shadow: 0 4px 10px rgba(255, 112, 67, 0.3); animation: pulse 2s infinite; }

/* 공통 UI 요소 */
.card { background: #fff; border: 1px solid #eee; border-radius: 16px; padding: 16px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.02); }
.btn { background-color: #FF7043; color: white; padding: 14px; border: none; border-radius: 12px; font-size: 16px; font-weight: bold; cursor: pointer; width: 100%; display: block; text-align: center; margin-top: 10px; transition: 0.2s; }
.btn:active { transform: scale(0.98); }
.img-placeholder { width: 100%; height: 200px; border-radius: 12px; object-fit: cover; background-color: #eee; margin-bottom: 10px; }

/* 모달 & 로딩 */
.modal-overlay { display: none; position: fixed; top:0; left:50%; transform:translateX(-50%); width: 100%; max-width: 480px; height: 100%; background: rgba(0,0,0,0.6); z-index: 2000; justify-content: center; align-items: center; }
.modal-content { background: white; padding: 30px 20px; border-radius: 16px; text-align: center; width: 80%; }
.spinner { border: 4px solid #f3f3f3; border-top: 4px solid #FF7043; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 15px auto; }

/* 카메라 스캐너 */
.scanner-box { position: relative; width: 100%; height: 300px; overflow: hidden; border-radius: 16px; margin-bottom: 20px; background: #000; }
.scanner-box img { width: 100%; height: 100%; object-fit: cover; opacity: 0.8; }
.scan-line { display: none; position: absolute; left: 0; width: 100%; height: 3px; background: #00FF00; box-shadow: 0 0 10px #00FF00; animation: scan 2s linear infinite; }
'''

# --- JS (동적 이벤트 및 모달 제어) ---
files['assets/js/app.js'] = '''
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
'''

# --- 공통 모달 UI ---
modal_html = '''
<div id="loading-modal" class="modal-overlay">
    <div class="modal-content">
        <div id="loading-spinner" class="spinner"></div>
        <h3 id="loading-msg" style="margin:0; line-height:1.4;"></h3>
    </div>
</div>
<script src="assets/js/app.js"></script>
'''

# 1. 스플래시 및 로그인 화면 (앱의 시작점)
files['splash.html'] = '''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><title>안녕멍뭉</title><link rel="stylesheet" href="assets/css/style.css">
<style>
    .splash-container { background: #FF7043; height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center; color: white; max-width: 480px; margin: 0 auto; }
    .logo { font-size: 40px; font-weight: 900; margin-bottom: 10px; animation: pulse 2s infinite; }
    .login-box { margin-top: 50px; width: 80%; animation: fadeIn 1s ease-out; }
    .login-btn { background: white; color: #FF7043; font-weight: bold; border-radius: 25px; padding: 15px; margin-bottom: 10px; display: block; text-align: center; text-decoration: none; }
    .kakao-btn { background: #FEE500; color: #000; }
</style></head>
<body><div class="splash-container">
    <div class="logo">🐶 안녕멍뭉</div>
    <p>우리아이 건강한 산책 습관</p>
    <div class="login-box">
        <a href="index.html" class="login-btn kakao-btn">카카오톡으로 시작하기</a>
        <a href="index.html" class="login-btn">이메일로 시작하기</a>
    </div>
</div></body></html>'''

# 2. 메인 홈 (대시보드)
files['index.html'] = f'''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><title>안녕멍뭉 - 홈</title><link rel="stylesheet" href="assets/css/style.css"></head>
<body><div class="app-container">
    <header><h1>안녕멍뭉</h1><a href="mypage.html" style="text-decoration:none; font-size:24px;">⚙️</a></header>
    <div class="content">
        <div class="card" style="background: linear-gradient(135deg, #FF7043, #FF8A65); color: white;">
            <h2>초코의 오늘 활동 🐾</h2>
            <p>보유 포인트: <b>1,500 P</b></p>
            <div style="background: rgba(255,255,255,0.3); border-radius: 10px; padding: 10px; margin-top: 10px;">
                목표 산책량 달성까지 2,000걸음 남았어요!
            </div>
        </div>
        <h3 style="margin-top: 30px;">미션 인증하기</h3>
        <a href="auth.html" style="text-decoration:none;"><div class="card" style="display:flex; align-items:center; gap:15px; border-left: 5px solid #4CAF50;">
            <div style="font-size:30px;">🦮</div><div><h4 style="margin:0;">산책 인증하기</h4><p style="margin:5px 0 0; font-size:13px; color:#666;">GPS 기반 야외 활동 인증 (+100P)</p></div>
        </div></a>
        <a href="auth.html" style="text-decoration:none;"><div class="card" style="display:flex; align-items:center; gap:15px; border-left: 5px solid #2196F3;">
            <div style="font-size:30px;">🥣</div><div><h4 style="margin:0;">식사/급여 인증하기</h4><p style="margin:5px 0 0; font-size:13px; color:#666;">시간대 및 밥그릇 인식 (+50P)</p></div>
        </div></a>
    </div>
{nav_html}</div></body></html>'''

# 3. 카메라 및 AI 인증 (가장 중요한 교차 검증 시연)
files['auth.html'] = f'''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><title>안녕멍뭉 - AI 인증</title><link rel="stylesheet" href="assets/css/style.css"></head>
<body><div class="app-container"><header><h1>실시간 카메라 인증</h1></header>
    <div class="content">
        <div class="scanner-box">
            <img src="https://images.unsplash.com/photo-1543466835-00a7907e9de1?auto=format&fit=crop&w=500&q=80" alt="camera view">
            <div class="scan-line"></div>
            <div style="position:absolute; top:10px; left:10px; background:rgba(0,0,0,0.5); color:white; padding:5px 10px; border-radius:5px; font-size:12px;">📍 GPS: 서울특별시 ㅇㅇ동<br>🕒 시간: 18:30</div>
        </div>
        <button class="btn" onclick="startCameraAuth()">📸 촬영 및 AI 검증 시작</button>
        <p style="text-align:center; font-size:12px; color:#888; margin-top:15px;">* 화면 도용 방지를 위해 실시간 촬영만 허용됩니다.</p>
    </div>
{nav_html}{modal_html}</div></body></html>'''

# 4. 영수증 OCR 인증
files['receipt.html'] = f'''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><title>안녕멍뭉 - 영수증</title><link rel="stylesheet" href="assets/css/style.css"></head>
<body><div class="app-container"><header><h1>영수증 리워드</h1></header>
    <div class="content">
        <p>오프라인 펫샵 결제 영수증을 인증하고<br>포인트와 맞춤형 샘플을 추천받으세요!</p>
        <div class="card" style="padding:0; overflow:hidden;">
            <img id="receipt-img" src="https://images.unsplash.com/photo-1605333310058-963503a6bc41?auto=format&fit=crop&w=500&q=80" class="img-placeholder" style="margin:0; border-radius:0; height:250px;">
        </div>
        <button class="btn" onclick="startOCR()">영수증 텍스트 추출 (OCR)</button>
    </div>
{nav_html}{modal_html}</div></body></html>'''

# 5. 커뮤니티 피드
files['feed.html'] = f'''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><title>안녕멍뭉 - 피드</title><link rel="stylesheet" href="assets/css/style.css"></head>
<body><div class="app-container"><header><h1>멍스텝 피드</h1></header>
    <div class="content">
        <div class="card">
            <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px;">
                <img src="https://images.unsplash.com/photo-1517849845537-4d257902454a?auto=format&fit=crop&w=100&q=80" style="width:40px; height:40px; border-radius:50%;">
                <b>초코 맘</b> <span style="color:#999; font-size:12px;">방금 전</span>
            </div>
            <img src="https://images.unsplash.com/photo-1583337130417-3346a1be7dee?auto=format&fit=crop&w=500&q=80" class="img-placeholder">
            <p>오늘 날씨가 너무 좋아서 한강 산책 나왔어요! 안녕멍뭉 AI 인식 진짜 빠르네요👍</p>
            <div style="color:#FF7043; font-weight:bold; margin-bottom:10px;">❤️ 24 좋아요</div>
            <hr style="border:0; border-top:1px solid #eee;">
            <p style="font-size:13px; color:#555; margin-top:10px;"><b>두부 아빠:</b> 동네 산책로 좋네요~ 코스 공유 부탁드려요!</p>
        </div>
        
        <div class="card">
            <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px;">
                <img src="https://images.unsplash.com/photo-1537151608804-ea2f1fa8c081?auto=format&fit=crop&w=100&q=80" style="width:40px; height:40px; border-radius:50%;">
                <b>보리 누나</b> <span style="color:#999; font-size:12px;">2시간 전</span>
            </div>
            <img src="https://images.unsplash.com/photo-1589924691995-400dc9ecc119?auto=format&fit=crop&w=500&q=80" class="img-placeholder">
            <p>저녁밥 야무지게 먹는 보리! 급여 시간대 맞춰서 추가 포인트 받았어요 ㅎㅎ</p>
            <div style="color:#FF7043; font-weight:bold;">❤️ 15 좋아요</div>
        </div>
    </div>
{nav_html}</div></body></html>'''

# 6. 상점 (B2B 샘플링)
files['shop.html'] = f'''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><title>안녕멍뭉 - 상점</title><link rel="stylesheet" href="assets/css/style.css"></head>
<body><div class="app-container"><header><h1>포인트 상점</h1></header>
    <div class="content">
        <h3 style="margin-top:0; color:#FF7043;">내 포인트: 1,500 P</h3>
        <p style="font-size:13px; color:#666;">영수증 분석 결과, <b>관절 영양제</b>를 많이 구매하셨네요!<br>맞춤형 B2B 무료 샘플을 추천해 드립니다.</p>
        
        <div class="card" style="display:flex; gap:15px;">
            <img src="https://images.unsplash.com/photo-1585848529606-2580a133fc16?auto=format&fit=crop&w=200&q=80" style="width:100px; height:100px; border-radius:10px; object-fit:cover;">
            <div style="flex:1;">
                <span style="background:#4CAF50; color:white; font-size:10px; padding:3px 6px; border-radius:4px;">맞춤 추천</span>
                <h4 style="margin:5px 0;">조인트 덴탈 츄 샘플팩</h4>
                <p style="margin:0; font-weight:bold; color:#FF7043;">500 P</p>
                <button class="btn" style="padding:8px; font-size:13px;" onclick="buyItem()">교환하기</button>
            </div>
        </div>
        
        <div class="card" style="display:flex; gap:15px;">
            <img src="https://images.unsplash.com/photo-1568644396922-5c3bfae12521?auto=format&fit=crop&w=200&q=80" style="width:100px; height:100px; border-radius:10px; object-fit:cover;">
            <div style="flex:1;">
                <h4 style="margin:5px 0;">프리미엄 연어 화식 100g</h4>
                <p style="margin:0; font-weight:bold; color:#FF7043;">1,000 P</p>
                <button class="btn" style="padding:8px; font-size:13px;" onclick="buyItem()">교환하기</button>
            </div>
        </div>
    </div>
{nav_html}{modal_html}</div></body></html>'''

# 7. 마이페이지 (설정)
files['mypage.html'] = f'''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><title>안녕멍뭉 - 마이페이지</title><link rel="stylesheet" href="assets/css/style.css"></head>
<body><div class="app-container"><header><h1>설정 및 내 정보</h1></header>
    <div class="content">
        <div class="card" style="text-align:center;">
            <img src="https://images.unsplash.com/photo-1517849845537-4d257902454a?auto=format&fit=crop&w=150&q=80" style="width:80px; height:80px; border-radius:50%; margin-bottom:10px;">
            <h3 style="margin:0;">초코 맘</h3>
            <p style="color:#666; font-size:14px;">등록 반려견: 초코 (푸들, 3살)</p>
        </div>
        
        <h4>교차 검증 설정 (시스템 변수)</h4>
        <div class="card">
            <p style="margin-top:0;"><b>📍 기준 집 위치 (GPS)</b><br><span style="font-size:13px; color:#888;">서울특별시 마포구 월드컵북로 123</span></p>
            <p><b>🕒 평균 급여 시간</b><br><span style="font-size:13px; color:#888;">아침 08:00 / 저녁 19:00</span></p>
            <button class="btn" style="background:#eee; color:#333; box-shadow:none;">설정 변경하기</button>
        </div>
    </div>
{nav_html}</div></body></html>'''

# 파일 생성 실행
for path, content in files.items():
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

print("✅ '안녕멍뭉'의 모든 프론트엔드 더미 파일(7종)이 애니메이션과 고화질 이미지와 함께 생성되었습니다!")