(function(){
  const NS = window.PROGRAMAR = window.PROGRAMAR || {};

  // Função utilitária: obtém o container de cards de atividade
  function getContainer() {
    return document.getElementById('metaCardsContainer');
  }

  // Função global: cria/exibe o card de atividade de uma meta
  NS.ensureMetaCard = function(metaId, metaTitle) {
    const container = getContainer();
    if (!container) return;

    // Evita duplicidade: se já existe, só foca nele
    let card = container.querySelector(`[data-meta-id="${metaId}"]`);
    if (card) {
      card.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'start' });
      return card;
    }

    // Monta o HTML do card de atividade
    card = document.createElement('div');
    card.className = 'card shadow-sm servidor-cardbox';
    card.dataset.metaId = metaId;
    card.style.minWidth = "340px";
    card.style.maxWidth = "370px";
    card.innerHTML = `
      <div class="card-header bg-light border-bottom py-2 d-flex align-items-center justify-content-between">
        <b>${metaTitle}</b>
        <button type="button" class="btn-close" aria-label="Remover" title="Remover card"></button>
      </div>
      <div class="card-body">
        <div class="alert alert-info py-2 mb-1">Configuração de atividades<br><span class="text-muted">Aqui virá o conteúdo detalhado do card.</span></div>
        <!-- Coloque aqui seus inputs, selects, grids, etc -->
      </div>
    `;
    container.appendChild(card);

    // Evento para remover o card (UX)
    card.querySelector('.btn-close').addEventListener('click', () => {
      card.remove();
    });

    // Rola até o card novo (opcional)
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'start' });

    return card;
  };
})();
