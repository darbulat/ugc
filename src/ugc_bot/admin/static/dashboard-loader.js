const panel = document.querySelector("#dashboard-panel");
const status = document.querySelector("#dashboard-loading-status");
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

async function loadDashboard() {
  retry.hidden = true;
  retry.disabled = true;
  panel.setAttribute("aria-busy", "true");
  status.textContent = "Загружаем показатели…";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  const cancel = () => controller.abort();
  window.addEventListener("pagehide", cancel, {once: true});
  try {
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
    startCharts();
  } catch {
    status.textContent = "Не удалось загрузить показатели. Попробуйте ещё раз.";
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

if (panel.querySelector("[data-dashboard-content]")) {
  startCharts();
} else {
  retry.addEventListener("click", loadDashboard);
  loadDashboard();
}
