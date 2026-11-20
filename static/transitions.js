/* Navegación directa: no se interceptan clics ni se anima el cambio de página. */
(() => {
  document.documentElement.classList.remove("page-leaving", "page-arriving");
  try { sessionStorage.removeItem("fr-beisshop:opening-section"); } catch (_) {}
})();
