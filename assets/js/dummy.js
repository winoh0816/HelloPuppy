
function authAction() {
    alert("AI 분석 중...");
    setTimeout(() => { alert("인증 완료! 100P가 지급되었습니다."); }, 2000);
}
function uploadReceipt() {
    document.getElementById('receipt-result').innerText = "영수증 분석 완료: 로얄캐닌 사료 15,000원 인식 성공 ✅";
}
function buyItem() {
    alert("쿠폰함으로 발급되었습니다!");
}
