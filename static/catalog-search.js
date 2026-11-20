(() => {
  const setSearchState = (form, trigger, isOpen) => {
    form.classList.toggle('is-open', isOpen);
    form.setAttribute('aria-hidden', String(!isOpen));
    trigger.setAttribute('aria-expanded', String(isOpen));
    trigger.setAttribute('aria-label', isOpen ? 'Ejecutar búsqueda' : 'Abrir buscador');
    trigger.setAttribute('title', isOpen ? 'Buscar' : 'Abrir buscador');
  };

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-focus-catalog-search]');
    if (!trigger) return;

    const input = document.getElementById('catalog-query');
    if (!input) return;

    event.preventDefault();
    const form = input.closest('.catalog-search-collapsible');
    if (form) {
      if (form.classList.contains('is-open')) {
        if (input.value.trim()) {
          if (typeof form.requestSubmit === 'function') form.requestSubmit();
          else form.submit();
        } else {
          input.focus({ preventScroll: true });
        }
        return;
      }
      setSearchState(form, trigger, true);
    }
    input.focus({ preventScroll: true });
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    const form = document.querySelector('.catalog-search-collapsible.is-open');
    const trigger = document.querySelector('[data-focus-catalog-search]');
    if (!form || !trigger) return;
    setSearchState(form, trigger, false);
    trigger.focus();
  });
})();

