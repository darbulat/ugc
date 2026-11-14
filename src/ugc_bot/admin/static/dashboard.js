const dashboard = document.querySelector("#dashboard-charts");
const detail = document.querySelector("#chart-detail");
const controls = detail.querySelector(".chart-controls");
const from = controls.elements.namedItem("from");
const to = controls.elements.namedItem("to");
const values = detail.querySelector(".chart-values");
const integers = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const amounts = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const colors = ["#285ed5", "#177864", "#9c5b0b", "#7d48a4"];

let selected;
let expandedChart;
let calendar;
let visibleDates;

function shortDate(date) {
  const [, month, day] = date.split("-");
  return day + "." + month;
}

function longDate(date) {
  return shortDate(date) + "." + date.slice(0, 4);
}

function series(label, rows, color, field = "count") {
  return { label, color, byDate: new Map(rows.map((row) => [row.date, row[field]])) };
}

function chartData(data) {
  const paid = new Map();
  for (const row of data.turnover) {
    paid.set(row.date, (paid.get(row.date) ?? 0) + row.orders_paid);
  }
  const currencies = [...new Set(data.turnover.map((row) => row.currency))].sort();
  return {
    registrations: {
      type: "line",
      note: "Регистрации за каждый день выбранного периода.",
      series: [
        series("Креаторы", data.registrations_creators, colors[0]),
        series("Заказчики", data.registrations_advertisers, colors[1]),
      ],
    },
    orders: {
      type: "bar",
      note: "Создано — видимые заявки, кроме помеченных тестовых. Оплачено — по дате платежа, включая ранее созданные заказы.",
      series: [
        series("Создано", data.orders, colors[0]),
        { label: "Оплачено", color: colors[1], byDate: paid },
      ],
    },
    turnover: {
      type: "bar",
      note: "Суммы по дате оплаты. У каждой валюты своя шкала.",
      money: true,
      series: currencies.map((currency, index) =>
        series(currency, data.turnover.filter((row) => row.currency === currency), colors[index % colors.length], "amount")
      ),
    },
  };
}

const dayValueLabels = {
  id: "dayValueLabels",
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    ctx.save();
    ctx.font = "600 14px Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    chart.data.datasets.forEach((dataset, index) => {
      if (!chart.isDatasetVisible(index)) return;
      const bar = chart.getDatasetMeta(index).data[0];
      ctx.fillStyle = dataset.backgroundColor;
      ctx.fillText(dataset.dayLabel, bar.x, bar.y - 5);
    });
    ctx.restore();
  },
};

function renderChart(canvas, config, dates, large = false) {
  if (!window.Chart) return undefined;
  const singleDay = dates.length === 1;
  const type = singleDay ? "bar" : config.type;
  const multipleCurrencies = config.money && config.series.length > 1;
  const format = config.money ? amounts : integers;
  const scales = {
    x: {
      ticks: {
        callback(index) {
          const date = this.getLabelForValue(index);
          return dates.length > 366 ? date.slice(0, 7) : shortDate(date);
        },
        maxRotation: 0,
        maxTicksLimit: large ? 12 : 6,
      },
      grid: { display: false },
      offset: singleDay || type === "bar",
    },
  };
  config.series.forEach(({ label }, index) => {
    if (!multipleCurrencies && index > 0) return;
    scales[multipleCurrencies ? `y${index}` : "y"] = {
      type: "linear",
      beginAtZero: true,
      grace: singleDay ? "15%" : 0,
      title: { display: multipleCurrencies, text: label },
      position: index % 2 ? "right" : "left",
      grid: { drawOnChartArea: !multipleCurrencies || index === 0 },
      ticks: { ...(config.money ? {} : { precision: 0 }), maxTicksLimit: 6 },
    };
  });
  return new window.Chart(canvas, {
    type,
    plugins: singleDay ? [dayValueLabels] : [],
    data: {
      labels: dates,
      datasets: config.series.map(({ label, byDate, color }, index) => ({
        label,
        data: dates.map((date) => byDate.get(date) ?? 0),
        backgroundColor: color,
        borderColor: color,
        borderWidth: type === "line" ? 2 : 0,
        dayLabel: singleDay ? format.format(byDate.get(dates[0]) ?? 0) : undefined,
        pointRadius: dates.length <= 31 ? 2 : 0,
        maxBarThickness: singleDay ? 60 : 34,
        yAxisID: multipleCurrencies ? `y${index}` : "y",
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      layout: { padding: { top: singleDay ? 14 : 0 } },
      interaction: { mode: "index", intersect: false },
      scales,
      plugins: {
        legend: { labels: { usePointStyle: true, boxWidth: 9 } },
        tooltip: {
          callbacks: {
            title(items) { return longDate(items[0].label); },
            label(item) { return item.dataset.label + " · " + format.format(item.parsed.y); },
          },
        },
      },
    },
  });
}

function renderValues(dates) {
  const format = selected.money ? amounts : integers;
  const head = values.querySelector("thead");
  const body = values.querySelector("tbody");
  head.replaceChildren();
  body.replaceChildren();
  const header = head.insertRow();
  for (const label of ["Дата", ...selected.series.map((item) => item.label)]) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    header.append(cell);
  }
  const rows = document.createDocumentFragment();
  for (const date of dates) {
    const row = document.createElement("tr");
    row.insertCell().textContent = longDate(date);
    for (const { byDate } of selected.series) {
      row.insertCell().textContent = format.format(byDate.get(date) ?? 0);
    }
    rows.append(row);
  }
  body.append(rows);
}

function updateDetail() {
  const dates = calendar.filter((date) => date >= from.value && date <= to.value);
  if (!dates.length) {
    to.setCustomValidity("Дата окончания должна быть не раньше начала.");
    to.reportValidity();
    return;
  }
  visibleDates = dates;
  detail.querySelector(".chart-range").textContent = dates.length === 1
    ? longDate(dates[0])
    : longDate(dates[0]) + " — " + longDate(dates.at(-1));
  expandedChart?.destroy();
  expandedChart = renderChart(detail.querySelector("canvas"), selected, dates, true);
  if (values.open) renderValues(dates);
}

function openDetail(title, config) {
  selected = config;
  detail.querySelector("#chart-detail-title").textContent = title;
  detail.querySelector(".chart-detail-note").textContent = config.note;
  for (const input of [from, to]) {
    input.min = calendar[0];
    input.max = calendar.at(-1);
  }
  from.value = from.min;
  to.value = to.max;
  to.setCustomValidity("");
  values.open = !window.Chart;
  detail.querySelector(".chart-plot").hidden = !window.Chart;
  detail.showModal();
  updateDetail();
}

function renderPeaks(charts) {
  const observations = document.querySelector(".chart-observations");
  const list = observations.querySelector("ul");
  for (const config of Object.values(charts)) {
    for (const { label, byDate } of config.series) {
      let peak = 0;
      let dates = [];
      for (const date of calendar) {
        const count = byDate.get(date) ?? 0;
        if (count > peak) {
          peak = count;
          dates = [date];
        } else if (count > 0 && count === peak) {
          dates.push(date);
        }
      }
      if (!peak) continue;
      const item = document.createElement("li");
      const format = config.money ? amounts : integers;
      const shown = dates.slice(0, 3).map(longDate).join(", ");
      const remaining = dates.length > 3 ? " и ещё " + (dates.length - 3) : "";
      item.textContent = label + " · " + format.format(peak) + " · " + shown + remaining;
      list.append(item);
    }
  }
  observations.hidden = !list.childElementCount;
}

async function loadDashboardCharts() {
  const response = await fetch(`/admin/api/dashboard/charts?period=${encodeURIComponent(dashboard.dataset.period)}`);
  if (!response.ok) throw new Error("Charts unavailable");
  const data = await response.json();
  calendar = data.dates;
  const charts = chartData(data);
  for (const [key, config] of Object.entries(charts)) {
    const card = dashboard.querySelector(`[data-chart="${key}"]`);
    const status = card.querySelector(".chart-state");
    if (!calendar.length || !config.series.length) {
      status.textContent = "За этот период данных нет.";
      continue;
    }
    const button = card.querySelector(".chart-expand");
    button.disabled = false;
    button.addEventListener("click", () => openDetail(card.querySelector("h3").textContent, config));
    if (window.Chart) {
      const plot = card.querySelector(".chart-plot");
      plot.hidden = false;
      renderChart(plot.querySelector("canvas"), config, calendar);
      status.hidden = true;
    } else {
      status.textContent = "Значения доступны в таблице.";
      button.textContent = "Открыть таблицу";
    }
  }
  if (calendar.length > 1) renderPeaks(charts);
}

controls.addEventListener("submit", (event) => {
  event.preventDefault();
  updateDetail();
});
controls.addEventListener("input", () => to.setCustomValidity(""));
controls.querySelectorAll("[data-days]").forEach((button) => {
  button.addEventListener("click", () => {
    const days = Number(button.dataset.days);
    from.value = days ? calendar.at(-Math.min(days, calendar.length)) : calendar[0];
    to.value = calendar.at(-1);
    to.setCustomValidity("");
    updateDetail();
  });
});
values.addEventListener("toggle", () => {
  if (values.open && detail.open) renderValues(visibleDates);
});
detail.addEventListener("close", () => {
  expandedChart?.destroy();
  expandedChart = undefined;
  values.open = false;
  values.querySelector("tbody").replaceChildren();
});

document.querySelector(".payout-jump").addEventListener("click", () => {
  document.querySelector("#payout-requests details").open = true;
});

loadDashboardCharts().catch(() => {
  dashboard.querySelectorAll(".chart-state:not([hidden])").forEach((status) => {
    status.textContent = "Данные графика недоступны. Обновите страницу.";
  });
});
