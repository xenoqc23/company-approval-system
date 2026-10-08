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
    const isStock = kind === 'stock';
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
    show('#unit-price-field', kind === 'office');
    show('#approver-field', !isStock);
    document.querySelector('#purchase-total').hidden = kind !== 'office';
    document.querySelector('#stock-explainer').hidden = !isStock;
    document.querySelector('#approval-arrow').hidden = isStock;
    document.querySelector('#approval-inputs').classList.toggle('review-only', isStock);
    document.querySelector('#quantity-price-grid').classList.toggle('single-column', isStock);
    document.querySelector('#approval-heading').textContent = isStock ? '검토자 지정' : '결재선 지정';
    document.querySelector('#compose-intro').textContent = isStock ? '부족한 품목과 수량을 작성하고 검토자를 선택해 주세요.' : '신청 내용을 작성하고 검토자와 승인자를 선택해 주세요.';
    document.querySelector('#approval-footnote').textContent = isStock ? '검토가 완료되면 발주 담당자가 생산 재고 요청함에서 확인하고 발주를 진행합니다.' : '같은 사람을 선택해도 검토와 최종 승인은 각각 진행됩니다.';
    document.querySelector('#needed-date-label').innerHTML = (isStock ? '발주 필요 날짜' : '구매 필요 날짜') + ' <span class="optional">선택</span>';
    document.querySelector('#compose-help-route').textContent = isStock ? '검토자를 선택하세요. 검토가 완료되면 발주 담당자에게 알림이 전달됩니다.' : '검토자와 승인자를 선택하면 해당 직원에게 알림이 전달됩니다.';
    document.querySelector('#submit-label').textContent = isStock ? '재고 요청 제출' : '기안 제출';
    id('product').placeholder = isStock ? '예: 제품 사용자 매뉴얼, 제품 보관함' : '예: A4 복사용지';
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
