(function () {
  const NS = (window.PROGRAMAR = window.PROGRAMAR || {});
  if (NS._metasLogicLoaded) return;
  NS._metasLogicLoaded = true;

  function escapeSelector(value) {
    const raw = String(value ?? "");
    if (window.CSS && typeof window.CSS.escape === "function") {
      try { return window.CSS.escape(raw); } catch (_) { return raw; }
    }
    return raw.replace(/["\\]/g, "\\$&");
  }

  function highlightExistingCard(metaId) {
    const container = document.getElementById("metaCardsContainer");
    if (!container) return;
    const card = container.querySelector(`[data-meta-id="${escapeSelector(metaId)}"]`);
    if (!card) return;
    card.classList.add("border-warning");
    try {
      if (window.PROGRAMAR?.autoScrollModal) {
        card.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    } catch (_) {}
    setTimeout(() => card.classList.remove("border-warning"), 1500);
  }

  function confirmLimite(programadasAtual, alocado) {
    if (alocado <= 0 || programadasAtual < alocado) return true;
    return window.confirm(
      `Esta meta ja possui ${programadasAtual} atividade${programadasAtual === 1 ? "" : "s"} em programacao ` +
      `para a unidade, igual ou maior que o total alocado (${alocado}). Deseja programar mesmo assim?`
    );
  }

  function confirmDuplicado(existingCards) {
    if (existingCards <= 0) return true;
    const mensagem = existingCards === 1
      ? "Ja existe uma atividade desta meta programada para este dia. Deseja inserir outra?"
      : `Ja existem ${existingCards} atividades desta meta programadas para este dia. Deseja inserir mais uma?`;
    return window.confirm(mensagem);
  }

  function makeIcon(iconClass) {
    const span = document.createElement("span");
    span.className = "icon";
    const icon = document.createElement("i");
    icon.className = iconClass;
    span.appendChild(icon);
    return span;
  }

  function makeDateRow(label, value) {
    const row = document.createElement("div");
    row.className = "meta-date";

    const icon = document.createElement("i");
    icon.className = "bi bi-calendar-event";
    row.appendChild(icon);

    const span = document.createElement("span");
    span.textContent = label;
    row.appendChild(span);

    const strong = document.createElement("strong");
    strong.textContent = value;
    row.appendChild(strong);

    return row;
  }

  function makeSmall(textPrefix, value) {
    const row = document.createElement("div");
    row.className = "meta-small mt-2";
    row.appendChild(document.createTextNode(textPrefix + " "));
    const bold = document.createElement("b");
    bold.textContent = String(value);
    row.appendChild(bold);
    return row;
  }

  function makeProgress(executado, alocado) {
    const wrap = document.createElement("div");
    wrap.className = "meta-progress mt-1";

    const summary = document.createElement("div");
    summary.className = "d-flex justify-content-between summary mb-1";
    const left = document.createElement("span");
    left.textContent = "Executado (unidade)";
    const right = document.createElement("span");
    const b = document.createElement("b");
    b.textContent = String(executado);
    right.appendChild(b);
    right.appendChild(document.createTextNode(` / ${alocado}`));
    summary.appendChild(left);
    summary.appendChild(right);

    const progress = document.createElement("div");
    progress.className = "progress";
    const bar = document.createElement("div");
    bar.className = "progress-bar bg-primary";
    const pct = alocado ? Math.min(100, Math.round((executado / alocado) * 100)) : 0;
    bar.style.width = `${pct}%`;
    progress.appendChild(bar);

    wrap.appendChild(summary);
    wrap.appendChild(progress);
    return wrap;
  }

  function buildMetaCard(meta) {
    const programadas = Number(meta.programadas_total || 0);
    const alocado = Number(meta.alocado_unidade || 0);
    const executado = Number(meta.executado_unidade || 0);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "meta-card";
    btn.dataset.id = String(meta.id ?? "");
    btn.dataset.programadas = String(programadas);
    btn.dataset.alocado = String(alocado);

    const head = document.createElement("div");
    head.className = "meta-head";
    head.appendChild(makeIcon("bi bi-flag"));

    const title = document.createElement("h6");
    title.className = "meta-title";
    title.textContent = String(meta.nome || "");
    head.appendChild(title);

    btn.appendChild(head);

    const sep = document.createElement("div");
    sep.className = "meta-sep";
    btn.appendChild(sep);

    if (meta.data_limite) {
      const raw = String(meta.data_limite || "").slice(0, 10);
      const [year, month, day] = raw.split("-").map((part) => Number(part));
      const label = Number.isFinite(year) && Number.isFinite(month) && Number.isFinite(day)
        ? new Date(year, month - 1, day, 12, 0, 0, 0).toLocaleDateString("pt-BR")
        : raw;
      btn.appendChild(makeDateRow("Data limite:", label));
    }

    btn.appendChild(makeSmall("Em programacao:", programadas));
    btn.appendChild(makeSmall("Alocado nesta unidade:", alocado));
    btn.appendChild(makeProgress(executado, alocado));

    return btn;
  }

  function renderMessage(container, text, className) {
    container.replaceChildren();
    const div = document.createElement("div");
    div.className = className;
    div.textContent = text;
    container.appendChild(div);
  }

  NS.loadMetas = async function (dateStr = null) {
    const metasGrid = document.getElementById("metasGrid");
    if (!metasGrid) return;

    renderMessage(metasGrid, "Carregando metas...", "text-muted");

    let url = NS.urls?.metas;
    if (!url) {
      renderMessage(metasGrid, "Endpoint de metas nao configurado.", "alert alert-danger");
      return;
    }
    if (dateStr) {
      url += (url.includes("?") ? "&" : "?") + "data=" + encodeURIComponent(dateStr);
    }

    try {
      const resp = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
      const data = await resp.json();

      if (!data.metas || !Array.isArray(data.metas) || data.metas.length === 0) {
        renderMessage(metasGrid, "Nenhuma meta disponivel.", "alert alert-light border mb-0");
        return;
      }

      metasGrid.replaceChildren();
      for (const meta of data.metas) {
        metasGrid.appendChild(buildMetaCard(meta));
      }

      metasGrid.querySelectorAll(".meta-card").forEach((card) => {
        card.addEventListener("click", () => {
          metasGrid.querySelectorAll(".meta-card").forEach((c) => c.classList.remove("selected"));
          card.classList.add("selected");

          const metaId = card.dataset.id;
          if (!metaId) return;

          const programadas = Number(card.dataset.programadas || "0") || 0;
          const alocado = Number(card.dataset.alocado || "0") || 0;
          const container = document.getElementById("metaCardsContainer");
          const selector = `[data-meta-id="${escapeSelector(metaId)}"]`;
          const cards = container ? Array.from(container.querySelectorAll(selector)) : [];
          const existingCards = cards.length;
          const novosNaoSalvos = cards.filter((c) => !c.dataset.itemId).length;
          const totalAtual = programadas + novosNaoSalvos;

          if (!confirmLimite(totalAtual, alocado)) return;

          const metaTitulo = card.querySelector(".meta-title")?.textContent?.trim() || "";
          const options = {};
          if (existingCards > 0) {
            if (!confirmDuplicado(existingCards)) {
              highlightExistingCard(metaId);
              return;
            }
            options.forceNew = true;
          }

          window.PROGRAMAR?.ensureMetaCard?.(metaId, metaTitulo, options);
        });
      });
    } catch (err) {
      renderMessage(metasGrid, "Erro ao carregar metas.", "alert alert-danger");
      console.error(err);
    }
  };
})();
