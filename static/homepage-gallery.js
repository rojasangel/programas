(() => {
  document.querySelectorAll('[data-home-gallery]').forEach((gallery) => {
    const slides = [...gallery.querySelectorAll('[data-home-slide]')];
    const controls = gallery.querySelector('[data-home-controls]');
    const previous = gallery.querySelector('[data-home-prev]');
    const next = gallery.querySelector('[data-home-next]');
    const dots = [...gallery.querySelectorAll('[data-home-slide-index]')];
    const status = gallery.querySelector('[data-home-status]');
    if (slides.length < 2 || !controls || !previous || !next || dots.length !== slides.length) return;

    let current = 0;
    const showSlide = (index) => {
      const requested = Number(index);
      if (!Number.isInteger(requested)) return;
      current = Math.max(0, Math.min(slides.length - 1, requested));
      slides.forEach((slide, slideIndex) => {
        const active = slideIndex === current;
        slide.hidden = !active;
        slide.classList.toggle('is-active', active);
        dots[slideIndex].classList.toggle('is-active', active);
        dots[slideIndex].setAttribute('aria-current', String(active));
      });
      previous.disabled = current === 0;
      next.disabled = current === slides.length - 1;
      if (status) status.textContent = `Foto ${current + 1} de ${slides.length}`;
    };

    previous.addEventListener('click', () => showSlide(current - 1));
    next.addEventListener('click', () => showSlide(current + 1));
    dots.forEach((dot) => {
      dot.addEventListener('click', () => showSlide(dot.dataset.homeSlideIndex));
    });
    controls.addEventListener('keydown', (event) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const targetIndex = {
        ArrowLeft: Math.max(0, current - 1),
        ArrowRight: Math.min(slides.length - 1, current + 1),
        Home: 0,
        End: slides.length - 1,
      }[event.key];
      if (targetIndex === undefined) return;
      event.preventDefault();
      showSlide(targetIndex);
      dots[current].focus();
    });

    showSlide(0);
    controls.hidden = false;
  });
})();

