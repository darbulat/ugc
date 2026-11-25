(() => {
  const consultation = new URLSearchParams(location.search).get("service") === "consultation";
  const token = location.hash.slice(1);
  const form = document.getElementById("payment-form");
  const email = document.getElementById("email");
  const button = form.querySelector("button");
  const payment = document.getElementById("payment-link");
  const status = document.getElementById("status");
  const error = document.getElementById("error");
  let poll;
  if (consultation) document.querySelector("h1").textContent = "Консультация по запуску UGC · 5 000 ₽";

  const text = {
    available: "",
    creating: "Подготавливаем счёт…",
    pending: "Счёт готов. Завершите оплату в ЮKassa.",
    review: "Проверяем результат оплаты. Обновим статус после сверки.",
    paid: consultation ? "Консультация оплачена." : "Заказ уже оплачен.",
    canceled: "Предыдущий счёт закрыт. Можно начать оплату заново.",
    failed: "Счёт пока недоступен. Попробуйте ещё раз.",
    telegram_pending: "Проверяем предыдущую попытку оплаты. Пожалуйста, подождите.",
    unavailable: "Ссылка недоступна. Свяжитесь с тем, кто её отправил.",
  };

  function render(data) {
    status.textContent = data.state === "pending" && !data.url
      ? "Проверяем статус счёта в ЮKassa."
      : (text[data.state] ?? text.unavailable);
    status.hidden = !status.textContent;
    form.hidden = !["available", "failed", "canceled"].includes(data.state);
    payment.hidden = !data.url;
    if (data.url) payment.href = data.url;
    if (["creating", "pending", "review", "telegram_pending"].includes(data.state)) {
      poll = setTimeout(() => load("status"), 5000);
    }
  }

  async function load(action, details = {}) {
    clearTimeout(poll);
    button.disabled = true;
    error.hidden = true;
    try {
      const response = await fetch("./api/browser-payment/" + action, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, ...(consultation ? {service: "consultation"} : {}), ...details }),
        cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Не удалось проверить оплату. Попробуйте ещё раз.");
      if (action === "start" && data.url) {
        location.assign(data.url);
        return;
      }
      render(data);
    } catch (err) {
      error.textContent = err instanceof Error && action === "start"
        ? err.message : "Не удалось проверить заказ. Обновите страницу.";
      error.hidden = false;
    } finally {
      button.disabled = false;
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!button.disabled) load("start", { email: email.value });
  });
  if (/^[a-f0-9-]{36}$/i.test(token)) load("status");
  else render({ state: "unavailable" });
})();
