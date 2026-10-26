document.addEventListener('DOMContentLoaded', () => {
  const root = document.querySelector('[data-unified-compose]');
  if (!root) return;
  const workflow = root.querySelector('[data-compose-pane="workflow"]');
  const purchase = root.querySelector('[data-compose-pane="office"]');
  const kindField = workflow.querySelector('[name="kind"]');
  const locked = root.dataset.kindLocked === 'true';
  const select = kind => {
    if (!['leave', 'office', 'stock'].includes(kind)) return;
    root.dataset.selectedKind = kind;
    workflow.hidden = kind === 'office';
    purchase.hidden = kind !== 'office';
    root.querySelectorAll('[data-kind]').forEach(card => {
      const selected = card.dataset.kind === kind;
      card.classList.toggle('selected', selected);
      card.querySelector('input').checked = selected;
    });
    if (kind !== 'office' && kindField.value !== kind) {
      kindField.value = kind;
      const mode = workflow.querySelector('[name="approval_mode"]');
      if (mode) mode.value = 'base';
      kindField.dispatchEvent(new Event('change', {bubbles: true}));
    }
    document.querySelectorAll('[data-compose-kind]').forEach(link => {
      const selected = link.dataset.composeKind === kind;
      link.classList.toggle('selected', selected);
      if (selected) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    if (!locked) {
      const url = new URL(location.href);
      url.searchParams.set('kind', kind);
      history.replaceState(history.state, '', url);
    }
  };
  root.querySelectorAll('[name="document-kind"]').forEach(input => input.addEventListener('change', () => {
    if (input.checked && !locked) select(input.value);
  }));
  select(root.dataset.selectedKind);
});
