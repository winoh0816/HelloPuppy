(function () {
    "use strict";

    const api = window.HelloPuppyAPI;
    const status = document.getElementById("accountSettingsStatus");
    const tabs = [
        { button: document.getElementById("profileTab"), panel: document.getElementById("profilePanel") },
        { button: document.getElementById("emailTab"), panel: document.getElementById("emailPanel") },
        { button: document.getElementById("passwordTab"), panel: document.getElementById("passwordPanel") },
    ];

    if (!api?.isLoggedIn()) {
        window.location.replace("account.html");
        return;
    }

    tabs.forEach(({ button, panel }) => {
        button.addEventListener("click", () => {
            tabs.forEach((tab) => {
                const selected = tab.button === button;
                tab.button.classList.toggle("active", selected);
                tab.button.setAttribute("aria-selected", String(selected));
                tab.panel.hidden = !selected;
            });
            status.textContent = "";
        });
    });

    const displayNameForm = document.getElementById("displayNameForm");
    api.me().then(({ user }) => {
        displayNameForm.elements.display_name.value = user.display_name;
        document.getElementById("emailForm").elements.email.value = user.email;
    }).catch((error) => {
        status.textContent = error.message;
        if (!api.isLoggedIn()) window.location.replace("account.html");
    });

    displayNameForm.addEventListener("submit", (event) => submitSettings(event, async (form) => {
        const result = await api.request("/api/auth/display-name", {
            method: "PUT",
            body: JSON.stringify({ display_name: form.display_name.value }),
        });
        displayNameForm.elements.display_name.value = result.user.display_name;
        return "닉네임이 변경되었습니다.";
    }));

    document.getElementById("emailForm").addEventListener("submit", (event) => submitSettings(event, async (form) => {
        const result = await api.request("/api/auth/email", {
            method: "PUT",
            body: JSON.stringify({ email: form.email.value, current_password: form.current_password.value }),
        });
        form.email.value = result.user.email;
        form.current_password.value = "";
        return "이메일 주소가 변경되었습니다.";
    }));

    document.getElementById("passwordForm").addEventListener("submit", (event) => submitSettings(event, async (form) => {
        if (form.new_password.value !== form.confirm_password.value) {
            throw new Error("새 비밀번호가 서로 일치하지 않습니다.");
        }
        await api.request("/api/auth/password", {
            method: "PUT",
            body: JSON.stringify({ current_password: form.current_password.value, new_password: form.new_password.value }),
        });
        form.reset();
        return "비밀번호가 변경되었습니다.";
    }));

    async function submitSettings(event, save) {
        event.preventDefault();
        const form = event.currentTarget.elements;
        const submitButton = event.currentTarget.querySelector('button[type="submit"]');
        submitButton.disabled = true;
        status.textContent = "저장하고 있습니다…";
        try {
            status.textContent = await save(form);
        } catch (error) {
            status.textContent = error.message;
        } finally {
            submitButton.disabled = false;
        }
    }
})();
