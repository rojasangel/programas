(() => {
  const dialog = document.querySelector('#auction-rule-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;

  const title = dialog.querySelector('[data-auction-rule-dialog-title]');
  const description = dialog.querySelector('[data-auction-rule-dialog-text]');
  const closeButtons = dialog.querySelectorAll('.auction-rule-dialog-close, [data-auction-rule-dialog-dismiss]');
  let lastTrigger = null;

  document.querySelectorAll('[data-auction-rule]').forEach((card) => {
    card.addEventListener('click', () => {
      const cardTitle = card.querySelector('.auction-rule-title');
      const cardDescription = card.querySelector('p');
      if (!cardTitle || !cardDescription) return;
      lastTrigger = card;
      title.textContent = cardTitle.textContent.trim();
      description.textContent = cardDescription.textContent.trim();
      dialog.showModal();
    });
  });

  closeButtons.forEach((button) => button.addEventListener('click', () => dialog.close()));
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener('close', () => lastTrigger?.focus());
})();

