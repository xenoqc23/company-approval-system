document.addEventListener('DOMContentLoaded', () => {
  const accountingTabs = document.querySelector('[data-accounting-status-url]');
  if (accountingTabs) {
    let checking = false;
    const checkNewDocuments = async () => {
      if (document.hidden || checking) return;
      checking = true;
      try {
        const response = await fetch(accountingTabs.dataset.accountingStatusUrl, {cache: 'no-store'});
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) return;
        const data = await response.json();
        data.tabs.forEach(tab => {
          const link = accountingTabs.querySelector(`[data-accounting-kind="${tab.key}"]`);
          if (!link) return;
          link.classList.toggle('has-new', tab.unread);
          link.querySelector('[data-tab-count]').textContent = tab.count;
          link.setAttribute('aria-label', `${tab.label} ${tab.count}건${tab.unread ? ', 확인하지 않은 문서 있음' : ''}`);
        });
      } catch {
        // Keep the existing indicators if a temporary connection fails.
      } finally {
        checking = false;
      }
    };
    window.setInterval(checkNewDocuments, 15000);
    document.addEventListener('visibilitychange', checkNewDocuments);
  }
  const exportForm = document.querySelector('[data-purchase-export]');
  if (exportForm) {
    const boxes = [...exportForm.querySelectorAll('[data-purchase-select]')];
    const selectAll = exportForm.querySelector('[data-select-all]');
    const refresh = () => {
      const count = boxes.filter(box => box.checked).length;
      exportForm.querySelector('[data-selection-count]').textContent = `${count}건 선택`;
      exportForm.querySelector('[data-export-button]').disabled = count === 0;
      selectAll.checked = boxes.length > 0 && count === boxes.length;
      selectAll.indeterminate = count > 0 && count < boxes.length;
      boxes.forEach(box => box.closest('tr').classList.toggle('export-selected', box.checked));
    };
    selectAll.addEventListener('change', () => {
      boxes.forEach(box => box.checked = selectAll.checked);
      refresh();
    });
    boxes.forEach(box => box.addEventListener('change', refresh));
    exportForm.addEventListener('submit', event => {
      if (!boxes.some(box => box.checked)) event.preventDefault();
    });
    refresh();
  }
  const dialog = document.querySelector('#confirmation');
  const feedback = document.querySelector('#approval-feedback');
  const feedbackMessage = document.querySelector('.message[data-approval-feedback]');
  if (feedback && feedbackMessage) {
    document.querySelector('#approval-feedback-title').textContent = feedbackMessage.textContent.trim();
    feedback.showModal();
  }
  document.querySelector('#approval-feedback-close')?.addEventListener('click', () => feedback.close());
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
  document.querySelectorAll('form[data-document-action]').forEach(actionForm => {
    actionForm.addEventListener('submit', event => {
      if (event.defaultPrevented) return;
      if (actionForm.dataset.processing === 'yes') {
        event.preventDefault();
        return;
      }
      actionForm.dataset.processing = 'yes';
      actionForm.setAttribute('aria-busy', 'true');
      const button = actionForm.querySelector('button');
      button.disabled = true;
      button.textContent = '처리 중…';
    });
  });
  const departmentPickers = [...document.querySelectorAll('[data-department-picker]')].map(picker => {
    const person = document.getElementById(picker.dataset.personField);
    const options = [...person.options].filter(option => option.value).map(option => option.cloneNode(true));
    const selected = options.find(option => option.value === person.value);
    if (!picker.value && selected) picker.value = selected.dataset.department;
    const sync = (clear = false) => {
      const selectedValue = clear ? '' : person.value;
      const department = picker.value;
      const available = options.filter(option => option.dataset.department === department);
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = !department ? '부서를 먼저 선택하세요' : available.length ? '직원을 선택하세요' : '선택 가능한 직원이 없습니다';
      person.replaceChildren(placeholder, ...available.map(option => option.cloneNode(true)));
      person.value = available.some(option => option.value === selectedValue) ? selectedValue : '';
      person.disabled = picker.disabled || !department || !available.length;
    };
    picker.addEventListener('change', () => sync(true));
    sync();
    return sync;
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
    departmentPickers.forEach(sync => sync());
    document.querySelector('#purchase-total').hidden = kind !== 'office';
    document.querySelector('#stock-explainer').hidden = !isStock;
    document.querySelector('#approval-arrow').hidden = isStock;
    document.querySelector('#approval-inputs').classList.toggle('review-only', isStock);
    document.querySelector('#quantity-price-grid').classList.toggle('single-column', isStock);
    document.querySelector('#approval-heading').textContent = isStock ? '검토자 지정' : '결재선 지정';
    document.querySelector('#compose-intro').textContent = isStock ? '부족한 품목과 수량을 작성하고 검토자를 선택해 주세요.' : '신청 내용을 작성하고 검토자와 승인자를 선택해 주세요.';
    document.querySelector('#approval-footnote').textContent = isStock ? 'admin을 제외한 주임 이상 검토자를 지정하세요. 검토가 완료되면 발주 담당자가 생산 재고 요청함에서 확인하고 발주를 진행합니다.' : 'admin을 제외한 주임 이상 직원을 지정하세요. 같은 사람을 선택해도 검토와 최종 승인은 각각 진행됩니다.';
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
