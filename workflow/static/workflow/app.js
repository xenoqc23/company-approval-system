document.addEventListener('DOMContentLoaded', () => {
  const dialog = document.querySelector('#confirmation');
  let pendingForm;
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', event => {
      if (form.dataset.confirmed === 'yes') return;
      event.preventDefault();
      pendingForm = form;
      document.querySelector('#confirmation-text').textContent = form.dataset.confirm;
      dialog.showModal();
    });
  });
  document.querySelector('#confirmation-back').addEventListener('click', () => dialog.close());
  document.querySelector('#confirmation-go').addEventListener('click', () => {
    if (!pendingForm) return;
    pendingForm.dataset.confirmed = 'yes';
    dialog.close();
    pendingForm.requestSubmit();
  });
  const form = document.querySelector('#compose-form');
  if (!form) return;
  const id = name => document.querySelector('#id_' + name);
  const show = (selector, enabled) => {
    const group = document.querySelector(selector);
    group.hidden = !enabled;
    group.querySelectorAll('input, select, textarea').forEach(field => field.disabled = !enabled);
  };
  const numeric = value => Number(String(value || 0).replaceAll(',', ''));
  const dateOnly = value => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    const [year, month, day] = value.split('-').map(Number);
    return new Date(Date.UTC(year, month - 1, day));
  };
  const update = () => {
    const kind = id('kind').value;
    const isLeave = kind === 'leave';
    const annual = id('leave_type').value === 'annual';
    document.querySelectorAll('[data-kind]').forEach(card => {
      const selected = card.dataset.kind === kind;
      card.classList.toggle('selected', selected);
      card.querySelector('input').checked = selected;
    });
    show('#leave-fields', isLeave);
    show('#purchase-fields', !isLeave);
    show('#time-fields', isLeave && !annual);
    show('#end-date-field', isLeave && annual);
    show('#url-field', kind === 'office');
    document.querySelector('#leave-preview').hidden = !isLeave;
    document.querySelector('#start-date-label').innerHTML = (annual ? '시작일' : '사용 날짜') + ' <em>*</em>';
    document.querySelector('#reason-label').innerHTML = isLeave ? '신청 사유 <em>*</em>' : '요청·긴급 사유 <span class="optional">선택</span>';
    if (!annual) id('end_date').value = id('start_date').value;
    let amount = null;
    if (isLeave) {
      const start = dateOnly(id('start_date').value);
      const end = dateOnly(id('end_date').value);
      if (start && end && end >= start) {
        if (annual) {
          amount = 0;
          for (let day = new Date(start); day <= end; day.setUTCDate(day.getUTCDate() + 1)) {
            if (![0, 6].includes(day.getUTCDay())) amount++;
          }
        } else amount = id('leave_type').value === 'outing' ? 0.25 : 0.5;
      }
      const remaining = numeric(form.dataset.remaining);
      document.querySelector('#deduction-preview').textContent = amount === null ? '—' : amount;
      document.querySelector('#remaining-preview').textContent = amount === null ? '—' : remaining - amount;
      document.querySelector('#negative-note').hidden = amount === null || remaining - amount >= 0;
      document.querySelector('.preview-result').classList.toggle('negative', amount !== null && remaining - amount < 0);
    }
    const price = numeric(id('quantity').value) * numeric(id('unit_price').value);
    document.querySelector('#price-preview').textContent = new Intl.NumberFormat('ko-KR', {maximumFractionDigits: 2}).format(price);
  };
  document.querySelectorAll('[data-kind] input').forEach(input => input.addEventListener('change', () => {
    id('kind').value = input.value;
    update();
  }));
  form.addEventListener('input', update);
  form.addEventListener('change', update);
  form.addEventListener('submit', event => {
    if (event.submitter) {
      const intent = document.createElement('input');
      intent.type = 'hidden'; intent.name = 'intent'; intent.value = event.submitter.value;
      form.appendChild(intent);
    }
    form.querySelectorAll('button[type=submit], .compose-actions button').forEach(button => button.disabled = true);
  });
  update();
});
