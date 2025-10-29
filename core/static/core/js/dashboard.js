(() => {
  const root = document.getElementById("dashboard-root");
  if (!root) {
    return;
  }

  const endpoints = window.DashboardEndpoints || {};
  const charts = {};

  async function fetchJson(url) {
    if (!url) {
      return null;
    }
    try {
      const response = await fetch(url, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) {
        throw new Error(`Erro ao buscar ${url}: ${response.status}`);
      }
      return await response.json();
    } catch (error) {
      console.error(error);
      return null;
    }
  }

  function formatValue(key, value) {
    if (typeof value !== "number") {
      return value;
    }
    if (key === "percentual_metas_concluidas") {
      return `${value.toFixed(2)}%`;
    }
    return value.toLocaleString("pt-BR");
  }

  function updateKpis(data) {
    if (!data) {
      return;
    }
    Object.entries(data).forEach(([key, value]) => {
      const el = root.querySelector(`[data-kpi="${key}"]`);
      if (!el) {
        return;
      }
      el.textContent = formatValue(key, value ?? 0);
    });
  }

  function renderChart(canvasId, payload, baseConfig) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !payload) {
      return;
    }

    const config = {
      ...baseConfig,
      data: {
        labels: payload.labels || [],
        datasets: payload.datasets || [],
      },
    };

    if (charts[canvasId]) {
      charts[canvasId].data = config.data;
      charts[canvasId].options = config.options || {};
      charts[canvasId].update();
      return;
    }

    charts[canvasId] = new Chart(canvas, config);
  }

  async function init() {
    if (typeof Chart === "undefined") {
      console.warn("Chart.js não encontrado.");
      return;
    }

    updateKpis(await fetchJson(endpoints.kpis));

    renderChart(
      "chartMetasUnidade",
      await fetchJson(endpoints.metasPorUnidade),
      {
        type: "bar",
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
          },
          scales: {
            y: {
              beginAtZero: true,
              ticks: { precision: 0 },
            },
          },
        },
      }
    );

    renderChart(
      "chartAtividadesArea",
      await fetchJson(endpoints.atividadesPorArea),
      {
        type: "doughnut",
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: "bottom" },
          },
        },
      }
    );

    renderChart(
      "chartProgressoMensal",
      await fetchJson(endpoints.progressoMensal),
      {
        type: "line",
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: "bottom" },
          },
          scales: {
            y: {
              beginAtZero: true,
            },
          },
        },
      }
    );

    renderChart(
      "chartProgramacoesStatus",
      await fetchJson(endpoints.programacoesStatus),
      {
        type: "bar",
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
      }
    );

    renderChart(
      "chartUsoVeiculos",
      await fetchJson(endpoints.usoVeiculos),
      {
        type: "bar",
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
      }
    );

    renderChart(
      "chartTopServidores",
      await fetchJson(endpoints.topServidores),
      {
        type: "bar",
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
      }
    );

    renderChart(
      "chartPlantaoSemanal",
      await fetchJson(endpoints.plantaoHeatmap),
      {
        type: "bar",
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
          },
          scales: {
            y: {
              beginAtZero: true,
              ticks: { precision: 0 },
            },
          },
        },
      }
    );
  }

  document.addEventListener("DOMContentLoaded", init);
})();
