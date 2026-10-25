(function () {
    "use strict";

    const container = document.getElementById("homeLatestCommunity");
    const api = window.HelloPuppyAPI;
    if (!container || !api) return;

    function addText(parent, tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        element.textContent = text;
        parent.append(element);
        return element;
    }

    function showMessage(message, linkText, href) {
        container.replaceChildren();
        addText(container, "p", "muted", message);
        if (linkText && href) {
            const link = document.createElement("a");
            link.className = "muted";
            link.href = href;
            link.textContent = linkText;
            container.append(link);
        }
        container.setAttribute("aria-busy", "false");
    }

    function renderPost(post) {
        container.replaceChildren();

        const meta = document.createElement("div");
        meta.className = "post-meta";
        const avatar = document.createElement("div");
        avatar.className = "avatar";
        const avatarImage = document.createElement("img");
        avatarImage.src = "assets/images/brand/emoji-hello.png";
        avatarImage.alt = "";
        avatar.append(avatarImage);
        const author = document.createElement("div");
        addText(author, "b", "", post.display_name || "안녕멍뭉 가족");
        addText(author, "div", "muted", new Date(post.created_at).toLocaleString("ko-KR"));
        meta.append(avatar, author);
        container.append(meta);

        if (post.title) addText(container, "h3", "community-post-title", post.title);
        addText(container, "p", "post-copy", post.body || "");

        if (post.image_id) {
            const image = document.createElement("img");
            image.className = "community-post-photo";
            image.alt = "커뮤니티 첨부 사진";
            container.append(image);
            api.imageUrl(post.image_id)
                .then((url) => { image.src = url; })
                .catch(() => image.remove());
        }

        const footer = document.createElement("div");
        footer.className = "post-actions";
        const likes = document.createElement("span");
        likes.textContent = `♥ ${Number(post.like_count) || 0} 좋아요`;
        const link = document.createElement("a");
        link.href = "feed.html";
        link.textContent = "커뮤니티에서 보기 ›";
        footer.append(likes, link);
        container.append(footer);
        container.setAttribute("aria-busy", "false");
    }

    async function loadLatestPost() {
        if (!api.isLoggedIn()) {
            showMessage("로그인하면 최신 커뮤니티 소식을 확인할 수 있어요.", "로그인하기 ›", "account.html");
            return;
        }

        try {
            const result = await api.request("/api/community/posts?limit=1");
            const latestPost = result.items?.[0];
            if (!latestPost) {
                showMessage("아직 커뮤니티 게시글이 없어요.", "첫 글 보러 가기 ›", "feed.html");
                return;
            }
            renderPost(latestPost);
        } catch (error) {
            console.warn("최신 커뮤니티 소식 조회 실패:", error.message);
            showMessage("최신 소식을 불러오지 못했어요.", "커뮤니티로 이동 ›", "feed.html");
        }
    }

    loadLatestPost();
})();
