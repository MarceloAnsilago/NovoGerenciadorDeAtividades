(() => {
  const root = document.getElementById("dashboard-root");
  if (!root) {
    return;
  }

  const endpoints = window.DashboardEndpoints || {};
  const charts = {};
  const startInput = document.getElementById("dashboardStartMonth");
  const endInput = document.getElementById("dashboardEndMonth");
  const currentMonthBtn = document.getElementById("dashboardCurrentMonthBtn");

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

    if (canvasId === "chartTopServidores") {
      try {
        const totalBars = (payload.labels && payload.labels.length) || 0;
        const targetHeight = Math.max(280, totalBars * 28);
        canvas.height = targetHeight;
        const container = canvas.parentElement;
        if (container) {
          const maxHeight = Math.max(320, Math.min(targetHeight, 560));
          container.style.maxHeight = `${maxHeight}px`;
          container.style.minHeight = "280px";
          container.style.overflowY = totalBars > 10 ? "auto" : "hidden";
          container.style.paddingRight = "8px";
        }
      } catch (e) {
        console.warn("Falha ao ajustar altura do grafico de servidores:", e);
      }
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
      try {
        charts[canvasId].resize();
      } catch (e) {
        /* ignore */
      }
      return;
    }

    charts[canvasId] = new Chart(canvas, config);
  }

  function getRangeValues() {
    const start = startInput && startInput.value ? startInput.value.trim() : "";
    const end = endInput && endInput.value ? endInput.value.trim() : "";
    return { start, end };
  }

  function buildEndpoint(url) {
    if (!url) {
      return url;
    }
    const { start, end } = getRangeValues();
    const endpoint = new URL(url, window.location.origin);
    if (start) {
      endpoint.searchParams.set("inicio", start);
    } else {
      endpoint.searchParams.delete("inicio");
    }
    if (end) {
      endpoint.searchParams.set("fim", end);
    } else {
      endpoint.searchParams.delete("fim");
    }
    return endpoint.toString();
  }

  function buildServidorDashboardUrl(servidorId) {
    if (!servidorId) {
      return "";
    }
    const template = endpoints.servidorDashboardTemplate || "";
    if (template.includes("/0/")) {
      return template.replace("/0/", `/${encodeURIComponent(String(servidorId))}/`);
    }
    return `/dashboard/servidor/${encodeURIComponent(String(servidorId))}/`;
  }

  function resolveTopServidorIndex(event, elements, chart) {
    if (elements && elements.length) {
      return elements[0].index;
    }
    const nativeEvent = event && event.native;
    if (!nativeEvent || !chart || !chart.scales || !chart.scales.y) {
      return -1;
    }
    const yScale = chart.scales.y;
    const labels = (chart.data && chart.data.labels) || [];
    if (!labels.length) {
      return -1;
    }
    const clickY = nativeEvent.offsetY;
    const step = labels.length > 1 ? Math.abs(yScale.getPixelForTick(1) - yScale.getPixelForTick(0)) : 24;
    const tolerance = Math.max(10, Math.floor(step / 2));
    for (let i = 0; i < labels.length; i += 1) {
      const tickY = yScale.getPixelForTick(i);
      if (Math.abs(clickY - tickY) <= tolerance) {
        return i;
      }
    }
    return -1;
  }

  function navigateToServidorDashboard(servidorId) {
    const targetUrl = buildServidorDashboardUrl(servidorId);
    if (!targetUrl) {
      return;
    }
    const { start, end } = getRangeValues();
    const target = new URL(targetUrl, window.location.origin);
    if (start) {
      target.searchParams.set("inicio", start);
    }
    if (end) {
      target.searchParams.set("fim", end);
    }
    window.location.href = target.toString();
  }

  function syncUrlParams() {
    const { start, end } = getRangeValues();
    const current = new URL(window.location.href);
    if (start) {
      current.searchParams.set("inicio", start);
    } else {
      current.searchParams.delete("inicio");
    }
    if (end) {
      current.searchParams.set("fim", end);
    } else {
      current.searchParams.delete("fim");
    }
    window.history.replaceState({}, "", current);
  }

  function normalizeRange() {
    if (!startInput || !endInput) {
      return;
    }
    const { start, end } = getRangeValues();
    if (!start || !end) {
      return;
    }
    if (start > end) {
      endInput.value = start;
    }
  }

  function clampMonthValue(value, input) {
    if (!value || !input) {
      return value;
    }
    const min = input.min ? input.min.trim() : "";
    const max = input.max ? input.max.trim() : "";
    let result = value;
    if (min && result < min) {
      result = min;
    }
    if (max && result > max) {
      result = max;
    }
    return result;
  }

  function getCurrentMonthValue() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    return `${year}-${month}`;
  }

  async function applyCurrentMonth() {
    if (!startInput || !endInput) {
      return;
    }
    const currentMonth = getCurrentMonthValue();
    startInput.value = clampMonthValue(currentMonth, startInput);
    endInput.value = clampMonthValue(currentMonth, endInput);
    normalizeRange();
    syncUrlParams();
    await refreshDashboard();
  }

  async function refreshDashboard() {
    updateKpis(await fetchJson(buildEndpoint(endpoints.kpis)));

    renderChart(
      "chartMetasUnidade",
      await fetchJson(buildEndpoint(endpoints.metasPorUnidade)),
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

    const atividadesAreaPayload = await fetchJson(buildEndpoint(endpoints.atividadesPorArea));
    renderChart(
      "chartAtividadesArea",
      atividadesAreaPayload,
      {
        type: "doughnut",
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: "bottom" },
          },
          onClick: (evt, elements) => {
            if (!elements || !elements.length) return;
            const idx = elements[0].index;
            const codes = (atividadesAreaPayload && atividadesAreaPayload.codes) || [];
            const code = codes[idx];
            const base = "/metas/";
            const url = code ? `${base}?area=${encodeURIComponent(code)}&status=ativas` : `${base}?status=ativas`;
            window.location.href = url;
          },
        },
      }
    );

    renderChart(
      "chartProgressoMensal",
      await fetchJson(buildEndpoint(endpoints.progressoMensal)),
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

    const progStatusPayload = await fetchJson(buildEndpoint(endpoints.programacoesStatus));
    renderChart(
      "chartProgramacoesStatus",
      progStatusPayload,
      {
        type: "bar",
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: "bottom" },
            tooltip: {
              callbacks: {
                label(context) {
                  const dsLabel = context.dataset?.label || "";
                  const value = context.parsed?.y ?? context.parsed ?? 0;
                  return `${dsLabel}: ${value}`;
                },
                footer(items) {
                  if (!items || !items.length) return "";
                  const idx = items[0].dataIndex;
                  const dsLabel = items[0].dataset?.label || "";
                  const hints = (progStatusPayload && progStatusPayload.hints) || {};
                  let hint = "";
                  if ((dsLabel || "").toLowerCase().includes("conclu")) {
                    hint = (hints.concluidas && hints.concluidas[idx]) || "";
                  } else if ((dsLabel || "").toLowerCase().includes("penden")) {
                    hint = (hints.pendentes && hints.pendentes[idx]) || "";
                  }
                  return hint ? `Atividade: ${hint}` : "";
                },
              },
            },
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
      await fetchJson(buildEndpoint(endpoints.usoVeiculos)),
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

    const topServPayload = await fetchJson(buildEndpoint(endpoints.topServidores));
    const hasStack = (topServPayload?.datasets || []).length > 1;
    const topHints = topServPayload?.hints || [];
    const topServidorIds = topServPayload?.servidor_ids || [];
    renderChart(
      "chartTopServidores",
      topServPayload,
      {
        type: "bar",
        options: {
          indexAxis: "y",
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: hasStack },
            tooltip: {
              callbacks: {
                label(context) {
                  const dsLabel = context.dataset?.label || "";
                  const value = context.parsed?.x ?? context.parsed ?? 0;
                  return `${dsLabel}: ${value}`;
                },
                footer(items) {
                  if (!items || !items.length) return "";
                  const idx = items[0].dataIndex;
                  const hint = topHints[idx];
                  return hint ? hint : "";
                },
              },
            },
          },
          onClick: (event, elements, chart) => {
            const idx = resolveTopServidorIndex(event, elements, chart);
            if (idx < 0) {
              return;
            }
            const servidorId = topServidorIds[idx];
            if (!servidorId) {
              return;
            }
            navigateToServidorDashboard(servidorId);
          },
          scales: {
            x: {
              beginAtZero: true,
              ticks: { precision: 0 },
              stacked: hasStack,
            },
            y: {
              stacked: hasStack,
            },
          },
        },
      }
    );

    renderChart(
      "chartPlantaoSemanal",
      await fetchJson(buildEndpoint(endpoints.plantaoHeatmap)),
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

  async function init() {
    if (typeof Chart === "undefined") {
      console.warn("Chart.js nao encontrado.");
      return;
    }

    if (startInput && root.dataset.start) {
      startInput.value = root.dataset.start;
    }
    if (endInput && root.dataset.end) {
      endInput.value = root.dataset.end;
    }

    if (startInput) {
      startInput.addEventListener("change", () => {
        normalizeRange();
        syncUrlParams();
        refreshDashboard();
      });
    }

    if (endInput) {
      endInput.addEventListener("change", () => {
        normalizeRange();
        syncUrlParams();
        refreshDashboard();
      });
    }

    if (currentMonthBtn) {
      currentMonthBtn.addEventListener("click", () => {
        applyCurrentMonth();
      });
    }

    normalizeRange();
    syncUrlParams();
    await refreshDashboard();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
