(() => {
  document.querySelectorAll('[data-identity-tabs]').forEach((container) => {
    const tabs = [...container.querySelectorAll('[data-identity-tab]')];
    const panels = [...container.querySelectorAll('[data-identity-panel]')];
    const tablist = container.querySelector('[data-identity-tablist]');
    if (!tablist || !tabs.length || tabs.some((tab) => !panels.some((panel) => panel.dataset.identityPanel === tab.dataset.identityTab))) return;

    function activate(tab, focus = false, updateLocation = false) {
      tabs.forEach((item) => {
        const selected = item === tab;
        item.setAttribute('aria-selected', String(selected));
        item.tabIndex = selected ? 0 : -1;
      });
      panels.forEach((panel) => {
        panel.hidden = panel.dataset.identityPanel !== tab.dataset.identityTab;
      });
      if (focus) tab.focus();
      if (updateLocation) window.history.replaceState(null, '', tab.getAttribute('href'));
    }

    function tabFromHash() {
      const fragment = window.location.hash.slice(1);
      return tabs.find((tab) => {
        const key = tab.dataset.identityTab;
        return [key, `${key}-panel`, `${key}-title`].includes(fragment);
      });
    }

    tablist.setAttribute('role', 'tablist');
    tabs.forEach((tab, index) => {
      tab.setAttribute('role', 'tab');
      tab.addEventListener('click', (event) => {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || (event.button !== undefined && event.button !== 0)) return;
        event.preventDefault();
        activate(tab, false, true);
      });
      tab.addEventListener('keydown', (event) => {
        let nextIndex;
        if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
        else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length;
        else if (event.key === 'Home') nextIndex = 0;
        else if (event.key === 'End') nextIndex = tabs.length - 1;
        else if (event.key === ' ') nextIndex = index;
        else return;
        event.preventDefault();
        activate(tabs[nextIndex], true, true);
      });
    });
    panels.forEach((panel) => panel.setAttribute('role', 'tabpanel'));
    activate(tabFromHash() || tabs[0]);
    window.addEventListener('hashchange', () => {
      const requested = tabFromHash();
      if (requested) activate(requested);
    });
  });
})();

