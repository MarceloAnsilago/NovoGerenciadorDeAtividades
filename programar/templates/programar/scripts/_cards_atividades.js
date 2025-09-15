(function(){
  const NS = window.PROGRAMAR = window.PROGRAMAR || {};

  // ---- cache/estado ----
  const allocations = {};    // sid -> total alocado em metas
  const servidoresData = []; // lista de servidores livres retornados pelo backend
  const DRAG = { id: null };

  // ---- helpers DOM ----
  const el = (id) => document.getElementById(id);
  const metaCardsContainer = () => el('metaCardsContainer');
  const expBody = () => el('expedienteBody');
  const expList = () => el('expedienteAdmin');

  // ---- criação de UI ----
  function makeDisponivelCard(s){
    const d = document.createElement('div');
    d.className = 'servidor-card';
    d.id = `srv-${s.id}`;
    d.dataset.id = s.id;
    d.setAttribute('draggable', 'true');
    d.innerHTML = `
      <span class="srv-icon"><i class="bi bi-person-fill"></i></span>
      <span class="srv-name">${s.nome}</span>
      <span class="srv-count-badge"></span>
    `;
    return d;
  }

  function makeMetaChip(srv){
    const chip = document.createElement('div');
    chip.className = 'servidor-chip';
    chip.dataset.id = srv.id;
    chip.innerHTML = `
      <span class="chip-icon"><i class="bi bi-person-fill"></i></span>
      <span class="chip-name">${srv.nome}</span>
      <button type="button" class="chip-remove" title="Remover">&times;</button>
    `;
    chip.querySelector('.chip-remove').addEventListener('click', () => {
      chip.remove();
      const sid = String(srv.id);
      allocations[sid] = Math.max(0, (allocations[sid] || 0) - 1);
      if ((allocations[sid] || 0) === 0) appendToExpediente(srv);
      updateCounts();
    });
    return chip;
  }

  function appendToExpediente(srv){
    const list = expList();
    if (!list) return;
    if (!list.querySelector(`.servidor-card[data-id="${srv.id}"]`)) {
      const el = document.createElement('div');
      el.className = 'servidor-card';
      el.dataset.id = srv.id;
      el.innerHTML = `
        <span class="srv-icon"><i class="bi bi-person-fill"></i></span>
        <span class="srv-name">${srv.nome}</span>
      `;
      list.appendChild(el);
    }
  }
  function removeOneFromExpediente(sid){
    const elx = expList()?.querySelector(`.servidor-card[data-id="${sid}"]`);
    if (elx) elx.remove();
  }
  function findSrv(id){ return servidoresData.find(s => String(s.id) === String(id)); }

  // ---- contagens/badges ----
  function updateCounts(){
    const livresBox = el('servidoresLivres');
    const freeCount = livresBox ? livresBox.querySelectorAll('.servidor-card').length : 0;
    const expCount  = expList() ? expList().querySelectorAll('.servidor-card').length : 0;

    const cLivres = el('countServidoresLivres');
    const cExp    = el('countExpedienteAdmin');
    if (cLivres) cLivres.textContent = String(freeCount);
    if (cExp)    cExp.textContent    = String(expCount);

    // atualiza badge de "alocações" nos cards livres
    if (livresBox) {
      livresBox.querySelectorAll('.servidor-card[data-id]').forEach(div => {
        const sid = div.dataset.id;
        const n = allocations[sid] || 0;
        const b = div.querySelector('.srv-count-badge');
        if (!b) return;
        if (n > 0) { div.classList.add('has-count'); b.textContent = n; }
        else       { div.classList.remove('has-count'); b.textContent = ''; }
      });
    }

    // badges nas metas
    const metaCont = metaCardsContainer();
    if (metaCont) {
      metaCont.querySelectorAll('[data-meta-id]').forEach(card => {
        const n = card.querySelectorAll('.servidor-chip').length;
        const badge = card.querySelector('.count-meta');
        if (badge) badge.textContent = String(n);
      });
    }
  }

  // ---- cards de meta (lado direito) ----
  NS.ensureMetaCard = function(metaId, metaTitle, options = {}){
    const { forceNew = false } = options;
    const container = metaCardsContainer();
    if (!container) return;

    if (!forceNew) {
      let card = container.querySelector(`[data-meta-id="${metaId}"]`);
      if (card) {
        card.querySelector('.meta-title-text').textContent = metaTitle;
        return card;
      }
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'card shadow-sm servidor-cardbox';
    wrapper.dataset.metaId = metaId;

    wrapper.innerHTML = `
      <div class="card-header">
        <div class="d-flex justify-content-between align-items-center">
          <div class="meta-header-title">
            <span class="icon"><i class="bi bi-clipboard2-check"></i></span>
            <span class="fw-semibold meta-title-text">${metaTitle}</span>
            <span class="badge text-bg-light index-badge ms-2">1</span>
          </div>
          <div class="d-flex align-items-center gap-2">
            <span class="badge bg-primary count-meta">0</span>
            <button type="button" class="btn btn-sm btn-outline-secondary meta-close" title="Fechar">&times;</button>
          </div>
        </div>
        <div class="meta-header-sep"></div>
      </div>
      <div class="card-body meta-body">
        <div class="servidores-grid meta-dropzone dropzone mb-3"></div>
        <div class="mt-2">
          <label class="form-label mb-1">Veículo da unidade</label>
          <select class="form-select form-select-sm veiculo-select" name="veiculo_id" data-meta-id="${metaId}">
            <option value="" selected disabled>Escolha um veículo</option>
            ${ (window.PROGRAMAR?.veiculosAtivos || [])
                .map(v => `<option value="${v.id}">${v.nome} - ${v.placa}</option>`).join('') }
          </select>
        </div>
      </div>
    `;

    // fechar card: retorna alocações
    wrapper.querySelector('.meta-close').addEventListener('click', () => {
      const removedCounts = {};
      wrapper.querySelectorAll('.servidor-chip').forEach(ch => {
        const sid = String(ch.dataset.id);
        removedCounts[sid] = (removedCounts[sid] || 0) + 1;
        ch.remove();
      });
      Object.entries(removedCounts).forEach(([sid, qty]) => {
        allocations[sid] = Math.max(0, (allocations[sid] || 0) - qty);
        if ((allocations[sid] || 0) === 0) {
          const srv = findSrv(sid);
          if (srv) appendToExpediente(srv);
        }
      });
      wrapper.remove();
      updateCounts();
    });

    container.prepend(wrapper);
    renumberMetaCopies(metaId);
    updateCounts();
    return wrapper;
  };

  function renumberMetaCopies(metaId){
    const container = metaCardsContainer();
    if (!container) return;
    const cards = Array.from(container.querySelectorAll(`.servidor-cardbox[data-meta-id="${metaId}"]`));
    cards.forEach((c, i) => c.querySelector('.index-badge').textContent = String(i + 1));
  }

  // ---- adicionar servidor à meta ----
  function addToMeta(serverId, metaId){
    const sid = String(serverId);
    const srv = findSrv(sid);
    if (!srv) return;

    const card = NS.ensureMetaCard(metaId, getMetaTitle(metaId));
    const dropzone = card.querySelector('.meta-dropzone');

    // evita duplicar no MESMO card
    const already = dropzone.querySelector(`.servidor-chip[data-id="${sid}"]`);
    if (already) {
      already.classList.add('dup-anim');
      setTimeout(() => already.classList.remove('dup-anim'), 450);
      return;
    }

    dropzone.appendChild(makeMetaChip(srv));

    // 1ª alocação retira do expediente
    const prev = allocations[sid] || 0;
    allocations[sid] = prev + 1;
    if (prev === 0) removeOneFromExpediente(sid);

    updateCounts();
  }

  function getMetaTitle(metaId){
    const metaCardBtn = document.querySelector(`.meta-card[data-id="${metaId}"] .meta-title`);
    return metaCardBtn ? metaCardBtn.textContent.trim() : 'Atividade';
  }

  // ---- drag & drop ----
  function setupDragAndDrop(){
    window.addEventListener('dragover', e => e.preventDefault());
    window.addEventListener('drop',     e => e.preventDefault());

    document.addEventListener('dragstart', (e) => {
      const card = e.target.closest('#servidoresLivres .servidor-card');
      if (!card) return;
      const sid = card.dataset.id;
      DRAG.id = sid;
      if (e.dataTransfer) {
        e.dataTransfer.setData('application/x-sid', sid);
        e.dataTransfer.setData('text/plain', `sid:${sid}`);
        e.dataTransfer.effectAllowed = 'copy';
      }
      card.classList.add('dragging');
    }, true);

    document.addEventListener('dragend', (e) => {
      const card = e.target.closest('#servidoresLivres .servidor-card');
      if (card) card.classList.remove('dragging');
      DRAG.id = null;
    }, true);

    // drop em QUALQUER card de meta
    metaCardsContainer()?.addEventListener('dragover', (e) => {
      const card = e.target.closest('[data-meta-id]');
      if (!card) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
      card.classList.add('dz-hover');
    }, true);

    metaCardsContainer()?.addEventListener('dragleave', (e) => {
      const card = e.target.closest('[data-meta-id]');
      if (card) card.classList.remove('dz-hover');
    }, true);

    metaCardsContainer()?.addEventListener('drop', (e) => {
      const card = e.target.closest('[data-meta-id]');
      if (!card) return;
      e.preventDefault();
      card.classList.remove('dz-hover');

      let sid = e.dataTransfer?.getData('application/x-sid');
      if (!sid) {
        const txt = e.dataTransfer?.getData('text/plain') || '';
        if (txt.startsWith('sid:')) sid = txt.slice(4);
      }
      if (!sid) sid = DRAG.id;
      if (!sid) return;

      addToMeta(sid, card.dataset.metaId);
    }, true);

    // drop no Expediente
    expBody()?.addEventListener('dragover', (e) => {
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
      expBody().classList.add('dz-hover');
    });
    expBody()?.addEventListener('dragleave', () => expBody().classList.remove('dz-hover'));
    expBody()?.addEventListener('drop', (e) => {
      e.preventDefault();
      expBody().classList.remove('dz-hover');

      let sid = e.dataTransfer?.getData('application/x-sid');
      if (!sid) {
        const txt = e.dataTransfer?.getData('text/plain') || '';
        if (txt.startsWith('sid:')) sid = txt.slice(4);
      }
      if (!sid) sid = DRAG.id;
      if (!sid) return;

      const srv = findSrv(sid);
      if (!srv) return;

      appendToExpediente(srv);
      updateCounts();
    });
  }

  // ---- carregar servidores p/ a data ----
  NS.loadServidores = async function(dateStr){
    const livresDiv = el('servidoresLivres');
    const tbodyImp  = document.querySelector('#tabelaImpedidos tbody');

    // limpa estado/UI
    Object.keys(allocations).forEach(k => delete allocations[k]);
    servidoresData.length = 0;
    if (metaCardsContainer()) metaCardsContainer().innerHTML = '';
    if (livresDiv) livresDiv.innerHTML = '<span class="text-muted">Carregando...</span>';
    if (expList())  expList().innerHTML  = '';
    if (tbodyImp)   tbodyImp.innerHTML   = '';

    let url = NS.urls?.servidores;
    if (!url) { if (livresDiv) livresDiv.textContent = 'Endpoint não configurado.'; return; }
    if (dateStr) url += (url.includes('?') ? '&' : '?') + 'data=' + encodeURIComponent(dateStr);

    try{
      const resp = await fetch(url, { headers:{'X-Requested-With':'XMLHttpRequest'} });
      const { livres, impedidos } = await resp.json();

      if (livresDiv) livresDiv.innerHTML = '';

      (livres || []).forEach(s => {
        servidoresData.push(s);
        allocations[String(s.id)] = 0;
        if (livresDiv) livresDiv.appendChild(makeDisponivelCard(s));
        appendToExpediente(s); // começa no expediente
      });

      if (tbodyImp){
        if (!impedidos || impedidos.length === 0) {
          tbodyImp.innerHTML = '<tr><td colspan="2" class="text-muted">Nenhum impedido.</td></tr>';
        } else {
          tbodyImp.innerHTML = impedidos.map(s=>`<tr><td>${s.nome}</td><td>${s.motivo || 'Descanso'}</td></tr>`).join('');
        }
      }

      updateCounts();
    }catch(err){
      console.error(err);
      if (livresDiv) livresDiv.innerHTML = '<span class="text-danger">Erro ao carregar.</span>';
      updateCounts();
    }
  };

  // instala DnD uma única vez
  setupDragAndDrop();

})();
