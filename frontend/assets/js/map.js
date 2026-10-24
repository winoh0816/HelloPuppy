(function () {
    "use strict";

    const api = window.HelloPuppyAPI;
    const mapElement = document.getElementById("walkMap");
    const status = document.getElementById("mapStatus");
    const recommendations = document.getElementById("mapRecommendations");
    let map;
    let activeTileLayer;
    let tileFallbackUsed = false;

    function setStatus(message, type = "") {
        status.textContent = message;
        status.dataset.type = type;
    }

    function googleMapsSearchUrl(location, latitude, longitude) {
        const query = latitude != null && longitude != null
            ? `${latitude},${longitude}`
            : location;
        return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
    }

    function createRecommendation(post) {
        const card = document.createElement("article");
        card.className = "map-recommendation-card";
        const header = document.createElement("div");
        header.className = "map-recommendation-header";
        const place = document.createElement("strong");
        place.textContent = post.location_name;
        const badge = document.createElement("span");
        badge.className = "map-category-badge";
        badge.textContent = post.category === "walk" ? "산책 코스" : "장소 추천";
        header.append(place, badge);
        const title = document.createElement("h3");
        title.textContent = post.title || "우리 동네 추천 장소";
        const detail = document.createElement("p");
        detail.textContent = post.body;
        const byline = document.createElement("p");
        byline.className = "map-recommendation-byline";
        byline.textContent = `${post.display_name} · ${new Date(post.created_at).toLocaleDateString("ko-KR")}`;
        const actions = document.createElement("div");
        actions.className = "map-recommendation-actions";
        const showPin = document.createElement("button");
        showPin.type = "button";
        showPin.textContent = "지도에서 보기";
        showPin.addEventListener("click", () => focusPost(post.id));
        actions.append(showPin);
        const openMaps = document.createElement("a");
        openMaps.href = googleMapsSearchUrl(post.location_name, post.latitude, post.longitude);
        openMaps.target = "_blank";
        openMaps.rel = "noopener noreferrer";
        openMaps.textContent = "Google Maps 열기 ↗";
        actions.append(openMaps);
        card.append(header, title, detail, byline, actions);
        return card;
    }

    const markersByPostId = new Map();
    function updateMarkerScore(postId, recommendationCount) {
        const markerCount = markersByPostId.get(postId)?.getElement()?.querySelector(".map-marker-heart-count");
        if (markerCount) markerCount.textContent = String(recommendationCount);
    }

    function makeMarker(post, bounds) {
        const position = [Number(post.latitude), Number(post.longitude)];
        const recommendationCount = Math.max(0, Number(post.recommendation_count) || 0);
        const markerIcon = L.divIcon({
            className: "map-marker-score-icon",
            html: `<span class="map-marker-pin" aria-hidden="true"><img src="https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png" alt=""></span><span class="map-marker-heart-badge" aria-label="추천 ${recommendationCount}개"><span aria-hidden="true">♥</span><span class="map-marker-heart-count">${recommendationCount}</span></span>`,
            iconSize: [76, 44],
            iconAnchor: [13, 41],
            popupAnchor: [0, -38]
        });
        const marker = L.marker(position, {
            icon: markerIcon,
            title: `${post.location_name} · 추천 ${recommendationCount}개`
        }).addTo(map);
        const popup = document.createElement("article");
        popup.className = "map-marker-info map-popup-card";

        if (post.image_id) {
            const photo = document.createElement("img");
            photo.className = "map-popup-photo";
            photo.alt = `${post.location_name} 커뮤니티 사진`;
            photo.loading = "eager";
            photo.src = `${api.baseUrl}/api/community/walk-map/images/${encodeURIComponent(post.image_id)}`;
            popup.append(photo);
        }

        const placeRow = document.createElement("div");
        placeRow.className = "map-popup-place-row";
        const place = document.createElement("strong");
        place.textContent = post.location_name;
        const badge = document.createElement("span");
        badge.className = "map-category-badge";
        badge.textContent = post.category === "walk" ? "산책 코스" : "추천 장소";
        placeRow.append(place, badge);

        const title = document.createElement("h3");
        title.className = "map-popup-title";
        title.textContent = post.title || "우리 동네 추천 장소";
        const body = document.createElement("p");
        body.className = "map-popup-body";
        body.textContent = post.body;
        const author = document.createElement("small");
        author.className = "map-popup-author";
        author.textContent = `🐾 ${post.display_name} · ${new Date(post.created_at).toLocaleDateString("ko-KR")}`;

        const actions = document.createElement("div");
        actions.className = "map-popup-actions";
        const recommendButton = document.createElement("button");
        recommendButton.type = "button";
        recommendButton.className = "map-recommend-button";
        recommendButton.setAttribute("aria-pressed", "false");
        const heart = document.createElement("span");
        heart.className = "map-recommend-heart";
        heart.setAttribute("aria-hidden", "true");
        const label = document.createElement("span");
        const count = document.createElement("span");
        count.className = "map-recommend-count";
        count.textContent = String(post.recommendation_count || 0);
        recommendButton.append(heart, label, count);

        const updateRecommendButton = (recommended, recommendationCount) => {
            recommendButton.classList.toggle("is-recommended", recommended);
            recommendButton.setAttribute("aria-pressed", String(recommended));
            heart.textContent = recommended ? "♥" : "♡";
            label.textContent = recommended ? "추천했어요!" : "이 장소가 마음에 들어요!";
            count.textContent = String(recommendationCount);
            updateMarkerScore(post.id, recommendationCount);
        };
        updateRecommendButton(false, Number(post.recommendation_count) || 0);
        recommendButton.addEventListener("click", async (event) => {
            event.stopPropagation();
            if (!api.isLoggedIn()) {
                window.alert("장소 추천은 로그인 후 할 수 있어요.");
                window.location.href = "account.html";
                return;
            }
            recommendButton.disabled = true;
            try {
                const result = await api.request(`/api/community/posts/${post.id}/recommendation`, { method: "POST" });
                updateRecommendButton(result.recommended, result.count);
            } catch (error) {
                window.alert(error.message);
            } finally {
                recommendButton.disabled = false;
            }
        });

        if (api.isLoggedIn()) {
            api.request(`/api/community/posts/${post.id}/recommendation`).then((result) => {
                updateRecommendButton(result.recommended, result.count);
            }).catch(() => {});
        }

        const link = document.createElement("a");
        link.className = "map-popup-directions";
        link.href = googleMapsSearchUrl(post.location_name, post.latitude, post.longitude);
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "길찾기 ↗";
        actions.append(recommendButton, link);
        popup.append(placeRow, title, body, author, actions);

        marker.bindPopup(popup, { maxWidth: 310, minWidth: 250, className: "walk-map-leaflet-popup" });
        markersByPostId.set(post.id, marker);
        bounds.push(position);
    }

    function useTileProvider(provider) {
        if (activeTileLayer) map.removeLayer(activeTileLayer);
        const tileUrl = provider === "osm-de"
            ? "https://tile.openstreetmap.de/{z}/{x}/{y}.png"
            : "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
        activeTileLayer = L.tileLayer(tileUrl, {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
        }).addTo(map);
        let errors = 0;
        activeTileLayer.on("tileerror", () => {
            errors += 1;
            if (errors >= 2 && provider === "osm" && !tileFallbackUsed) {
                tileFallbackUsed = true;
                useTileProvider("osm-de");
            } else if (errors >= 2 && provider === "osm") {
                setStatus("기본 지도 타일을 불러오지 못해 대체 서버를 시도하고 있어요.", "notice");
            } else if (errors >= 2 && provider === "osm-de") {
                setStatus("지도 타일 서버 접근이 차단되었습니다. 네트워크 연결이나 보안 프로그램을 확인해 주세요.", "error");
            }
        });
    }

    async function loadMapPage() {
        setStatus("커뮤니티에서 장소를 불러오는 중입니다.");
        try {
            const result = await api.request("/api/community/walk-map?limit=100");
            const posts = result.items || [];
            await window.loadHelloPuppyMapLibrary();
            mapElement.classList.remove("map-unavailable");
            map = L.map(mapElement, { scrollWheelZoom: false }).setView([37.5665, 126.9780], 12);
            useTileProvider("osm");

            const bounds = [];
            for (const post of posts) {
                if (post.latitude != null && post.longitude != null &&
                    Number.isFinite(Number(post.latitude)) && Number.isFinite(Number(post.longitude))) {
                    makeMarker(post, bounds);
                }
            }
            if (bounds.length > 0) {
                if (bounds.length === 1) map.setView(bounds[0], 14);
                else map.fitBounds(bounds, { padding: [32, 32], maxZoom: 15 });
                setStatus(`${bounds.length}개의 장소를 지도에 표시하고 있어요. 누구나 장소를 볼 수 있습니다.`, "success");
            } else if (posts.length > 0) {
                setStatus("장소 게시물은 있지만 좌표가 없습니다. 피드에서 검색 결과를 선택해 공유해 주세요.", "notice");
            } else {
                setStatus("아직 공유된 산책 장소가 없어요. 피드에서 장소를 공유해 주세요.", "notice");
            }
            recommendations.replaceChildren(...posts.map(createRecommendation));
            window.setTimeout(() => map.invalidateSize(), 50);
        } catch (error) {
            mapElement.classList.add("map-unavailable");
            setStatus(error.message || "지도를 불러오지 못했습니다. 인터넷 연결을 확인해 주세요.", "error");
        }
    }

    function focusPost(postId) {
        const marker = markersByPostId.get(postId);
        if (!marker) return;
        map.setView(marker.getLatLng(), Math.max(map.getZoom(), 15), { animate: true });
        marker.openPopup();
    }

    loadMapPage();
})();
