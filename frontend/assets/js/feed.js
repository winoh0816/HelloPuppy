(function () {
    "use strict";

    const api = window.HelloPuppyAPI;
    const postsRoot = document.getElementById("serverPosts");
    const composer = document.getElementById("composer");
    const writeButton = document.querySelector(".section-heading .btn");
    const locationInput = document.getElementById("postLocation");
    const locationHelp = document.getElementById("locationHelp");
    const latitudeInput = document.getElementById("postLatitude");
    const longitudeInput = document.getElementById("postLongitude");
    let locationPredictionList;
    let locationSearchTimer;
    let locationSearchController;

    if (composer && writeButton) {
        writeButton.removeAttribute("onclick");
        writeButton.setAttribute("aria-controls", "composer");
        writeButton.setAttribute("aria-expanded", "false");
        composer.style.display = "none";
        writeButton.addEventListener("click", () => {
            const isOpening = composer.style.display === "none";
            composer.style.display = isOpening ? "block" : "none";
            writeButton.setAttribute("aria-expanded", String(isOpening));
            if (isOpening) {
                document.getElementById("postTitle")?.focus({ preventScroll: true });
                composer.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }
        });
    }

    if (locationInput) {
        locationPredictionList = document.createElement("div");
        locationPredictionList.className = "location-prediction-list";
        locationPredictionList.hidden = true;
        locationPredictionList.setAttribute("role", "listbox");
        locationInput.insertAdjacentElement("afterend", locationPredictionList);

        locationInput.addEventListener("input", () => {
            latitudeInput.value = "";
            longitudeInput.value = "";
            locationInput.dataset.placeSelected = "false";
            locationPredictionList.replaceChildren();
            const query = locationInput.value.trim();
            if (query.length < 2) {
                locationPredictionList.hidden = true;
                if (locationHelp) locationHelp.textContent = "두 글자 이상 입력한 뒤 검색 결과를 선택해 주세요. 선택한 장소는 지도에서 공개됩니다.";
                return;
            }
            if (locationHelp) locationHelp.textContent = "장소를 검색하고 있어요…";
            window.clearTimeout(locationSearchTimer);
            locationSearchController?.abort();
            locationSearchTimer = window.setTimeout(async () => {
                const controller = new AbortController();
                locationSearchController = controller;
                try {
                    const url = new URL("https://photon.komoot.io/api/");
                    url.searchParams.set("q", query);
                    url.searchParams.set("lang", "en");
                    url.searchParams.set("limit", "6");
                    url.searchParams.set("lat", "37.5665");
                    url.searchParams.set("lon", "126.9780");
                    const response = await fetch(url, { signal: controller.signal });
                    if (!response.ok) throw new Error("검색 응답 오류");
                    const data = await response.json();
                    locationPredictionList.replaceChildren();
                    const features = data.features || [];
                    if (!features.length) {
                        locationPredictionList.hidden = true;
                        if (locationHelp) locationHelp.textContent = "검색 결과가 없습니다. 다른 장소 이름으로 검색해 보세요.";
                        return;
                    }
                    for (const feature of features) {
                        const properties = feature.properties || {};
                        const label = [properties.name, properties.street, properties.district, properties.city, properties.state]
                            .filter((part, index, all) => part && all.indexOf(part) === index)
                            .join(", ");
                        if (!label || !Array.isArray(feature.geometry?.coordinates)) continue;
                        const option = document.createElement("button");
                        option.type = "button";
                        option.className = "location-prediction";
                        option.setAttribute("role", "option");
                        option.textContent = label;
                        option.addEventListener("click", () => {
                            locationInput.value = label;
                            locationInput.dataset.placeSelected = "true";
                            longitudeInput.value = String(feature.geometry.coordinates[0]);
                            latitudeInput.value = String(feature.geometry.coordinates[1]);
                            locationPredictionList.replaceChildren();
                            locationPredictionList.hidden = true;
                            if (locationHelp) locationHelp.textContent = "장소가 선택됐어요. 장소명과 좌표가 공개 지도에 표시됩니다.";
                        });
                        locationPredictionList.append(option);
                    }
                    locationPredictionList.hidden = locationPredictionList.childElementCount === 0;
                    if (locationHelp) locationHelp.textContent = locationPredictionList.hidden
                        ? "좌표가 포함된 장소 검색 결과가 없습니다."
                        : "목록에서 정확한 장소를 선택해 주세요. 위치 정보는 지도에 공개됩니다.";
                } catch (error) {
                    if (error.name === "AbortError") return;
                    locationPredictionList.hidden = true;
                    if (locationHelp) locationHelp.textContent = "장소 검색을 사용할 수 없습니다. 인터넷 연결을 확인해 주세요.";
                }
            }, 550);
        });
    }

    function makeElement(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    }

    function showError(message) {
        window.alert(message || "요청을 처리하지 못했습니다.");
    }

    async function loadComments(postId, list, emptyMessage) {
        list.replaceChildren();
        try {
            const result = await api.request(`/api/community/posts/${postId}/comments`);
            if (!result.items.length) {
                list.append(makeElement("p", "inline-comment-empty", emptyMessage));
                return;
            }
            for (const item of result.items) {
                const row = makeElement("div", "inline-comment");
                row.append(makeElement("span", "inline-comment-avatar", "🐾"));
                const content = makeElement("div", "inline-comment-content");
                content.append(makeElement("span", "inline-comment-author", item.display_name));
                content.append(document.createTextNode(item.body));
                row.append(content);
                list.append(row);
            }
        } catch (error) {
            list.append(makeElement("p", "inline-comment-empty", error.message));
        }
    }

    function makeCommentArea(postId) {
        const panel = makeElement("section", "inline-comments");
        panel.id = `comments-${postId}`;
        panel.setAttribute("aria-label", "댓글");
        const inner = makeElement("div", "inline-comment-inner");
        const list = makeElement("div", "inline-comment-list");
        list.setAttribute("aria-live", "polite");
        const emptyMessage = makeElement("p", "inline-comment-empty", "댓글을 불러오는 중입니다…");
        list.append(emptyMessage);

        const form = makeElement("form", "inline-comment-form");
        const input = makeElement("input", "inline-comment-input");
        input.type = "text";
        input.name = "body";
        input.maxLength = 1000;
        input.placeholder = "따뜻한 댓글을 남겨 주세요 🐾";
        input.setAttribute("aria-label", "댓글 내용");
        const submit = makeElement("button", "inline-comment-submit", "등록");
        submit.type = "submit";
        form.append(input, submit);
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const body = input.value.trim();
            if (!body) {
                input.focus();
                return;
            }
            submit.disabled = true;
            try {
                await api.request(`/api/community/posts/${postId}/comments`, {
                    method: "POST",
                    body: JSON.stringify({ body })
                });
                input.value = "";
                await loadComments(postId, list, "첫 댓글을 남겨 대화를 시작해 보세요.");
            } catch (error) {
                showError(error.message);
            } finally {
                submit.disabled = false;
                input.focus();
            }
        });

        inner.append(list, form);
        panel.append(inner);
        return { panel, list };
    }

    function makePostCard(post) {
        const card = makeElement("article", "card feed-post");
        card.dataset.kind = post.category;

        const meta = makeElement("div", "post-meta");
        const avatar = makeElement("div", "avatar");
        avatar.append(makeElement("img"));
        avatar.firstElementChild.src = "assets/images/brand/emoji-start.png";
        avatar.firstElementChild.alt = "";
        const author = makeElement("div");
        author.append(makeElement("b", "", post.display_name));
        author.append(makeElement("div", "muted", new Date(post.created_at).toLocaleString("ko-KR")));
        meta.append(avatar, author);

        const title = makeElement("h3", "community-post-title", post.title || "우리 아이 이야기");
        const body = makeElement("p", "post-copy", post.body);
        card.append(meta, title, body);

        if (post.image_id) {
            const image = makeElement("img", "img-placeholder");
            image.alt = "커뮤니티 첨부 사진";
            card.append(image);
            api.imageUrl(post.image_id).then((url) => { image.src = url; }).catch(() => image.remove());
        }

        const actions = makeElement("div", "post-actions");
        const like = makeElement("button", post.liked ? "liked" : "");
        like.type = "button";
        like.setAttribute("aria-pressed", String(Boolean(post.liked)));
        const heart = makeElement("img", "brand-icon small");
        heart.src = "assets/images/brand/icon-heart.png";
        heart.alt = "";
        like.append(heart, document.createTextNode(` ${post.like_count} 좋아요`));
        like.addEventListener("click", async () => {
            like.disabled = true;
            try {
                const result = await api.request(`/api/community/posts/${post.id}/like`, { method: "POST" });
                like.classList.toggle("liked", result.liked);
                like.setAttribute("aria-pressed", String(result.liked));
                like.lastChild.textContent = ` ${result.count} 좋아요`;
            } catch (error) {
                showError(error.message);
            } finally {
                like.disabled = false;
            }
        });

        const commentButton = makeElement("button", "comment-toggle", "댓글 보기");
        commentButton.type = "button";
        commentButton.setAttribute("aria-expanded", "false");
        commentButton.setAttribute("aria-controls", `comments-${post.id}`);
        const { panel, list } = makeCommentArea(post.id);
        let commentsLoaded = false;
        commentButton.addEventListener("click", async () => {
            const opening = !panel.classList.contains("is-open");
            panel.classList.toggle("is-open", opening);
            commentButton.setAttribute("aria-expanded", String(opening));
            commentButton.textContent = opening ? "댓글 접기" : "댓글 보기";
            if (opening && !commentsLoaded) {
                commentsLoaded = true;
                await loadComments(post.id, list, "첫 댓글을 남겨 대화를 시작해 보세요.");
            }
        });

        actions.append(like, commentButton);
        card.append(actions, panel);
        return card;
    }

    async function loadCommunityPosts() {
        if (!api?.isLoggedIn() || !postsRoot) return;
        try {
            const result = await api.request("/api/community/posts");
            postsRoot.replaceChildren(...result.items.map(makePostCard));
        } catch (error) {
            console.warn("게시글 조회 실패:", error.message);
        }
    }

    window.loadServerPosts = loadCommunityPosts;
    window.publishPost = async function () {
        const bodyInput = document.getElementById("postBody");
        const titleInput = document.getElementById("postTitle");
        const photoInput = document.getElementById("postPhoto");
        const submit = composer?.querySelector(".btn");
        const body = bodyInput?.value.trim() || "";
        const title = titleInput?.value.trim() || "";
        const photo = photoInput?.files?.[0];
        const locationName = locationInput?.value.trim() || "";
        const latitude = latitudeInput?.value ? Number(latitudeInput.value) : null;
        const longitude = longitudeInput?.value ? Number(longitudeInput.value) : null;

        if (!api?.isLoggedIn()) {
            window.location.href = "account.html";
            return;
        }
        if (!body) {
            showError("게시글 내용을 입력해 주세요 🐾");
            bodyInput?.focus();
            return;
        }
        if (locationName && (!latitudeInput?.value || !longitudeInput?.value)) {
            showError("장소 검색 결과를 선택해야 산책 지도에 공유할 수 있어요. 장소를 다시 검색해 선택해 주세요.");
            locationInput?.focus();
            return;
        }
        if (photo && photo.size > 12 * 1024 * 1024) {
            showError("사진은 12MB 이하로 선택해 주세요.");
            return;
        }

        if (submit) {
            submit.disabled = true;
            submit.textContent = "게시글을 올리는 중…";
        }
        try {
            let imageId = null;
            if (photo) {
                const form = new FormData();
                form.append("photo", photo, photo.name);
                const upload = await api.request("/api/uploads?purpose=community", { method: "POST", body: form });
                imageId = upload.image_id;
            }
            await api.request("/api/community/posts", {
                method: "POST",
                body: JSON.stringify({
                    category: locationName ? "walk" : "daily",
                    title,
                    body,
                    location_name: locationName,
                    latitude,
                    longitude,
                    image_id: imageId
                })
            });
            bodyInput.value = "";
            titleInput.value = "";
            if (photoInput) photoInput.value = "";
            if (locationInput) {
                locationInput.value = "";
                locationInput.dataset.placeSelected = "false";
            }
            if (latitudeInput) latitudeInput.value = "";
            if (longitudeInput) longitudeInput.value = "";
            if (locationHelp) locationHelp.textContent = "장소 검색 결과를 선택하면 지도 마커로 공유돼요.";
            if (locationPredictionList) {
                locationPredictionList.replaceChildren();
                locationPredictionList.hidden = true;
            }
            if (composer) composer.style.display = "none";
            if (writeButton) writeButton.setAttribute("aria-expanded", "false");
            await loadCommunityPosts();
            postsRoot?.scrollIntoView({ behavior: "smooth", block: "start" });
        } catch (error) {
            showError(error.message);
        } finally {
            if (submit) {
                submit.disabled = false;
                submit.textContent = "게시하기";
            }
        }
    };

    loadCommunityPosts();
})();
