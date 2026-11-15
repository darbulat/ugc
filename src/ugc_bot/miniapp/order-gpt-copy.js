"use strict";

const telegram = window.Telegram?.WebApp;
const orderId = new URLSearchParams(window.location.search).get("order");
const promptText = document.getElementById("prompt");
const copy = document.getElementById("copy");
const status = document.getElementById("status");

async function loadPrompt() {
    telegram?.ready();
    if (!telegram?.initData || !orderId) {
        status.textContent = "Откройте эту страницу кнопкой в карточке бота.";
        return;
    }

    try {
        const response = await fetch("api/orders/gpt-copy", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({init_data: telegram.initData, order_id: orderId}),
            cache: "no-store",
        });
        if (!response.ok) {
            status.textContent = [401, 403].includes(response.status)
                ? "Доступ недоступен. Откройте карточку в личном чате с ботом."
                : "Не удалось загрузить заявку. Откройте карточку снова.";
            return;
        }
        const result = await response.json();
        if (typeof result.prompt !== "string" || !result.prompt) {
            throw new Error("invalid prompt");
        }
        promptText.value = result.prompt;
        promptText.hidden = false;
        copy.disabled = false;
        status.textContent = "";
    } catch {
        status.textContent = "Не удалось загрузить заявку. Откройте карточку снова.";
    }
}

function selectPrompt() {
    promptText.focus();
    promptText.select();
    promptText.setSelectionRange(0, promptText.value.length);
}

copy.addEventListener("click", async () => {
    try {
        await navigator.clipboard.writeText(promptText.value);
        status.textContent = "Скопировано. Вставьте текст в GPT.";
        return;
    } catch {
        selectPrompt();
    }

    try {
        if (document.execCommand("copy")) {
            status.textContent = "Скопировано. Вставьте текст в GPT.";
            return;
        }
    } catch {
        // The selection stays available through the operating system menu.
    }
    status.textContent = "Текст выделен. Нажмите «Скопировать» в меню устройства.";
});

void loadPrompt();
