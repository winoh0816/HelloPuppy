(function () {
    "use strict";

    const mapElement = document.getElementById("homeWalkMap");
    const status = document.getElementById("homeWalkMapStatus");
    if (!mapElement || !status || !window.HelloPuppyAPI) return;

    function setStatus(message) {
        status.textContent = message;
    }

    function createPreviewIcon(count) {
        return L.divIcon({
            className: "home-map-marker-icon",
            html: `<span class="home-map-marker-pin"><img src="https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png" alt=""></span><span class="home-map-marker-heart"><span>♥</span><b>${Math.max(0, Number(count) || 0)}</b></span>`,
            iconSize: [66, 40],
            iconAnchor: [12, 38],
            popupAnchor: [0, -34]
        });
    }

    async function loadPreview() {
        try {
            const [{ items = [] }] = await Promise.all([
                window.HelloPuppyAPI.request("/api/community/walk-map?limit=50"),
                window.loadHelloPuppyMapLibrary()
            ]);
            const posts = items.filter((post) => post.latitude != null && post.longitude != null &&
                Number.isFinite(Number(post.latitude)) && Number.isFinite(Number(post.longitude)));
            const previewMap = L.map(mapElement, {
                zoomControl: false,
                attributionControl: false,
                scrollWheelZoom: false,
                dragging: true,
                doubleClickZoom: false,
                boxZoom: false,
                keyboard: false,
                tap: false
            }).setView([37.5665, 126.9780], 11);
            L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                maxZoom: 19,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>'
            }).addTo(previewMap);

            const bounds = [];
            for (const post of posts) {
                const position = [Number(post.latitude), Number(post.longitude)];
                const marker = L.marker(position, { icon: createPreviewIcon(post.recommendation_count) }).addTo(previewMap);
                const popup = document.createElement("div");
                popup.className = "home-map-preview-popup";
                const place = document.createElement("strong");
                place.textContent = post.location_name;
                const title = document.createElement("span");
                title.textContent = post.title || "커뮤니티 추천 산책 장소";
                popup.append(place, title);
                marker.bindPopup(popup, { closeButton: false, offset: [0, -2] });
                bounds.push(position);
            }

            if (bounds.length === 1) previewMap.setView(bounds[0], 13);
            else if (bounds.length > 1) previewMap.fitBounds(bounds, { padding: [24, 24], maxZoom: 13 });
            setStatus(bounds.length ? `${bounds.length}곳의 커뮤니티 추천 장소 · 하트를 눌러 자세히 보기` : "공유된 장소가 생기면 지도에 표시돼요");
            window.setTimeout(() => previewMap.invalidateSize(), 80);
        } catch (error) {
            mapElement.classList.add("home-map-unavailable");
            setStatus("지도를 불러오지 못했어요. 눌러서 산책 코스 지도로 이동해 주세요.");
            console.warn("홈 지도 미리보기 실패:", error.message);
        }
    }

    loadPreview();
})();
