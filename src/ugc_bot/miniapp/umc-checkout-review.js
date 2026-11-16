(() => {
  const telegram = window.Telegram?.WebApp;
  const launch = /^payreview_([a-f0-9]{8})([a-f0-9]{4})([a-f0-9]{4})([a-f0-9]{4})([a-f0-9]{12})$/
    .exec(telegram?.initDataUnsafe?.start_param ?? "");
  if (!launch) return;

  const orderId = launch.slice(1).join("-");
  const orderNumber = launch[1].toUpperCase();
  const initData = telegram.initData;
  const dialog = document.getElementById("checkout-review");
  const status = document.getElementById("checkout-review-status");
  const form = document.getElementById("checkout-review-form");
  const evidence = document.getElementById("checkout-review-evidence");
  const confirmed = document.getElementById("checkout-review-confirmed");
  const submit = form.querySelector("button[type=submit]");
  const currency = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB" });
  let reviewable;

  async function call(path, fields = {}) {
    if (!initData || telegram.initData !== initData) {
      throw new Error("Откройте сверку заново из Telegram под аккаунтом администратора.");
    }
    const response = await fetch(`/miniapp/api/financial/checkout/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      redirect: "error",
      body: JSON.stringify({ init_data: initData, platform: "telegram", ...fields }),
    });
    if ([401, 403].includes(response.status)) {
      throw new Error("Сверка доступна администратору с действующим входом в Telegram.");
    }
    if (!response.ok) {
      throw new Error("UMC не смог подтвердить состояние оплаты. Откройте сверку заново.");
    }
    return response.json();
  }

  async function refresh() {
    form.hidden = true;
    reviewable = null;
    const current = await call(`orders/${orderId}/review-context`);
    const unpaid = current.order_id === orderId && current.currency === "RUB" &&
      Number.isSafeInteger(current.amount_minor) && current.amount_minor > 0 &&
      current.order_open_for_payment === true && current.paid_receipt_count === 0 &&
      current.capture_state === "not_recorded";
    if (!unpaid) {
      status.textContent = `Заказ №${orderNumber}. Проверьте статус оплаты в админке.`;
      return;
    }
    if (current.authorization_id === null) {
      status.textContent = `Авторизация заказа №${orderNumber} закрыта. Проверьте ссылку на оплату в админке.`;
      return;
    }
    reviewable = current;
    status.textContent = `Заказ №${orderNumber} · ${currency.format(current.amount_minor / 100)}`;
    form.hidden = false;
  }

  document.getElementById("checkout-review-close").addEventListener("click", () => dialog.close());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!reviewable || !confirmed.checked || submit.disabled) return;
    const reference = evidence.value.trim();
    if (reference.length < 8) {
      status.textContent = "Укажите ID операции или обращения в ЮKassa (минимум 8 символов).";
      return;
    }
    const { authorization_id: id, version } = reviewable;
    submit.disabled = true;
    try {
      await call(`authorizations/${encodeURIComponent(id)}/review`, {
        operation_key: `telegram-checkout-review:${id}`,
        expected_version: version,
        decision: "confirmed_not_charged",
        reason: "Администратор сверил операцию в ЮKassa и подтвердил, что списания не было.",
        evidence_reference: reference,
      });
      await refresh();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });

  dialog.showModal();
  refresh().catch((error) => { status.textContent = error.message; });
})();
