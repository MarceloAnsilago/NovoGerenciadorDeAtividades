(function(){
  // Namespace do app
  const NS = window.PROGRAMAR = window.PROGRAMAR || {};

  // Função para buscar e renderizar as metas
  NS.loadMetas = async function(dateStr = null) {
    const metasGrid = document.getElementById('metasGrid');
    if (!metasGrid) return;

    metasGrid.innerHTML = `
      <div class="placeholder-glow">
        <span class="placeholder col-12 mb-2"></span>
      </div>
    `;

    // Use o endpoint correto!
    let url = NS.urls?.metas;
    if (!url) {
      metasGrid.innerHTML = `<div class="alert alert-danger">Endpoint de metas não configurado.</div>`;
      return;
    }
    if (dateStr) {
      // Se o backend espera data na querystring
      url += (url.includes('?') ? '&' : '?') + 'data=' + encodeURIComponent(dateStr);
    }

    try {
      const resp = await fetch(url, {headers: {'X-Requested-With':'XMLHttpRequest'}});
      const data = await resp.json();

      // Adapte se o JSON vier diferente!
      if (!data.metas || !Array.isArray(data.metas) || data.metas.length === 0) {
        metasGrid.innerHTML = `<div class="alert alert-light border mb-0">Nenhuma meta disponível.</div>`;
        return;
      }

      // Renderiza os cards
      metasGrid.innerHTML = data.metas.map(m => {
        return `
          <button type="button" class="meta-card" data-id="${m.id}">
            <div class="meta-head">
              <span class="icon"><i class="bi bi-flag"></i></span>
              <h6 class="meta-title">${m.nome}</h6>
            </div>
            <div class="meta-sep"></div>
            ${m.data_limite ? `
              <div class="meta-date">
                <i class="bi bi-calendar-event"></i>
                <span>Data limite:</span>
                <strong>${new Date(m.data_limite).toLocaleDateString('pt-BR')}</strong>
              </div>
            ` : ''}
            <div class="meta-small mt-2">Alocado nesta unidade: <b>${m.alocado_unidade || 0}</b></div>
            <div class="meta-progress mt-1">
              <div class="d-flex justify-content-between summary mb-1">
                <span>Executado (unidade)</span>
                <span><b>${m.executado_unidade || 0}</b> / ${m.alocado_unidade || 0}</span>
              </div>
              <div class="progress"><div class="progress-bar bg-primary" style="width:${(m.alocado_unidade ? Math.min(100, Math.round((m.executado_unidade/m.alocado_unidade)*100)) : 0)}%"></div></div>
            </div>
          </button>
        `;
      }).join('');

      // Evento de click para seleção
      metasGrid.querySelectorAll('.meta-card').forEach(card => {
        card.addEventListener('click', () => {
          metasGrid.querySelectorAll('.meta-card').forEach(c => c.classList.remove('selected'));
          card.classList.add('selected');
          // Ao clicar, chama para abrir o card de atividade!
          if (window.PROGRAMAR && typeof window.PROGRAMAR.ensureMetaCard === 'function') {
            window.PROGRAMAR.ensureMetaCard(
              card.dataset.id,
              card.querySelector('.meta-title').textContent.trim()
            );
          }
        });
      });

    } catch (err) {
      metasGrid.innerHTML = `<div class="alert alert-danger">Erro ao carregar metas.</div>`;
      console.error(err);
    }
  };

  // Exemplo: você pode disparar manualmente NS.loadMetas(dataStr)
  // quando abrir o modal ou quando a data for escolhida.

})();
