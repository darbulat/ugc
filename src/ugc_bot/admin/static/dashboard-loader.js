const panel = document.querySelector("#dashboard-panel");
const status = document.querySelector("#dashboard-loading-status");
const dates = new Intl.DateTimeFormat("ru-RU", {
  timeZone: panel.dataset.timezone || "Europe/Moscow",
  day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
});
const retry = document.querySelector("#dashboard-retry");

function loadScript(url, timeout = 10000) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    const timer = setTimeout(() => reject(new Error("Script timeout")), timeout);
    script.src = url;
    script.onload = () => { clearTimeout(timer); resolve(); };
    script.onerror = () => { clearTimeout(timer); reject(new Error("Script unavailable")); };
    document.head.append(script);
  });
}

async function loadCharts() {
  if (!panel.querySelector("#dashboard-charts")) return;
  // The chart library must never hold up the metrics or navigation.
  await loadScript("https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js", 3000).catch(() => {});
  await loadScript(panel.dataset.chartsScript);
}

async function loadGoals() {
  const response = await fetch(window.location.href, {
    headers: {"X-Dashboard-Content": "goals"},
    cache: "no-store",
    signal: AbortSignal.timeout(3500),
  });
  if (!response.ok || response.redirected) return;
  const template = document.createElement("template");
  template.innerHTML = await response.text();
  const goals = template.content.firstElementChild;
  if (goals?.matches("#dashboard-goals")) panel.replaceChildren(goals);
}

async function loadDashboard() {
  retry.hidden = true;
  retry.disabled = true;
  panel.setAttribute("aria-busy", "true");
  const previous = panel.querySelector("[data-dashboard-content]");
  status.textContent = previous?.dataset.calculatedAt
    ? `Срез рассчитан ${dates.format(new Date(previous.dataset.calculatedAt))} · Проверяем обновления…`
    : "Загружаем показатели…";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  const cancel = () => controller.abort();
  window.addEventListener("pagehide", cancel, {once: true});
  try {
    if (!previous && !panel.querySelector("#dashboard-goals")) {
      await loadGoals().catch(() => {});
    }
    const response = await fetch(window.location.href, {
      headers: {"X-Dashboard-Content": "1"},
      cache: "no-store",
      signal: controller.signal,
    });
    if (response.redirected) {
      window.location.assign(response.url);
      return;
    }
    if (!response.ok) throw new Error("Dashboard unavailable");
    const template = document.createElement("template");
    template.innerHTML = await response.text();
    if (!template.content.querySelector("[data-dashboard-content]")) {
      throw new Error("Unexpected dashboard response");
    }
    panel.replaceChildren(template.content);
    const current = panel.querySelector("[data-dashboard-content]");
    status.textContent = current.dataset.calculatedAt
      ? `Срез рассчитан ${dates.format(new Date(current.dataset.calculatedAt))} · Счётчики проверены ${dates.format(new Date(current.dataset.countsAt))}`
      : "Показатели обновлены";
    startCharts();
  } catch {
    status.textContent = previous?.dataset.calculatedAt
      ? `Срез рассчитан ${dates.format(new Date(previous.dataset.calculatedAt))} · Не удалось обновить. Попробуйте ещё раз.`
      : "Не удалось загрузить показатели. Попробуйте ещё раз.";
    retry.hidden = false;
    retry.disabled = false;
  } finally {
    clearTimeout(timer);
    window.removeEventListener("pagehide", cancel);
    panel.setAttribute("aria-busy", "false");
  }
}

function startCharts() {
  loadCharts().catch(() => {
    panel.querySelectorAll(".chart-state").forEach((item) => {
      item.textContent = "Данные графика недоступны. Обновите страницу.";
    });
  });
}

retry.addEventListener("click", loadDashboard);
loadDashboard();
