(() => {
  const showMessage = (message, category = 'success', links = {}) => {
    let region = document.querySelector('[data-cart-message]');
    if (!region) {
      region = document.createElement('div');
      region.className = 'ajax-cart-message';
      region.dataset.cartMessage = 'true';
      region.setAttribute('role', 'status');
      region.setAttribute('aria-live', 'polite');
      document.body.appendChild(region);
    }
    region.replaceChildren();
    const copy = document.createElement('div');
    copy.className = 'ajax-cart-message-copy';
    copy.textContent = message;
    region.appendChild(copy);
    if (category === 'success' && links.cartUrl) {
      const actions = document.createElement('div');
      actions.className = 'ajax-cart-message-actions';
      const continueLink = document.createElement('a');
      continueLink.href = links.continueUrl || '/';
      continueLink.textContent = 'Seguir comprando';
      continueLink.className = 'ajax-cart-message-link';
      const cartLink = document.createElement('a');
      cartLink.href = links.cartUrl;
      cartLink.textContent = 'Ir al carrito y pagar';
      cartLink.className = 'ajax-cart-message-link ajax-cart-message-link-primary';
      actions.append(continueLink, cartLink);
      region.appendChild(actions);
      const close = document.createElement('button');
      close.type = 'button';
      close.className = 'ajax-cart-message-close';
      close.setAttribute('aria-label', 'Cerrar aviso');
      close.textContent = '×';
      close.addEventListener('click', () => { region.hidden = true; });
      region.appendChild(close);
    }
    region.className = `ajax-cart-message ajax-cart-message-${category}`;
    region.hidden = false;
    window.clearTimeout(region._hideTimer);
    region._hideTimer = window.setTimeout(() => { region.hidden = true; }, 3200);
  };

  const updateCartCount = (count) => {
    document.querySelectorAll('.cart-count').forEach((element) => {
      element.textContent = String(count);
    });
    const link = document.querySelector('.cart-link');
    if (link) link.setAttribute('aria-label', `Carrito, ${count} productos`);
  };

  document.addEventListener('submit', async (event) => {
    const form = event.target.closest('form[action*="/carrito/agregar/"]');
    if (!form) return;
    event.preventDefault();
    const formData = new FormData(form);
    const controls = form.querySelectorAll('button, input, select');
    controls.forEach((control) => { control.disabled = true; });
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        body: formData,
        headers: {
          'Accept': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
      });
      let data = {};
      try { data = await response.json(); } catch (_) { data = {}; }
      if (!response.ok || !data.ok) {
        throw new Error(data.message || 'No pudimos agregar el producto al carrito.');
      }
      updateCartCount(data.cart_count || 0);
      showMessage(data.message || 'Producto agregado al carrito.', 'success', {
        continueUrl: data.continue_url,
        cartUrl: data.cart_url,
      });
    } catch (error) {
      showMessage(error.message || 'No pudimos agregar el producto al carrito.', 'error');
    } finally {
      controls.forEach((control) => { control.disabled = false; });
    }
  });
})();

