document.addEventListener('DOMContentLoaded', () => {
  const progressPicker = document.querySelector('[data-progress-picker]');
  if (progressPicker) progressPicker.addEventListener('change', () => progressPicker.form.requestSubmit());
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
    person.dataset.departments = JSON.stringify(Object.fromEntries(options.map(option => [option.value, option.dataset.department])));
    const selected = options.find(option => option.value === person.value);
    if (!picker.value && selected) picker.value = selected.dataset.department;
    const sync = (clear = false) => {
      const selectedValue = clear ? '' : person.value;
      const department = picker.value;
      const allowed = person.dataset.allowedIds ? new Set(JSON.parse(person.dataset.allowedIds)) : null;
      const available = options.filter(option => option.dataset.department === department && (!allowed || allowed.has(Number(option.value))));
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
    form.dataset.documentKind = kind;
    const isLeave = kind === 'leave';
    const isStock = kind === 'stock';
    const finalApproval = !isStock || form.dataset.stockFinalApproval === 'true';
    const deferredApprover = form.dataset.progressive === 'true' && (id('approval_mode')?.value || 'base') === 'base';
    const directRepresentative = id('approval_mode')?.value === 'ceo';
    const selfComplete = false;
    const skipReview = finalApproval && (selfComplete || directRepresentative || form.dataset.skipReview === 'true');
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
    show('#approver-field', finalApproval && !selfComplete && !deferredApprover && !directRepresentative);
    show('#reviewer-field', !skipReview);
    document.querySelector('#approval-arrow').hidden = !finalApproval || skipReview || deferredApprover;
    departmentPickers.forEach(sync => sync());
    document.querySelector('#purchase-total').hidden = kind !== 'office';
    document.querySelector('#stock-explainer').hidden = !isStock;
    document.querySelector('#approval-arrow').hidden = !finalApproval || skipReview || deferredApprover;
    document.querySelector('#approval-inputs').classList.toggle('review-only', !finalApproval || deferredApprover || directRepresentative || selfComplete);
    document.querySelector('#quantity-price-grid').classList.toggle('single-column', isStock);
    document.querySelector('#representative-mode-note').hidden = !directRepresentative;
    document.querySelector('#approval-heading').textContent = directRepresentative ? '대표 결재 요청' : !finalApproval || deferredApprover ? '검토자 지정' : '결재선 지정';
    document.querySelector('#compose-intro').textContent = directRepresentative ? '신청 내용을 작성해 대표에게 최종 결재를 요청합니다.' : deferredApprover ? '신청 내용을 작성하고 검토자만 선택해 주세요. 다음 승인자는 검토자가 결정합니다.' : selfComplete ? '다른 결재 담당자에게 요청합니다.' : !finalApproval ? '부족한 품목과 수량을 작성하고 검토자를 선택해 주세요.' : skipReview ? '신청 내용을 작성하고 최종 승인자를 선택해 주세요.' : '신청 내용을 작성하고 검토자와 승인자를 선택해 주세요.';
    document.querySelector('#approval-footnote').textContent = selfComplete ? '다른 결재 담당자에게 요청합니다.' : !finalApproval ? '선택 가능한 직원 중 검토자를 지정해 주세요. 검토가 완료되면 발주 담당자가 생산 재고 요청함에서 확인하고 발주를 진행합니다.' : '선택 가능한 직원 중 결재 담당자를 지정해 주세요. 적용된 결재규정에 따라 검토·승인 단계가 진행됩니다.';
    document.querySelector('#needed-date-label').innerHTML = (isStock ? '발주 필요 날짜' : '구매 필요 날짜') + ' <span class="optional">선택</span>';
    document.querySelector('#compose-help-route').textContent = selfComplete ? '다른 결재 담당자에게 요청합니다.' : skipReview ? '최종 승인자를 선택하면 승인대기 알림이 전달됩니다.' : !finalApproval ? '검토자를 선택하세요. 검토가 완료되면 발주 담당자에게 알림이 전달됩니다.' : '검토자와 승인자를 선택하면 해당 직원에게 알림이 전달됩니다.';
    document.querySelector('#submit-label').textContent = directRepresentative ? '대표 결재 요청' : selfComplete ? '기안 제출' : isStock ? '재고 요청 제출' : form.dataset.reviewerOnly === 'true' && id('kind').value === 'leave' ? '검토 요청' : '기안 제출';
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
    if (id('approval_mode')) id('approval_mode').value = 'base';
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
  let routeTimer;
  let routeSequence = 0;
  const resolveRoute = async () => {
    const sequence = ++routeSequence;
    const params = new URLSearchParams({kind: id('kind').value,
      total: String(Math.round(numeric(id('quantity').value) * numeric(id('unit_price').value) * 100) / 100), reviewer: id('reviewer').value, mode: id('approval_mode')?.value || 'base',
      ...Object.fromEntries(['leave_type','start_date','end_date','start_time','end_time'].map(key => [key,id(key).value]))});
    try {
      const response = await fetch(form.dataset.routeUrl + '?' + params, {cache: 'no-store'});
      const route = await response.json();
      if (sequence !== routeSequence) return;
      if (!response.ok) throw new Error(route.error);
      form.dataset.progressive = String(route.progressive || false);
      form.dataset.skipReview = String(route.skip_review);
      form.dataset.stockFinalApproval = String(route.stock_final_approval || false);
      const modePicker = document.querySelector('#approval-mode-picker');
      if (modePicker) {
        modePicker.hidden = route.available_modes.length < 2;
        const select = id('approval_mode');
        const selectedMode = select.value || 'base';
        const labels = {base:'검토 요청',ceo:'대표 결재 요청'};
        select.replaceChildren(...route.available_modes.map(value => new Option(labels[value], value)));
        select.value = route.available_modes.includes(selectedMode) ? selectedMode : 'base';
        if (select.value !== selectedMode) { resolveRoute(); return; }
      }
      for (const stage of ['reviewer', 'approver']) {
        const fixed = route.progressive && stage === 'approver' && route.mode === 'base' ? null : route['fixed_' + stage + '_id'];
        if (fixed) {
          const department = JSON.parse(id(stage).dataset.departments || '{}')[String(fixed)];
          if (department) id(stage + '_department').value = department;
        }
      }
      id('reviewer').dataset.allowedIds = JSON.stringify(route.reviewer_ids);
      id('approver').dataset.allowedIds = JSON.stringify(route.approver_ids);
      update();
      for (const stage of ['reviewer', 'approver']) {
        const fixed = route.progressive && stage === 'approver' && route.mode === 'base' ? null : route['fixed_' + stage + '_id'];
        if (fixed) id(stage).value = String(fixed);
      }
      document.querySelector('#route-preview').textContent = `${route.name} · ${route.path}${route.note ? ' · ' + route.note : ''}`;
      document.querySelector('#approval-footnote').textContent = route.progressive && route.mode === 'base' ? '검토자는 허용 범위에서 전결하거나 상위 승인자를 지정합니다. 기준 이상에서도 허용된 전결은 유지하며 승인자는 대표 결재 요청도 선택할 수 있습니다.' : route.direct_representative ? '대표에게 직접 최종 결재를 요청합니다. 대표 승인 전에는 완료되지 않습니다.' : route.self_complete ? '다른 결재 담당자에게 요청합니다.' : route.skip_review ? '검토 없이 최종 승인자가 승인하면 완료됩니다. 기안자 본인은 승인자로 지정할 수 없습니다.' : '기안자 ≤ 검토자 ≤ 승인자 직급 조건을 적용합니다. 같은 사람도 단계별로 확인합니다.';
      document.querySelector('#compose-help-route').textContent = route.progressive && route.mode === 'base' ? '검토자를 선택해 제출하면 검토자가 다음 결재 단계를 결정합니다.' : route.direct_representative ? '대표 계정으로 결재 요청 알림이 전달됩니다.' : route.self_complete ? '다른 결재 담당자에게 요청합니다.' : route.skip_review ? '승인자를 선택하면 승인대기 알림이 전달됩니다.' : '담당자를 선택하면 결재 순서대로 알림이 전달됩니다.';
    } catch (error) {
      if (sequence === routeSequence) document.querySelector('#route-preview').textContent = error.message || '경로를 확인하지 못했습니다. 제출 시 최신 규정을 다시 확인합니다.';
    }
  };
  const scheduleRoute = () => { clearTimeout(routeTimer); routeTimer = setTimeout(resolveRoute, 180); };
  form.addEventListener('change', scheduleRoute);
  ['quantity', 'unit_price'].forEach(name => id(name).addEventListener('input', scheduleRoute));
  update();
  resolveRoute();
});
// 부재 일정의 종일 선택에 맞춰 시간 입력을 표시합니다.
document.addEventListener('DOMContentLoaded', () => {
  const checkbox = document.querySelector('#id_all_day');
  if (!checkbox) return;
  const update = () => ['#id_start_time', '#id_end_time'].forEach(selector => {
    const input = document.querySelector(selector);
    if (input) input.closest('.field').hidden = checkbox.checked;
  });
  checkbox.addEventListener('change', update);
  update();
});

// Policy table rows and a read-only delegation simulator.
document.addEventListener('DOMContentLoaded', () => {
  const add = document.querySelector('[data-add-policy-row]');
  if (add) add.addEventListener('click', () => {
    const count = document.querySelector('#id_rules-TOTAL_FORMS');
    if (Number(count.value) >= 200) return;
    const html = document.querySelector('#policy-empty-row').innerHTML.replaceAll('__prefix__', count.value);
    document.querySelector('[data-policy-rows]').insertAdjacentHTML('beforeend', html);
    count.value = Number(count.value) + 1;
  });
  const simulator = document.querySelector('#rule-simulator');
  if (simulator) simulator.addEventListener('submit', async event => {
    event.preventDefault();
    const result = document.querySelector('#rule-simulator-result');
    result.textContent = '규정을 확인하고 있습니다…';
    try {
      const response = await fetch(simulator.dataset.url + '?' + new URLSearchParams(new FormData(simulator)), {cache: 'no-store'});
      const route = await response.json();
      if (!response.ok) throw new Error(route.error);
      result.replaceChildren();
      for (const text of [route.name, route.path,
        ...(route.skip_review ? [] : ['검토 가능 직급: ' + route.reviewers.join(' · ')]),
        ...(!route.final_approval_required ? [] : ['승인 가능 직급: ' + (route.approvers.join(' · ') || '해당 직급 없음'), '기안자 본인 승인 불가']),
        route.note]) {
        if (!text) continue;
        const paragraph = document.createElement('p'); paragraph.textContent = text; result.appendChild(paragraph);
      }
    } catch (error) { result.textContent = error.message || '미리보기를 불러오지 못했습니다.'; }
  });
});
