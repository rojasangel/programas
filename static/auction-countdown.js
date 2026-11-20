(() => {
  const countdowns = [...document.querySelectorAll('[data-auction-countdown]')];
  if (!countdowns.length) return;

  const formatRemaining = (milliseconds) => {
    let seconds = Math.floor(milliseconds / 1000);
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

  const update = () => {
    let active = 0;
    countdowns.forEach((card) => {
      const remainingLabel = card.querySelector('[data-auction-remaining]');
      const deadline = new Date(card.dataset.auctionDeadline || '');
      if (!remainingLabel || Number.isNaN(deadline.getTime())) {
        if (remainingLabel) remainingLabel.textContent = 'Fecha de cierre no disponible';
        return;
      }
      const remaining = deadline.getTime() - Date.now();
      if (remaining <= 0) {
        remainingLabel.textContent = 'Subasta cerrada';
        card.classList.add('is-closed');
        return;
      }
      remainingLabel.textContent = `Tiempo restante: ${formatRemaining(remaining)}`;
      active += 1;
    });
    return active;
  };

  update();
  const timer = window.setInterval(() => {
    if (!update()) window.clearInterval(timer);
  }, 1000);
})();

