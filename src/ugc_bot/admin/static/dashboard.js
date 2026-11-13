const dashboard = document.querySelector("#dashboard-charts");

function renderDashboardChart(key, type, series) {
  const card = dashboard.querySelector(`[data-chart="${key}"]`);
  const status = card.querySelector(".chart-state");
  const labels = [...new Set(series.flatMap(({ points }) => points.map(({ date }) => date)))].sort();
  if (!labels.length) {
    status.textContent = "За этот период данных нет.";
    return;
  }
  const plot = card.querySelector(".chart-plot");
  plot.hidden = false;
  new window.Chart(plot.querySelector("canvas"), {
    type,
    data: {
      labels,
      datasets: series.map(({ label, points, color, field }) => {
        const byDate = new Map(points.map((row) => [row.date, row[field]]));
        return {
          label,
          data: labels.map((date) => byDate.get(date) ?? 0),
          backgroundColor: color,
          borderColor: color,
        };
      }),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { beginAtZero: true }, x: { ticks: { maxTicksLimit: 7 } } },
    },
  });
  status.hidden = true;
}

async function loadDashboardCharts() {
  const response = await fetch(`/admin/api/dashboard/charts?period=${encodeURIComponent(dashboard.dataset.period)}`);
  if (!response.ok || !window.Chart) throw new Error("Charts unavailable");
  const data = await response.json();
  const colors = ["#285ed5", "#177864", "#9c5b0b", "#7d48a4"];
  renderDashboardChart("registrations", "line", [
    { label: "Креаторы", points: data.registrations_creators, color: colors[0], field: "count" },
    { label: "Заказчики", points: data.registrations_advertisers, color: colors[1], field: "count" },
  ]);
  renderDashboardChart("orders", "bar", [
    { label: "Новые заявки", points: data.orders, color: colors[0], field: "count" },
  ]);
  const currencies = [...new Set(data.turnover.map(({ currency }) => currency))];
  renderDashboardChart("turnover", "bar", currencies.map((currency, index) => ({
    label: currency,
    points: data.turnover.filter((row) => row.currency === currency),
    color: colors[index % colors.length],
    field: "amount",
  })));
}

loadDashboardCharts().catch(() => {
  dashboard.querySelectorAll(".chart-state:not([hidden])").forEach((status) => {
    status.textContent = "График недоступен. Обновите страницу.";
  });
});
