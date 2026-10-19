document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-birthday-calendar]').forEach(calendar => {
    const leap = calendar.form?.querySelector('[data-birthday-leap]');
    if (!leap) return;
    const update = () => {
      const enabled = calendar.value === 'lunar';
      leap.disabled = !enabled;
      if (!enabled) leap.checked = false;
      const field = leap.closest('.field');
      if (field) field.hidden = !enabled;
    };
    calendar.addEventListener('change', update);
    update();
  });
  if (/^#birthday-employee-\d+$/.test(location.hash)) {
    const editor = document.getElementById(location.hash.slice(1));
    if (editor?.tagName === 'DETAILS') {
      editor.open = true;
      editor.scrollIntoView({block: 'center'});
    }
  }
});
