(() => {
  const root = document.getElementById("dashboard-servidor-root");
  if (!root) {
    return;
  }

  function readJsonScript(id, fallback) {
    const el = document.getElementById(id);
    if (!el) {
      return fallback;
    }
    try {
      return JSON.parse(el.textContent);
    } catch (error) {
      console.error(`Falha ao parsear ${id}`, error);
      return fallback;
    }
  }

  function parseNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : 0;
  }

  function normalizeRows(rows) {
    if (!Array.isArray(rows)) {
      return [];
    }
    return rows.filter((row) => row && typeof row === "object");
  }

  function takeTop(rows, limit = 10) {
    return normalizeRows(rows).slice(0, limit);
  }

  function truncateLabel(value, max = 38) {
    const text = String(value || "").trim();
    if (!text) {
      return "-";
    }
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
  }

  function withFallback(labels, data, fallbackLabel = "Sem dados no periodo") {
    if (labels.length && data.length) {
      return { labels, data };
    }
    return { labels: [fallbackLabel], data: [0], isEmpty: true };
  }

  function createOrUpdateChart(canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) {
      return;
    }
    if (!window.__dashboardServidorCharts) {
      window.__dashboardServidorCharts = {};
    }
    const charts = window.__dashboardServidorCharts;
    if (charts[canvasId]) {
      charts[canvasId].destroy();
    }
    charts[canvasId] = new Chart(canvas, config);
  }

  function renderStatusChart() {
    const concluidas = parseNumber(root.dataset.concluidas);
    const pendentes = parseNumber(root.dataset.pendentes);
    createOrUpdateChart("chartServidorStatus", {
      type: "doughnut",
      data: {
        labels: ["Concluidas", "Pendentes"],
        datasets: [
          {
            data: [concluidas, pendentes],
            backgroundColor: ["#198754", "#dc3545"],
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" },
        },
      },
    });
  }

  function renderExpCampoChart() {
    const rawExpediente = (root.dataset.expedienteTotal || "").trim();
    const rawCampo = (root.dataset.campoTotal || "").trim();
    const hasNatureza = rawExpediente !== "" && rawCampo !== "";

    if (!hasNatureza) {
      createOrUpdateChart("chartServidorExpCampo", {
        type: "doughnut",
        data: {
          labels: ["Sem classificacao configurada"],
          datasets: [
            {
              data: [1],
              backgroundColor: ["#adb5bd"],
              borderWidth: 0,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: "bottom" },
            tooltip: { enabled: false },
          },
        },
      });
      return;
    }

    createOrUpdateChart("chartServidorExpCampo", {
      type: "doughnut",
      data: {
        labels: ["Expediente administrativo", "Atividades de campo"],
        datasets: [
          {
            data: [parseNumber(rawExpediente), parseNumber(rawCampo)],
            backgroundColor: ["#6c757d", "#0d6efd"],
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" },
        },
      },
    });
  }

  function renderMensalChart() {
    const rows = normalizeRows(readJsonScript("dashboard-servidor-mensal-rows", []));
    const labels = rows.map((row) => String(row.mes || "-"));
    const concluidas = rows.map((row) => parseNumber(row.concluidas));
    const pendentes = rows.map((row) => parseNumber(row.pendentes));
    const totais = rows.map((row) => parseNumber(row.total));

    const fallback = withFallback(labels, totais, "Sem serie mensal");
    const isEmpty = Boolean(fallback.isEmpty);

    createOrUpdateChart("chartServidorMensal", {
      data: {
        labels: fallback.labels,
        datasets: [
          {
            type: "bar",
            label: "Concluidas",
            data: isEmpty ? [0] : concluidas,
            backgroundColor: "#198754",
            stack: "status",
          },
          {
            type: "bar",
            label: "Pendentes",
            data: isEmpty ? [0] : pendentes,
            backgroundColor: "#dc3545",
            stack: "status",
          },
          {
            type: "line",
            label: "Total",
            data: fallback.data,
            borderColor: "#0d6efd",
            backgroundColor: "rgba(13,110,253,0.2)",
            pointRadius: 3,
            tension: 0.25,
            yAxisID: "y",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" },
        },
        scales: {
          x: { stacked: true },
          y: {
            stacked: true,
            beginAtZero: true,
            ticks: { precision: 0 },
          },
        },
      },
    });
  }

  function renderSimpleHorizontalBar(canvasId, rows, labelKey, valueKey, datasetLabel, color, fallbackLabel) {
    const topRows = takeTop(rows, 10);
    const labels = topRows.map((row) => truncateLabel(row[labelKey]));
    const values = topRows.map((row) => parseNumber(row[valueKey]));
    const fallback = withFallback(labels, values, fallbackLabel);

    createOrUpdateChart(canvasId, {
      type: "bar",
      data: {
        labels: fallback.labels,
        datasets: [
          {
            label: datasetLabel,
            data: fallback.data,
            backgroundColor: color,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
        },
        scales: {
          x: {
            beginAtZero: true,
            ticks: { precision: 0 },
          },
        },
      },
    });
  }

  function renderTopStacked(canvasId, rows, labelKey, fallbackLabel) {
    const topRows = takeTop(rows, 10);
    const labels = topRows.map((row) => truncateLabel(row[labelKey], 44));
    const concluidas = topRows.map((row) => parseNumber(row.concluidas));
    const pendentes = topRows.map((row) => parseNumber(row.pendentes));
    const fallback = withFallback(labels, topRows.map((row) => parseNumber(row.total)), fallbackLabel);
    const isEmpty = Boolean(fallback.isEmpty);

    createOrUpdateChart(canvasId, {
      type: "bar",
      data: {
        labels: fallback.labels,
        datasets: [
          {
            label: "Concluidas",
            data: isEmpty ? [0] : concluidas,
            backgroundColor: "#198754",
            stack: "status",
          },
          {
            label: "Pendentes",
            data: isEmpty ? [0] : pendentes,
            backgroundColor: "#ffc107",
            stack: "status",
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" },
        },
        scales: {
          x: {
            stacked: true,
            beginAtZero: true,
            ticks: { precision: 0 },
          },
          y: {
            stacked: true,
          },
        },
      },
    });
  }

  function init() {
    if (typeof Chart === "undefined") {
      console.warn("Chart.js nao encontrado.");
      return;
    }

    renderStatusChart();
    renderExpCampoChart();
    renderMensalChart();

    renderSimpleHorizontalBar(
      "chartServidorArea",
      readJsonScript("dashboard-servidor-area-rows", []),
      "nome",
      "total",
      "Atividades",
      "#0d6efd",
      "Sem areas no periodo",
    );
    renderSimpleHorizontalBar(
      "chartServidorUnidade",
      readJsonScript("dashboard-servidor-unidade-rows", []),
      "nome",
      "total",
      "Atividades",
      "#6610f2",
      "Sem unidades no periodo",
    );
    renderSimpleHorizontalBar(
      "chartServidorVeiculo",
      readJsonScript("dashboard-servidor-veiculo-rows", []),
      "placa",
      "total",
      "Uso de veiculos",
      "#0dcaf0",
      "Sem uso de veiculos",
    );

    renderTopStacked(
      "chartServidorAtividadesTop",
      readJsonScript("dashboard-servidor-atividade-rows", []),
      "atividade",
      "Sem atividades no periodo",
    );
    renderTopStacked(
      "chartServidorMetasTop",
      readJsonScript("dashboard-servidor-meta-rows", []),
      "titulo",
      "Sem metas no periodo",
    );
  }

  document.addEventListener("DOMContentLoaded", init);
})();
