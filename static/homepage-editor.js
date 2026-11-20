(() => {
  'use strict';
  const root = document.querySelector('[data-visual-home-editor]');
  if (!root) return;
  const $ = (s) => root.querySelector(s);
  const initial = JSON.parse($('[data-home-initial]').textContent);
  let model = structuredClone(initial.content);
  const limits = initial.limits;
  const frame = $('[data-home-canvas]');
  const inspector = $('[data-inspector]');
  const layers = $('[data-layer-list]');
  const status = $('[data-editor-status]');
  const errorBox = $('[data-home-error]');
  const csrf = $('[name=csrf_token]').value;
  const uploads = new Map();
  const undo = [], redo = [];
  let selected = 'hero', activePhoto = model.hero.images[0]?.id, device = 'desktop';
  const customButtonModes = new Set();
  let saved = JSON.stringify(model), saving = false, rendering = 0, requestController, renderTimer;
  const copy = (x) => structuredClone(x);
  const uid = () => crypto.randomUUID();
  const clamp = (n, a, b) => Math.round(Math.max(a, Math.min(b, n)));
  const fontNames = { modern: 'Moderna', classic: 'Clásica', sport: 'Deportiva', mono: 'Técnica' };
  const fieldNames = { eyebrow: 'Texto pequeño', title: 'Título', accent: 'Texto destacado', description: 'Descripción', body: 'Información', watermark: 'Etiqueta', button_label: 'Texto del botón', button_url: 'Destino del botón' };
  const maxLength = (key, field) => ({ title: 100, accent: 100, eyebrow: 60, description: 500, body: key.startsWith('section:') ? 1600 : 500, watermark: 40, button_label: 50, button_url: 300 }[field] || 180);
  const buttonDestinations = {
    '/#catalogo': 'Ver catálogo',
    '/?categoria=B%C3%A9isbol#catalogo': 'Ver béisbol',
    '/?categoria=Softball#catalogo': 'Ver sóftbol',
    '/nuestra-marca': 'Nuestra marca',
    '/producto/7': 'Bat personalizado',
    '/subasta': 'Subastas',
    '/ayuda': 'Ayuda',
    '/contacto': 'Contacto',
    '/nosotros': 'Nosotros',
    '/carrito': 'Carrito',
  };
  function block(key = selected) {
    if (!key.includes(':')) return model[key];
    const [type, id] = key.split(':');
    return model[type === 'section' ? 'sections' : 'announcements'].find((b) => b.id === id);
  }
  function blockName(key) { return ({ hero: 'Portada', catalog: 'Catálogo', callout: 'Mensaje final' })[key] || block(key)?.title || (key.startsWith('section:') ? 'Foto y texto' : 'Anuncio'); }
  function domBlock(key = selected) { return [...(frame.contentDocument?.querySelectorAll('[data-home-block-key]') || [])].find((el) => el.dataset.homeBlockKey === key); }
  function make(tag, className, text, doc = document) { const el = doc.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el; }
  function button(text, onClick, parent, title) { const el = make('button', 've-button', text); el.type = 'button'; if (title) { el.title = title; el.setAttribute('aria-label', title); } el.addEventListener('click', onClick); parent.append(el); return el; }
  const previewButton = make('button', 've-button ve-preview-button', 'Vista previa');
  previewButton.type = 'button';
  previewButton.setAttribute('aria-label', 'Abrir vista previa de la pÃ¡gina de inicio');
  root.querySelector('[data-save="draft"]')?.before(previewButton);
  function message(text) { errorBox.textContent = text; errorBox.hidden = !text; }
  function dirty() {
    const changed = JSON.stringify(model) !== saved;
    status.textContent = changed ? 'Cambios sin guardar' : 'Borrador guardado';
    status.classList.toggle('is-dirty', changed);
    $('[data-undo]').disabled = !undo.length || saving;
    $('[data-redo]').disabled = !redo.length || saving;
  }
  function checkpoint() {
    const snapshot = JSON.stringify(model);
    if (undo.at(-1) !== snapshot) undo.push(snapshot);
    if (undo.length > 40) undo.shift();
    redo.length = 0;
  }
  function history(back) {
    if (saving) return;
    const from = back ? undo : redo, to = back ? redo : undo;
    if (!from.length) return;
    to.push(JSON.stringify(model));
    model = JSON.parse(from.pop());
    if (!block()) selected = 'hero';
    dirty(); renderLayers(); renderInspector(); renderCanvas();
  }
  $('[data-undo]').addEventListener('click', () => history(true));
  $('[data-redo]').addEventListener('click', () => history(false));
  function keyboard(event) {
    if (!(event.ctrlKey || event.metaKey)) return;
    if (event.key.toLowerCase() === 's') { event.preventDefault(); save('draft'); }
    if (event.key.toLowerCase() === 'z') { event.preventDefault(); history(!event.shiftKey); }
    if (event.key.toLowerCase() === 'y') { event.preventDefault(); history(false); }
  }
  document.addEventListener('keydown', keyboard);
  function change(fn, rerender = true) {
    if (saving) return;
    checkpoint(); fn(); dirty(); renderLayers(); renderInspector();
    if (rerender) renderCanvas(); else applyStyles();
  }
  function select(key, scroll = false) {
    selected = key;
    renderLayers(); renderInspector(); paintSelection();
    if (scroll) domBlock()?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
  function paintSelection() {
    frame.contentDocument?.querySelectorAll('[data-home-block-key]').forEach((el) => el.classList.toggle('ve-selected', el.dataset.homeBlockKey === selected));
  }
  function move(key, offset) {
    const order = model.block_order, i = order.indexOf(key), j = i + offset;
    if (j < 0 || j >= order.length) return;
    change(() => { [order[i], order[j]] = [order[j], order[i]]; });
  }
  function reorder(key, target, after = false) {
    if (key === target || !model.block_order.includes(target)) return;
    change(() => {
      const order = model.block_order.filter((k) => k !== key);
      order.splice(order.indexOf(target) + (after ? 1 : 0), 0, key);
      model.block_order = order;
    });
  }
  let draggedLayer = null;
  function renderLayers() {
    layers.replaceChildren();
    model.block_order.forEach((key, index) => {
      const b = block(key); if (!b) return;
      const row = make('div', 've-layer' + (key === selected ? ' is-selected' : '') + (!b.enabled ? ' is-hidden' : ''));
      row.dataset.layerKey = key; row.draggable = true; row.tabIndex = 0; row.setAttribute('aria-label', blockName(key));
      row.append(make('span', 've-drag-grip', '⠿'), make('span', 've-layer-label', blockName(key)));
      row.addEventListener('click', () => select(key, true));
      row.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(key, true); } });
      const up = button('↑', (e) => { e.stopPropagation(); move(key, -1); }, row, 'Subir sección');
      const down = button('↓', (e) => { e.stopPropagation(); move(key, 1); }, row, 'Bajar sección');
      up.disabled = index === 0; down.disabled = index === model.block_order.length - 1;
      row.addEventListener('dragstart', (e) => { draggedLayer = key; e.dataTransfer.setData('text/plain', key); e.dataTransfer.effectAllowed = 'move'; });
      row.addEventListener('dragover', (e) => { if (draggedLayer) { e.preventDefault(); row.classList.add('is-drop-target'); } });
      row.addEventListener('dragleave', () => row.classList.remove('is-drop-target'));
      row.addEventListener('drop', (e) => { e.preventDefault(); if (draggedLayer) reorder(draggedLayer, key, e.clientY > row.getBoundingClientRect().top + row.offsetHeight / 2); draggedLayer = null; });
      row.addEventListener('dragend', () => { draggedLayer = null; layers.querySelectorAll('.is-drop-target').forEach((el) => el.classList.remove('is-drop-target')); });
      layers.append(row);
    });
    $('[data-add=section]').disabled = model.sections.length >= limits.sections;
    $('[data-add=announcement]').disabled = model.announcements.length >= limits.announcements;
  }
  function add(type) {
    const list = type === 'section' ? model.sections : model.announcements;
    if (list.length >= limits[type === 'section' ? 'sections' : 'announcements']) return;
    const id = uid(), key = type + ':' + id;
    change(() => {
      list.push({ id, enabled: true, position: 'before_catalog', title: type === 'section' ? 'Tu nueva sección' : 'Novedades de la tienda', eyebrow: 'FR BEISSHOP', body: 'Haz clic aquí y escribe el mensaje para tus clientes.', image_url: '', image_alt: '', button_label: '', button_url: '', font_family: 'modern', text_color: '#171d32', accent_color: '#1234d6', background_color: '#ffffff', text_align: 'left' });
      const at = model.block_order.indexOf(selected);
      model.block_order.splice(at + 1, 0, key); selected = key;
    });
  }
  root.querySelectorAll('[data-add]').forEach((el) => el.addEventListener('click', () => add(el.dataset.add)));
  function inspectorField(labelText, name, opts = {}) {
    const b = block(), key = selected;
    const label = make('label', 've-field'), caption = make('span', '', labelText);
    const input = make(opts.choices ? 'select' : opts.type === 'textarea' ? 'textarea' : 'input');
    input.dataset.inspectField = name;
    if (opts.choices) Object.entries(opts.choices).forEach(([value, text]) => { const option = make('option', '', text); option.value = value; input.append(option); });
    else if (opts.type !== 'textarea') input.type = opts.type || 'text';
    if (input.type === 'checkbox') input.checked = b[name] !== false;
    else input.value = b[name] ?? '';
    if (opts.min !== undefined) input.min = opts.min;
    if (opts.max !== undefined) input.max = opts.max;
    if (opts.type === 'range') { input.step = '1'; caption.textContent += ' · ' + input.value + (opts.unit || ''); }
    if (input.type === 'text' || opts.type === 'textarea') input.maxLength = maxLength(key, name);
    input.addEventListener('focus', checkpoint);
    input.addEventListener('pointerdown', () => { if (opts.type === 'range' || opts.type === 'color') checkpoint(); });
    input.addEventListener('input', () => {
      if (saving) return;
      b[name] = input.type === 'checkbox' ? input.checked : opts.type === 'range' ? Number(input.value) : input.value;
      if (opts.type === 'range') caption.textContent = labelText + ' · ' + input.value + (opts.unit || '');
      dirty();
      if (opts.structural || input.type === 'checkbox') {
        clearTimeout(renderTimer); renderTimer = setTimeout(renderCanvas, 180); renderLayers();
      } else {
        const el = domBlock(key);
        el?.querySelectorAll('[data-home-field]').forEach((node) => { if (node.dataset.homeField === name) node.textContent = b[name]; });
        applyStyles(key);
      }
    });
    input.addEventListener('change', () => { if (opts.structural) renderInspector(); });
    label.append(caption, input); inspector.append(label); return input;
  }
  function subtitle(text) { inspector.append(make('div', 've-subtitle', text)); }
  function renderInspector() {
    inspector.replaceChildren();
    const b = block(); if (!b) return;
    $('[data-selection-label]').textContent = blockName(selected);
    inspector.append(make('p', 've-muted', 'Selecciona un texto en la página para escribir. Aquí ajustas su sección.'));
    inspectorField('Mostrar esta sección', 'enabled', { type: 'checkbox', structural: true });
    const orderActions = make('div', 've-actions');
    button('↑ Subir', () => move(selected, -1), orderActions);
    button('↓ Bajar', () => move(selected, 1), orderActions);
    inspector.append(orderActions);
    if (selected === 'hero') {
      subtitle('Distribución de la portada');
      inspectorField('Imagen y texto', 'image_layout', { choices: { side: 'Foto a la derecha', left: 'Foto a la izquierda', below: 'Foto debajo del texto', above: 'Foto encima del texto', background: 'Foto como fondo', free: 'Posición libre con el mouse' }, structural: true });
      if (b.image_layout === 'free') {
        inspector.append(make('p', 've-muted', 'Arrastra «Mover foto» o «Mover texto» en la vista de computadora. En celular se acomodan uno debajo del otro.'));
        inspectorField('Ancho de la foto', 'image_width', { type: 'range', min: 15, max: 100, unit: '%' });
        inspectorField('Ancho del texto', 'copy_width', { type: 'range', min: 15, max: 100, unit: '%' });
        inspectorField('Altura del recuadro', 'canvas_height', { type: 'range', min: 400, max: 1000, unit: ' px' });
      } else inspectorField('Tamaño de la foto', 'image_size', { choices: { small: 'Pequeña', medium: 'Mediana', large: 'Grande' }, structural: true });
      inspectorField('Encuadre', 'image_fit', { choices: { contain: 'Mostrar completa', cover: 'Llenar el recuadro' }, structural: true });
      inspectorField('Acercamiento', 'image_zoom', { type: 'range', min: 100, max: 180, unit: '%' });
      inspectorField('Encuadre horizontal', 'image_position_x', { type: 'range', min: 0, max: 100, unit: '%' });
      inspectorField('Encuadre vertical', 'image_position_y', { type: 'range', min: 0, max: 100, unit: '%' });
      subtitle('Fotos de portada');
      const gallery = make('div', 've-gallery');
      model.hero.images.forEach((photo, i) => {
        const item = make('div', 've-photo' + (photo.id === activePhoto ? ' is-selected' : ''));
        const image = make('img'); image.src = imageUrl(photo); image.alt = photo.alt || 'Foto de portada';
        image.addEventListener('click', () => { activePhoto = photo.id; showPhoto(); renderInspector(); });
        const info = make('div'); info.append(make('span', '', 'Foto ' + (i + 1)));
        const actions = make('div', 've-actions');
        button('↑', () => { if (i) change(() => { [model.hero.images[i - 1], model.hero.images[i]] = [model.hero.images[i], model.hero.images[i - 1]]; }); }, actions, 'Subir foto');
        button('Cambiar', () => chooseImage('hero', photo.id), actions);
        button('×', () => change(() => { model.hero.images = model.hero.images.filter((p) => p.id !== photo.id); }), actions, 'Quitar foto');
        const removeButton = actions.lastElementChild;
        if (removeButton) { removeButton.textContent = 'Eliminar foto'; removeButton.title = 'Eliminar foto de la portada'; removeButton.setAttribute('aria-label', 'Eliminar foto de la portada'); }
        info.append(actions); item.append(image, info); gallery.append(item);
      });
      inspector.append(gallery);
      button('＋ Subir foto', () => chooseImage('hero'), inspector).disabled = model.hero.images.length >= limits.hero_images;
    } else if (selected.includes(':')) {
      subtitle('Imagen');
      const actions = make('div', 've-actions');
      button(b.image_url || b._upload ? 'Cambiar foto' : '＋ Subir foto', () => chooseImage(selected), actions);
      if (b.image_url || b._upload) button('Eliminar foto', () => change(() => { b.image_url = ''; delete b._upload; }), actions, 'Eliminar foto del bloque');
      inspector.append(actions);
      inspectorField('Descripción de la foto', 'image_alt');
    }
    subtitle('Estilo de la sección');
    inspectorField('Tipo de letra', 'font_family', { choices: fontNames });
    inspectorField('Alineación', 'text_align', { choices: { left: 'Izquierda', center: 'Centrada', right: 'Derecha' } });
    inspectorField('Color del texto', 'text_color', { type: 'color' });
    inspectorField('Color destacado y botón', 'accent_color', { type: 'color' });
    inspectorField('Color del panel', 'background_color', { type: 'color' });
    inspectorField('Color del borde', 'border_color', { type: 'color' });
    inspectorField('Redondeado del panel', 'panel_radius', { type: 'range', min: 0, max: 48, unit: ' px' });
    inspectorField('Espaciado interno', 'panel_padding', { type: 'range', min: 12, max: 72, unit: ' px' });
    if (selected !== 'catalog') {
      subtitle('Botón');
      inspectorField('Texto del botón', 'button_label');
      const destinationChoices = { '': 'Sin acción', ...buttonDestinations, '__custom__': 'Enlace personalizado' };
      const destinationSelect = make('select');
      destinationSelect.className = 've-control';
      destinationSelect.dataset.buttonAction = 'true';
      const currentDestination = b.button_url || '';
      const usesCustomDestination = customButtonModes.has(selected) || (currentDestination && !Object.prototype.hasOwnProperty.call(buttonDestinations, currentDestination));
      Object.entries(destinationChoices).forEach(([value, label]) => {
        const option = make('option', '', label); option.value = value; destinationSelect.append(option);
      });
      destinationSelect.value = usesCustomDestination ? '__custom__' : currentDestination;
      const destinationLabel = make('label', 've-field');
      destinationLabel.append(make('span', '', 'Función del botón'), destinationSelect);
      destinationSelect.addEventListener('change', () => {
        if (destinationSelect.value === '__custom__') {
          customButtonModes.add(selected);
          change(() => { b.button_url = usesCustomDestination ? currentDestination : ''; });
        } else {
          customButtonModes.delete(selected);
          change(() => { b.button_url = destinationSelect.value; });
        }
      });
      inspector.append(destinationLabel);
      if (usesCustomDestination || destinationSelect.value === '__custom__') inspectorField('Destino personalizado', 'button_url');
      inspector.append(make('p', 've-muted', 'Elige qué debe abrir el botón. Deja el texto vacío para ocultarlo.'));
    }
    if (selected.includes(':')) {
      inspector.append(make('hr'));
      button('Eliminar sección', () => {
        const key = selected;
        change(() => {
          model.sections = model.sections.filter((s) => 'section:' + s.id !== key);
          model.announcements = model.announcements.filter((s) => 'announcement:' + s.id !== key);
          model.block_order = model.block_order.filter((k) => k !== key); selected = 'hero';
        });
      }, inspector);
    }
  }
  function imageUrl(photo) { return photo._upload ? uploads.get(photo._upload)?.url || '' : photo.url || photo.image_url || ''; }
  function chooseImage(key, replaceId) {
    const picker = make('input'); picker.type = 'file'; picker.accept = 'image/jpeg,image/png,image/webp'; picker.multiple = key === 'hero' && !replaceId;
    picker.addEventListener('change', () => {
      const files = [...picker.files]; if (!files.length) return;
      if (files.some((f) => !/\.(png|jpe?g|webp)$/i.test(f.name) || f.size > 8 * 1024 * 1024)) { message('Selecciona imágenes JPG, PNG o WEBP de hasta 8 MB.'); return; }
      if (key === 'hero' && !replaceId && model.hero.images.length + files.length > limits.hero_images) { message('La portada admite hasta ' + limits.hero_images + ' fotos.'); return; }
      message('');
      change(() => {
        files.forEach((file) => {
          const token = uid(); uploads.set(token, { file, url: URL.createObjectURL(file) });
          if (key === 'hero') {
            let photo = model.hero.images.find((p) => p.id === replaceId);
            if (!photo) { photo = { id: uid(), url: '', alt: file.name.replace(/\.[^.]+$/, '') }; model.hero.images.push(photo); }
            photo._upload = token; activePhoto = photo.id;
          } else {
            const b = block(key); if (b) { b._upload = token; b.image_alt = b.image_alt || file.name.replace(/\.[^.]+$/, ''); }
          }
        });
      });
    });
    picker.click();
  }
  function previewContent() {
    const payload = copy(model), placeholder = '/static/uploads/' + '0'.repeat(32) + '.png';
    payload.hero.images.forEach((photo) => { if (photo._upload) photo.url = placeholder; delete photo._upload; });
    [...payload.sections, ...payload.announcements].forEach((b) => { if (b._upload) b.image_url = placeholder; delete b._upload; });
    // A preview may contain temporarily empty text while the user is typing.
    [payload.hero, payload.catalog, payload.callout, ...payload.sections, ...payload.announcements].forEach((b) => {
      if (!b.title.trim()) b.title = 'Escribe un título';
      if (b.button_label && !b.button_url) b.button_url = '/';
    });
    payload.catalog.enabled = true;
    return payload;
  }
  async function renderCanvas() {
    clearTimeout(renderTimer);
    const serial = ++rendering;
    requestController?.abort(); requestController = new AbortController();
    const scroll = frame.contentWindow?.scrollY || 0;
    try {
      const response = await fetch(root.dataset.renderUrl, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify({ content: previewContent() }), signal: requestController.signal });
      if (response.redirected) throw new Error('Tu sesión terminó. Abre la administración en otra pestaña e inicia sesión para guardar.');
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.error || 'No se pudo mostrar la vista previa.'); }
      const html = await response.text(); if (serial !== rendering) return;
      frame.onload = () => { if (serial !== rendering) return; installCanvas(); frame.contentWindow.scrollTo(0, scroll); $('[data-canvas-loading]').hidden = true; };
      frame.srcdoc = html.replace('</head>', '<link rel="stylesheet" href="/static/homepage-canvas-editor.css?v=visual4"></head>');
    } catch (error) { if (error.name !== 'AbortError') { message(error.message); $('[data-canvas-loading]').hidden = true; } }
  }
  function openCurrentPreview() {
    const source = frame.contentDocument?.documentElement;
    const popup = window.open('', '_blank');
    if (!popup) { message('Permite las ventanas emergentes para abrir la vista previa.'); return; }
    if (!source) { popup.close(); message('La vista previa aún se está cargando. Inténtalo de nuevo en un momento.'); return; }
    const preview = source.cloneNode(true);
    preview.querySelector('body')?.classList.remove('home-live-editing');
    preview.querySelectorAll('.ve-block-controls,.ve-move-handle,.ve-resize-handle,.home-image-empty').forEach((el) => el.remove());
    preview.querySelectorAll('.ve-selected').forEach((el) => el.classList.remove('ve-selected'));
    preview.querySelectorAll('.ve-disabled-block').forEach((el) => el.remove());
    preview.querySelectorAll('script').forEach((el) => el.remove());
    preview.querySelectorAll('[contenteditable]').forEach((el) => { el.removeAttribute('contenteditable'); el.removeAttribute('role'); });
    preview.querySelectorAll('link[href*="homepage-canvas-editor.css"]').forEach((el) => el.remove());
    const head = preview.querySelector('head');
    if (head && !head.querySelector('base')) { const base = preview.ownerDocument.createElement('base'); base.href = location.origin + '/'; head.prepend(base); }
    if (head) {
      const previewStyles = preview.ownerDocument.createElement('style');
      previewStyles.textContent = '.admin-preview-toolbar{position:sticky;top:0;z-index:1000;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 20px;color:#172038;background:#fff;border-bottom:1px solid #dce2ef;box-shadow:0 4px 18px #17203818;font:600 12px/1.4 Segoe UI,Arial,sans-serif}.admin-preview-toolbar strong{font-size:13px}.admin-preview-toolbar small{display:block;margin-top:2px;color:#66738b;font-weight:400}.admin-preview-toolbar-actions{display:flex;flex-wrap:wrap;gap:8px}.admin-preview-toolbar button{min-height:34px;padding:8px 12px;border:1px solid #dce2ef;border-radius:8px;color:#293854;background:#fff;font:inherit;cursor:pointer}.admin-preview-toolbar button:hover{border-color:#94a5f7;background:#f4f6ff}.admin-preview-toolbar [data-preview-publish]{color:#fff;border-color:#2946ee;background:#2946ee}.admin-preview-toolbar [data-preview-publish]:hover{background:#1735d3}.admin-preview-toolbar button:disabled{opacity:.55;cursor:wait}@media(max-width:600px){.admin-preview-toolbar{align-items:flex-start;flex-direction:column;padding:12px 14px}.admin-preview-toolbar-actions{width:100%}.admin-preview-toolbar button{flex:1}}';
      head.append(previewStyles);
    }
    const previewBody = preview.querySelector('body');
    if (previewBody) {
      const toolbar = preview.ownerDocument.createElement('div');
      toolbar.className = 'admin-preview-toolbar';
      toolbar.innerHTML = '<div><strong>Vista previa de tus cambios</strong><small>Guardar cambios los publicará en la tienda.</small></div><div class="admin-preview-toolbar-actions"><button type="button" data-preview-back>Volver al editor</button><button type="button" data-preview-publish>Guardar cambios</button></div>';
      previewBody.prepend(toolbar);
    }
    popup.document.open();
    popup.document.write('<!doctype html>' + preview.outerHTML);
    popup.document.close();
    popup.addEventListener('load', () => {
      popup.document.querySelector('[data-preview-back]')?.addEventListener('click', () => { popup.close(); window.focus(); });
      popup.document.querySelector('[data-preview-publish]')?.addEventListener('click', async (event) => {
        const publishButton = event.currentTarget;
        publishButton.disabled = true;
        publishButton.textContent = 'Guardando…';
        const published = await window.homepageVisualEditor?.publish();
        publishButton.textContent = published ? 'Cambios publicados' : 'Reintentar guardar';
        publishButton.disabled = false;
      });
    });
  }

  function applyStyles(key = selected) {
    const b = block(key), el = domBlock(key); if (!b || !el) return;
    for (const [prop, value] of Object.entries({ '--home-text': b.text_color, '--home-accent': b.accent_color, '--home-bg': b.background_color, '--home-align': b.text_align, '--home-border': b.border_color, '--home-radius': (b.panel_radius ?? 20) + 'px', '--home-padding': (b.panel_padding ?? 24) + 'px' })) if (value) el.style.setProperty(prop, value);
    Object.keys(fontNames).forEach((font) => el.classList.toggle('home-font-' + font, b.font_family === font));
    el.classList.toggle('ve-disabled-block', !b.enabled);
    if (key === 'hero') {
      const fields = { text_color: ['text-color',''], accent_color: ['accent-color',''], image_position_x: ['image-x','%'], image_position_y: ['image-y','%'], image_zoom: ['image-zoom',''], image_left: ['image-left','%'], image_top: ['image-top','%'], image_width: ['image-width','%'], copy_left: ['copy-left','%'], copy_top: ['copy-top','%'], copy_width: ['copy-width','%'], canvas_height: ['canvas-height','px'] };
      Object.entries(fields).forEach(([name, [css, suffix]]) => el.style.setProperty('--hero-' + css, b[name] + suffix));
    }
  }
  function showPhoto() {
    const images = model.hero.images;
    if (!images.some((p) => p.id === activePhoto)) activePhoto = images[0]?.id;
    frame.contentDocument?.querySelectorAll('[data-home-image-slot^="hero:"]').forEach((img) => {
      const photo = images.find((p) => 'hero:' + p.id === img.dataset.homeImageSlot);
      if (photo) { img.src = imageUrl(photo); img.hidden = photo.id !== activePhoto; img.classList.toggle('is-active', !img.hidden); }
    });
  }
  function installCanvas() {
    const doc = frame.contentDocument;
    doc.body.classList.add('home-live-editing');
    doc.addEventListener('keydown', keyboard);
    doc.addEventListener('submit', (e) => e.preventDefault(), true);
    doc.addEventListener('click', (e) => {
      const el = e.target.closest('[data-home-block-key]');
      const action = e.target.closest('.home-content-action');
      if (action) {
        e.preventDefault();
        if (el) {
          select(el.dataset.homeBlockKey);
          window.setTimeout(() => inspector.querySelector('[data-button-action]')?.focus(), 0);
        }
        return;
      }
      if (e.target.closest('a,button')) e.preventDefault();
      if (el && selected !== el.dataset.homeBlockKey) select(el.dataset.homeBlockKey);
    }, true);
    doc.querySelectorAll('[data-home-block-key]').forEach((el) => {
      const key = el.dataset.homeBlockKey, b = block(key); if (!b) return;
      const bar = make('div', 've-block-controls', undefined, doc);
      const handle = make('button', '', '⠿ Mover sección', doc); handle.type = 'button'; handle.dataset.veDragBlock = key;
      bar.append(handle);
      for (const [text, offset] of [['↑', -1], ['↓', 1]]) {
        const btn = make('button', '', text, doc); btn.type = 'button'; btn.setAttribute('aria-label', offset < 0 ? 'Subir sección' : 'Bajar sección');
        btn.addEventListener('click', () => move(key, offset)); bar.append(btn);
      }
      el.prepend(bar); attachBlockDrag(handle, key);
      el.querySelectorAll('[data-home-field]').forEach((text) => {
        const name = text.dataset.homeField;
        text.textContent = b[name] || '';
        text.contentEditable = 'plaintext-only'; text.spellcheck = true; text.setAttribute('role', 'textbox'); text.setAttribute('aria-label', fieldNames[name] || name);
        text.addEventListener('focus', () => { checkpoint(); if (selected !== key) select(key); });
        text.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !['body', 'description'].includes(name)) { event.preventDefault(); text.blur(); } });
        text.addEventListener('input', () => {
          let value = text.innerText.replace(/\u00a0/g, ' ').replace(/\r/g, '');
          if (value.length > maxLength(key, name)) { value = value.slice(0, maxLength(key, name)); text.textContent = value; }
          b[name] = value;
          if (selected === key) { const field = inspector.querySelector('[data-inspect-field="' + name + '"]'); if (field) field.value = value; }
          dirty();
        });
        text.addEventListener('blur', () => { b[name] = text.innerText.trim(); dirty(); renderLayers(); });
      });
      el.querySelectorAll('[data-home-image-slot]').forEach((img) => {
        img.draggable = false;
        if (key !== 'hero') img.src = imageUrl(b);
        img.addEventListener('click', () => {
          select(key);
          if (key !== 'hero') chooseImage(key);
        });
        img.title = key === 'hero' ? 'Usa «Mover foto» para acomodarla y la esquina para cambiar su tamaño' : 'Haz clic para cambiar la foto';
      });
      el.querySelector('[data-home-add-image]')?.addEventListener('click', () => chooseImage(key));
      applyStyles(key);
    });
    const hero = domBlock('hero');
    if (hero) {
      // La foto se mueve directamente con el ratón; el control de texto queda como apoyo.
      hero.querySelectorAll('[data-home-image-slot^="hero:"]').forEach((img) => {
        img.classList.add('ve-direct-image');
        const photoId = img.dataset.homeImageSlot.slice(5);
        img.addEventListener('dblclick', (event) => {
          event.preventDefault(); event.stopPropagation();
          chooseImage('hero', photoId);
        });
        attachHeroDrag(img, 'image', false);
      });
      for (const type of ['copy', 'image']) {
        const el = hero.querySelector(type === 'copy' ? '[data-home-hero-copy]' : '[data-home-hero-media]');
        if (!el) continue;
        const handle = make('button', 've-move-handle', type === 'copy' ? '✥ Mover texto' : '✥ Mover foto', doc);
        handle.type = 'button'; handle.dataset.veMove = type; el.prepend(handle);
        attachHeroDrag(handle, type, false);
        const resize = make('button', 've-resize-handle', '↘', doc); resize.type = 'button'; resize.setAttribute('aria-label', type === 'copy' ? 'Cambiar ancho del texto' : 'Cambiar tamaño de foto'); resize.dataset.veResize = type;
        el.append(resize); attachHeroDrag(resize, type, true);
      }
    }
    showPhoto(); paintSelection();
    doc.querySelectorAll('a').forEach((link) => link.removeAttribute('target'));
  }
  function attachBlockDrag(handle, key) {
    let targetKey, after, startY, active = false;
    handle.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || saving) return; e.preventDefault(); startY = e.clientY; active = true; targetKey = null; handle.setPointerCapture(e.pointerId); select(key);
    });
    handle.addEventListener('pointermove', (e) => {
      if (!active || Math.abs(e.clientY - startY) < 6) return;
      const doc = frame.contentDocument;
      doc.querySelectorAll('.ve-drop-before,.ve-drop-after').forEach((el) => el.classList.remove('ve-drop-before','ve-drop-after'));
      const candidates = [...doc.querySelectorAll('[data-home-block-key]')].filter((el) => el.dataset.homeBlockKey !== key);
      const closest = candidates.sort((a,b) => Math.abs(a.getBoundingClientRect().top + a.offsetHeight / 2 - e.clientY) - Math.abs(b.getBoundingClientRect().top + b.offsetHeight / 2 - e.clientY))[0];
      if (closest) { targetKey = closest.dataset.homeBlockKey; after = e.clientY > closest.getBoundingClientRect().top + closest.offsetHeight / 2; closest.classList.add(after ? 've-drop-after' : 've-drop-before'); }
      if (e.clientY < 60) frame.contentWindow.scrollBy(0, -22);
      if (e.clientY > frame.clientHeight - 60) frame.contentWindow.scrollBy(0, 22);
    });
    const finish = () => { if (!active) return; active = false; if (targetKey) reorder(key, targetKey, after); frame.contentDocument?.querySelectorAll('.ve-drop-before,.ve-drop-after').forEach((el) => el.classList.remove('ve-drop-before','ve-drop-after')); };
    handle.addEventListener('pointerup', finish); handle.addEventListener('pointercancel', () => { active = false; }); handle.addEventListener('lostpointercapture', finish);
  }
  function attachHeroDrag(handle, type, resizing) {
    let drag;
    const gutter = 4;
    handle.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || saving) return;
      e.preventDefault(); e.stopPropagation();
      if (frame.contentWindow.innerWidth <= 600 || device === 'mobile') { message('Para mover libremente la portada, selecciona la vista de Computadora.'); return; }
      message(''); checkpoint(); select('hero');
      const hero = domBlock('hero'), rect = hero.getBoundingClientRect(), b = model.hero;
      if (b.image_layout !== 'free') {
        for (const kind of ['image','copy']) {
          const part = hero.querySelector(kind === 'copy' ? '[data-home-hero-copy]' : '[data-home-hero-media]');
          if (!part) continue;
          const box = part.getBoundingClientRect();
          b[kind + '_width'] = clamp(box.width / rect.width * 100, 15, 100 - gutter * 2);
          b[kind + '_left'] = clamp((box.left - rect.left) / rect.width * 100, gutter, Math.max(gutter, 100 - b[kind + '_width'] - gutter));
          b[kind + '_top'] = clamp((box.top - rect.top) / rect.height * 100, gutter, 95 - gutter);
        }
        b.canvas_height = clamp(rect.height, 400, 1000);
        ['side','left','above','below','background'].forEach((layout) => hero.classList.remove('home-hero-layout-' + layout));
        b.image_layout = 'free'; hero.classList.add('home-hero-layout-free'); applyStyles('hero');
      }
      drag = { x: e.clientX, y: e.clientY, left: b[type + '_left'], top: b[type + '_top'], width: b[type + '_width'], rect: hero.getBoundingClientRect() };
      handle.setPointerCapture(e.pointerId);
    });
    handle.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const b = model.hero, dx = (e.clientX - drag.x) / drag.rect.width * 100, dy = (e.clientY - drag.y) / drag.rect.height * 100;
      if (resizing) b[type + '_width'] = clamp(drag.width + dx, 15, Math.max(15, 100 - b[type + '_left'] - gutter));
      else {
        b[type + '_left'] = clamp(drag.left + dx, gutter, Math.max(gutter, 100 - b[type + '_width'] - gutter));
        const part = domBlock('hero').querySelector(type === 'copy' ? '[data-home-hero-copy]' : '[data-home-hero-media]');
        const maxTop = Math.max(0, 100 - part.offsetHeight / drag.rect.height * 100);
        b[type + '_top'] = clamp(drag.top + dy, gutter, Math.max(gutter, Math.min(95 - gutter, maxTop - gutter)));
      }
      applyStyles('hero'); dirty();
    });
    const finish = () => { if (drag) { drag = null; renderInspector(); dirty(); } };
    handle.addEventListener('pointerup', finish); handle.addEventListener('pointercancel', finish); handle.addEventListener('lostpointercapture', finish);
    handle.addEventListener('keydown', (e) => {
      if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      if (model.hero.image_layout !== 'free') return;
      checkpoint(); const b = model.hero, delta = e.shiftKey ? 5 : 1;
      if (resizing) b[type + '_width'] = clamp(b[type + '_width'] + (e.key === 'ArrowLeft' ? -delta : delta), 15, Math.max(15, 100 - b[type + '_left'] - gutter));
      else { const field = type + (['ArrowLeft','ArrowRight'].includes(e.key) ? '_left' : '_top'); b[field] = clamp(b[field] + (['ArrowLeft','ArrowUp'].includes(e.key) ? -delta : delta), gutter, field.endsWith('_left') ? Math.max(gutter, 100 - b[type + '_width'] - gutter) : 95 - gutter); }
      applyStyles('hero'); dirty();
    });
  }
  root.querySelectorAll('[data-device]').forEach((btn) => btn.addEventListener('click', () => {
    device = btn.dataset.device; $('[data-canvas-wrap]').classList.toggle('is-mobile', device === 'mobile');
    root.querySelectorAll('[data-device]').forEach((el) => el.setAttribute('aria-pressed', String(el === btn)));
  }));
  function prepareSubmission(action) {
    const payload = copy(model), data = new FormData(), photoOrder = [], newAlts = [];
    data.append('csrf_token', csrf); data.append('accion', action === 'publish' ? 'publish' : 'save_draft');
    let index = 0;
    payload.hero.images = payload.hero.images.filter((photo) => {
      if (photo._upload) {
        const item = uploads.get(photo._upload); if (!item) throw new Error('Vuelve a seleccionar la foto nueva antes de guardar.');
        data.append('hero_images', item.file, item.file.name); newAlts.push(photo.alt || '');
        photoOrder.push('new:' + index++); return false;
      }
      photoOrder.push('existing:' + photo.id); return true;
    });
    for (const [list, field] of [[payload.sections, 'section_image_'], [payload.announcements, 'announcement_image_']]) {
      list.forEach((b) => {
        if (b._upload) { const item = uploads.get(b._upload); if (!item) throw new Error('Vuelve a seleccionar la foto antes de guardar.'); data.append(field + b.id, item.file, item.file.name); b.image_url = ''; }
        delete b._upload;
      });
    }
    data.append('content_json', JSON.stringify(payload));
    data.append('new_hero_alts', JSON.stringify(newAlts));
    data.append('hero_image_order', JSON.stringify(photoOrder));
    return data;
  }
  async function save(action) {
    if (saving) return false;
    frame.contentDocument?.activeElement?.blur();
    let data;
    try { data = prepareSubmission(action); } catch (e) { message(e.message); return false; }
    let completed = false;
    saving = true; message(''); root.querySelectorAll('[data-save]').forEach((el) => { el.disabled = true; });
    status.textContent = action === 'publish' ? 'Publicando…' : 'Guardando…';
    frame.style.pointerEvents = 'none'; inspector.inert = true; layers.inert = true;
    try {
      const response = await fetch($('[data-home-form]').action, { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': csrf }, body: data });
      if (response.redirected) throw new Error('Tu sesión terminó. Inicia sesión en otra pestaña y vuelve a guardar aquí.');
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.content) throw new Error(result.errors?.join(' ') || 'No se pudo guardar. Tus cambios siguen aquí para volver a intentarlo.');
      model = result.content; saved = JSON.stringify(model); undo.length = 0; redo.length = 0;
      uploads.forEach((item) => URL.revokeObjectURL(item.url)); uploads.clear();
      dirty(); status.textContent = result.published ? 'Publicado · Tu inicio está actualizado' : 'Borrador guardado · Sin publicar';
      renderLayers(); renderInspector(); await renderCanvas();
      completed = true;
    } catch (e) { message(e.message); dirty(); }
    finally { saving = false; frame.style.pointerEvents = ''; inspector.inert = false; layers.inert = false; root.querySelectorAll('[data-save]').forEach((el) => { el.disabled = false; }); $('[data-undo]').disabled = !undo.length; $('[data-redo]').disabled = !redo.length; }
    return completed;
  }
  window.homepageVisualEditor = { publish: () => save('publish'), focus: () => window.focus() };
  previewButton.addEventListener('click', openCurrentPreview);
  root.querySelectorAll('[data-preview-link]').forEach((link) => link.addEventListener('click', (event) => {
    event.preventDefault();
    openCurrentPreview();
  }));
  root.querySelectorAll('[data-save]').forEach((el) => el.addEventListener('click', () => save(el.dataset.save)));
  window.addEventListener('beforeunload', (e) => { if (JSON.stringify(model) !== saved) { e.preventDefault(); e.returnValue = ''; } });
  window.addEventListener('pagehide', (e) => { if (!e.persisted) uploads.forEach((item) => URL.revokeObjectURL(item.url)); });
  renderLayers(); renderInspector(); renderCanvas();
})();

