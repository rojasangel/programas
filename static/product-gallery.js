(() => {
  const mainImage = document.querySelector('[data-gallery-main-image]');
  const thumbnails = [...document.querySelectorAll('[data-gallery-thumbnail]')];
  if (!mainImage || thumbnails.length < 2) return;

  thumbnails.forEach((thumbnail) => {
    thumbnail.addEventListener('click', () => {
      const image = thumbnail.dataset.galleryImage;
      if (!image) return;
      mainImage.src = image;
      mainImage.alt = thumbnail.dataset.galleryAlt || mainImage.alt;
      thumbnails.forEach((item) => {
        const selected = item === thumbnail;
        item.classList.toggle('is-selected', selected);
        item.setAttribute('aria-pressed', selected ? 'true' : 'false');
      });
    });
  });
})();

