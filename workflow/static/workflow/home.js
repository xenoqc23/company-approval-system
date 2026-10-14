document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-home-tab]').forEach(button => {
    button.addEventListener('click', () => {
      document.querySelectorAll('[data-home-tab]').forEach(tab => {
        const selected = tab === button;
        tab.classList.toggle('selected', selected);
        tab.setAttribute('aria-selected', String(selected));
      });
      document.querySelectorAll('[data-home-documents]').forEach(panel => {
        panel.hidden = panel.dataset.homeDocuments !== button.dataset.homeTab;
      });
    });
  });
  document.querySelectorAll('[data-quick-compose]').forEach(form => {
    const field = name => form.elements.namedItem(`${form.dataset.prefix}-${name}`);
    const remaining = Number(form.dataset.remaining || 0);
    const displayDays = value => `${Number(value.toFixed(2))}일`;
    const refresh = () => {
      if (form.dataset.quickCompose === 'office') {
        const total = Number(field('quantity').value || 0) * Number(field('unit_price').value || 0);
        form.querySelector('[data-quick-total]').textContent = Number.isFinite(total) ? total.toLocaleString('ko-KR', {maximumFractionDigits: 2}) : '—';
        return;
      }
      const annual = field('leave_type').value === 'annual';
      const end = field('end_date');
      const times = form.querySelector('[data-quick-times]');
      times.hidden = annual;
      field('start_time').disabled = annual;
      field('end_time').disabled = annual;
      form.querySelector('[data-quick-end-date]').hidden = !annual;
      form.querySelector('[data-quick-date-separator]').hidden = !annual;
      end.disabled = !annual;
      if (!annual) end.value = field('start_date').value;
      let deduction = field('leave_type').value === 'outing' ? .25 : .5;
      if (annual) {
        deduction = null;
        const start = new Date(field('start_date').value + 'T00:00:00Z');
        const finish = new Date(end.value + 'T00:00:00Z');
        if (Number.isFinite(start.valueOf()) && finish >= start && finish - start <= 36600 * 86400000) {
          deduction = 0;
          for (let day = new Date(start); day <= finish; day.setUTCDate(day.getUTCDate() + 1)) {
            if (day.getUTCDay() !== 0 && day.getUTCDay() !== 6) deduction++;
          }
        }
      }
      form.querySelector('[data-quick-deduction]').textContent = deduction === null ? '—' : displayDays(deduction);
      const expected = deduction === null ? null : remaining - deduction;
      const output = form.querySelector('[data-quick-remaining]');
      output.textContent = expected === null ? '—' : displayDays(expected);
      output.classList.toggle('negative', expected !== null && expected < 0);
      form.querySelector('[data-quick-negative]').hidden = expected === null || expected >= 0;
    };
    form.addEventListener('input', refresh);
    form.addEventListener('change', refresh);
    refresh();
  });
});
