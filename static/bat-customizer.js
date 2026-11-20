(() => {
  const preview = document.querySelector('[data-bat-preview]');
  const source = document.querySelector('[data-bat-source]');
  const colorSelect = document.querySelector('select[name="color_bat"]');
  const handleColorSelect = document.querySelector('select[name="color_bat_handle"]');
  const gripColorSelect = document.querySelector('select[name="color_grip"]');
  const logoColorSelect = document.querySelector('select[name="logo_color"]');
  const measureSelect = document.querySelector('select[name="medida"]');
  const gripEnabledToggle = document.querySelector('[data-grip-enabled]');
  const nameInput = document.querySelector('input[name="nombre_personalizado"]');
  const numberInput = document.querySelector('input[name="numero"]');
  const logo = document.querySelector('[data-bat-logo]');
  const swatches = [...document.querySelectorAll('[data-color-swatch]')];
  const colorSummary = document.querySelector('[data-color-summary]');
  const personalizationSummary = document.querySelector('[data-bat-personalization-summary]');
  const bat3d = document.querySelector('[data-bat-3d]');
  const viewButtons = [...document.querySelectorAll('[data-bat-view]')];
  const designViewButton = viewButtons.find((button) => button.dataset.batView === 'design');
  const referencePhoto = document.querySelector('[data-bat-reference-photo]');
  const viewLabel = document.querySelector('[data-bat-view-label]');
  const photoCaption = document.querySelector('[data-bat-photo-caption]');
  const defaultPhotoCaption = photoCaption?.textContent;
  const designThumbnail = document.querySelector('[data-bat-view-thumbnail]');
  const engravingPreview = document.querySelector('[data-bat-engraving-preview]');
  const engravingThumbnail = document.querySelector('[data-bat-engraving-thumbnail]');
  const logoPreview = document.querySelector('[data-bat-logo-preview]');
  const logoThumbnail = document.querySelector('[data-bat-logo-thumbnail]');
  const handlePreview = document.querySelector('[data-bat-handle-preview]');
  const handleThumbnail = document.querySelector('[data-bat-handle-thumbnail]');
  const basePreview = document.querySelector('[data-bat-base-preview]');
  const baseThumbnail = document.querySelector('[data-bat-base-thumbnail]');
  const previewForm = document.querySelector('form[action*="/carrito/agregar/"]');
  const previewDataInput = previewForm?.querySelector('[data-bat-preview-data]');
  const previewNote = previewForm?.querySelector('.customization-note');
  const previewNoteText = previewNote?.textContent;
  if (!preview || !source || !colorSelect || !handleColorSelect || !gripColorSelect || !nameInput) return;

  const context = preview.getContext('2d', { willReadFrequently: true });
  let logoStamp = null;
  const colors = {
    Natural: [177, 118, 59],
    Negro: [25, 26, 30],
    Vino: [86, 12, 31],
    Rojo: [214, 54, 54],
    Azul: [48, 91, 207],
    Rosa: [230, 105, 155],
    Blanco: [248, 248, 248]
  };
  const logoColors = {
    Blanco: [255, 255, 255],
    Plateado: [230, 236, 248],
    Dorado: [255, 198, 24],
    Negro: [25, 26, 30]
  };

  const clamp = (value) => Math.max(0, Math.min(255, Math.round(value)));

  // El grip comienza en la marca de referencia del bat y conserva la tapa
  // final de madera sin cubrir.
  const handleStart = 0.60;
  const gripStart = 0.68;
  const gripEnd = 0.94;
  const engravingZone = { x: 0.23596, y: 0.14346, angle: 49.22312 * Math.PI / 180 };
  const logoZone = { x: 0.53, y: 0.49 };
  const handleZone = { x: 0.89, y: 0.91, zoom: 4.5 };
  const baseZone = { x: 0.91903, y: 0.94466, zoom: 7 };

  function selectBatView(button) {
    if (!button || !bat3d) return;
    const showPhoto = button.dataset.batView === 'photo' && Boolean(referencePhoto);
    const showEngraving = button.dataset.batView === 'engraving' && Boolean(engravingPreview);
    const showLogo = button.dataset.batView === 'logo' && Boolean(logoPreview);
    const showHandle = button.dataset.batView === 'handle' && Boolean(handlePreview);
    const showBase = button.dataset.batView === 'base' && Boolean(basePreview);
    if (referencePhoto) {
      if (showPhoto) {
        referencePhoto.src = button.dataset.batPhotoUrl;
        referencePhoto.alt = `${source.alt} · ${button.dataset.batPhotoLabel}`;
      }
      referencePhoto.hidden = !showPhoto;
    }
    if (engravingPreview) engravingPreview.hidden = !showEngraving;
    if (logoPreview) logoPreview.hidden = !showLogo;
    if (handlePreview) handlePreview.hidden = !showHandle;
    if (basePreview) basePreview.hidden = !showBase;
    bat3d.classList.toggle('is-reference-photo', showPhoto);
    bat3d.classList.toggle('is-engraving-view', showEngraving);
    bat3d.classList.toggle('is-logo-view', showLogo);
    bat3d.classList.toggle('is-handle-view', showHandle);
    bat3d.classList.toggle('is-base-view', showBase);
    bat3d.classList.remove('is-tilting');
    bat3d.style.transform = '';
    const viewTitles = { design: 'Tu diseño', engraving: 'Letras de cerca', logo: 'Marca de cerca', handle: 'Punta del mango', base: 'Base del mango' };
    if (viewLabel) viewLabel.textContent = showPhoto ? button.dataset.batPhotoLabel : viewTitles[button.dataset.batView];
    if (photoCaption) {
      photoCaption.hidden = !showPhoto;
      if (showPhoto) photoCaption.textContent = button.dataset.batPhotoCaption || defaultPhotoCaption;
    }
    viewButtons.forEach((viewButton) => {
      const selected = viewButton === button;
      viewButton.classList.toggle('is-selected', selected);
      viewButton.setAttribute('aria-pressed', String(selected));
    });
  }

  function refreshDesign() {
    if (bat3d?.classList.contains('is-reference-photo')) selectBatView(designViewButton);
    drawPreview();
  }

  function previewAssetsReady() {
    return source.complete && source.naturalWidth > 0 &&
      (!logo || (logo.complete && logo.naturalWidth > 0));
  }

  function drawPreview() {
    if (!source.naturalWidth || !source.naturalHeight) return;

    preview.width = source.naturalWidth;
    preview.height = source.naturalHeight;
    context.clearRect(0, 0, preview.width, preview.height);
    context.drawImage(source, 0, 0);

    const mainTarget = colors[colorSelect.value];
    const handleTarget = colors[handleColorSelect.value];
    const gripEnabled = !gripEnabledToggle || gripEnabledToggle.checked;
    const gripTarget = gripEnabled ? colors[gripColorSelect.value] : null;
    if (mainTarget || handleTarget || gripTarget) {
      const pixels = context.getImageData(0, 0, preview.width, preview.height);
      for (let index = 0; index < pixels.data.length; index += 4) {
        if (pixels.data[index + 3] === 0) continue;

        const pixel = index / 4;
        const x = pixel % preview.width;
        const y = Math.floor(pixel / preview.width);
        const progress = (x + y) / (preview.width + preview.height);
        // El bate va de la esquina superior izquierda al mango inferior derecho.
        // El último 40% de ese eje corresponde al mango.
        const target = gripEnabled && progress >= gripStart && progress < gripEnd
          ? gripTarget
          : progress >= handleStart
            ? handleTarget
            : mainTarget;
        if (!target) continue;

        const luminance = (
          pixels.data[index] * 0.2126 +
          pixels.data[index + 1] * 0.7152 +
          pixels.data[index + 2] * 0.0722
        ) / 255;
        const shade = 0.45 + luminance * 0.55;
        pixels.data[index] = clamp(target[0] * shade);
        pixels.data[index + 1] = clamp(target[1] * shade);
        pixels.data[index + 2] = clamp(target[2] * shade);
      }
      context.putImageData(pixels, 0, 0);
    }

    // Da al acabado una luz de barniz como el bat negro de referencia.
    context.save();
    context.globalCompositeOperation = 'source-atop';
    const gloss = context.createLinearGradient(0, 0, preview.width, preview.height);
    gloss.addColorStop(0, 'rgba(255,255,255,.18)');
    gloss.addColorStop(.24, 'rgba(255,255,255,.04)');
    gloss.addColorStop(.48, 'rgba(255,255,255,0)');
    gloss.addColorStop(.72, 'rgba(0,0,0,.12)');
    gloss.addColorStop(1, 'rgba(255,255,255,.10)');
    context.fillStyle = gloss;
    context.fillRect(0, 0, preview.width, preview.height);
    context.restore();

    // Simula la cinta enrollada del grip y deja el extremo final sin cubrir.
    if (gripEnabled) {
      context.save();
    const gripStartAxis = gripStart * (preview.width + preview.height);
    const gripEndAxis = gripEnd * (preview.width + preview.height);
    context.beginPath();
    context.moveTo(preview.width, gripStartAxis - preview.width);
    context.lineTo(preview.width, gripEndAxis - preview.width);
    context.lineTo(gripEndAxis - preview.height, preview.height);
    context.lineTo(gripStartAxis - preview.height, preview.height);
    context.closePath();
    context.clip();
    context.globalCompositeOperation = 'source-atop';
    context.lineWidth = 7;
    context.strokeStyle = 'rgba(255, 255, 255, .28)';
    for (let offset = -preview.height; offset < preview.width; offset += 26) {
      context.beginPath();
      context.moveTo(offset, preview.height);
      context.lineTo(offset + preview.height, 0);
      context.stroke();
    }
    context.lineWidth = 2;
    context.strokeStyle = 'rgba(16, 20, 32, .28)';
    for (let offset = -preview.height + 13; offset < preview.width; offset += 26) {
      context.beginPath();
      context.moveTo(offset, preview.height);
      context.lineTo(offset + preview.height, 0);
      context.stroke();
    }
      context.restore();
    }

    // Convierte el fondo negro del archivo en transparencia para que el monograma
    // se vea como una marca aplicada sobre la zona azul del bat.
    if (logo && logo.complete && logo.naturalWidth) {
      if (!logoStamp) {
        const cropX = logo.naturalWidth * 0.14;
        const cropY = logo.naturalHeight * 0.19;
        const cropWidth = logo.naturalWidth * 0.72;
        const cropHeight = logo.naturalHeight * 0.58;
        const rawLogo = document.createElement('canvas');
        rawLogo.width = Math.round(cropWidth);
        rawLogo.height = Math.round(cropHeight);
        const logoContext = rawLogo.getContext('2d', { willReadFrequently: true });
        logoContext.drawImage(logo, cropX, cropY, cropWidth, cropHeight, 0, 0, rawLogo.width, rawLogo.height);
        const logoPixels = logoContext.getImageData(0, 0, rawLogo.width, rawLogo.height);
        let minX = rawLogo.width;
        let minY = rawLogo.height;
        let maxX = -1;
        let maxY = -1;
        for (let index = 0; index < logoPixels.data.length; index += 4) {
          const luminance = (
            logoPixels.data[index] * 0.2126 +
            logoPixels.data[index + 1] * 0.7152 +
            logoPixels.data[index + 2] * 0.0722
          );
          if (luminance < 16) {
            logoPixels.data[index + 3] = 0;
          } else {
            // Conserva el brillo del archivo para poder cambiar el acabado.
            logoPixels.data[index] = clamp(luminance);
            logoPixels.data[index + 1] = clamp(luminance);
            logoPixels.data[index + 2] = clamp(luminance);
            logoPixels.data[index + 3] = clamp((luminance - 16) * 4.6);
            const pixel = index / 4;
            const x = pixel % rawLogo.width;
            const y = Math.floor(pixel / rawLogo.width);
            minX = Math.min(minX, x);
            minY = Math.min(minY, y);
            maxX = Math.max(maxX, x);
            maxY = Math.max(maxY, y);
          }
        }
        logoStamp = document.createElement('canvas');
        if (maxX >= minX && maxY >= minY) {
          logoStamp.width = maxX - minX + 1;
          logoStamp.height = maxY - minY + 1;
          logoStamp.getContext('2d').putImageData(logoPixels, -minX, -minY);
        } else {
          logoStamp.width = rawLogo.width;
          logoStamp.height = rawLogo.height;
          logoStamp.getContext('2d').putImageData(logoPixels, 0, 0);
        }
      }
      const selectedLogoColor = logoColorSelect?.value || 'Blanco';
      const logoTone = logoColors[selectedLogoColor] || logoColors.Plateado;
      const logoTintStamp = document.createElement('canvas');
      logoTintStamp.width = logoStamp.width;
      logoTintStamp.height = logoStamp.height;
      const tintContext = logoTintStamp.getContext('2d');
      const tintPixels = logoStamp.getContext('2d', { willReadFrequently: true }).getImageData(0, 0, logoStamp.width, logoStamp.height);
      for (let index = 0; index < tintPixels.data.length; index += 4) {
        if (tintPixels.data[index + 3] === 0) continue;
        const shine = selectedLogoColor === 'Blanco'
          ? 0.94 + (tintPixels.data[index] / 255) * 0.06
          : 0.70 + (tintPixels.data[index] / 255) * 0.30;
        tintPixels.data[index] = clamp(logoTone[0] * shine);
        tintPixels.data[index + 1] = clamp(logoTone[1] * shine);
        tintPixels.data[index + 2] = clamp(logoTone[2] * shine);
      }
      tintContext.putImageData(tintPixels, 0, 0);
      const logoWidth = preview.width * 0.105;
      const logoHeight = logoWidth * (logoStamp.height / logoStamp.width);
      function drawLogo(targetContext) {
        targetContext.save();
        targetContext.translate(preview.width * logoZone.x, preview.height * logoZone.y);
        targetContext.rotate(Math.atan2(preview.height, preview.width));
        targetContext.globalCompositeOperation = 'source-atop';
        targetContext.globalAlpha = 0.98;
        targetContext.drawImage(logoTintStamp, -logoWidth / 2, -logoHeight / 2, logoWidth, logoHeight);
        targetContext.restore();
      }
      // La vista ampliada usa el monograma a su resolución original.
      if (logoPreview) {
        logoPreview.width = preview.width;
        logoPreview.height = preview.height;
        const logoDetailContext = logoPreview.getContext('2d');
        logoDetailContext.save();
        logoDetailContext.translate(logoPreview.width / 2, logoPreview.height / 2);
        logoDetailContext.scale(3.5, 3.5);
        logoDetailContext.translate(-preview.width * logoZone.x, -preview.height * logoZone.y);
        logoDetailContext.drawImage(preview, 0, 0);
        drawLogo(logoDetailContext);
        logoDetailContext.restore();
        if (logoThumbnail) {
          logoThumbnail.width = 200;
          logoThumbnail.height = 200;
          logoThumbnail.getContext('2d').drawImage(logoPreview, 0, 0, 200, 200);
        }
      }
      drawLogo(context);
    }

    const name = nameInput.value.trim();
    const number = numberInput ? numberInput.value.trim() : '';
    const measureNumber = Number.parseFloat(measureSelect?.value || '33');
    const dropWeight = Number.parseFloat(preview.dataset.batDropWeight || '-3');
    const weightNumber = Number.isFinite(measureNumber + dropWeight)
      ? String(Math.round((measureNumber + dropWeight) * 10) / 10).replace(/\.0$/, '')
      : '';
    const engraving = `${Number.isFinite(measureNumber) ? measureNumber : 33}/${weightNumber} MAPLE`;
    const lines = [
      { text: 'FR BATS', font: '800 16px Arial, sans-serif' },
      ...(name || number ? [{ text: [name, number ? `#${number}` : ''].filter(Boolean).join(' '), font: '800 18px Arial, sans-serif' }] : []),
      { text: engraving, font: '700 13px Georgia, serif' }
    ];
    function drawEngraving(targetContext) {
      targetContext.save();
      // Centro y ángulo medidos sobre la silueta de bat-transition.png.
      // Todas las líneas comparten este eje, también al cambiar el nombre.
      targetContext.translate(preview.width * engravingZone.x, preview.height * engravingZone.y);
      targetContext.rotate(engravingZone.angle);
      targetContext.textAlign = 'center';
      targetContext.textBaseline = 'middle';
      targetContext.lineJoin = 'round';
      targetContext.fillStyle = '#f7f7f4';
      targetContext.shadowColor = 'rgba(255,255,255,.35)';
      targetContext.shadowBlur = 2;
      const lineGap = 22;
      const firstLineY = -((lines.length - 1) * lineGap) / 2;
      lines.forEach((line, index) => {
        targetContext.font = line.font;
        const lineY = firstLineY + (index * lineGap);
        targetContext.fillText(line.text.toLocaleUpperCase(), 0, lineY, preview.width * 0.17);
      });
      targetContext.restore();
    }
    // El acercamiento comparte el mismo diseño y vuelve a dibujar las letras
    // a su resolución ampliada para que se vean nítidas.
    if (engravingPreview) {
      engravingPreview.width = preview.width;
      engravingPreview.height = preview.height;
      const detailContext = engravingPreview.getContext('2d');
      detailContext.save();
      detailContext.translate(engravingPreview.width / 2, engravingPreview.height / 2);
      detailContext.scale(3.5, 3.5);
      detailContext.translate(-preview.width * engravingZone.x, -preview.height * engravingZone.y);
      detailContext.drawImage(preview, 0, 0);
      drawEngraving(detailContext);
      detailContext.restore();
      if (engravingThumbnail) {
        engravingThumbnail.width = 200;
        engravingThumbnail.height = 200;
        engravingThumbnail.getContext('2d').drawImage(engravingPreview, 0, 0, 200, 200);
      }
    }
    drawEngraving(context);

    // Encuadra la tapa completa y el tramo final del mango/grip.
    if (handlePreview) {
      handlePreview.width = preview.width;
      handlePreview.height = preview.height;
      const handleContext = handlePreview.getContext('2d');
      handleContext.save();
      handleContext.translate(handlePreview.width / 2, handlePreview.height / 2);
      handleContext.scale(handleZone.zoom, handleZone.zoom);
      handleContext.translate(-preview.width * handleZone.x, -preview.height * handleZone.y);
      handleContext.drawImage(preview, 0, 0);
      handleContext.restore();
      if (handleThumbnail) {
        handleThumbnail.width = 200;
        handleThumbnail.height = 200;
        handleThumbnail.getContext('2d').drawImage(handlePreview, 0, 0, 200, 200);
      }
    }

    // Amplía la tapa que ya existe en la imagen del personalizador.
    // Al girar el mismo diseño, el mango sale de la tapa hacia abajo.
    if (basePreview) {
      basePreview.width = preview.width;
      basePreview.height = preview.height;
      const baseContext = basePreview.getContext('2d');
      baseContext.save();
      baseContext.translate(basePreview.width / 2, basePreview.height * 0.4);
      baseContext.scale(baseZone.zoom, baseZone.zoom);
      baseContext.rotate(Math.PI);
      baseContext.translate(-preview.width * baseZone.x, -preview.height * baseZone.y);
      baseContext.drawImage(preview, 0, 0);
      baseContext.restore();
      if (baseThumbnail) {
        baseThumbnail.width = 200;
        baseThumbnail.height = 200;
        baseThumbnail.getContext('2d').drawImage(basePreview, 0, 0, 200, 200);
      }
    }

    preview.parentElement.classList.add('is-ready');
    if (previewAssetsReady() && previewNote) previewNote.textContent = previewNoteText;
    if (designThumbnail) {
      designThumbnail.width = 200;
      designThumbnail.height = 200;
      designThumbnail.getContext('2d').drawImage(preview, 0, 0, 200, 200);
    }
    if (colorSummary) {
      const measure = measureSelect?.value ? `${measureSelect.value} in` : '';
      const logoColor = logoColorSelect?.value || 'Plateado';
      colorSummary.textContent = [
        measure,
        colorSelect.value,
        `mango ${handleColorSelect.value}`,
        gripEnabled ? `grip ${gripColorSelect.value}` : 'sin grip',
        `logo ${logoColor}`
      ].filter(Boolean).join(' · ');
    }
    if (personalizationSummary) {
      const personalization = [name, number ? `#${number}` : ''].filter(Boolean).join(' ');
      personalizationSummary.textContent = personalization
        ? `Grabado en tu bat: ${personalization}`
        : 'Agrega tu nombre o número para verlo en la vista previa.';
    }
  }

  function syncSwatches(select) {
    swatches
      .filter((swatch) => swatch.dataset.colorTarget === select.name)
      .forEach((swatch) => {
        const selected = swatch.dataset.colorValue === select.value;
        swatch.classList.toggle('is-selected', selected);
        swatch.setAttribute('aria-pressed', String(selected));
      });
  }

  if (bat3d) {
    const reset3d = () => {
      bat3d.classList.remove('is-tilting');
      bat3d.style.transform = '';
    };

    bat3d.addEventListener('pointermove', (event) => {
      if (['is-reference-photo', 'is-engraving-view', 'is-logo-view', 'is-handle-view', 'is-base-view'].some((mode) => bat3d.classList.contains(mode))) return reset3d();
      const bounds = bat3d.getBoundingClientRect();
      const horizontal = (event.clientX - bounds.left) / bounds.width;
      const vertical = (event.clientY - bounds.top) / bounds.height;
      const rotateY = (horizontal - 0.5) * 14;
      const rotateX = (0.5 - vertical) * 12;
      bat3d.classList.add('is-tilting');
      bat3d.style.transform = `rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg)`;
    });
    bat3d.addEventListener('pointerleave', reset3d);
    bat3d.addEventListener('pointercancel', reset3d);
  }

  swatches.forEach((swatch) => {
    swatch.addEventListener('click', () => {
      const select = document.querySelector(`select[name="${swatch.dataset.colorTarget}"]`);
      if (!select) return;
      select.value = swatch.dataset.colorValue;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });

  viewButtons.forEach((button) => button.addEventListener('click', () => selectBatView(button)));
  colorSelect.addEventListener('change', refreshDesign);
  handleColorSelect.addEventListener('change', refreshDesign);
  gripColorSelect.addEventListener('change', refreshDesign);
  measureSelect?.addEventListener('change', refreshDesign);
  if (gripEnabledToggle) gripEnabledToggle.addEventListener('change', refreshDesign);
  colorSelect.addEventListener('change', () => syncSwatches(colorSelect));
  handleColorSelect.addEventListener('change', () => syncSwatches(handleColorSelect));
  if (logoColorSelect) {
    logoColorSelect.addEventListener('change', refreshDesign);
    logoColorSelect.addEventListener('change', () => syncSwatches(logoColorSelect));
  }
  nameInput.addEventListener('input', refreshDesign);
  if (numberInput) numberInput.addEventListener('input', refreshDesign);
  syncSwatches(colorSelect);
  syncSwatches(handleColorSelect);
  if (logoColorSelect) syncSwatches(logoColorSelect);
  if (source.complete) drawPreview();
  else source.addEventListener('load', drawPreview, { once: true });
  if (logo && !logo.complete) logo.addEventListener('load', drawPreview, { once: true });
  if (previewForm && previewDataInput) {
    previewForm.addEventListener('submit', (event) => {
      if (!previewAssetsReady()) {
        event.preventDefault();
        event.stopPropagation();
        if (previewNote) previewNote.textContent = 'Espera a que termine de cargar tu diseño antes de agregarlo al carrito. Si no carga, recarga la página.';
        return;
      }
      drawPreview();
      try {
        previewDataInput.value = preview.toDataURL('image/png');
      } catch (error) {
        previewDataInput.value = '';
        event.preventDefault();
        event.stopPropagation();
        if (previewNote) previewNote.textContent = 'No pudimos guardar la imagen de tu diseño. Recarga la página e inténtalo de nuevo.';
      }
    });
  }
})();

