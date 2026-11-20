(() => {
  const dashboard = document.querySelector('[data-admin-auction-dashboard]');
  if (!dashboard) return;

  const endpoint = dashboard.dataset.adminAuctionEndpoint;
  const money = new Intl.NumberFormat('es-MX', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  const formatMoney = (value) => `${money.format(Number(value) || 0)} MXN`;

  const formatRemaining = (milliseconds) => {
    let seconds = Math.max(0, Math.floor(milliseconds / 1000));
    const days = Math.floor(seconds / 86400);
    seconds %= 86400;
    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;
    const minutes = Math.floor(seconds / 60);
    seconds %= 60;
    const parts = [];
    if (days) parts.push(`${days} d`);
    if (days || hours) parts.push(`${hours} h`);
    if (days || hours || minutes) parts.push(`${minutes} min`);
    parts.push(`${seconds} s`);
    return parts.join(' ');
  };

  const setText = (element, value) => {
    if (element) element.textContent = value;
  };

  const setupClosedAuctionToggles = () => {
    document.querySelectorAll('[data-auction-toggle]').forEach((button) => {
      if (button.dataset.toggleReady) return;
      button.dataset.toggleReady = 'true';
      button.addEventListener('click', () => {
        const card = button.closest('[data-auction-card]');
        if (!card) return;
        const expanded = card.classList.toggle('is-expanded');
        button.setAttribute('aria-expanded', String(expanded));
        button.textContent = expanded ? 'Ocultar información' : 'Ver información';
      });
    });
  };

  const updateHistory = (card, bids) => {
    const history = card.querySelector('[data-auction-bid-history]');
    const list = card.querySelector('[data-auction-bids]');
    if (!history || !list) return;
    let empty = history.querySelector('[data-auction-bids-empty]');
    list.innerHTML = '';
    if (!bids.length) {
      if (!empty) {
        empty = document.createElement('p');
        empty.dataset.auctionBidsEmpty = '';
        history.appendChild(empty);
      }
      empty.textContent = 'Aún no hay pujas.';
      empty.hidden = false;
      list.hidden = true;
      return;
    }
    if (empty) empty.hidden = true;
    list.hidden = false;
    bids.forEach((bid) => {
      const item = document.createElement('li');
      const user = document.createElement('span');
      const name = document.createElement('strong');
      const date = document.createElement('small');
      const amount = document.createElement('b');
      name.textContent = bid.user_name || 'Usuario';
      date.textContent = bid.created_at || '';
      amount.textContent = formatMoney(bid.amount);
      user.append(name);
      if (date.textContent) user.append(date);
      item.append(user, amount);
      list.appendChild(item);
    });
  };

  const updateCard = (card, data) => {
    const closed = Boolean(data.closed);
    const leader = data.leader || null;
    card.classList.toggle('is-closed', closed);
    card.dataset.auctionDeadline = data.ends_at || card.dataset.auctionDeadline;
    let toggle = card.querySelector('[data-auction-toggle]');
    if (closed && !toggle) {
      const heading = card.querySelector('h3');
      if (heading) {
        toggle = document.createElement('button');
        toggle.className = 'auction-admin-expand';
        toggle.type = 'button';
        toggle.dataset.auctionToggle = '';
        toggle.setAttribute('aria-expanded', 'false');
        toggle.textContent = 'Ver información';
        heading.insertAdjacentElement('afterend', toggle);
      }
    } else if (!closed && toggle) {
      toggle.remove();
      card.classList.remove('is-expanded');
    }
    const state = card.querySelector('[data-auction-state]');
    if (state) {
      state.textContent = closed ? 'Cerrada' : 'Activa';
      state.classList.toggle('is-live', !closed);
    }
    setText(card.querySelector('[data-auction-current-price]'), formatMoney(data.current_price));
    setText(card.querySelector('[data-auction-leader-name]'), leader ? (leader.user_name || 'Usuario') : 'Sin pujas');
    setText(card.querySelector('[data-auction-leader-amount]'), leader ? formatMoney(leader.amount) : '0.00 MXN');
    setText(card.querySelector('[data-auction-bid-count]'), String(data.bid_count || 0));
    const label = card.querySelector('[data-auction-bid-count-label]');
    if (label) label.textContent = `${data.bid_count || 0} puja${data.bid_count === 1 ? '' : 's'}`;
    updateHistory(card, Array.isArray(data.bids) ? data.bids : []);
  };

  const updateCountdowns = () => {
    document.querySelectorAll('[data-auction-card]').forEach((card) => {
      const remaining = card.querySelector('[data-auction-remaining]');
      if (!remaining) return;
      const deadline = new Date(card.dataset.auctionDeadline || '');
      if (Number.isNaN(deadline.getTime())) {
        remaining.textContent = 'Fecha no disponible';
        return;
      }
      const difference = deadline.getTime() - Date.now();
      remaining.textContent = difference <= 0 ? 'Subasta cerrada' : `Tiempo restante: ${formatRemaining(difference)}`;
    });
  };

  const updateSummary = (auctions) => {
    const active = auctions.filter((auction) => !auction.closed).length;
    const closed = auctions.length - active;
    const bids = auctions.reduce((total, auction) => total + (Number(auction.bid_count) || 0), 0);
    setText(dashboard.querySelector('[data-admin-active-count]'), String(active));
    setText(dashboard.querySelector('[data-admin-closed-count]'), String(closed));
    setText(dashboard.querySelector('[data-admin-total-bids]'), String(bids));
    setText(dashboard.querySelector('[data-admin-auction-count]'), String(auctions.length));
  };

  const setLiveStatus = (message, hasError = false) => {
    const status = dashboard.querySelector('.auction-admin-live-status');
    const update = dashboard.querySelector('[data-admin-last-update]');
    if (status) status.classList.toggle('has-error', hasError);
    if (update) update.textContent = message;
  };

  const refresh = async () => {
    try {
      const response = await fetch(`${endpoint}?t=${Date.now()}`, {
        headers: { Accept: 'application/json' },
        cache: 'no-store',
      });
      if (!response.ok) throw new Error('No se pudo actualizar la subasta');
      const payload = await response.json();
      const auctions = Array.isArray(payload.auctions) ? payload.auctions : [];
      const cards = new Map([...document.querySelectorAll('[data-auction-card]')].map((card) => [String(card.dataset.auctionId), card]));
      auctions.forEach((auction) => {
        const card = cards.get(String(auction.id));
        if (card) updateCard(card, auction);
      });
      setupClosedAuctionToggles();
      updateSummary(auctions);
      setLiveStatus(payload.updated_at || 'ahora');
      updateCountdowns();
    } catch (error) {
      setLiveStatus('sin conexión', true);
    }
  };

  setupClosedAuctionToggles();
  updateCountdowns();
  refresh();
  window.setInterval(refresh, 3000);
  window.setInterval(updateCountdowns, 1000);
})();

