(() => {
  const select = document.querySelector('select[name="color_grip"]');
  const swatches = [...document.querySelectorAll('[data-grip-swatch]')];
  const toggle = document.querySelector('[data-grip-enabled]');
  const options = document.querySelector('[data-grip-options]');
  if (!select || !swatches.length) return;

  const sync = () => {
    swatches.forEach((swatch) => {
      const selected = swatch.dataset.colorValue === select.value;
      swatch.classList.toggle('is-selected', selected);
      swatch.setAttribute('aria-pressed', String(selected));
    });
  };

  swatches.forEach((swatch) => {
    swatch.addEventListener('click', () => {
      select.value = swatch.dataset.colorValue;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      sync();
    });
  });

  const syncEnabled = () => {
    const enabled = !toggle || toggle.checked;
    select.disabled = !enabled;
    swatches.forEach((swatch) => {
      swatch.disabled = !enabled;
      swatch.setAttribute('aria-disabled', String(!enabled));
    });
    if (options) {
      options.hidden = !enabled;
      options.classList.toggle('is-disabled', !enabled);
    }
  };

  select.addEventListener('change', sync);
  if (toggle) toggle.addEventListener('change', syncEnabled);
  sync();
  syncEnabled();
})();

